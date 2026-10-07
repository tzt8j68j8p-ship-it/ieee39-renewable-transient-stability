"""Build reproducible S0-S3 cases from local adapted baseline and pilot assets."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ieee39ts.io import configure_logging, write_json
from ieee39ts.scenarios import build_models


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/renewable_scenarios.json")
    parser.add_argument("--output", type=Path, default=ROOT / "cases/renewable")
    parser.add_argument("--audit-only", action="store_true", help="PFlow candidate table only; no TDS or model generation")
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8-sig"))
    if args.audit_only:
        from ieee39ts.scenario_smoke import audit_candidates
        output = ROOT / "results/day3a/generator_audit"
        configure_logging(output)
        rows = audit_candidates(ROOT / config["adapted_source"], ROOT / "docs/day3_generator_candidates.csv", output)
        print(json.dumps(rows, indent=2))
        return 0
    accepted_path = ROOT / config["smoke_results"] / "scenario_summary.json"
    accepted = json.loads(accepted_path.read_text(encoding="utf-8")) if accepted_path.exists() else None
    manifest = build_models(ROOT, config, args.output, smoke_report=accepted)
    write_json(args.output / "manifest.json", manifest)
    for scenario in manifest["scenarios"]:
        print(scenario["scenario_id"], scenario["renewable_buses"], scenario["sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
