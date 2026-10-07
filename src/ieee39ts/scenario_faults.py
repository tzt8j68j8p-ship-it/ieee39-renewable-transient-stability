"""Fresh-load fault adapter for immutable Main models; frozen core is reused."""
from dataclasses import asdict
import logging
import math
import os
from pathlib import Path
import time
import traceback

import numpy as np

from .scenario_smoke import _diagnostic_channels
from .scenarios import sha256
from .simulation import extract_trajectory
from .stability import assess_trajectory
from .types import FaultResult, RunDiagnostics, SimulationSettings, SimulationStatus

ROOT = Path(__file__).resolve().parents[2]


def run_main_fault(scenario, model_path, bus, duration, frozen_solver):
    """Day1 fault flow with manifest counts, plus existing converter diagnostics."""
    settings = SimulationSettings(bus=bus)
    settings.validate_duration(duration)
    if duration > .5 or duration*128 != round(duration*128):
        raise ValueError("Day3B duration must be on the 1/128 grid and <=0.5 s")
    started = time.perf_counter()
    clear = settings.fault_start_s + duration
    diagnostic = RunDiagnostics()
    summary = {"scenario_id": scenario["scenario_id"], "model_id": "adapted_main_"+scenario["scenario_id"],
               "model_sha256": sha256(model_path), "model_file": Path(model_path).name,
               "fault_bus": bus, "clearing_duration_s": duration, "fault_clear_absolute_s": clear,
               "fault_type": "THREE_PHASE_TO_GROUND_BUS_FAULT", "post_fault_topology": "Original network retained; no line trip",
               "settings": asdict(settings), "tds_run_called": False, "diagnostic_extraction_error": None}
    system = trace = None
    extras, channel_index = {}, {}
    cache = ROOT / ".cache"
    os.environ["MPLCONFIGDIR"] = str(cache / "matplotlib")
    os.environ["NUMBA_CACHE_DIR"] = str(cache / "numba")
    stage = "LOAD_SETUP"
    try:
        import andes
        if andes.__version__ != "2.0.0":
            raise RuntimeError("Require accepted ANDES 2.0.0")
        system = andes.load(str(model_path), setup=False, no_undill=True, default_config=True,
                            no_output=True, pycode_path=str(cache / "andes/pycode"))
        system.prepare(quick=True, incremental=True, nomp=True)
        for event in system.TimedEvent.models.values():
            for idx in event.idx.v:
                event.set("u", idx, value=0)
        system.add("Fault", bus=bus, tf=1., tc=clear, xf=1e-4)
        if not system.setup():
            raise RuntimeError("System setup failed")
        if (system.Bus.n, system.GENROU.n, system.REGCP1.n) != (39, scenario["num_synch_generators"], scenario["num_renewable_generators"]):
            raise ValueError("Main dynamic-source counts differ from immutable manifest")
        if summary["model_sha256"] != scenario["sha256"]:
            raise ValueError("Immutable main model hash changed")
        stage = "PFLOW"
        diagnostic.pflow_converged = bool(system.PFlow.run() and system.PFlow.converged)
        if not diagnostic.pflow_converged:
            diagnostic.simulation_status = SimulationStatus.PFLOW_FAILED
            diagnostic.termination_reason = "PFLOW_NON_CONVERGENCE"
            diagnostic.numerical_failure = True
        else:
            for key, value in frozen_solver.items():
                setattr(system.TDS.config, key, value)
            system.TDS.set_method("trapezoid")
            summary["solver_config"] = system.TDS.config.as_dict(refresh=True)
            if summary["solver_config"] != frozen_solver:
                raise ValueError("Actual solver differs from frozen configuration")
            stage = "INITIALIZATION"
            system.TDS.init()
            diagnostic.tds_initialized = bool(system.TDS.initialized)
            if not diagnostic.tds_initialized:
                diagnostic.simulation_status = SimulationStatus.INITIALIZATION_FAILED
                diagnostic.termination_reason = "TDS_INITIALIZATION_FAILED"
                diagnostic.numerical_failure = True
            else:
                stage = "TDS"
                summary["tds_run_called"] = True
                diagnostic.tds_return = bool(system.TDS.run(no_summary=True))
                diagnostic.busted = bool(system.TDS.busted)
                diagnostic.exit_code = int(system.exit_code)
                diagnostic.err_msg = str(system.TDS.err_msg or "")
                message = diagnostic.err_msg.lower()
                if "violated stability criteria" in message:
                    diagnostic.simulation_status = SimulationStatus.ANGLE_CRITERION_STOP
                    diagnostic.termination_reason = "ANGLE_SEPARATION_CRITERION"
                elif not diagnostic.tds_return or diagnostic.busted or diagnostic.exit_code or diagnostic.err_msg:
                    diagnostic.simulation_status = SimulationStatus.NUMERICAL_FAILURE
                    diagnostic.termination_reason = "NEWTON_INTEGRATION_FAILURE" if any(x in message for x in ("converg", "time step", "newton")) else "TDS_ABNORMAL_TERMINATION"
                    diagnostic.numerical_failure = True
                    failure = float(system.dae.t)
                    diagnostic.failure_time_s = failure if math.isfinite(failure) else None
                else:
                    diagnostic.simulation_status = SimulationStatus.COMPLETED
                    diagnostic.termination_reason = "OBSERVATION_END_REACHED"
    except Exception as exc:
        logging.exception("Main fault failure during %s", stage)
        diagnostic.simulation_status = SimulationStatus.EXECUTION_FAILED
        diagnostic.termination_reason = stage+"_EXCEPTION"
        diagnostic.numerical_failure = True
        diagnostic.execution_error = f"{type(exc).__name__}: {exc}"
        summary["traceback"] = traceback.format_exc()
        if system is not None:
            failure = float(system.dae.t)
            diagnostic.failure_time_s = failure if math.isfinite(failure) else None
    if system is not None:
        diagnostic.exit_code = int(system.exit_code)
        diagnostic.tds_initialized = bool(system.TDS.initialized)
        diagnostic.busted = bool(system.TDS.busted)
        diagnostic.err_msg = str(system.TDS.err_msg or diagnostic.err_msg)
        try:
            trace = extract_trajectory(system)
            diagnostic.fault_cleared = bool(trace is not None and len(trace.time_s) and trace.time_s[-1] >= clear and system.Fault.uf.v[0] == 0)
            if len(system.dae.g):
                residual = float(np.max(np.abs(system.dae.g)))
                summary["end_algebraic_residual_max"] = residual if math.isfinite(residual) else None
                # Identical to the frozen Day1 fault runner's end-state quality rule.
                if diagnostic.simulation_status == SimulationStatus.COMPLETED and (not math.isfinite(residual) or residual > 1e-3):
                    diagnostic.simulation_status = SimulationStatus.NUMERICAL_FAILURE
                    diagnostic.termination_reason = "END_ALGEBRAIC_RESIDUAL_INVALID"
                    diagnostic.numerical_failure = True
                    diagnostic.failure_time_s = float(trace.time_s[-1]) if trace is not None else None
        except (ValueError, AttributeError, IndexError) as exc:
            diagnostic.simulation_status = SimulationStatus.INVALID_TRAJECTORY
            diagnostic.termination_reason = "TRAJECTORY_EXTRACTION_FAILED"
            diagnostic.execution_error = f"{type(exc).__name__}: {exc}"
            trace = None
        if trace is not None:
            try:
                extras, channel_index = _diagnostic_channels(system, trace.time_s)
                extras["dae_states"] = system.dae.ts.x.copy()
                extras["dae_algebraic"] = system.dae.ts.y.copy()
                summary["finite_diagnostic_arrays"] = bool(all(np.isfinite(a).all() for a in extras.values()))
            except Exception as exc:
                # Diagnostic extraction never supplies or changes a stability label.
                summary["diagnostic_extraction_error"] = f"{type(exc).__name__}: {exc}"
    summary["last_stored_time_s"] = float(trace.time_s[-1]) if trace is not None and len(trace.time_s) else None
    if diagnostic.simulation_status == SimulationStatus.COMPLETED and (trace is None or not np.isclose(trace.time_s[-1], 8., rtol=0, atol=1e-9)):
        diagnostic.simulation_status = SimulationStatus.EARLY_TERMINATION
        diagnostic.termination_reason = "INCOMPLETE_OBSERVATION_WINDOW"
    assessment, derived = assess_trajectory(trace, diagnostic, angle_limit_deg=180., observation_end_s=8.)
    if assessment["tail_invalid"] and diagnostic.simulation_status == SimulationStatus.COMPLETED:
        diagnostic.simulation_status = SimulationStatus.INVALID_TRAJECTORY
        diagnostic.termination_reason = "INVALID_TRAJECTORY_SAMPLE"
    summary.update(asdict(diagnostic))
    summary.update(assessment)
    summary.update(runtime_s=time.perf_counter()-started, diagnostic_channels=channel_index,
                   rotor_metrics_scope="remaining synchronous generators only")
    return FaultResult(summary, trace, {**derived, **extras})
