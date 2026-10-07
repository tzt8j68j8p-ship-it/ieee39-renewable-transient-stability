"""Regenerate Day 2 figures from persisted results; never runs TDS."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ieee39ts.io import new_output_directory
from ieee39ts.plots import generate_figures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--day1", type=Path, default=ROOT / "results/day1")
    args = parser.parse_args()
    output = new_output_directory(args.output)
    manifest = generate_figures(args.batch, output, args.day1)
    print(f"Generated {len(manifest['figures'])} figures in {output.resolve()}; no simulation calls")


if __name__ == "__main__":
    main()
