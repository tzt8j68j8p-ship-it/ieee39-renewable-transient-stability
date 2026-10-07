"""Config, persistent result files and CLI logging (no simulation side effects)."""
from dataclasses import asdict
import csv
import json
import logging
from pathlib import Path

import numpy as np

from .types import FaultResult, SimulationSettings

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def read_settings(config_path: Path, *, bus: int | None = None) -> SimulationSettings:
    values = json.loads(Path(config_path).read_text(encoding="utf-8-sig"))
    if bus is not None:
        values["bus"] = bus
    return SimulationSettings(**values)


def write_json(path: Path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def save_fault_result(directory: Path, result: FaultResult):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    if result.trajectory is not None:
        # Preserve raw accepted samples and explicitly mask unusable rows.
        np.savez_compressed(directory / "trajectory.npz", **asdict(result.trajectory),
                            **result.derived_arrays)
        result.summary["trajectory_file"] = "trajectory.npz"
    else:
        result.summary["trajectory_file"] = None
    write_json(directory / "summary.json", result.summary)


def configure_logging(directory: Path):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(directory / "run.log", mode="w", encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    stream = logging.StreamHandler()
    stream.setLevel(logging.ERROR)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
                        handlers=[file_handler, stream], force=True)
    logging.captureWarnings(True)


def save_trial_history(directory: Path, record: dict, history: list):
    directory = Path(directory)
    with (directory / "trials.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
    fields = ["phase", "clearing_ticks", "clearing_duration_s", "stability_status",
              "simulation_status", "termination_reason", "max_angle_separation_deg",
              "max_speed_deviation_pu", "last_valid_time_s", "runtime_s", "trial_directory"]
    with (directory / "trials.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(history)


def new_output_directory(path: Path):
    """Do not silently overwrite an earlier experiment with the same name."""
    path = Path(path)
    if path.exists() and any(path.iterdir()):
        raise ValueError(f"Output directory is not empty: {path}; choose a new --output")
    path.mkdir(parents=True, exist_ok=True)
    return path
