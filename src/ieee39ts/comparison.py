"""Fixed 4x5 comparison and a thin composition of existing CCT workflows."""
import csv
import json
from pathlib import Path
import time

import numpy as np

from .batch import reference_metrics
from .bracket import DISCOVERY_DURATIONS_S, _trial_summary, discover_bracket
from .cct import search_cct
from .io import write_json
from .scenarios import sha256
from .types import FaultResult, SearchSettings

BUSES = (10, 16, 23, 25, 37)
SCENARIOS = ("S0", "S1", "S2", "S3")
FIELDS = ("scenario_id", "renewable_buses", "renewable_share_pct", "removed_M_fraction_pct", "model_sha256", "fault_bus",
          "reference_stability_status", "reference_simulation_status", "max_angle_separation_deg", "max_speed_deviation_pu",
          "min_bus_voltage_pu", "fault_bus_voltage_min_pu", "postfault_min_bus_voltage_pu", "max_abs_pll_frequency_deviation_hz",
          "search_status", "cct_estimate_s", "stable_lower_s", "unstable_upper_s", "interval_width_s", "cct_reason", "trial_count",
          "reference_runtime_s", "cct_runtime_s", "metrics_clear_duration_s", "failed_clearing_time_s", "cct_range_statement",
          "reference_reason", "reference_tail_invalid", "reference_directory", "cct_directory")


def load_main_manifest(root, path):
    root, path = Path(root), Path(path).resolve()
    if path != (root/"cases/renewable/main/manifest.json").resolve():
        raise ValueError("Only the accepted main manifest may enter Day3B")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest["scenario_class"] != "main_penetration_scenarios" or not manifest["include_in_day3b_main_heatmap"]:
        raise ValueError("Stress scenarios are excluded")
    if tuple(row["scenario_id"] for row in manifest["scenarios"]) != SCENARIOS:
        raise ValueError("Require exactly four main scenarios")
    for row in manifest["scenarios"]:
        if row["scenario_class"] != "main_penetration_scenarios" or not row["include_in_day3b_main_heatmap"] or {31,39}&set(row["renewable_buses"]):
            raise ValueError("Stress/Slack replacement cannot enter main matrix")
        if sha256(path.parent/row["file"]) != row["sha256"] or not row["smoke_passed"]:
            raise ValueError("Main model hash or accepted smoke differs")
    return manifest


def matrix(manifest):
    return [{**dict.fromkeys(FIELDS), "scenario_id": s["scenario_id"], "renewable_buses": s["renewable_buses"],
             "renewable_share_pct": s["renewable_share_pct"], "removed_M_fraction_pct": s["removed_M_fraction_pct"],
             "model_sha256": s["sha256"], "fault_bus": bus, "search_status": "PENDING", "metrics_clear_duration_s": .125,
             "trial_count": 0} for s in manifest["scenarios"] for bus in BUSES]


def cache_identity_matches(cached, requested):
    return bool(cached) and cached == requested and requested.get("model_family") == "adapted_main"


def search_cell(run_trial):
    """Verify 4/25 ticks, then compose unchanged discovery/core. No boundary loop."""
    started = time.perf_counter()
    records, memo = [], {}
    def trial(duration, phase="binary_or_discovery"):
        if duration in memo:
            return memo[duration]
        try:
            row = _trial_summary(run_trial(duration))
        except Exception as exc:
            row = {"stability_status":"NON_CONVERGENT", "simulation_status":"EXECUTION_FAILED",
                   "execution_error":f"{type(exc).__name__}: {exc}"}
        row.update(clearing_duration_s=duration, clearing_ticks=round(duration*128), comparison_phase=phase)
        memo[duration] = row
        records.append(row)
        return row
    def stopped(reason, lower=None, upper=None, failure=None):
        return {"search_status":"UNRESOLVED", "reason":reason, "stable_lower_s":lower, "unstable_upper_s":upper,
                "interval_width_s":None if lower is None or upper is None else upper-lower,
                "cct_estimate_s":None, "failed_clearing_time_s":failure}
    low = trial(4/128, "initial_lower")
    if low["stability_status"] == "NON_CONVERGENT":
        report = stopped("NON_CONVERGENT_STABLE_ENDPOINT", failure=4/128)
    elif low["stability_status"] != "STABLE":
        report = stopped("NO_STABLE_ENDPOINT", upper=4/128)
    else:
        high = trial(25/128, "initial_upper")
        if high["stability_status"] == "NON_CONVERGENT":
            report = stopped("NON_CONVERGENT_UNSTABLE_ENDPOINT", lower=4/128, failure=25/128)
        elif high["stability_status"] == "UNSTABLE":
            report = search_cct(SearchSettings(tc_max_s=25/128), trial)
        else:
            report = discover_bracket(trial, seed=high)
    report.update(trial_count=len(records), trials=records, runtime_s=time.perf_counter()-started)
    if report["search_status"] == "RESOLVED":
        report["cct_range_statement"] = f"[{report['stable_lower_s']}, {report['unstable_upper_s']}] s"
    elif report["reason"] == "NO_UNSTABLE_ENDPOINT_WITHIN_0P5S":
        report["cct_range_statement"] = "CCT > 500 ms within tested range"
    else:
        report["cct_range_statement"] = f"UNRESOLVED: {report['reason']}; failure={report.get('failed_clearing_time_s')} s"
    return report


def reference_extras(result):
    post = pll = None
    if result.trajectory is not None:
        trace = result.trajectory
        valid = result.derived_arrays["valid_mask"]
        after = valid & (trace.time_s > result.summary["fault_clear_absolute_s"] + 1e-9)
        if np.any(after):
            post = float(trace.bus_voltage_pu[after].min())
        freq = result.derived_arrays.get("PLL2_frequency_hz")
        if freq is not None and np.any(valid) and np.isfinite(freq[valid]).all():
            # Accepted PLL2.fn is 60 Hz in the immutable main models.
            pll = float(np.abs(freq[valid]-60.).max())
    return {"postfault_min_bus_voltage_pu":post, "max_abs_pll_frequency_deviation_hz":pll}


def run_comparison(manifest, run_case, *, checkpoint=None, on_search=None):
    rows = matrix(manifest)
    if checkpoint: checkpoint(rows)
    for row in rows:
        scenario = next(s for s in manifest["scenarios"] if s["scenario_id"] == row["scenario_id"])
        reference = run_case(scenario, row["fault_bus"], .125, "reference")
        row.update(reference_metrics(reference, row["fault_bus"], .125), **reference_extras(reference))
        if _trial_summary(reference)["stability_status"] == "NON_CONVERGENT":
            report = {"search_status":"UNRESOLVED", "reason":"NON_CONVERGENT_OR_INVALID_REFERENCE",
                      "stable_lower_s":None, "unstable_upper_s":None, "interval_width_s":None,
                      "cct_estimate_s":None, "failed_clearing_time_s":.125, "trial_count":0,
                      "trials":[], "runtime_s":0., "cct_range_statement":"UNRESOLVED due to failure in 125 ms reference"}
        else:
            report = search_cell(lambda duration: run_case(scenario, row["fault_bus"], duration, "cct"))
        row.update({key:report[key] for key in ("search_status","stable_lower_s","unstable_upper_s","interval_width_s","cct_estimate_s","failed_clearing_time_s","trial_count","cct_range_statement")})
        row.update(cct_reason=report["reason"],cct_runtime_s=report["runtime_s"],
                   reference_directory=f"{row['scenario_id']}/bus{row['fault_bus']:02d}/reference",
                   cct_directory=f"{row['scenario_id']}/bus{row['fault_bus']:02d}/cct")
        if on_search: on_search(row,report)
        if checkpoint: checkpoint(rows)
    return rows


def write_summary(directory, rows, metadata):
    cleaned=[]
    for original in rows:
        row=dict(original)
        if row["search_status"] != "RESOLVED": row["cct_estimate_s"]=None
        elif row["cct_estimate_s"] is None: raise ValueError("Resolved requires midpoint estimate")
        cleaned.append(row)
    directory=Path(directory)
    write_json(directory/"scenario_fault_summary.json",{"metadata":metadata,"results":cleaned})
    with (directory/"scenario_fault_summary.csv.tmp").open("w",encoding="utf-8",newline="") as handle:
        writer=csv.DictWriter(handle,fieldnames=FIELDS,extrasaction="ignore")
        writer.writeheader()
        writer.writerows({**row,"renewable_buses":','.join(map(str,row["renewable_buses"]))} for row in cleaned)
    (directory/"scenario_fault_summary.csv.tmp").replace(directory/"scenario_fault_summary.csv")
