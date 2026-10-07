"""Run a single official IEEE39 three-phase bus fault, or no-fault smoke."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from ieee39ts.io import configure_logging, new_output_directory, read_settings, save_fault_result
from ieee39ts.simulation import run_fault_case


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bus", type=int, help="Official IEEE39 bus (default: config bus 16)")
    parser.add_argument("--clear-time", type=float, default=0.125,
                        help="Fault duration in seconds; ANDES tc = 1 + this value")
    parser.add_argument("--no-fault", action="store_true", help="Disable all timed events and run an 8 s smoke")
    parser.add_argument("--config", type=Path, default=ROOT / "configs/baseline.json")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        settings = read_settings(args.config, bus=args.bus)
        settings.validate_duration(args.clear_time)
        label = "nofault" if args.no_fault else f"bus{settings.bus}_fault"
        output = new_output_directory(args.output or ROOT / "results" / f"{label}_{datetime.now():%Y%m%d_%H%M%S_%f}")
        configure_logging(output)
        result = run_fault_case(settings, args.clear_time, no_fault=args.no_fault)
        save_fault_result(output, result)
    except (ValueError, FileNotFoundError) as exc:
        parser.error(str(exc))
    keys = ("simulation_status", "stability_status", "termination_reason", "clearing_duration_s",
            "max_angle_separation_deg", "max_speed_deviation_pu", "last_valid_time_s", "runtime_s")
    print(json.dumps({**{k: result.summary[k] for k in keys}, "output": str(output.resolve())}, indent=2))
    return 0 if result.summary["stability_status"] != "NON_CONVERGENT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
