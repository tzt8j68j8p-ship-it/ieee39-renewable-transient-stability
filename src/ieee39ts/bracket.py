"""One bounded endpoint-discovery pass, followed by the unchanged CCT search."""
import csv
from pathlib import Path
import time

from .batch import sort_results
from .cct import search_cct
from .io import write_json
from .types import FaultResult, SearchSettings, StabilityStatus

EXTENSION_BUSES = (1, 3, 4, 8, 14, 17, 21, 23, 25, 26, 29, 37)
SEED_DURATION_S = 25 / 128
DISCOVERY_DURATIONS_S = (32 / 128, 40 / 128, 48 / 128, 64 / 128)
EXTENDED_FIELDS = (
    "fault_bus", "search_status", "cct_estimate_s", "stable_lower_s",
    "unstable_upper_s", "interval_width_s", "reason", "original_day2_status",
    "original_day2_reason", "extension_trials", "total_trial_count",
    "cct_range_statement", "failed_clearing_time_s", "last_tested_upper_s",
    "seed_revalidation_trials", "extension_runtime_s", "extension_action",
    "day2_trial_count", "source_directory",
)


def identity_matches(cached: dict, requested: dict) -> bool:
    """Exact identity equality; never ignore program/config differences."""
    return bool(cached) and cached == requested


def _trial_summary(outcome):
    summary = dict(outcome.summary if isinstance(outcome, FaultResult) else outcome)
    reported = StabilityStatus(summary["stability_status"]).value
    # Use the frozen assessor's quality metadata, without introducing thresholds.
    # Preserve its classification in the original summary and in this record.
    invalid = bool(summary.get("tail_invalid") or summary.get("quality_failure_reasons")
                   or summary.get("first_quality_failure_s") is not None)
    summary["reported_stability_status"] = reported
    summary["stability_status"] = "NON_CONVERGENT" if invalid else reported
    summary["search_rejection_reason"] = "INVALID_NUMERICAL_QUALITY_TRAJECTORY" if invalid else None
    return summary


def range_statement(report):
    if report["search_status"] == "RESOLVED":
        return f"[{report['stable_lower_s']}, {report['unstable_upper_s']}] s"
    if report["reason"] == "NO_UNSTABLE_ENDPOINT_WITHIN_0P5S":
        return ">0.5 s within the tested range (180-degree criterion, 8 s horizon)"
    failed = report.get("failed_clearing_time_s")
    if failed is not None:
        return f"UNRESOLVED due to numerical/quality/execution failure at {failed} s"
    return f"UNRESOLVED: {report['reason']}"


def discover_bracket(run_trial, *, seed=None, on_trial=None):
    """Try only 0.25, 0.3125, 0.375, 0.5 s; stop at the first failure or bracket.

    seed is optional and must already have passed an exact identity check by
    the caller. With no reusable seed, revalidate 0.1953125 s once. Newly tested
    endpoints are memoized for search_cct, so its endpoint calls add no TDS runs.
    All midpoint choices and boundary updates belong to search_cct.
    """
    started = time.perf_counter()
    records, outcomes = [], {}
    stable = unstable = failed = None
    tested_upper = None
    seed_count = 0
    binary_report = None
    endpoint_reuses = 0

    def finish(reason, *, core=None):
        lower = stable if core is None else core["stable_lower_s"]
        upper = unstable if core is None else core["unstable_upper_s"]
        report = {"search_status": "UNRESOLVED" if core is None else core["search_status"],
                  "reason": reason, "stable_lower_s": lower, "unstable_upper_s": upper,
                  "interval_width_s": None if lower is None or upper is None else upper - lower,
                  "cct_estimate_s": None if core is None else core["cct_estimate_s"],
                  "failed_clearing_time_s": failed if core is None else core["failed_clearing_time_s"],
                  "extension_trials": len(records), "seed_revalidation_trials": seed_count,
                  "last_tested_upper_s": tested_upper, "runtime_s": time.perf_counter() - started,
                  "discovery_durations_s": [r["clearing_duration_s"] for r in records if r["phase"] == "bracket_discovery"],
                  "binary_endpoint_reuses": endpoint_reuses, "binary_search": core,
                  "trials": records}
        report["cct_range_statement"] = range_statement(report)
        return report

    def evaluate(duration, phase):
        try:
            row = _trial_summary(run_trial(duration))
        except Exception as exc:
            row = {"stability_status": "NON_CONVERGENT", "reported_stability_status": "NON_CONVERGENT",
                   "simulation_status": "EXECUTION_FAILED", "termination_reason": "TRIAL_EXECUTION_EXCEPTION",
                   "execution_error": f"{type(exc).__name__}: {exc}", "search_rejection_reason": None}
        row.update(clearing_duration_s=duration, clearing_ticks=round(duration * 128), phase=phase)
        records.append(row)
        outcomes[duration] = row
        if on_trial:
            on_trial(row)
        return row["stability_status"]

    if seed is None:
        seed_count = 1
        seed_status = evaluate(SEED_DURATION_S, "seed_revalidation")
    else:
        seed_row = _trial_summary(seed)
        if seed_row.get("clearing_duration_s") != SEED_DURATION_S:
            raise ValueError("The discovery seed must be the verified 0.1953125 s endpoint")
        outcomes[SEED_DURATION_S] = seed_row
        seed_status = seed_row["stability_status"]
    if seed_status == "NON_CONVERGENT":
        failed = SEED_DURATION_S
        return finish("NON_CONVERGENT_SEED_ENDPOINT")
    if seed_status != "STABLE":
        unstable = SEED_DURATION_S
        return finish("NO_STABLE_SEED_ENDPOINT")
    stable = SEED_DURATION_S

    for duration in DISCOVERY_DURATIONS_S:
        tested_upper = duration
        status = evaluate(duration, "bracket_discovery")
        if status == "STABLE":
            stable = duration
        elif status == "UNSTABLE":
            unstable = duration
            break
        else:
            failed = duration
            return finish("NON_CONVERGENT_BRACKET_DISCOVERY")
    if unstable is None:
        return finish("NO_UNSTABLE_ENDPOINT_WITHIN_0P5S")

    def binary_trial(duration):
        nonlocal endpoint_reuses
        if duration in outcomes:
            endpoint_reuses += 1
            return {**outcomes[duration], "reused_verified_endpoint": True}
        evaluate(duration, "bisection")
        return outcomes[duration]

    binary_report = search_cct(SearchSettings(tc_min_s=stable, tc_max_s=unstable), binary_trial)
    return finish(binary_report["reason"], core=binary_report)


def _extended_row(day2_row):
    row = {key: day2_row.get(key) for key in (
        "fault_bus", "search_status", "cct_estimate_s", "stable_lower_s",
        "unstable_upper_s", "interval_width_s", "failed_clearing_time_s")}
    row.update(fault_id=day2_row["fault_id"], reason=day2_row["cct_reason"],
               original_day2_status=day2_row["search_status"], original_day2_reason=day2_row["cct_reason"],
               extension_trials=0, total_trial_count=day2_row["trial_count"],
               day2_trial_count=day2_row["trial_count"], seed_revalidation_trials=0,
               last_tested_upper_s=None, extension_runtime_s=0.,
               extension_action="RETAINED_DAY2", source_directory=day2_row.get("cct_directory"))
    row["cct_range_statement"] = range_statement(row)
    return row


def extend_day2_results(day2_rows, run_case, *, seeds=None, on_trial=None,
                        on_search=None, on_checkpoint=None):
    """Retain all rows; only the 12 eligible missing-upper cases can run TDS."""
    rows = [_extended_row(row) for row in day2_rows]
    reports = {}
    if on_checkpoint:
        on_checkpoint(sort_results(rows))
    for row in rows:
        bus = row["fault_bus"]
        if (bus not in EXTENSION_BUSES or row["original_day2_status"] != "UNRESOLVED"
                or row["original_day2_reason"] != "NO_UNSTABLE_ENDPOINT_IN_RANGE"):
            continue
        report = discover_bracket(lambda duration, bus=bus: run_case(bus, duration),
                                  seed=(seeds or {}).get(bus),
                                  on_trial=(lambda trial, bus=bus: on_trial(bus, trial)) if on_trial else None)
        row.update({key: report[key] for key in (
            "search_status", "cct_estimate_s", "stable_lower_s", "unstable_upper_s",
            "interval_width_s", "reason", "failed_clearing_time_s", "extension_trials",
            "seed_revalidation_trials", "last_tested_upper_s", "cct_range_statement")})
        row["extension_action"] = "BOUNDED_EXTENSION"
        row["total_trial_count"] = row["day2_trial_count"] + row["extension_trials"]
        row["extension_runtime_s"] = report["runtime_s"]
        row["source_directory"] = f"bus{bus:02d}"
        reports[str(bus)] = report
        if on_search:
            on_search(bus, report)
        if on_checkpoint:
            on_checkpoint(sort_results(rows))
    return {"results": sort_results(rows), "extensions": reports}


def write_extended_summary(directory: Path, rows, *, metadata=None):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    ordered = sort_results(rows)
    report = {"metadata": metadata or {}, "results": ordered,
              "cct_ranking": [r["fault_bus"] for r in ordered if r["search_status"] == "RESOLVED"]}
    write_json(directory / "cct_extended_summary.json", report)
    temporary = directory / "cct_extended_summary.csv.tmp"
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=EXTENDED_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(ordered)
    temporary.replace(directory / "cct_extended_summary.csv")
    return report
