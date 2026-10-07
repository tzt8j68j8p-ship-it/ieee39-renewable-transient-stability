"""Search one bus CCT on an integer clearing-time grid."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from ieee39ts.cct import search_cct
from ieee39ts.io import configure_logging, new_output_directory, read_settings, save_fault_result, save_trial_history, write_json
from ieee39ts.simulation import run_fault_case
from ieee39ts.types import SearchSettings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bus", type=int)
    parser.add_argument("--tc-min", type=float, default=4 / 128)
    parser.add_argument("--tc-max", type=float, default=32 / 128)
    parser.add_argument("--tolerance", type=float, default=1 / 128)
    parser.add_argument("--max-iterations", type=int, default=12)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/baseline.json")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        simulation_settings = read_settings(args.config, bus=args.bus)
        simulation_settings.validate_duration(args.tc_min)
        simulation_settings.validate_duration(args.tc_max)
        search_settings = SearchSettings(simulation_settings.time_step_s, args.tc_min, args.tc_max,
                                         args.tolerance, args.max_iterations)
        search_settings.grid_ticks()
        output = new_output_directory(args.output or ROOT / "results" / f"bus{simulation_settings.bus}_cct_{datetime.now():%Y%m%d_%H%M%S_%f}")
    except (ValueError, FileNotFoundError) as exc:
        parser.error(str(exc))
    configure_logging(output)
    history = []

    def run_trial(duration):
        trial_name = f"trial_{len(history)+1:02d}_{round(duration / simulation_settings.time_step_s):03d}ticks"
        result = run_fault_case(simulation_settings, duration)
        save_fault_result(output / trial_name, result)
        result.summary["trial_directory"] = trial_name
        return result

    def checkpoint(record):
        history.append(record)
        save_trial_history(output, record, history)
        print(f"{record['phase']}: {record['clearing_duration_s']:.7f} s -> "
              f"{record['stability_status']} ({record['simulation_status']})", flush=True)

    report = search_cct(search_settings, run_trial, on_trial=checkpoint)
    report["simulation_settings"] = vars(simulation_settings)
    report["model_id"] = "ieee39_official"
    write_json(output / "cct.json", report)
    keys = ("search_status", "reason", "stable_lower_s", "unstable_upper_s", "interval_width_s",
            "cct_estimate_s", "failed_clearing_time_s", "trial_count", "iterations", "runtime_s")
    print(json.dumps({**{k: report[k] for k in keys}, "output": str(output.resolve())}, indent=2))
    return 0 if report["search_status"] == "RESOLVED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
