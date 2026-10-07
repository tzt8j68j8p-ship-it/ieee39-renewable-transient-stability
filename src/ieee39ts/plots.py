"""Simple scientific figures from saved results only; no simulator imports."""
import hashlib
import json
import os
from pathlib import Path

import numpy as np

from .batch import cct_ranking, severity_ranking
from .io import write_json

ROOT = Path(__file__).resolve().parents[2]


def _hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def generate_figures(batch_directory: Path, output_directory: Path, day1_directory: Path) -> dict:
    """Read four approved Bus16 examples and the batch rankings, then save six PNGs."""
    batch_directory, output_directory, day1_directory = map(Path, (batch_directory, output_directory, day1_directory))
    output_directory.mkdir(parents=True, exist_ok=True)
    cache = ROOT / ".cache/matplotlib"
    cache.mkdir(parents=True, exist_ok=True)
    os.environ["MPLCONFIGDIR"] = str(cache)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False,
                         "axes.spines.right": False, "figure.dpi": 120})
    report_path = batch_directory / "batch_summary.json"
    input_bytes = report_path.read_bytes()
    report = json.loads(input_bytes)
    if not report["metadata"].get("complete"):
        raise ValueError("Figures require a completed batch")
    rows = report["results"]
    # Batch runtime metadata may be finalized after plotting. Preserve the exact
    # input bytes so its recorded hash remains independently verifiable.
    snapshot_path = output_directory / "batch_summary_input.json"
    snapshot_path.write_bytes(input_bytes)
    manifest = {"matplotlib_version": matplotlib.__version__, "simulation_calls": 0,
                "plot_program_sha256": _hash(Path(__file__)),
                "batch_summary_source": str(report_path.resolve()),
                "batch_summary_snapshot": str(snapshot_path.resolve()),
                "batch_summary_sha256": _hash(snapshot_path), "figures": []}
    verified = day1_directory / "bus16_cct_verified_bracket"
    cct = json.loads((verified / "cct.json").read_text(encoding="utf-8"))
    near = next(trial for trial in cct["trials"]
                if trial["clearing_duration_s"] == 0.1875 and trial["stability_status"] == "STABLE")
    examples = [
        ("01_bus16_stable_125ms.png", batch_directory / "bus16/reference", False),
        ("02_bus16_near_critical_187p5ms.png", verified / near["trial_directory"], False),
        ("03_bus16_unstable_195p3125ms.png", day1_directory / "bus16_unstable_boundary", False),
        ("04_bus16_coi_relative_195p3125ms.png", day1_directory / "bus16_unstable_boundary", True),
    ]
    for name, source, relative in examples:
        summary_path, npz_path = source / "summary.json", source / "trajectory.npz"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if summary["fault_bus"] != 16 or summary["stability_status"] not in ("STABLE", "UNSTABLE"):
            raise ValueError("Bus16 examples must have an accepted stability classification")
        with np.load(npz_path, allow_pickle=False) as arrays:
            mask = arrays["valid_mask"].astype(bool)
            t = arrays["time_s"][mask]
            angle = np.rad2deg(arrays["delta_relative_rad" if relative else "delta_rad"][mask])
            separation = arrays["angle_separation_deg"][mask]
            ids = arrays["generator_ids"].astype(str)
        duration = summary["clearing_duration_s"]
        fault_start = summary["settings"]["fault_start_s"]
        clearing = fault_start + duration
        fig, axes = plt.subplots(2, 1, figsize=(9, 6), sharex=True, gridspec_kw={"height_ratios": [2, 1]}, layout="constrained")
        for column, generator in enumerate(ids):
            axes[0].plot(t, angle[:, column], linewidth=1.2, label=generator)
        axes[0].set_ylabel("COI-relative angle (deg)" if relative else "Rotor angle (deg)")
        axes[0].legend(ncol=5, fontsize=8, loc="upper left")
        axes[1].plot(t, separation, color="#343434", linewidth=1.5, label="Simultaneous separation")
        axes[1].axhline(180, color="#bf3535", linestyle="--", linewidth=1, label="180 deg threshold")
        axes[1].set_ylim(0, max(195, float(np.max(separation)) * 1.08))
        axes[1].set_ylabel("Max separation (deg)")
        axes[1].set_xlabel("Time (s)")
        axes[1].legend(fontsize=8, loc="upper left")
        for ax in axes:
            ax.axvspan(fault_start, clearing, color="#dca84a", alpha=0.16)
            ax.axvline(fault_start, color="#987324", linestyle=":", linewidth=1)
            ax.axvline(clearing, color="#987324", linestyle="-.", linewidth=1)
            ax.grid(alpha=0.2)
        duration_label = f"{duration * 1000:.4f}".rstrip("0").rstrip(".")
        clearing_label = f"{clearing:.7f}".rstrip("0").rstrip(".")
        axes[0].set_title(f"Bus16 | {duration_label} ms | {summary['stability_status']}\n"
                          f"Fault applied {fault_start:g} s; cleared {clearing_label} s | {summary['simulation_status']}")
        fig.savefig(output_directory / name, dpi=180)
        plt.close(fig)
        manifest["figures"].append({"file": name, "source": str(source.resolve()),
                                   "summary_sha256": _hash(summary_path), "trajectory_sha256": _hash(npz_path),
                                   "stability_status": summary["stability_status"], "clearing_duration_s": duration})

    resolved = cct_ranking(rows)
    name = "05_resolved_cct_ranking.png"
    fig, ax = plt.subplots(figsize=(9, max(4, len(resolved) * .42 + 1.5)), layout="constrained")
    if resolved:
        estimates = np.array([r["cct_estimate_s"] * 1000 for r in resolved])
        error = np.array([[r["cct_estimate_s"] - r["stable_lower_s"] for r in resolved],
                          [r["unstable_upper_s"] - r["cct_estimate_s"] for r in resolved]]) * 1000
        ax.barh([f"Bus{r['fault_bus']}" for r in resolved], estimates, xerr=error,
                color="#466d8e", capsize=3)
        ax.invert_yaxis()
        for index, value in enumerate(estimates):
            ax.text(value + error[1, index] + 1, index, f"{value:.3f}", va="center", fontsize=9)
        ax.set_xlim(0, max(estimates + error[1]) * 1.18)
    else:
        ax.text(.5, .5, "No RESOLVED CCT in the fixed search window", ha="center", transform=ax.transAxes)
    ax.set_xlabel("CCT midpoint (ms); whiskers = STABLE lower / UNSTABLE upper")
    ax.set_title(f"Resolved CCT ranking | 180 deg criterion, 8 s horizon\n"
                 f"31.25-195.3125 ms window; {len(rows) - len(resolved)} unresolved cases excluded")
    ax.grid(axis="x", alpha=.2)
    fig.savefig(output_directory / name, dpi=180)
    plt.close(fig)
    manifest["figures"].append({"file": name, "source": str(snapshot_path.resolve()), "included_fault_buses": [r["fault_bus"] for r in resolved]})

    severity = severity_ranking(rows)
    name = "06_reference_angle_ranking_125ms.png"
    fig, ax = plt.subplots(figsize=(9, max(4, len(severity) * .38 + 1.8)), layout="constrained")
    peaks = [r["max_angle_separation_deg"] for r in severity]
    colors = ["#507a63" if r["reference_stability_status"] == "STABLE" else "#b54a46" for r in severity]
    labels = [f"Bus{r['fault_bus']} ({r['reference_stability_status']})" for r in severity]
    ax.barh(labels, peaks, color=colors)
    ax.invert_yaxis()
    ax.axvline(180, color="#bf3535", linestyle="--", linewidth=1, label="180 deg threshold")
    for index, value in enumerate(peaks):
        ax.text(value + 1, index, f"{value:.2f}", va="center", fontsize=8)
    ax.set_xlim(0, max([195] + peaks) * 1.12)
    ax.set_xlabel("Maximum simultaneous rotor-angle separation (deg)")
    ax.set_title(f"125 ms reference-fault severity | {len(severity)} valid cases\n"
                 "Accepted valid samples only; angle-criterion stops have a shorter window")
    ax.legend(fontsize=9, loc="lower right")
    ax.grid(axis="x", alpha=.2)
    fig.savefig(output_directory / name, dpi=180)
    plt.close(fig)
    manifest["figures"].append({"file": name, "source": str(snapshot_path.resolve()), "included_fault_buses": [r["fault_bus"] for r in severity],
                               "excluded_fault_buses": [r["fault_bus"] for r in rows if r not in severity]})
    write_json(output_directory / "manifest.json", manifest)
    return manifest


def plot_extended_cct_ranking(result_directory: Path, output_directory: Path):
    """Draw only resolved CCTs from Day 2.5; retain an exact input snapshot."""
    result_directory, output_directory = Path(result_directory), Path(output_directory)
    source = result_directory / "cct_extended_summary.json"
    input_bytes = source.read_bytes()
    report = json.loads(input_bytes)
    if not report["metadata"].get("complete") or report["metadata"].get("new_resolved", 0) < 2:
        raise ValueError("Extended ranking requires a complete pass with at least two new resolved CCTs")
    resolved = cct_ranking(report["results"])
    output_directory.mkdir(parents=True, exist_ok=True)
    snapshot = output_directory / "cct_extended_summary_input.json"
    snapshot.write_bytes(input_bytes)
    os.environ["MPLCONFIGDIR"] = str(ROOT / ".cache/matplotlib")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(9, max(4, len(resolved) * .43 + 1.8)), layout="constrained")
    estimates = np.array([row["cct_estimate_s"] * 1000 for row in resolved])
    errors = np.array([[row["cct_estimate_s"] - row["stable_lower_s"] for row in resolved],
                       [row["unstable_upper_s"] - row["cct_estimate_s"] for row in resolved]]) * 1000
    ax.barh([f"Bus{row['fault_bus']}" for row in resolved], estimates, xerr=errors,
            color="#466d8e", capsize=3)
    ax.invert_yaxis()
    for index, value in enumerate(estimates):
        ax.text(value + errors[1, index] + 2, index, f"{value:.3f}", va="center", fontsize=9)
    ax.set_xlim(0, max(estimates + errors[1]) * 1.16)
    ax.set_xlabel("CCT midpoint (ms); whiskers = STABLE lower / UNSTABLE upper")
    ax.set_title(f"Day 2.5 resolved CCT ranking | 180 deg, 8 s horizon\n"
                 f"{len(resolved)} resolved; {len(report['results']) - len(resolved)} unresolved / lower-bound cases excluded")
    ax.grid(axis="x", alpha=.2)
    ax.spines[["top", "right"]].set_visible(False)
    figure = output_directory / "resolved_cct_ranking.png"
    fig.savefig(figure, dpi=180)
    plt.close(fig)
    manifest = {"figure": figure.name, "included_fault_buses": [r["fault_bus"] for r in resolved],
                "excluded_fault_buses": [r["fault_bus"] for r in report["results"] if r["search_status"] != "RESOLVED"],
                "input_source": str(source.resolve()), "input_snapshot": str(snapshot.resolve()),
                "input_sha256": _hash(snapshot), "plot_program_sha256": _hash(Path(__file__)), "simulation_calls": 0}
    write_json(output_directory / "manifest.json", manifest)
    return manifest
