"""Reuse accepted S0/S1 and run exactly the two new no-fault main smokes."""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ieee39ts.io import configure_logging, new_output_directory, write_json
from ieee39ts.main_scenarios import reuse_decision
from ieee39ts.scenario_smoke import run_scenario_smoke
from ieee39ts.scenarios import sha256


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "cases/renewable/main/manifest.json")
    parser.add_argument("--output", type=Path, default=ROOT / "results/day3a5/main_smoke")
    args = parser.parse_args()
    started = time.perf_counter()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    frozen = json.loads((ROOT / manifest["configuration"]["frozen_solver_summary"]).read_text(encoding="utf-8"))["solver_config"]
    decisions = []
    for row in manifest["scenarios"]:
        path = args.manifest.parent / row["file"]
        if sha256(path) != row["sha256"] or 39 in row["renewable_buses"] or 31 in row["renewable_buses"]:
            raise ValueError("Invalid main model hash or replacement plan")
        decision = reuse_decision(ROOT, row, path, frozen)
        if row["scenario_id"] in ("S0", "S1") and not decision["reused"]:
            raise ValueError(f"Reuse identity failed: {decision['reasons']}; no automatic rerun")
        decisions.append({"scenario_id": row["scenario_id"], **decision})
    output = new_output_directory(args.output)
    configure_logging(output)
    (output / "source_manifest.json").write_bytes(args.manifest.read_bytes())
    write_json(output / "cache_decisions.json", decisions)
    report = {"scenarios": [], "new_no_fault_TDS_calls": 0, "reused_no_fault_cases": 0,
              "fault_TDS_calls": 0, "cct_calls": 0, "complete": False,
              "source_manifest_sha256": sha256(args.manifest)}
    for row, decision in zip(manifest["scenarios"], decisions):
        if decision["reused"]:
            summary = deepcopy(json.loads((ROOT / decision["summary_reference"]).read_text(encoding="utf-8")))
            summary.update(smoke_mode="REUSED_DAY3A", tds_run_called_this_stage=False,
                           reused_summary_reference=decision["summary_reference"], reused_summary_sha256=decision["summary_sha256"])
            source_dir = (ROOT / decision["summary_reference"]).parent
            summary["trajectory_file"] = Path(os.path.relpath(source_dir / "trajectory.npz", output / row["scenario_id"])).as_posix()
            summary["reused_diagnostic_channels_reference"] = str((source_dir / "diagnostic_channels.json").relative_to(ROOT)).replace("\\", "/")
            summary["historical_tds_run_called"] = summary["tds_run_called"]
            summary["tds_run_called"] = False
            write_json(output / row["scenario_id"] / "summary.json", summary)
            report["reused_no_fault_cases"] += 1
        else:
            summary = run_scenario_smoke(row, args.manifest.parent / row["file"], output / row["scenario_id"], frozen)
            summary.update(smoke_mode="MEASURED_DAY3A5", tds_run_called_this_stage=summary["tds_run_called"])
            report["new_no_fault_TDS_calls"] += int(summary["tds_run_called"])
        summary.update({key:row[key] for key in ("remaining_sg_M_sum", "removed_sg_M_sum", "removed_M_fraction_pct", "original_sg_M_sum")})
        report["scenarios"].append(summary)
        write_json(output / "scenario_summary.json", report)
        print(f"{row['scenario_id']}: {summary['smoke_mode']}; share={summary['renewable_share_pct']}; "
              f"PFlow={summary['pflow_converged']}; init={summary['tds_initialized']}; smoke={summary['smoke_passed']}", flush=True)
    report.update(complete=True, runtime_s=time.perf_counter()-started)
    write_json(output / "scenario_summary.json", report)
    return 0 if all(row["smoke_passed"] for row in report["scenarios"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
