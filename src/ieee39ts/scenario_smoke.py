"""Adapted-model PFlow and no-fault smoke; frozen official runner stays intact."""
from dataclasses import asdict
import csv
import logging
import os
from pathlib import Path
import time
import traceback

import numpy as np

from .io import save_fault_result, write_json
from .scenarios import renewable_share, sha256
from .simulation import extract_trajectory
from .stability import assess_trajectory
from .types import FaultResult, RunDiagnostics, SimulationStatus

ROOT = Path(__file__).resolve().parents[2]


def load_system(model_path):
    cache = ROOT / ".cache"
    os.environ["MPLCONFIGDIR"] = str(cache / "matplotlib")
    os.environ["NUMBA_CACHE_DIR"] = str(cache / "numba")
    import andes
    if andes.__version__ != "2.0.0":
        raise RuntimeError("Require the accepted ANDES 2.0.0 environment")
    system = andes.load(str(model_path), setup=False, no_undill=True, default_config=True,
                        no_output=True, pycode_path=str(cache / "andes/pycode"))
    system.prepare(quick=True, incremental=True, nomp=True)
    for model in system.TimedEvent.models.values():
        for idx in model.idx.v:
            model.set("u", idx, value=0)
    if not system.setup():
        raise RuntimeError("ANDES setup failed")
    return system


def pflow_generations(system):
    rows = []
    for model in (system.PV, system.Slack):
        for uid, idx in enumerate(model.idx.v):
            rows.append({"static_gen_id": idx, "model": model.class_name,
                         "bus": int(model.bus.v[uid]), "online": bool(model.u.v[uid]),
                         "P0_MW": float(model.get("p", idx)) * system.config.mva,
                         "Q0_Mvar": float(model.get("q", idx)) * system.config.mva})
    return rows


def audit_candidates(model_path, csv_path, output):
    """PFlow only; capture machine-base H and setup-time system-base M explicitly."""
    system = load_system(model_path)
    if not (system.PFlow.run() and system.PFlow.converged):
        raise RuntimeError("Candidate baseline PFlow failed")
    injections = {row["static_gen_id"]: row for row in pflow_generations(system)}
    rows = []
    for uid, generator_id in enumerate(system.GENROU.idx.v):
        idx = system.GENROU.gen.v[uid]
        static = injections[idx]
        sn = float(system.GENROU.Sn.v[uid])
        mass = float(system.GENROU.M.v[uid])
        machine_mass = mass * system.config.mva / sn
        rows.append({"generator_id": generator_id, "bus": static["bus"], "static_gen_id": idx,
                     "P0_MW": static["P0_MW"], "Q0_Mvar": static["Q0_Mvar"], "Sn_MVA": sn,
                     "M": mass, "M_machine_2H_s": machine_mass, "H_s": machine_mass / 2,
                     "is_slack": static["model"] == "Slack",
                     "replacement_allowed": static["model"] != "Slack", "fixed_S1_bus37": static["bus"] == 37})
    csv_path = Path(csv_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)
    write_json(Path(output) / "audit.json", {"pflow_converged": True, "tds_runs": 0,
               "model_sha256": sha256(model_path), "base_mva": system.config.mva, "generators": rows,
               "bus_ids": system.Bus.idx.v, "bus_voltage_pu": system.Bus.v.v.tolist()})
    return rows


def _diagnostic_channels(system, time_s):
    arrays, index = {}, {}
    requested = {"REGCP1": ("Pe", "Qe", "Ipout", "Iqout_y", "vd", "vq"),
                 "PLL2": ("am", "PI_y", "PI_xi"),
                 "REECB1": ("Ipcmd", "Iqcmd", "Pord", "Pref", "Qref", "IpHL_y", "IqHL_y", "Iqinj_y")}
    for model_name, names in requested.items():
        model = getattr(system, model_name)
        if not model.n:
            continue
        for name in names:
            variable = getattr(model, name, None)
            if variable is None or not hasattr(variable, "a"):
                continue
            frame = system.TDS.get_timeseries(variable)
            if not np.array_equal(frame.index.to_numpy(dtype=float), time_s):
                raise ValueError(f"Diagnostic channel time alignment mismatch: {model_name}.{name}")
            key = f"{model_name}_{name}"
            arrays[key] = frame.to_numpy(dtype=float)
            index[key] = {"model_ids": list(map(str, model.idx.v)), "variable": f"{model_name}.{name}",
                          "unit": "rad" if model_name == "PLL2" and name == "am" else "system-base pu / model variable"}
    if "PLL2_PI_y" in arrays:
        arrays["PLL2_frequency_hz"] = (1 + arrays["PLL2_PI_y"]) * np.asarray(system.PLL2.fn.v)
        index["PLL2_frequency_hz"] = {"model_ids": list(map(str, system.PLL2.idx.v)), "unit": "Hz",
                                      "definition": "fn * (1 + PI_y); diagnostic only"}
    return arrays, index


def run_scenario_smoke(scenario, model_path, output, frozen_solver_config):
    """One fresh no-fault run; no recovery, no model tuning, no fault events."""
    started = time.perf_counter()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(output / "run.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    logging.getLogger().addHandler(handler)
    diagnostics = RunDiagnostics(no_fault=True, fault_cleared=True)
    summary = {"scenario_id": scenario["scenario_id"], "model_sha256": sha256(model_path),
               "model_file": Path(model_path).name, "renewable_buses": scenario["renewable_buses"],
               "num_synch_generators": scenario["num_synch_generators"],
               "num_renewable_generators": scenario["num_renewable_generators"],
               "no_fault": True, "renewable_P_MW": None, "total_generation_P_MW": None,
               "renewable_share_pct": None, "smoke_passed": False, "tds_run_called": False}
    system = trajectory = None
    extras, channel_index = {}, {}
    try:
        system = load_system(model_path)
        if (system.GENROU.n, system.REGCP1.n, system.PLL2.n, system.REECB1.n) != (
                scenario["num_synch_generators"], scenario["num_renewable_generators"],
                scenario["num_renewable_generators"], scenario["num_renewable_generators"]):
            raise ValueError("Scenario dynamic-source/controller counts differ from manifest")
        if system.Fault.n != 0:
            raise ValueError("Smoke models must not contain Fault devices")
        diagnostics.pflow_converged = bool(system.PFlow.run() and system.PFlow.converged)
        if not diagnostics.pflow_converged:
            diagnostics.simulation_status = SimulationStatus.PFLOW_FAILED
            diagnostics.termination_reason = "PFLOW_NON_CONVERGENCE"
            raise RuntimeError("Scenario PFlow failed")
        # Capture while StaticGen is still online, before dynamic replacement disables it.
        generation = pflow_generations(system)
        ren = [{"gen": idx, "u": int(system.REGCP1.u.v[uid])}
               for uid, idx in enumerate(system.REGCP1.gen.v)]
        summary.update(renewable_share(generation, ren))
        summary["static_generation_after_pflow"] = generation
        summary["pflow_bus_ids"] = list(map(int, system.Bus.idx.v))
        summary["pflow_bus_v_pu"] = system.Bus.v.v.tolist()
        summary["pflow_bus_angle_rad"] = system.Bus.a.v.tolist()
        summary["pflow_config"] = system.PFlow.config.as_dict(refresh=True)
        for key, value in frozen_solver_config.items():
            setattr(system.TDS.config, key, value)
        system.TDS.set_method("trapezoid")
        summary["solver_config"] = system.TDS.config.as_dict(refresh=True)
        if summary["solver_config"] != frozen_solver_config:
            raise ValueError("Actual TDS configuration differs from frozen solver settings")
        system.TDS.init()
        diagnostics.tds_initialized = bool(system.TDS.initialized)
        if not diagnostics.tds_initialized:
            diagnostics.simulation_status = SimulationStatus.INITIALIZATION_FAILED
            diagnostics.termination_reason = "TDS_INITIALIZATION_FAILED"
            raise RuntimeError("Scenario TDS initialization failed")
        summary["initial_renewable_p0_pu"] = np.asarray(system.REGCP1.p0.v).tolist()
        summary["initial_renewable_q0_pu"] = np.asarray(system.REGCP1.q0.v).tolist()
        summary["initial_renewable_Sn_MVA"] = np.asarray(system.REGCP1.Sn.v).tolist()
        summary["initial_power_fractions"] = {"gammap": np.asarray(system.REGCP1.gammap.v).tolist(),
                                               "gammaq": np.asarray(system.REGCP1.gammaq.v).tolist()}
        summary["tds_run_called"] = True
        diagnostics.tds_return = bool(system.TDS.run(no_summary=True))
        diagnostics.busted = bool(system.TDS.busted)
        diagnostics.exit_code = int(system.exit_code)
        diagnostics.err_msg = str(system.TDS.err_msg or "")
        if not diagnostics.tds_return or diagnostics.busted or diagnostics.exit_code or diagnostics.err_msg:
            diagnostics.simulation_status = SimulationStatus.NUMERICAL_FAILURE
            diagnostics.termination_reason = "NOFAULT_TDS_ABNORMAL_TERMINATION"
            diagnostics.numerical_failure = True
            diagnostics.failure_time_s = float(system.dae.t)
        else:
            diagnostics.simulation_status = SimulationStatus.COMPLETED
            diagnostics.termination_reason = "OBSERVATION_END_REACHED"
        trajectory = extract_trajectory(system)
        extras, channel_index = _diagnostic_channels(system, trajectory.time_s)
        extras["dae_states"] = system.dae.ts.x.copy()
        extras["dae_algebraic"] = system.dae.ts.y.copy()
        summary["finite_all_states"] = bool(np.isfinite(extras["dae_states"]).all())
        summary["finite_all_algebraic"] = bool(np.isfinite(extras["dae_algebraic"]).all())
        summary["finite_renewable_diagnostics"] = bool(all(np.isfinite(value).all() for value in extras.values()))
        summary["last_stored_time_s"] = float(trajectory.time_s[-1])
        summary["bus_voltage_range_pu"] = [float(trajectory.bus_voltage_pu.min()), float(trajectory.bus_voltage_pu.max())]
        summary["end_algebraic_residual_max"] = float(np.max(np.abs(system.dae.g)))
        summary["SG_delta_range_rad"] = [float(trajectory.delta_rad.min()), float(trajectory.delta_rad.max())]
        summary["SG_omega_range_pu"] = [float(trajectory.omega_pu.min()), float(trajectory.omega_pu.max())]
        if system.REGCP1.n:
            expected = {row["static_gen_id"]: row for row in generation}
            expected_p = np.array([expected[idx]["P0_MW"] for idx in system.REGCP1.gen.v])
            expected_q = np.array([expected[idx]["Q0_Mvar"] for idx in system.REGCP1.gen.v])
            pe_mw, qe_mvar = extras["REGCP1_Pe"] * system.config.mva, extras["REGCP1_Qe"] * system.config.mva
            summary["renewable_P_range_MW"] = [[float(col.min()), float(col.max())] for col in pe_mw.T]
            summary["renewable_Q_range_Mvar"] = [[float(col.min()), float(col.max())] for col in qe_mvar.T]
            summary["initial_renewable_P_mismatch_MW"] = (pe_mw[0] - expected_p).tolist()
            summary["initial_renewable_Q_mismatch_Mvar"] = (qe_mvar[0] - expected_q).tolist()
            summary["renewable_initial_power_matches_pflow"] = bool(np.allclose(pe_mw[0], expected_p, atol=1e-3, rtol=0)
                and np.allclose(qe_mvar[0], expected_q, atol=1e-3, rtol=0))
            summary["PLL_frequency_range_hz"] = [float(extras["PLL2_frequency_hz"].min()), float(extras["PLL2_frequency_hz"].max())]
        else:
            summary["renewable_initial_power_matches_pflow"] = True
    except Exception as exc:
        logging.exception("Scenario %s smoke failed", scenario["scenario_id"])
        diagnostics.execution_error = f"{type(exc).__name__}: {exc}"
        summary["traceback"] = traceback.format_exc()
        if diagnostics.simulation_status not in (SimulationStatus.PFLOW_FAILED, SimulationStatus.INITIALIZATION_FAILED):
            diagnostics.simulation_status = SimulationStatus.EXECUTION_FAILED
            diagnostics.termination_reason = "SCENARIO_SMOKE_EXCEPTION"
        diagnostics.numerical_failure = True
        if system is not None:
            diagnostics.failure_time_s = float(system.dae.t)
    finally:
        logging.getLogger().removeHandler(handler)
        handler.close()
    assessment, derived = assess_trajectory(trajectory, diagnostics, angle_limit_deg=180., observation_end_s=8.)
    summary.update(asdict(diagnostics))
    summary.update(assessment)
    summary["smoke_passed"] = bool(summary["stability_status"] == "STABLE"
        and summary.get("finite_all_states") and summary.get("finite_all_algebraic")
        and summary.get("finite_renewable_diagnostics")
        and summary.get("renewable_initial_power_matches_pflow"))
    summary["runtime_s"] = time.perf_counter() - started
    summary["COI_generator_ids"] = list(map(str, trajectory.generator_ids)) if trajectory else []
    save_fault_result(output, FaultResult(summary, trajectory, {**derived, **extras}))
    write_json(output / "diagnostic_channels.json", channel_index)
    return summary
