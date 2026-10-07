"""Day3B fixed 20-cell matrix, fresh Main fault loads and bounded CCT search."""
import argparse
from datetime import datetime, timezone
from importlib.metadata import version
import json
import logging
from pathlib import Path
import platform
import sys
import time

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/"src"))

from ieee39ts.comparison import BUSES, SCENARIOS, cache_identity_matches, load_main_manifest, run_comparison, write_summary
from ieee39ts.io import configure_logging, new_output_directory, save_fault_result, write_json
from ieee39ts.scenario_faults import run_main_fault
from ieee39ts.scenarios import sha256


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config",type=Path,default=ROOT/"configs/scenario_fault_comparison.json")
    parser.add_argument("--output",type=Path,default=ROOT/"results/day3b/main_matrix_20261007")
    parser.add_argument("--figures",type=Path,default=ROOT/"figures/day3b")
    args=parser.parse_args()
    started=time.perf_counter()
    config=json.loads(args.config.read_text(encoding="utf-8"))
    expected={"main_manifest":"cases/renewable/main/manifest.json","scenario_ids":list(SCENARIOS),"fault_buses":list(BUSES),
              "reference_duration_s":.125,"fault_start_s":1.,"observation_end_s":8.,"fault_reactance_pu":1e-4,
              "time_step_s":1/128,"angle_limit_deg":180.,"initial_lower_s":4/128,"initial_upper_s":25/128,
              "extension_durations_s":[.25,.3125,.375,.5],"tolerance_s":1/128,"frozen_solver_summary":"configs/frozen_solver.json"}
    if config!=expected: parser.error("Require exact frozen Day3B conditions and 4x5 matrix")
    manifest_path=ROOT/config["main_manifest"]
    manifest=load_main_manifest(ROOT,manifest_path)
    frozen=json.loads((ROOT/config["frozen_solver_summary"]).read_text(encoding="utf-8"))["solver_config"]
    output=new_output_directory(args.output)
    figures=new_output_directory(args.figures)
    configure_logging(output)
    paths=list((ROOT/"src/ieee39ts").glob("*.py"))+[ROOT/"run_scenario_comparison.py",args.config]
    program={str(path.relative_to(ROOT)).replace("\\","/"):sha256(path) for path in sorted(paths)}
    versions={"python":platform.python_version(),**{name:version(name) for name in ("andes","numpy","scipy","pandas")}}
    metadata={"complete":False,"created_utc":datetime.now(timezone.utc).isoformat(),"config":config,
              "main_manifest_sha256":sha256(manifest_path),"program_identity":program,"versions":versions,
              "solver_config":frozen,"model_family":"adapted_main","prior_physical_cache_used":False,
              "actual_TDS_calls":0,"runner_calls":0,"cache_hits":0}
    for rel in program:
        target=output/"program_snapshot"/rel
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes((ROOT/rel).read_bytes())
    (output/"main_manifest.json").write_bytes(manifest_path.read_bytes())
    memo,calls,cache_hits={},[],[]
    def run_case(scenario,bus,duration,role):
        identity={"model_family":"adapted_main","scenario_id":scenario["scenario_id"],"fault_bus":bus,
                  "model_sha256":scenario["sha256"],"config":config,"solver_config":frozen,
                  "program_identity":program,"versions":versions,"clearing_duration_s":duration}
        key=(scenario["scenario_id"],bus,round(duration*128))
        if key in memo and cache_identity_matches(memo[key].summary["run_identity"],identity):
            cache_hits.append({"scenario_id":key[0],"fault_bus":bus,"clearing_duration_s":duration,
                               "source_directory":memo[key].summary["result_directory"],"identity_match":True})
            write_json(output/"cache_decisions.json",cache_hits)
            return memo[key]
        relative=Path(scenario["scenario_id"])/f"bus{bus:02d}"/("reference" if role=="reference" else f"cct/trial_{round(duration*128):03d}ticks")
        directory=output/relative
        directory.mkdir(parents=True,exist_ok=True)
        handler=logging.FileHandler(directory/"run.log",encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
        logging.getLogger().addHandler(handler)
        try:
            result=run_main_fault(scenario,manifest_path.parent/scenario["file"],bus,duration,frozen)
            result.summary.update(run_identity=identity,result_directory=relative.as_posix())
            if role=="reference": result.summary["reference_directory"]=relative.as_posix()
            save_fault_result(directory,result)
            write_json(directory/"diagnostic_channels.json",result.summary.get("diagnostic_channels",{}))
            calls.append({"scenario_id":key[0],"fault_bus":bus,"duration_s":duration,"role":role,
                          "tds_run_called":result.summary["tds_run_called"],"directory":relative.as_posix(),
                          "stability_status":result.summary["stability_status"],"simulation_status":result.summary["simulation_status"]})
            write_json(output/"runner_calls.json",calls)
            memo[key]=result
            print(f"{key[0]} Bus{bus} {role} {duration*1000:.4f} ms: {result.summary['stability_status']} / {result.summary['simulation_status']}",flush=True)
            return result
        finally:
            logging.getLogger().removeHandler(handler)
            handler.close()
    def on_search(row,report):
        write_json(output/row["cct_directory"]/"cct.json",report)
        print(f"CELL {row['scenario_id']} Bus{row['fault_bus']}: {report['search_status']} / {report['reason']}",flush=True)
    def checkpoint(rows):
        metadata.update(runner_calls=len(calls),actual_TDS_calls=sum(c["tds_run_called"] for c in calls),cache_hits=len(cache_hits),elapsed_s=time.perf_counter()-started)
        write_summary(output,rows,metadata)
    rows=run_comparison(manifest,run_case,checkpoint=checkpoint,on_search=on_search)
    metadata.update(complete=True,simulation_runtime_s=time.perf_counter()-started)
    checkpoint(rows)
    write_json(output/"cache_decisions.json",cache_hits)
    from ieee39ts.comparison_plots import draw_comparison
    draw_comparison(output,figures)
    metadata["total_runtime_s"]=time.perf_counter()-started
    checkpoint(rows)
    print(f"DONE 20 cells; TDS={metadata['actual_TDS_calls']}; seconds={metadata['total_runtime_s']:.2f}",flush=True)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
