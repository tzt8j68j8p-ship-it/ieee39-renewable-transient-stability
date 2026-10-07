"""Batch orchestration and comparable reference metrics; reuse the Day 1 search."""
from dataclasses import dataclass
import csv
import json
import math
from pathlib import Path
import time

import numpy as np

from .cct import search_cct
from .io import write_json
from .types import FaultResult, SearchSettings

REFERENCE_DURATION_S = 0.125
DEFAULT_BUSES = (1, 3, 4, 6, 8, 10, 14, 16, 17, 21, 23, 25, 26, 29, 37)
SUMMARY_FIELDS = (
    "fault_id", "fault_bus", "model_id", "search_status", "cct_estimate_s",
    "stable_lower_s", "unstable_upper_s", "interval_width_s", "cct_reason",
    "trial_count", "cct_runtime_s", "metrics_clear_duration_s",
    "reference_stability_status", "reference_simulation_status",
    "max_angle_separation_deg", "max_speed_deviation_pu", "min_bus_voltage_pu",
    "fault_bus_voltage_min_pu", "reference_runtime_s",
    "reference_reason", "reference_last_valid_time_s", "reference_tail_invalid",
    "reference_execution_error", "failed_clearing_time_s",
    "reference_directory", "cct_directory",
)


@dataclass(frozen=True)
class BatchSettings:
    fault_buses: tuple[int, ...] = DEFAULT_BUSES
    metrics_clear_duration_s: float = REFERENCE_DURATION_S
    search: SearchSettings = SearchSettings(tc_max_s=25 / 128)
    model_id: str = "ieee39_official"

    def __post_init__(self):
        if not self.fault_buses:
            raise ValueError("fault_buses must not be empty")
        for bus in self.fault_buses:
            if isinstance(bus, bool) or not isinstance(bus, int) or not 1 <= bus <= 39:
                raise ValueError(f"Invalid fault bus {bus!r}: require an integer from 1 to 39")
        if len(set(self.fault_buses)) != len(self.fault_buses):
            raise ValueError("Duplicate fault bus in configuration")
        if self.metrics_clear_duration_s != REFERENCE_DURATION_S:
            raise ValueError("Day 2 reference metrics require a common 0.125 s duration")
        self.search.grid_ticks()
        if (self.search.time_step_s, self.search.tc_min_s, self.search.tc_max_s,
                self.search.tolerance_s) != (1 / 128, 4 / 128, 25 / 128, 1 / 128):
            raise ValueError("Day 2 fixes grid=1/128 s, CCT window=[0.03125, 0.1953125] s and one-grid tolerance")
        if self.model_id != "ieee39_official":
            raise ValueError("Day 2 requires ieee39_official")


def read_batch_settings(path: Path) -> BatchSettings:
    values = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    return BatchSettings(tuple(values["fault_buses"]), values["metrics_clear_duration_s"],
                         SearchSettings(**values["cct"]), values["model_id"])


def _finite(value):
    return float(value) if value is not None and math.isfinite(value) else None


def reference_metrics(result: FaultResult, bus: int, duration_s: float) -> dict:
    """Voltage minima use the same accepted valid prefix as Day 1 rotor metrics."""
    summary = result.summary
    if duration_s != REFERENCE_DURATION_S or summary.get("clearing_duration_s") != duration_s:
        raise ValueError("Reference result must come from the common 0.125 s fault")
    if summary.get("fault_bus") != bus:
        raise ValueError("Reference result fault_bus does not match the requested bus")
    voltage_min = fault_voltage_min = None
    if result.trajectory is not None:
        trajectory = result.trajectory
        mask = np.asarray(result.derived_arrays["valid_mask"], dtype=bool)
        if mask.shape != trajectory.time_s.shape:
            raise ValueError("Reference valid_mask and time dimensions differ")
        valid_voltages = trajectory.bus_voltage_pu[mask]
        matches = np.flatnonzero(np.asarray(trajectory.bus_ids).astype(str) == str(bus))
        if len(matches) != 1:
            raise ValueError("Reference trajectory must uniquely identify the fault bus voltage")
        if valid_voltages.size:
            if not np.isfinite(valid_voltages).all():
                raise ValueError("Reference valid_mask contains non-finite voltage samples")
            voltage_min = float(np.min(valid_voltages))
            fault_voltage_min = float(np.min(valid_voltages[:, matches[0]]))
    return {
        "metrics_clear_duration_s": duration_s,
        "reference_stability_status": summary["stability_status"],
        "reference_simulation_status": summary["simulation_status"],
        "max_angle_separation_deg": _finite(summary.get("max_angle_separation_deg")),
        "max_speed_deviation_pu": _finite(summary.get("max_speed_deviation_pu")),
        "min_bus_voltage_pu": voltage_min,
        "fault_bus_voltage_min_pu": fault_voltage_min,
        "reference_runtime_s": _finite(summary.get("runtime_s")),
        "reference_reason": summary.get("assessment_reason", summary.get("termination_reason")),
        "reference_last_valid_time_s": summary.get("last_valid_time_s"),
        "reference_tail_invalid": summary.get("tail_invalid"),
        "reference_execution_error": summary.get("execution_error"),
        "reference_directory": summary.get("reference_directory"),
    }


def sort_results(rows):
    """Keep unresolved estimates null and retain every configured fault position."""
    cleaned = [dict(row) for row in rows]
    for row in cleaned:
        if row["search_status"] != "RESOLVED":
            row["cct_estimate_s"] = None
        elif _finite(row["cct_estimate_s"]) is None:
            raise ValueError("RESOLVED row requires a finite CCT estimate")
    return sorted(cleaned, key=lambda row: (
        row["search_status"] != "RESOLVED",
        row["cct_estimate_s"] if row["search_status"] == "RESOLVED" else math.inf,
        row["fault_bus"],
    ))


def cct_ranking(rows):
    return [row for row in sort_results(rows) if row["search_status"] == "RESOLVED"]


def severity_ranking(rows):
    valid = [row for row in rows
             if row["reference_stability_status"] in ("STABLE", "UNSTABLE")
             and _finite(row["max_angle_separation_deg"]) is not None]
    return sorted(valid, key=lambda row: (-row["max_angle_separation_deg"], row["fault_bus"]))


def write_batch_summary(directory: Path, rows, *, metadata=None):
    ordered = sort_results(rows)
    report = {"metadata": metadata or {}, "results": ordered,
              "rankings": {"cct": [r["fault_id"] for r in cct_ranking(ordered)],
                           "reference_severity": [r["fault_id"] for r in severity_ranking(ordered)]}}
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    write_json(directory / "batch_summary.json", report)
    temporary = directory / "batch_summary.csv.tmp"
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(ordered)
    temporary.replace(directory / "batch_summary.csv")
    return report


def run_batch(settings: BatchSettings, run_case, *, on_reference=None, on_trial=None,
              on_search=None, on_checkpoint=None) -> dict:
    """Run each reference once, then reuse search_cct per bus without expansion.

    run_case(bus, duration_s) returns FaultResult. Persistence callbacks receive
    each result before checkpointing; this module does not import ANDES.
    """
    started = time.perf_counter()
    rows = [{**dict.fromkeys(SUMMARY_FIELDS), "fault_id": f"bus{bus:02d}",
             "fault_bus": bus, "model_id": settings.model_id,
             "search_status": "PENDING", "trial_count": 0,
             "metrics_clear_duration_s": settings.metrics_clear_duration_s}
            for bus in settings.fault_buses]
    searches = {}

    def checkpoint():
        if on_checkpoint:
            on_checkpoint(sort_results(rows))

    checkpoint()
    for row in rows:
        bus = row["fault_bus"]
        reference_started = time.perf_counter()
        try:
            result = run_case(bus, settings.metrics_clear_duration_s)
            if on_reference:
                on_reference(bus, result)
            row.update(reference_metrics(result, bus, settings.metrics_clear_duration_s))
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            row.update(reference_stability_status="NON_CONVERGENT",
                       reference_simulation_status="EXECUTION_FAILED",
                       reference_reason="REFERENCE_EXECUTION_EXCEPTION",
                       reference_execution_error=error,
                       reference_runtime_s=time.perf_counter() - reference_started)
            write_result = FaultResult({"fault_bus": bus, "clearing_duration_s": settings.metrics_clear_duration_s,
                                       "stability_status": "NON_CONVERGENT", "simulation_status": "EXECUTION_FAILED",
                                       "termination_reason": "REFERENCE_EXECUTION_EXCEPTION",
                                       "execution_error": error, "runtime_s": row["reference_runtime_s"]})
            if on_reference:
                on_reference(bus, write_result)
        checkpoint()

    for row in rows:
        bus = row["fault_bus"]
        search = search_cct(settings.search, lambda duration: run_case(bus, duration),
                            on_trial=(lambda record, bus=bus: on_trial(bus, record)) if on_trial else None)
        # Public batch reason states the finite search-window limitation explicitly.
        search["core_reason"] = search["reason"]
        if search["reason"] == "NO_UNSTABLE_ENDPOINT":
            search["reason"] = "NO_UNSTABLE_ENDPOINT_IN_RANGE"
        search["fault_bus"] = bus
        search["model_id"] = settings.model_id
        if on_search:
            on_search(bus, search)
        searches[str(bus)] = search
        row.update({key: search[key] for key in (
            "search_status", "cct_estimate_s", "stable_lower_s", "unstable_upper_s",
            "interval_width_s", "trial_count", "failed_clearing_time_s")})
        row["cct_reason"] = search["reason"]
        row["cct_runtime_s"] = search["runtime_s"]
        row["cct_directory"] = f"bus{bus:02d}/cct"
        checkpoint()
    return {"results": sort_results(rows), "searches": searches,
            "runtime_s": time.perf_counter() - started}
