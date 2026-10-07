"""Run the fixed Day 2 bus scan and checkpoint CSV/JSON results."""
import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from ieee39ts.batch import DEFAULT_BUSES, read_batch_settings, run_batch, write_batch_summary
from ieee39ts.io import configure_logging, new_output_directory, read_settings, save_fault_result, save_trial_history, write_json
from ieee39ts.simulation import run_fault_case


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/fault_scan.json")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--figures", type=Path, help="Generate six figures after the batch, without extra simulations")
    args = parser.parse_args()
    started = time.perf_counter()
    try:
        config = json.loads(args.config.read_text(encoding="utf-8-sig"))
        settings = read_batch_settings(args.config)
        if settings.fault_buses != DEFAULT_BUSES:
            raise ValueError("Day 2 CLI requires the fixed 15 buses in configs/fault_scan.json")
        baseline_path = ROOT / config["simulation_config"]
        baseline = read_settings(baseline_path)
        if baseline.time_step_s != settings.search.time_step_s:
            raise ValueError("Simulation and clearing-time grids must match")
        output = new_output_directory(args.output or ROOT / "results/day2" / f"fault_scan_{datetime.now():%Y%m%d_%H%M%S}")
        figures = new_output_directory(args.figures) if args.figures else None
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    configure_logging(output)
    source_paths = list((ROOT / "src/ieee39ts").glob("*.py")) + [ROOT / "run_batch.py"]
    program_identity = {str(p.relative_to(ROOT)): sha256(p) for p in sorted(source_paths)}
    metadata = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "fault_buses": list(settings.fault_buses),
        "simulation_settings": asdict(baseline), "batch_settings": asdict(settings),
        "model_sha256": sha256(ROOT / "cases/ieee39_official.xlsx"),
        "program_identity": program_identity,
        "config_identity": {str(args.config.resolve()): sha256(args.config),
                            str(baseline_path.resolve()): sha256(baseline_path)},
        "cache_policy": "No trial-result reuse. All 15 references and 15 CCT searches are fresh; Day 1 results lack the complete cache identity.",
        "planned_reference_cases": 15, "planned_cct_searches": 15,
        "reference_metric_samples": "Day 1 valid_mask only; criterion-stopped cases have a shorter valid window",
        "complete": False,
    }
    write_json(output / "run_identity.json", metadata)
    references_finished = set()
    histories = {bus: [] for bus in settings.fault_buses}
    calls = []

    def run_case(bus, duration):
        reference = bus not in references_finished
        relative_dir = Path(f"bus{bus:02d}") / ("reference" if reference else
            f"cct/trial_{len(histories[bus])+1:02d}_{round(duration / baseline.time_step_s):03d}ticks")
        directory = output / relative_dir
        directory.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(directory / "run.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
        logging.getLogger().addHandler(handler)
        logging.info("Bus%d %s fault duration %.7f s", bus, "reference" if reference else "CCT", duration)
        calls.append({"fault_bus": bus, "clearing_duration_s": duration,
                      "purpose": "reference" if reference else "cct", "directory": relative_dir.as_posix()})
        try:
            result = run_fault_case(replace(baseline, bus=bus), duration)
            summary = result.summary
            summary["run_identity"] = {
                "model_sha256": summary["model_sha256"], "fault_bus": bus,
                "fault_type": summary["fault_type"], "fault_start_s": baseline.fault_start_s,
                "clearing_duration_s": duration, "fault_clear_absolute_s": baseline.fault_start_s + duration,
                "fault_reactance_pu": baseline.fault_reactance_pu,
                "observation_end_s": baseline.observation_end_s, "angle_limit_deg": baseline.angle_limit_deg,
                "integration_config": summary["solver_config"], "versions": summary["versions"],
                "program_identity": program_identity, "config_identity": metadata["config_identity"],
            }
            if reference:
                summary["reference_directory"] = relative_dir.as_posix()
            else:
                summary["trial_directory"] = relative_dir.name
            save_fault_result(directory, result)
            return result
        finally:
            logging.getLogger().removeHandler(handler)
            handler.close()

    def on_reference(bus, result):
        result.summary["reference_directory"] = f"bus{bus:02d}/reference"
        save_fault_result(output / result.summary["reference_directory"], result)
        references_finished.add(bus)
        print(f"REFERENCE Bus{bus}: 0.125 s -> {result.summary['stability_status']} ({result.summary['simulation_status']})", flush=True)

    def on_trial(bus, record):
        history = histories[bus]
        record.setdefault("trial_directory", f"trial_{len(history)+1:02d}_{record['clearing_ticks']:03d}ticks")
        if "run_identity" not in record:
            record["attempted_run_identity"] = {"model_sha256": metadata["model_sha256"],
                "fault_bus": bus, "clearing_duration_s": record["clearing_duration_s"],
                "simulation_settings": asdict(replace(baseline, bus=bus)),
                "program_identity": program_identity, "config_identity": metadata["config_identity"]}
            from ieee39ts.types import FaultResult
            save_fault_result(output / f"bus{bus:02d}/cct" / record["trial_directory"], FaultResult(record))
        history.append(record)
        save_trial_history(output / f"bus{bus:02d}/cct", record, history)
        print(f"CCT Bus{bus} {record['phase']}: {record['clearing_duration_s']:.7f} s -> "
              f"{record['stability_status']} ({record['simulation_status']})", flush=True)

    def on_search(bus, search):
        write_json(output / f"bus{bus:02d}/cct/cct.json", search)
        print(f"CCT Bus{bus}: {search['search_status']} / {search['reason']}", flush=True)

    def checkpoint(rows):
        metadata["runner_calls"] = len(calls)
        metadata["elapsed_s"] = time.perf_counter() - started
        write_batch_summary(output, rows, metadata=metadata)

    report = run_batch(settings, run_case, on_reference=on_reference, on_trial=on_trial,
                       on_search=on_search, on_checkpoint=checkpoint)
    metadata.update(complete=True, batch_runtime_s=report["runtime_s"],
                    actual_reference_cases=sum(call["purpose"] == "reference" for call in calls),
                    actual_cct_trials=sum(call["purpose"] == "cct" for call in calls),
                    actual_cct_searches=len(report["searches"]))
    write_json(output / "runner_calls.json", calls)
    write_batch_summary(output, report["results"], metadata=metadata)
    if figures:
        from ieee39ts.plots import generate_figures
        plot_started = time.perf_counter()
        generate_figures(output, figures, ROOT / "results/day1")
        metadata["plot_runtime_s"] = time.perf_counter() - plot_started
        metadata["figures_directory"] = str(figures.resolve())
    metadata["total_runtime_s"] = time.perf_counter() - started
    write_json(output / "run_identity.json", metadata)
    write_batch_summary(output, report["results"], metadata=metadata)
    counts = {status: sum(r["search_status"] == status for r in report["results"])
              for status in ("RESOLVED", "UNRESOLVED")}
    print(json.dumps({**counts, "output": str(output.resolve()), "runtime_s": metadata["total_runtime_s"]}, indent=2))
    # A completed batch can contain legitimate unresolved searches.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
