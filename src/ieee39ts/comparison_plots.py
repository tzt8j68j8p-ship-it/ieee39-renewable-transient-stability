"""Read-only scientific figures; unresolved values remain masked."""
import hashlib
import json
import os
from pathlib import Path

import numpy as np

from .comparison import BUSES, SCENARIOS
from .io import write_json
from .scenarios import sha256


def heatmap_data(rows):
    values=np.full((4,5),np.nan)
    labels=np.full((4,5),"UR",dtype=object)
    for row in rows:
        i,j=SCENARIOS.index(row["scenario_id"]),BUSES.index(row["fault_bus"])
        if row["search_status"]=="RESOLVED":
            values[i,j]=row["cct_estimate_s"]*1000
            labels[i,j]=f"{values[i,j]:.0f}"
        elif row["cct_reason"]=="NO_UNSTABLE_ENDPOINT_WITHIN_0P5S":labels[i,j]=">500"
        elif "NON_CONVERGENT" in row["cct_reason"]:labels[i,j]="NC"
    return values,labels


def adjacent_resolved_segments(rows,bus):
    selected={row["scenario_id"]:row for row in rows if row["fault_bus"]==bus}
    return [(selected[a],selected[b]) for a,b in zip(SCENARIOS,SCENARIOS[1:])
            if selected[a]["search_status"]==selected[b]["search_status"]=="RESOLVED"]


def draw_comparison(results,output):
    results,output=Path(results),Path(output)
    output.mkdir(parents=True,exist_ok=True)
    os.environ["MPLCONFIGDIR"]=str(Path(__file__).resolve().parents[2]/".cache/matplotlib")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    source=results/"scenario_fault_summary.json"
    source_bytes=source.read_bytes()
    source_hash=hashlib.sha256(source_bytes).hexdigest()
    snapshot=output/f"input_summary-{source_hash}.json"
    if snapshot.exists():
        if snapshot.read_bytes()!=source_bytes:
            raise ValueError("Plot input snapshot does not match its content hash")
    else:
        snapshot.write_bytes(source_bytes)
    report=json.loads(source_bytes)
    rows=report["results"]
    by_scenario={row["scenario_id"]:row for row in rows}
    scenario_labels=[f"{sid} — {by_scenario[sid]['renewable_share_pct']:.1f}%" for sid in SCENARIOS]
    manifest={"source_summary":str(snapshot.resolve()),
              "original_summary":str(source.resolve()),
              "summary_sha256":source_hash,"figures":[],
              "precision":"interval midpoint; <=7.8125 ms bracket width; rounded text is display only"}
    def save(fig,name,description):
        fig.savefig(output/(name+".png"),dpi=180)
        fig.savefig(output/(name+".svg"))
        plt.close(fig)
        manifest["figures"].append({"file":name+".png","svg":name+".svg","sha256":sha256(output/(name+".png")),"description":description})
    values,labels=heatmap_data(rows)
    fig,ax=plt.subplots(figsize=(10,5.1),layout="constrained")
    cmap=plt.get_cmap("cividis").copy();cmap.set_bad("#e4e4e8")
    image=ax.imshow(np.ma.masked_invalid(values),cmap=cmap,aspect="auto")
    if np.isfinite(values).any():fig.colorbar(image,ax=ax,label="CCT interval midpoint (ms)")
    for i in range(4):
        for j in range(5):
            if not np.isfinite(values[i,j]):
                ax.add_patch(Rectangle((j-.5,i-.5),1,1,facecolor="#e4e4e8",edgecolor="#a1a1aa",hatch="//" if labels[i,j]==">500" else "xx",linewidth=.5))
            color="white" if np.isfinite(values[i,j]) and values[i,j] < np.nanmedian(values) else "black"
            ax.text(j,i,labels[i,j],ha="center",va="center",color=color,fontsize=13)
    ax.set_xticks(range(5),[f"Bus{bus}" for bus in BUSES]);ax.set_yticks(range(4),scenario_labels)
    ax.set_title("Main scenarios: 180° rotor-angle screening | 8 s horizon\nCCT midpoint; grid/tolerance 7.8125 ms")
    ax.set_xlabel("Fault bus | NC: numerical/quality failure; >500: lower bound; UR: missing bracket")
    save(fig,"01_cct_heatmap","Resolved cells only receive numeric colors; NC/>500/UR are masked")
    fig,ax=plt.subplots(figsize=(10,5.5),layout="constrained")
    for color,bus in zip(plt.get_cmap("tab10").colors,BUSES):
        selected=[row for row in rows if row["fault_bus"]==bus and row["search_status"]=="RESOLVED"]
        if selected:
            x=[row["renewable_share_pct"] for row in selected];y=[row["cct_estimate_s"]*1000 for row in selected]
            error=[row["interval_width_s"]*500 for row in selected]
            ax.errorbar(x,y,yerr=error,fmt="o",color=color,capsize=3,label=f"Bus{bus}")
        for a,b in adjacent_resolved_segments(rows,bus):
            ax.plot([a["renewable_share_pct"],b["renewable_share_pct"]],[a["cct_estimate_s"]*1000,b["cct_estimate_s"]*1000],color=color)
    ax.set_xticks([by_scenario[sid]["renewable_share_pct"] for sid in SCENARIOS])
    ax.set_xlabel("Actual renewable active-power share (%)")
    ax.set_ylabel("CCT interval midpoint (ms)")
    ax.set_title("CCT across main replacement scenarios | 180° screening, 8 s\nBars show verified brackets; unresolved gaps are not connected")
    ax.grid(alpha=.2);ax.legend()
    save(fig,"02_cct_vs_renewable_share","Only adjacent resolved scenarios are connected; bars are verified intervals")
    fig,ax=plt.subplots(figsize=(10,5.5),layout="constrained")
    manifest["bus16_sources"]=[]
    for sid in SCENARIOS:
        row=next(r for r in rows if r["scenario_id"]==sid and r["fault_bus"]==16)
        directory=results/row["reference_directory"]
        summary=json.loads((directory/"summary.json").read_text())
        path=directory/"trajectory.npz"
        if path.exists():
            with np.load(path) as trace:
                mask=trace["valid_mask"]
                ax.plot(trace["time_s"][mask],trace["angle_separation_deg"][mask],label=f"{sid} ({row['renewable_share_pct']:.1f}%) — {summary['stability_status']}")
                if mask.any() and trace["time_s"][mask][-1]<8-1e-9:ax.plot(trace["time_s"][mask][-1],trace["angle_separation_deg"][mask][-1],"x",color="black")
            manifest["bus16_sources"].append({"scenario_id":sid,"trajectory_sha256":sha256(path),"summary_sha256":sha256(directory/"summary.json")})
    ax.axhline(180,color="#b33232",linestyle="--",label="180° threshold")
    ax.axvspan(1.,1.125,color="#dca84a",alpha=.18)
    ax.axvline(1.,color="#987324",linestyle=":");ax.axvline(1.125,color="#987324",linestyle="-.")
    ax.set_xlim(0,8);ax.set_xlabel("Time (s); fault applied 1.0 s, cleared 1.125 s")
    ax.set_ylabel("Simultaneous maximum rotor-angle separation (deg)")
    ax.set_title("Bus16 | 125 ms reference fault\nRemaining synchronous generators; valid accepted trajectory only")
    ax.grid(alpha=.2);ax.legend(fontsize=8)
    save(fig,"03_bus16_reference_angle_response","Remaining SG only; early termination is marked by x")
    voltage=np.array([[next(r for r in rows if r["scenario_id"]==sid and r["fault_bus"]==bus)["min_bus_voltage_pu"] for bus in BUSES] for sid in SCENARIOS],dtype=float)
    fig,ax=plt.subplots(figsize=(9,4.8),layout="constrained")
    image=ax.imshow(np.ma.masked_invalid(voltage),aspect="auto",cmap="viridis")
    fig.colorbar(image,ax=ax,label="Minimum voltage over valid reference prefix (pu)")
    for i in range(4):
        for j in range(5):
            row=next(r for r in rows if r["scenario_id"]==SCENARIOS[i] and r["fault_bus"]==BUSES[j])
            text=f"{voltage[i,j]:.4f}" if np.isfinite(voltage[i,j]) else "NA"
            if text=="-0.0000":text="0.0000"
            if row["reference_stability_status"]=="NON_CONVERGENT":
                text+="\nNC prefix"
                ax.add_patch(Rectangle((j-.5,i-.5),1,1,facecolor="none",edgecolor="#a1a1aa",hatch="//",linewidth=.5))
            ax.text(j,i,text,ha="center",va="center",color="black" if voltage[i,j]>.5 else "white",fontsize=10)
    ax.set_xticks(range(5),[f"Bus{bus}" for bus in BUSES]);ax.set_yticks(range(4),scenario_labels)
    ax.set_title("125 ms reference | same 39 buses\nMinimum voltage: valid prefix; NC marks early failure",fontsize=12,pad=8)
    save(fig,"04_reference_min_voltage_heatmap","Optional same-39-bus metric; includes fault-on minimum")
    write_json(output/"manifest.json",manifest)
