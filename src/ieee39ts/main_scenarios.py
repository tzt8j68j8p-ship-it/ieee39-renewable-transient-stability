"""Main penetration catalogue over the unchanged Day3A builder and smoke runner."""
from collections import deque
from copy import deepcopy
import importlib.metadata
import json
from pathlib import Path
import platform
import tempfile

import numpy as np

from .scenarios import build_models, read_books, renewable_share, sha256

MAIN_ROLE = "main_penetration_scenarios"
STRESS_ROLE = "external-equivalent_stress_scenarios"
ASSEMBLY_VERSION = "1.0"


def shortest_bus_path(books, start, end):
    """Unweighted, undirected online-Line graph, including step-up transformers."""
    graph = {int(row["idx"]): set() for row in books["Bus"]}
    for row in books["Line"]:
        if row["u"]:
            a, b = int(row["bus1"]), int(row["bus2"])
            graph[a].add(b)
            graph[b].add(a)
    queue, seen = deque([[start]]), {start}
    while queue:
        path = queue.popleft()
        if path[-1] == end:
            return path
        for bus in sorted(graph[path[-1]]):
            if bus not in seen:
                seen.add(bus)
                queue.append(path + [bus])
    raise ValueError(f"No online topology path from Bus{start} to Bus{end}")


def choose_third_bus(books, fixed=(37, 38), candidates=(35, 32)):
    slack = {int(row["bus"]) for row in books["Slack"] if row["u"]}
    online = {int(row["bus"]) for row in books["GENROU"] if row["u"]}
    if set(candidates) & (slack | set(fixed) | {39}) or not set(candidates).issubset(online):
        raise ValueError("Third-bus candidates must be ordinary, distinct, non-Slack online SG buses")
    if len(candidates) != len(set(candidates)) or not candidates:
        raise ValueError("Need unique third-bus candidates")
    records = []
    for bus in sorted(candidates):
        paths = [shortest_bus_path(books, bus, target) for target in fixed]
        hops = [len(path)-1 for path in paths]
        records.append({"bus": bus, "target_buses": list(fixed), "paths": paths,
                        "hop_distances": hops, "minimum_distance": min(hops), "sum_distance": sum(hops)})
    winner = max(records, key=lambda row: (row["minimum_distance"], row["sum_distance"], -row["bus"]))
    return {"chosen_bus": winner["bus"], "candidate_metrics": records,
            "rule": "maximize minimum hop distance; then sum of hop distances; then smallest bus ID",
            "graph": "online Line; undirected; unweighted; includes step-up transformer edges"}


def inertia_inventory(root):
    """Read the accepted setup-time S0 GENROU weights, not raw machine-base 2H."""
    trace_path = Path(root) / "results/day3a/scenario_smoke/S0/trajectory.npz"
    with np.load(trace_path) as trace:
        rows = [{"generator_id": str(idx), "bus": int(bus), "M": float(weight)} for idx, bus, weight in
                zip(trace["generator_ids"], trace["generator_bus_ids"], trace["inertia_weights"])]
    if len(rows) != 10 or len({row["bus"] for row in rows}) != 10:
        raise ValueError("Accepted S0 inertia inventory must contain ten unique GENROU buses")
    return rows


def inertia_metrics(inventory, buses):
    by_bus = {row["bus"]: row["M"] for row in inventory}
    if len(set(buses)) != len(buses) or not set(buses).issubset(by_bus):
        raise ValueError("Inertia removal must reference unique original SG buses")
    total = sum(by_bus.values())
    removed = sum(by_bus[bus] for bus in buses)
    return {"original_sg_M_sum": total, "remaining_sg_M_sum": total-removed,
            "removed_sg_M_sum": removed, "removed_M_fraction_pct": 100*removed/total}


def reuse_decision(root, scenario, model_path, frozen_solver):
    """Require model, executed runner/core, environment/API and settings identity."""
    root = Path(root)
    if scenario["scenario_id"] not in ("S0", "S1"):
        return {"reused": False, "reasons": ["NEW_MAIN_SCENARIO"], "identity": None}
    source = root / "results/day3a/scenario_smoke" / scenario["scenario_id"] / "summary.json"
    old = json.loads(source.read_text(encoding="utf-8"))
    program = json.loads((root / "results/day3a/program_snapshot/manifest.json").read_text(encoding="utf-8"))
    verification = json.loads((root / "results/day3a/verification.json").read_text(encoding="utf-8"))
    modules = {name: sha256(root / name) for name in program}
    reasons = []
    if old["model_sha256"] != sha256(model_path) or sha256(model_path) != scenario["sha256"]:
        reasons.append("MODEL_IDENTITY_MISMATCH")
    if modules != program:
        reasons.append("RUNNER_CORE_IDENTITY_MISMATCH")
    if old["solver_config"] != frozen_solver:
        reasons.append("SOLVER_IDENTITY_MISMATCH")
    python_version, andes_version = platform.python_version(), importlib.metadata.version("andes")
    if python_version != verification["python_version"] or andes_version != verification["ANDES_version"]:
        reasons.append("ENVIRONMENT_IDENTITY_MISMATCH")
    andes_root = Path(importlib.metadata.distribution("andes").locate_file("andes"))
    api = {name: sha256(andes_root / name) for name in verification["installed_ANDES_API_sha256"]}
    if api != verification["installed_ANDES_API_sha256"]:
        reasons.append("ANDES_API_IDENTITY_MISMATCH")
    if not (old["smoke_passed"] and old["no_fault"] and old["last_stored_time_s"] == 8.
            and old["simulation_status"] == "COMPLETED" and old["stability_status"] == "STABLE"
            and old["renewable_buses"] == scenario["renewable_buses"]):
        reasons.append("PRIOR_SMOKE_NOT_APPLICABLE")
    identity = {"model_sha256": sha256(model_path), "program_sha256": modules,
                "ANDES_API_sha256": api, "python_version": python_version, "ANDES_version": andes_version,
                "solver_config": frozen_solver, "pflow_config": old["pflow_config"],
                "no_fault": True, "observation_end_s": 8.0}
    return {"reused": not reasons, "reasons": reasons or ["EXACT_CASE_IDENTITY_MATCH"],
            "summary_reference": str(source.relative_to(root)).replace("\\", "/"),
            "summary_sha256": sha256(source), "identity": identity}


def preserve_bytes(path, content):
    """Idempotent: leave an identical file untouched; reject differing model bytes."""
    path = Path(path)
    if path.exists():
        if path.read_bytes() != content:
            raise ValueError(f"Refuse to overwrite an existing model: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def build_main_models(root, config, output, *, accepted_report=None):
    """Use the original Day3A builder; catalogue edits do not change its algorithm."""
    root, output = Path(root), Path(output)
    day3a_path = root / config["day3a_manifest"]
    day3a = json.loads(day3a_path.read_text(encoding="utf-8"))
    books = read_books(root / day3a["configuration"]["adapted_source"])
    if config["fixed_replacement_buses"] != [37, 38]:
        raise ValueError("Main plan must start with Bus37, then Bus38")
    selection = choose_third_bus(books, config["fixed_replacement_buses"], config["third_bus_candidates"])
    if config["selection_rule"] != selection["rule"]:
        raise ValueError("Configured topology selection rule differs from implementation")
    inventory = inertia_inventory(root)
    frozen = json.loads((root / day3a["configuration"]["frozen_solver_summary"]).read_text(encoding="utf-8"))["solver_config"]
    plan = [37, 38, selection["chosen_bus"]]
    generation_config = deepcopy(day3a["configuration"])
    generation_config.update(replacement_order=plan, smoke_results=config["smoke_results"])
    cache = root / ".cache/day3a5-build"
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=cache) as staging:
        generated = build_models(root, generation_config, Path(staging))
        for row in generated["scenarios"]:
            content = (Path(staging) / row["file"]).read_bytes()
            if row["scenario_id"] in ("S0", "S1"):
                prior = next(s for s in day3a["scenarios"] if s["scenario_id"] == row["scenario_id"])
                source = day3a_path.parent / prior["file"]
                if sha256(source) != prior["sha256"] or row["sha256"] != prior["sha256"]:
                    raise ValueError("S0/S1 are not byte-identical to accepted Day3A models")
                content = source.read_bytes()
            preserve_bytes(output / row["file"], content)
    manifest = {**generated, "assembly_version": ASSEMBLY_VERSION, "scenario_class": MAIN_ROLE,
                "include_in_day3b_main_heatmap": True, "assembly_configuration": config,
                "assembly_builder": {"script": "scripts/build_main_renewable_scenarios.py",
                    "script_sha256": sha256(root / "scripts/build_main_renewable_scenarios.py"),
                    "module_sha256": sha256(Path(__file__))}, "selection": selection,
                "inertia_basis": {"source": "results/day3a/scenario_smoke/S0/trajectory.npz",
                    "sha256": sha256(root / "results/day3a/scenario_smoke/S0/trajectory.npz"),
                    "definition": "sum of original setup-time GENROU.M.v; includes retained Bus39", "inventory": inventory}}
    baseline_smoke = json.loads((root / "results/day3a/scenario_smoke/S0/summary.json").read_text(encoding="utf-8"))
    for row in manifest["scenarios"]:
        row.update(scenario_class=MAIN_ROLE, include_in_day3b_main_heatmap=True)
        row.update(inertia_metrics(inventory, row["renewable_buses"]))
        model_books = read_books(output / row["file"])
        row["expected_share_from_identical_static_plan"] = renewable_share(
            baseline_smoke["static_generation_after_pflow"], model_books.get("REGCP1", []))
        if row["scenario_id"] in ("S0", "S1"):
            decision = reuse_decision(root, row, output / row["file"], frozen)
            if not decision["reused"]:
                raise ValueError(f"S0/S1 reuse identity failed: {decision['reasons']}; no automatic rerun")
            measured = json.loads((root / decision["summary_reference"]).read_text(encoding="utf-8"))
            row["smoke_evidence"] = {"mode": "REUSED_DAY3A", **decision}
        elif accepted_report is not None:
            measured = next(s for s in accepted_report["scenarios"] if s["scenario_id"] == row["scenario_id"])
            if measured["model_sha256"] != row["sha256"]:
                raise ValueError("New main smoke model hash mismatch")
            row["smoke_evidence"] = {"mode": "MEASURED_DAY3A5", "summary_reference":
                config["smoke_results"] + "/" + row["scenario_id"] + "/summary.json"}
        else:
            measured = None
            row["smoke_evidence"] = {"mode": "PENDING"}
        if measured is not None:
            row.update({key: measured[key] for key in ("renewable_P_MW", "total_generation_P_MW", "renewable_share_pct", "smoke_passed")})
            row["share_basis"] = "Own online StaticGen actual P after PFlow, captured before TDS.init (S0/S1 exact identity reuse)"
    stress = {"schema_version": 1, "scenario_class": STRESS_ROLE, "include_in_day3b_main_heatmap": False,
              "reference_only": True, "original_day3a_manifest_sha256": sha256(day3a_path), "scenarios": []}
    for old in day3a["scenarios"]:
        if 39 not in old["renewable_buses"]:
            continue
        row = deepcopy(old)
        row.update(scenario_id="STRESS_"+old["scenario_id"], source_day3a_scenario_id=old["scenario_id"],
                   file="../"+old["file"], scenario_class=STRESS_ROLE, include_in_day3b_main_heatmap=False,
                   smoke_summary_reference="results/day3a/scenario_smoke/"+old["scenario_id"]+"/summary.json")
        row.update(inertia_metrics(inventory, row["renewable_buses"]))
        if sha256(day3a_path.parent / old["file"]) != old["sha256"]:
            raise ValueError("Original Bus39 stress model hash changed")
        stress["scenarios"].append(row)
    return manifest, stress
