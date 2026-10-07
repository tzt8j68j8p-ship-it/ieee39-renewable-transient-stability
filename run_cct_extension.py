"""One Day 2.5 bounded extension; retain Day 2 results and skip Bus6/10/16."""
import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import logging
from pathlib import Path
import platform
import sys
import time

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from ieee39ts.batch import DEFAULT_BUSES
from ieee39ts.bracket import (DISCOVERY_DURATIONS_S, EXTENSION_BUSES, SEED_DURATION_S,
    extend_day2_results, identity_matches, write_extended_summary)
from ieee39ts.io import (configure_logging, new_output_directory, read_settings,
    save_fault_result, save_trial_history, write_json)
from ieee39ts.simulation import run_fault_case
from ieee39ts.types import FaultResult


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--day2", type=Path, default=ROOT / "results/day2/fault_scan_20261007")
    parser.add_argument("--config", type=Path, default=ROOT / "configs/cct_extension.json")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--figures", type=Path, help="Draw only the new CCT ranking, if at least two new CCTs resolve")
    args = parser.parse_args()
    started = time.perf_counter()
    try:
        config = json.loads(args.config.read_text(encoding="utf-8-sig"))
        expected = {"fault_buses": list(EXTENSION_BUSES), "seed_duration_s": SEED_DURATION_S,
                    "discovery_durations_s": list(DISCOVERY_DURATIONS_S),
                    "simulation_config": "configs/baseline.json", "time_step_s": 1 / 128,
                    "tolerance_s": 1 / 128, "max_iterations": 12}
        if config != expected:
            raise ValueError("Day 2.5 requires the exact fixed buses, seed, four upper bounds and one-grid tolerance")
        original_path = args.day2 / "batch_summary.json"
        day2 = json.loads(original_path.read_text(encoding="utf-8-sig"))
        if not day2["metadata"]["complete"] or sorted(r["fault_bus"] for r in day2["results"]) != sorted(DEFAULT_BUSES):
            raise ValueError("Require the accepted complete 15-bus Day 2 report")
        eligible = [r["fault_bus"] for r in day2["results"] if r["search_status"] == "UNRESOLVED"
                    and r["cct_reason"] == "NO_UNSTABLE_ENDPOINT_IN_RANGE"]
        if sorted(eligible) != sorted(EXTENSION_BUSES):
            raise ValueError("Day 2 missing-upper cases do not match the fixed 12-bus extension")
        baseline_path = ROOT / config["simulation_config"]
        baseline = read_settings(baseline_path)
        if asdict(baseline) != day2["metadata"]["simulation_settings"]:
            raise ValueError("Simulation settings differ from frozen Day 2")
        for name in ("simulation.py", "stability.py", "cct.py", "types.py"):
            key = str(Path("src/ieee39ts") / name)
            if sha256(ROOT / key) != day2["metadata"]["program_identity"][key]:
                raise ValueError(f"Frozen core changed: {name}")
        output = new_output_directory(args.output or ROOT / "results/day2_5" / f"cct_extension_{datetime.now():%Y%m%d_%H%M%S}")
        figures = new_output_directory(args.figures) if args.figures else None
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    configure_logging(output)
    paths = list((ROOT / "src/ieee39ts").glob("*.py")) + [ROOT / "run_cct_extension.py", ROOT / "run_batch.py"]
    program_identity = {str(p.relative_to(ROOT)): sha256(p) for p in sorted(paths)}
    config_identity = {str(args.config.resolve()): sha256(args.config), str(baseline_path.resolve()): sha256(baseline_path)}
    versions = {"python": platform.python_version(), **{name: version(name) for name in ("andes", "numpy", "scipy", "pandas")}}
    model_sha = sha256(ROOT / "cases/ieee39_official.xlsx")
    if model_sha != day2["metadata"]["model_sha256"]:
        parser.error("Model hash differs from Day 2")
    seed_summaries, requested_seeds, seeds, decisions = {}, {}, {}, []
    for bus in EXTENSION_BUSES:
        row = next(r for r in day2["results"] if r["fault_bus"] == bus)
        cct_dir = args.day2 / row["cct_directory"]
        prior_search = json.loads((cct_dir / "cct.json").read_text(encoding="utf-8"))
        trial = next(t for t in prior_search["trials"]
                     if t["clearing_duration_s"] == SEED_DURATION_S and t["stability_status"] == "STABLE")
        source = cct_dir / trial["trial_directory"] / "summary.json"
        summary = json.loads(source.read_text(encoding="utf-8"))
        seed_summaries[bus] = summary
        requested = {**summary["run_identity"], "model_sha256": model_sha,
                     "versions": versions, "program_identity": program_identity,
                     "config_identity": config_identity}
        requested_seeds[bus] = requested
        same = identity_matches(summary["run_identity"], requested)
        differences = [key for key in requested if requested[key] != summary["run_identity"].get(key)]
        decisions.append({"fault_bus": bus, "source_summary": str(source.resolve()), "source_sha256": sha256(source),
                          "identity_match": same, "different_identity_fields": differences,
                          "action": "REUSE_DAY2_SEED" if same else "REVALIDATE_SEED_ONCE"})
        if same:
            seeds[bus] = summary
    metadata = {"created_utc": datetime.now(timezone.utc).isoformat(), "complete": False,
                "day2_source": str(args.day2.resolve()), "day2_summary_sha256": sha256(original_path),
                "config": config, "program_identity": program_identity, "config_identity": config_identity,
                "versions": versions, "model_sha256": model_sha,
                "cache_decisions": decisions, "planned_buses": list(EXTENSION_BUSES),
                "excluded_buses": [6, 10, 16], "actual_runner_calls": 0}
    write_json(output / "run_identity.json", metadata)
    write_json(output / "cache_decisions.json", decisions)
    for rel in program_identity:
        destination = output / "program_snapshot" / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / rel).read_bytes())
    calls = []
    histories = {bus: [] for bus in EXTENSION_BUSES}

    def run_case(bus, duration):
        if bus not in EXTENSION_BUSES or not SEED_DURATION_S <= duration <= .5 or duration * 128 != round(duration * 128):
            raise ValueError("Attempt outside the authorized extension buses/grid/range")
        relative = Path(f"bus{bus:02d}/trial_{len(histories[bus])+1:02d}_{round(duration * 128):03d}ticks")
        directory = output / relative
        directory.mkdir(parents=True, exist_ok=True)
        calls.append({"fault_bus": bus, "clearing_duration_s": duration, "directory": relative.as_posix()})
        handler = logging.FileHandler(directory / "run.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
        logging.getLogger().addHandler(handler)
        try:
            logging.info("Day2.5 Bus%d duration %.7f s", bus, duration)
            result = run_fault_case(replace(baseline, bus=bus), duration)
            summary = result.summary
            summary["trial_directory"] = relative.name
            summary["run_identity"] = {**requested_seeds[bus], "clearing_duration_s": duration,
                                       "fault_clear_absolute_s": baseline.fault_start_s + duration,
                                       "integration_config": summary.get("solver_config"), "versions": summary["versions"]}
            save_fault_result(directory, result)
            if summary.get("solver_config") != seed_summaries[bus]["solver_config"]:
                raise RuntimeError("Actual solver configuration differs from frozen Day 2; trial preserved")
            if summary["settings"] != asdict(replace(baseline, bus=bus)) or summary["model_sha256"] != model_sha:
                raise RuntimeError("Actual simulation settings/model differ; trial preserved")
            return result
        finally:
            logging.getLogger().removeHandler(handler)
            handler.close()

    def on_trial(bus, record):
        history = histories[bus]
        record.setdefault("trial_directory", f"trial_{len(history)+1:02d}_{record['clearing_ticks']:03d}ticks")
        directory = output / f"bus{bus:02d}" / record["trial_directory"]
        if not (directory / "summary.json").exists():
            record["attempted_run_identity"] = {**requested_seeds[bus], "clearing_duration_s": record["clearing_duration_s"],
                                                "fault_clear_absolute_s": baseline.fault_start_s + record["clearing_duration_s"]}
            save_fault_result(directory, FaultResult(record))
        history.append(record)
        calls[-1]["phase"] = record["phase"]
        save_trial_history(output / f"bus{bus:02d}", record, history)
        write_json(output / "runner_calls.json", calls)
        print(f"Bus{bus} {record['phase']}: {record['clearing_duration_s']:.7f} s -> "
              f"{record['stability_status']} ({record.get('simulation_status')})", flush=True)

    def on_search(bus, report):
        write_json(output / f"bus{bus:02d}/extension.json", report)
        print(f"Bus{bus}: {report['search_status']} / {report['reason']}", flush=True)

    def checkpoint(rows):
        metadata["actual_runner_calls"] = len(calls)
        metadata["elapsed_s"] = time.perf_counter() - started
        write_extended_summary(output, rows, metadata=metadata)

    original_rows = [{**row, "cct_directory": str((args.day2 / row["cct_directory"]).resolve())}
                     for row in day2["results"]]
    report = extend_day2_results(original_rows, run_case, seeds=seeds, on_trial=on_trial,
                                on_search=on_search, on_checkpoint=checkpoint)
    new_resolved = sum(row["search_status"] == "RESOLVED" and row["original_day2_status"] != "RESOLVED"
                       for row in report["results"])
    metadata.update(complete=True, new_resolved=new_resolved,
                    extension_runtime_s=time.perf_counter() - started,
                    seed_revalidation_calls=sum(c["phase"] == "seed_revalidation" for c in calls),
                    discovery_calls=sum(c["phase"] == "bracket_discovery" for c in calls),
                    bisection_calls=sum(c["phase"] == "bisection" for c in calls))
    write_extended_summary(output, report["results"], metadata=metadata)
    if figures and new_resolved >= 2:
        from ieee39ts.plots import plot_extended_cct_ranking
        plot_extended_cct_ranking(output, figures)
        metadata["ranking_figure"] = str((figures / "resolved_cct_ranking.png").resolve())
    else:
        metadata["ranking_figure"] = None
        metadata["ranking_skip_reason"] = "FEWER_THAN_TWO_NEW_RESOLVED" if new_resolved < 2 else "NO_FIGURES_REQUESTED"
    metadata["total_runtime_s"] = time.perf_counter() - started
    write_json(output / "run_identity.json", metadata)
    write_extended_summary(output, report["results"], metadata=metadata)
    print(json.dumps({"new_resolved": new_resolved, "total_resolved": sum(r["search_status"] == "RESOLVED" for r in report["results"]),
                      "TDS_calls": len(calls), "runtime_s": metadata["total_runtime_s"], "output": str(output.resolve())}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
