"""COI metrics and validity-first 180-degree simultaneous-angle screening."""
from collections.abc import Mapping

import numpy as np

from .types import RunDiagnostics, SimulationStatus, StabilityStatus, Trajectory


def mapped_inertias(generator_ids, inertia_by_id: Mapping) -> np.ndarray:
    """Align inertia values explicitly with the order of trajectory columns."""
    ids = list(generator_ids)
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate generator ID")
    try:
        weights = np.asarray([inertia_by_id[idx] for idx in ids], dtype=float)
    except KeyError as exc:
        raise ValueError(f"Missing inertia for generator {exc.args[0]}") from exc
    if not np.isfinite(weights).all() or np.any(weights <= 0):
        raise ValueError("Inertia weights must be finite and positive")
    return weights


def angle_metrics(delta_rad: np.ndarray, inertia_weights: np.ndarray) -> dict:
    """Use continuous GENROU delta and setup-time, system-base M (no unwrap)."""
    delta = np.asarray(delta_rad, dtype=float)
    weights = np.asarray(inertia_weights, dtype=float)
    if delta.ndim != 2 or weights.shape != (delta.shape[1],) or delta.shape[1] < 2:
        raise ValueError("Angle columns and inertia weights must match")
    if not np.isfinite(delta).all() or not np.isfinite(weights).all() or np.any(weights <= 0):
        raise ValueError("COI needs finite angles and positive finite inertia weights")
    coi = delta @ weights / weights.sum()
    relative = delta - coi[:, None]
    # A common COI offset cancels; use raw simultaneous differences to match ANDES.
    separation = np.rad2deg(delta.max(axis=1) - delta.min(axis=1))
    return {"delta_coi_rad": coi, "delta_relative_rad": relative,
            "angle_separation_deg": separation}


def assess_trajectory(trajectory: Trajectory | None, diagnostics: RunDiagnostics,
                      *, angle_limit_deg: float = 180.0,
                      observation_end_s: float = 8.0) -> tuple[dict, dict]:
    """Keep a trusted crossing even when a later part of the run fails.

    ANDES stores accepted steps. Numeric failure time and the first invalid row
    censor the data conservatively: only samples strictly before them qualify.
    A criterion stop is not a numeric failure and its crossing row is retained.
    """
    report = {"stability_status": StabilityStatus.NON_CONVERGENT.value,
              "assessment_reason": "NO_VALID_TRAJECTORY", "valid_sample_count": 0,
              "sample_count": 0, "first_angle_crossing_s": None,
              "first_quality_failure_s": None, "quality_failure_reasons": [],
              "last_valid_time_s": None, "max_angle_separation_deg": None,
              "max_speed_deviation_pu": None, "tail_invalid": False}
    if trajectory is None:
        return report, {}
    try:
        trajectory.validate_shapes()
    except ValueError as exc:
        report["assessment_reason"] = f"INVALID_TRAJECTORY_SHAPE: {exc}"
        return report, {}
    t = trajectory.time_s
    n = len(t)
    report["sample_count"] = n
    if n == 0:
        return report, {}
    masks = {
        "NONFINITE": (~np.isfinite(t) | ~np.isfinite(trajectory.delta_rad).all(axis=1)
                      | ~np.isfinite(trajectory.omega_pu).all(axis=1)
                      | ~np.isfinite(trajectory.bus_voltage_pu).all(axis=1)),
        "INVALID_VOLTAGE": ((trajectory.bus_voltage_pu < -1e-4)
                            | (trajectory.bus_voltage_pu > 2.0)).any(axis=1),
        "INVALID_TIME_ORDER": np.r_[t[0] < 0, np.diff(t) <= 0],
    }
    bad = np.logical_or.reduce(list(masks.values()))
    if diagnostics.numerical_failure:
        if diagnostics.failure_time_s is None or not np.isfinite(diagnostics.failure_time_s):
            # An unknown failure time cannot support historical physical evidence.
            masks["UNKNOWN_NUMERIC_FAILURE_TIME"] = np.ones(n, dtype=bool)
        else:
            masks["NUMERIC_FAILURE"] = t >= diagnostics.failure_time_s
        bad |= list(masks.values())[-1]
    bad_indices = np.flatnonzero(bad)
    end = int(bad_indices[0]) if bad_indices.size else n
    valid_mask = np.arange(n) < end
    if end < n:
        report["first_quality_failure_s"] = float(t[end]) if np.isfinite(t[end]) else None
        report["quality_failure_reasons"] = [k for k, v in masks.items() if v[end]]
    elif diagnostics.numerical_failure:
        report["first_quality_failure_s"] = diagnostics.failure_time_s
        report["quality_failure_reasons"] = ["NUMERIC_FAILURE_AFTER_LAST_ACCEPTED_SAMPLE"]
    if diagnostics.numerical_failure and diagnostics.failure_time_s is not None and np.isfinite(diagnostics.failure_time_s):
        first_bad = report["first_quality_failure_s"]
        if first_bad is None or diagnostics.failure_time_s < first_bad:
            report["first_quality_failure_s"] = diagnostics.failure_time_s
            report["quality_failure_reasons"] = ["NUMERIC_FAILURE"]
    report["valid_sample_count"] = end
    report["tail_invalid"] = bool(end < n or diagnostics.numerical_failure)
    derived = {"valid_mask": valid_mask,
               "delta_coi_rad": np.full(n, np.nan),
               "delta_relative_rad": np.full_like(trajectory.delta_rad, np.nan, dtype=float),
               "angle_separation_deg": np.full(n, np.nan)}
    if end:
        metrics = angle_metrics(trajectory.delta_rad[:end], trajectory.inertia_weights)
        for key, value in metrics.items():
            derived[key][:end] = value
        report["last_valid_time_s"] = float(t[end - 1])
        report["max_angle_separation_deg"] = float(metrics["angle_separation_deg"].max())
        report["max_speed_deviation_pu"] = float(np.abs(trajectory.omega_pu[:end] - 1).max())
        cross = np.flatnonzero(metrics["angle_separation_deg"] >= angle_limit_deg)
        if cross.size:
            report["first_angle_crossing_s"] = float(t[cross[0]])
    prerequisite = diagnostics.pflow_converged and diagnostics.tds_initialized
    if prerequisite and report["first_angle_crossing_s"] is not None:
        report.update(stability_status=StabilityStatus.UNSTABLE.value,
                      assessment_reason="VALID_ANGLE_SEPARATION_THRESHOLD")
    elif (prerequisite and end == n and not diagnostics.numerical_failure
          and diagnostics.simulation_status == SimulationStatus.COMPLETED
          and diagnostics.tds_return and not diagnostics.busted and diagnostics.exit_code == 0
          and not diagnostics.err_msg
          and np.isclose(t[-1], observation_end_s, rtol=0, atol=1e-9)
          and (diagnostics.fault_cleared or diagnostics.no_fault)):
        report.update(stability_status=StabilityStatus.STABLE.value,
                      assessment_reason="COMPLETED_WITHOUT_ANGLE_THRESHOLD")
    elif diagnostics.simulation_status == SimulationStatus.ANGLE_CRITERION_STOP:
        report["assessment_reason"] = "CRITERION_STOP_WITHOUT_VALID_ANGLE_EVIDENCE"
    else:
        report["assessment_reason"] = "NUMERIC_FAILURE_OR_INCOMPLETE_VALID_OBSERVATION"
    return report, derived
