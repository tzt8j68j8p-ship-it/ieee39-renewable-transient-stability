"""Run four no-fault scenario smokes; no CCT or fault batches."""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ieee39ts.io import configure_logging, new_output_directory, write_json
from ieee39ts.scenario_smoke import run_scenario_smoke
from ieee39ts.scenarios import sha256


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "cases/renewable/manifest.json")
    parser.add_argument("--output", type=Path, default=ROOT / "results/day3a/scenario_smoke")
    args = parser.parse_args()
    started = time.perf_counter()
    output = new_output_directory(args.output)
    configure_logging(output)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    config = manifest["configuration"]
    frozen = json.loads((ROOT / config["frozen_solver_summary"]).read_text(encoding="utf-8"))["solver_config"]
    report = {"scenarios": [], "no_fault_TDS_attempts": 0, "fault_TDS_attempts": 0,
              "source_manifest_sha256": sha256(args.manifest), "complete": False}
    for scenario in manifest["scenarios"]:
        path = args.manifest.parent / scenario["file"]
        if sha256(path) != scenario["sha256"]:
            raise ValueError(f"Model hash mismatch: {scenario['scenario_id']}")
        summary = run_scenario_smoke(scenario, path, output / scenario["scenario_id"], frozen)
        report["no_fault_TDS_attempts"] += int(summary["tds_run_called"])
        report["scenarios"].append(summary)
        write_json(output / "scenario_summary.json", report)
        print(f"{scenario['scenario_id']}: PFlow={summary['pflow_converged']}; init={summary['tds_initialized']}; "
              f"smoke={summary['smoke_passed']}; share={summary['renewable_share_pct']}; "
              f"simulation={summary['simulation_status']}", flush=True)
    report.update(complete=True, runtime_s=time.perf_counter() - started)
    write_json(output / "scenario_summary.json", report)
    return 0 if all(row["smoke_passed"] for row in report["scenarios"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
