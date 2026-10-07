"""Official IEEE39 fault runner, extracted from the validated single-case flow."""
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import logging
import math
import os
from pathlib import Path
import platform
import time
import traceback

import numpy as np

from .stability import assess_trajectory
from .types import FaultResult, RunDiagnostics, SimulationSettings, SimulationStatus, Trajectory

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOGGER = logging.getLogger(__name__)


def _series(system, variable, time_reference=None):
    frame = system.TDS.get_timeseries(variable)
    t = frame.index.to_numpy(dtype=float)
    if time_reference is not None and not np.array_equal(t, time_reference):
        raise ValueError(f"Time alignment failure for {variable.name}")
    return t, frame.to_numpy(dtype=float)


def extract_trajectory(system) -> Trajectory | None:
    """Extract accepted steps and map all rotor columns to setup-time M.v."""
    t, delta = _series(system, system.GENROU.delta)
    if not len(t):
        return None
    _, omega = _series(system, system.GENROU.omega, t)
    _, voltage = _series(system, system.Bus.v, t)
    active = np.flatnonzero(np.asarray(system.GENROU.u.v, dtype=bool))
    trace = Trajectory(
        time_s=t, delta_rad=delta[:, active], omega_pu=omega[:, active],
        bus_voltage_pu=voltage,
        generator_ids=np.asarray(system.GENROU.idx.v, dtype=str)[active],
        generator_bus_ids=np.asarray(system.GENROU.bus.v, dtype=int)[active],
        inertia_weights=np.asarray(system.GENROU.M.v, dtype=float)[active].copy(),
        bus_ids=np.asarray(system.Bus.idx.v, dtype=int))
    trace.validate_shapes()
    return trace


def run_fault_case(settings: SimulationSettings, clearing_duration_s: float = 0.125,
                   *, no_fault: bool = False, case_path: Path | None = None,
                   cache_dir: Path | None = None) -> FaultResult:
    """Fresh load per trial; no solver switching, recovery or hidden reruns."""
    settings.validate_duration(clearing_duration_s)
    model_path = Path(case_path or PROJECT_ROOT / "cases/ieee39_official.xlsx").resolve()
    if not model_path.is_file():
        raise FileNotFoundError(model_path)
    cache = Path(cache_dir or PROJECT_ROOT / ".cache").resolve()
    cache.mkdir(parents=True, exist_ok=True)
    os.environ["MPLCONFIGDIR"] = str(cache / "matplotlib")
    os.environ["NUMBA_CACHE_DIR"] = str(cache / "numba")
    import andes  # Pure unit tests do not need to import or run ANDES.

    if andes.__version__ != "2.0.0":
        raise RuntimeError(f"Day 1 requires ANDES 2.0.0; found {andes.__version__}")
    started = time.perf_counter()
    diagnostics = RunDiagnostics(no_fault=no_fault)
    clear_time = settings.fault_start_s + clearing_duration_s
    summary = {
        "model_id": "ieee39_official", "model_file": model_path.name,
        "model_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
        "fault_type": "NONE" if no_fault else "THREE_PHASE_TO_GROUND_BUS_FAULT",
        "fault_bus": None if no_fault else settings.bus,
        "clearing_duration_s": None if no_fault else clearing_duration_s,
        "fault_clear_absolute_s": None if no_fault else clear_time,
        "post_fault_topology": "Original network retained; no line trip",
        "settings": asdict(settings), "timings_s": {},
        "versions": {"python": platform.python_version(), "andes": andes.__version__,
                     "numpy": version("numpy"), "scipy": version("scipy"),
                     "pandas": version("pandas")},
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "accepted_sample_source": "ANDES TDS.get_timeseries; save_every=1; no interpolation",
    }
    system = None
    trace = None
    stage = "LOAD_SETUP"
    try:
        tick = time.perf_counter()
        system = andes.load(str(model_path), setup=False, no_undill=True,
                            default_config=True, no_output=True,
                            pycode_path=str(cache / "andes/pycode"))
        if system is None:
            raise RuntimeError("ANDES failed to load the bundled IEEE39 case")
        system.prepare(quick=True, incremental=True, nomp=True)
        for event_model in system.TimedEvent.models.values():
            for idx in event_model.idx.v:
                event_model.set("u", idx, value=0)
        if not no_fault:
            system.add("Fault", bus=settings.bus, tf=settings.fault_start_s,
                       tc=clear_time, xf=settings.fault_reactance_pu)
        system.setup()
        if system.Bus.n != 39 or system.GENROU.n != 10:
            raise RuntimeError("Unexpected official IEEE39 bus/generator counts")
        summary["timings_s"]["load_setup_s"] = time.perf_counter() - tick
        summary["counts"] = {"buses": int(system.Bus.n), "genrou": int(system.GENROU.n)}
        stage = "PFLOW"
        tick = time.perf_counter()
        diagnostics.pflow_converged = bool(system.PFlow.run() and system.PFlow.converged)
        summary["timings_s"]["pflow_s"] = time.perf_counter() - tick
        if not diagnostics.pflow_converged:
            diagnostics.simulation_status = SimulationStatus.PFLOW_FAILED
            diagnostics.termination_reason = "PFLOW_NON_CONVERGENCE"
            diagnostics.numerical_failure = True
        else:
            config = system.TDS.config
            config.t0 = 0.0
            config.tf = settings.observation_end_s
            config.tstep = settings.time_step_s
            config.fixt = 1
            config.shrinkt = 1  # Preserve the existing ANDES integration behavior.
            config.criteria = 1
            config.ddelta_limit = settings.angle_limit_deg
            config.no_tqdm = 1
            config.save_every = 1
            config.limit_store = 0
            system.TDS.set_method("trapezoid")
            summary["solver_config"] = config.as_dict(refresh=True)
            stage = "INITIALIZATION"
            tick = time.perf_counter()
            system.TDS.init()
            summary["timings_s"]["tds_init_s"] = time.perf_counter() - tick
            diagnostics.tds_initialized = bool(system.TDS.initialized)
            if not diagnostics.tds_initialized:
                diagnostics.simulation_status = SimulationStatus.INITIALIZATION_FAILED
                diagnostics.termination_reason = "TDS_INITIALIZATION_FAILED"
                diagnostics.numerical_failure = True
            else:
                stage = "TDS"
                tick = time.perf_counter()
                diagnostics.tds_return = bool(system.TDS.run(no_summary=True))
                summary["timings_s"]["tds_run_s"] = time.perf_counter() - tick
                diagnostics.busted = bool(system.TDS.busted)
                diagnostics.exit_code = int(system.exit_code)
                diagnostics.err_msg = str(system.TDS.err_msg or "")
                message = diagnostics.err_msg.lower()
                criterion_stop = "violated stability criteria" in message
                if criterion_stop:
                    diagnostics.simulation_status = SimulationStatus.ANGLE_CRITERION_STOP
                    diagnostics.termination_reason = "ANGLE_SEPARATION_CRITERION"
                elif (not diagnostics.tds_return or diagnostics.busted
                      or diagnostics.exit_code != 0 or diagnostics.err_msg):
                    diagnostics.numerical_failure = True
                    diagnostics.simulation_status = SimulationStatus.NUMERICAL_FAILURE
                    diagnostics.termination_reason = (
                        "NEWTON_INTEGRATION_FAILURE" if any(x in message for x in ("converg", "time step", "newton"))
                        else "TDS_ABNORMAL_TERMINATION")
                    failure_time = float(system.dae.t)
                    diagnostics.failure_time_s = failure_time if math.isfinite(failure_time) else None
                else:
                    diagnostics.simulation_status = SimulationStatus.COMPLETED
                    diagnostics.termination_reason = "OBSERVATION_END_REACHED"
    except Exception as exc:
        LOGGER.exception("Failure during %s", stage)
        diagnostics.simulation_status = SimulationStatus.EXECUTION_FAILED
        diagnostics.termination_reason = f"{stage}_EXCEPTION"
        diagnostics.numerical_failure = True
        diagnostics.execution_error = f"{type(exc).__name__}: {exc}"
        summary["traceback"] = traceback.format_exc()
        if system is not None:
            value = float(system.dae.t)
            diagnostics.failure_time_s = value if math.isfinite(value) else None

    tick = time.perf_counter()
    if system is not None:
        diagnostics.exit_code = int(system.exit_code)
        diagnostics.tds_initialized = bool(system.TDS.initialized)
        diagnostics.busted = bool(system.TDS.busted)
        diagnostics.err_msg = str(system.TDS.err_msg or diagnostics.err_msg)
        try:
            trace = extract_trajectory(system)
            diagnostics.fault_cleared = bool(
                no_fault or (trace is not None and len(trace.time_s)
                             and trace.time_s[-1] >= clear_time and system.Fault.uf.v[0] == 0))
            if len(system.dae.g):
                residual = float(np.max(np.abs(system.dae.g)))
                summary["end_algebraic_residual_max"] = residual if math.isfinite(residual) else None
                # This is an end-state diagnostic, not a per-sample residual check.
                if diagnostics.simulation_status == SimulationStatus.COMPLETED and (not math.isfinite(residual) or residual > 1e-3):
                    diagnostics.simulation_status = SimulationStatus.NUMERICAL_FAILURE
                    diagnostics.termination_reason = "END_ALGEBRAIC_RESIDUAL_INVALID"
                    diagnostics.numerical_failure = True
                    diagnostics.failure_time_s = float(trace.time_s[-1]) if trace is not None else None
        except (ValueError, AttributeError, IndexError) as exc:
            diagnostics.simulation_status = SimulationStatus.INVALID_TRAJECTORY
            diagnostics.termination_reason = "TRAJECTORY_EXTRACTION_FAILED"
            diagnostics.execution_error = f"{type(exc).__name__}: {exc}"
            trace = None
        summary["last_stored_time_s"] = float(trace.time_s[-1]) if trace is not None and len(trace.time_s) else None
    if (diagnostics.simulation_status == SimulationStatus.COMPLETED
            and (trace is None or not np.isclose(trace.time_s[-1], settings.observation_end_s, rtol=0, atol=1e-9))):
        diagnostics.simulation_status = SimulationStatus.EARLY_TERMINATION
        diagnostics.termination_reason = "INCOMPLETE_OBSERVATION_WINDOW"
    assessment, derived = assess_trajectory(trace, diagnostics,
                                            angle_limit_deg=settings.angle_limit_deg,
                                            observation_end_s=settings.observation_end_s)
    if assessment["tail_invalid"] and diagnostics.simulation_status == SimulationStatus.COMPLETED:
        diagnostics.simulation_status = SimulationStatus.INVALID_TRAJECTORY
        diagnostics.termination_reason = "INVALID_TRAJECTORY_SAMPLE"
    summary.update(asdict(diagnostics))
    summary.update(assessment)
    summary["timings_s"]["extraction_assessment_s"] = time.perf_counter() - tick
    summary["runtime_s"] = time.perf_counter() - started
    LOGGER.info("bus=%s duration=%s simulation=%s stability=%s max_sep=%s last_valid=%s",
                summary["fault_bus"], summary["clearing_duration_s"], summary["simulation_status"],
                summary["stability_status"], summary["max_angle_separation_deg"], summary["last_valid_time_s"])
    return FaultResult(summary, trace, derived)
