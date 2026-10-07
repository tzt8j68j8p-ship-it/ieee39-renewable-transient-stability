"""Day3A.5 main/stress catalogue; keep original Day3A models and results intact."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ieee39ts.io import write_json
from ieee39ts.main_scenarios import build_main_models


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/renewable_main.json")
    parser.add_argument("--output", type=Path, help="New main directory; existing differing models are rejected")
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    output = args.output or ROOT / config["main_output"]
    if output.resolve() == (ROOT / "cases/renewable").resolve():
        raise ValueError("Do not write into the original Day3A model directory")
    accepted_path = ROOT / config["smoke_results"] / "scenario_summary.json"
    accepted = json.loads(accepted_path.read_text(encoding="utf-8")) if accepted_path.exists() else None
    manifest, stress = build_main_models(ROOT, config, output, accepted_report=accepted)
    write_json(output / "manifest.json", manifest)
    if args.output is None:
        write_json(ROOT / config["stress_output"] / "manifest.json", stress)
        write_json(ROOT / "cases/renewable/scenario_catalog.json", {
            "schema_version": 1, "main_manifest": "main/manifest.json", "stress_manifest": "stress/manifest.json",
            "day3b_main_heatmap_source": "main/manifest.json only", "main_scenario_ids": ["S0", "S1", "S2", "S3"],
            "original_day3a_archive": "manifest.json", "Bus39_replacements_role": "external-equivalent stress scenarios",
            "original_day3a_models_and_results_preserved": True})
    print("Topology choice: Bus", manifest["selection"]["chosen_bus"])
    for row in manifest["scenarios"]:
        print(row["scenario_id"], row["renewable_buses"], row["sha256"], row["smoke_evidence"]["mode"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
