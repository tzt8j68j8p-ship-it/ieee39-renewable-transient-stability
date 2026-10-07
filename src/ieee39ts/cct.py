"""Refactor of the validated integer clearing-grid search; no simulator import.

The original trial/record loop, integer midpoint and stable/unstable updates
are retained. Missing endpoints and numerical failures now return structured
UNRESOLVED results. Recovery, plotting and extra endpoint reruns are removed.
"""
from dataclasses import asdict
import time

from .types import FaultResult, SearchSettings, StabilityStatus


def search_cct(settings: SearchSettings, run_trial, *, on_trial=None) -> dict:
    """Bisect a verified STABLE/UNSTABLE bracket and preserve every trial."""
    low_ticks, high_ticks, tolerance_ticks = settings.grid_ticks()
    started = time.perf_counter()
    step = settings.time_step_s
    records = []
    stable_ticks = unstable_ticks = None
    failed_duration = None
    iterations = 0

    def finish(reason, resolved=False):
        lower = None if stable_ticks is None else stable_ticks * step
        upper = None if unstable_ticks is None else unstable_ticks * step
        width = None if lower is None or upper is None else upper - lower
        return {"search_status": "RESOLVED" if resolved else "UNRESOLVED",
                "reason": reason, "stable_lower_s": lower, "unstable_upper_s": upper,
                "interval_width_s": width,
                "cct_estimate_s": (lower + upper) / 2 if resolved else None,
                "failed_clearing_time_s": failed_duration, "iterations": iterations,
                "trial_count": len(records), "trials": records,
                "runtime_s": time.perf_counter() - started,
                "settings": asdict(settings),
                "assumption": "A monotonic local stability boundary within the tested bracket"}

    def trial(ticks, phase):
        duration = ticks * step
        try:
            outcome = run_trial(duration)
            row = dict(outcome.summary if isinstance(outcome, FaultResult) else outcome)
            status = StabilityStatus(row["stability_status"])
        except Exception as exc:
            status = StabilityStatus.NON_CONVERGENT
            row = {"stability_status": status.value, "simulation_status": "EXECUTION_FAILED",
                   "termination_reason": "TRIAL_EXECUTION_EXCEPTION",
                   "execution_error": f"{type(exc).__name__}: {exc}"}
        record = {**row, "phase": phase, "clearing_ticks": ticks,
                  "clearing_duration_s": duration, "stability_status": status.value}
        records.append(record)
        if on_trial is not None:
            on_trial(record)
        return status

    low_status = trial(low_ticks, "stable_endpoint")
    if low_status == StabilityStatus.NON_CONVERGENT:
        failed_duration = low_ticks * step
        return finish("NON_CONVERGENT_STABLE_ENDPOINT")
    if low_status != StabilityStatus.STABLE:
        unstable_ticks = low_ticks
        return finish("NO_STABLE_ENDPOINT")
    stable_ticks = low_ticks
    high_status = trial(high_ticks, "unstable_endpoint")
    if high_status == StabilityStatus.NON_CONVERGENT:
        failed_duration = high_ticks * step
        return finish("NON_CONVERGENT_UNSTABLE_ENDPOINT")
    if high_status != StabilityStatus.UNSTABLE:
        stable_ticks = high_ticks
        return finish("NO_UNSTABLE_ENDPOINT")
    unstable_ticks = high_ticks

    while unstable_ticks - stable_ticks > tolerance_ticks:
        if iterations >= settings.max_iterations:
            return finish("MAXIMUM_ITERATIONS_REACHED")
        midpoint_ticks = (stable_ticks + unstable_ticks) // 2
        status = trial(midpoint_ticks, "bisection")
        iterations += 1
        if status == StabilityStatus.STABLE:
            stable_ticks = midpoint_ticks
        elif status == StabilityStatus.UNSTABLE:
            unstable_ticks = midpoint_ticks
        else:
            failed_duration = midpoint_ticks * step
            return finish("NON_CONVERGENT_MIDPOINT")
    return finish("VERIFIED_BRACKET_WITHIN_TOLERANCE", resolved=True)
