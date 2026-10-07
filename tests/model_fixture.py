"""Compact accepted metadata in an isolated tree; no solver or TDS execution."""
import json
from pathlib import Path
import shutil

import numpy as np


def validation_archive(project_root, destination):
    project_root,destination=Path(project_root),Path(destination)
    fixture=project_root/'tests/fixtures/model_validation'
    for directory in ('cases','configs','src','scripts'):
        shutil.copytree(project_root/directory,destination/directory,ignore=shutil.ignore_patterns('__pycache__'))
    def copy(name,path):
        target=destination/path;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(fixture/name,target)
    for sid in ('S0','S1','S2','S3'):
        copy(f'{sid}_smoke.json',f'results/day3a/scenario_smoke/{sid}/summary.json')
    for sid in ('S0','S1'):
        copy(f'{sid}_reused_smoke.json',f'results/day3a5/main_smoke/{sid}/summary.json')
    copy('scenario_summary.json','results/day3a/scenario_smoke/scenario_summary.json')
    copy('main_scenario_summary.json','results/day3a5/main_smoke/scenario_summary.json')
    copy('identity_validation.json','results/day3a/verification.json')
    copy('program_identity.json','results/day3a/program_snapshot/manifest.json')
    solver=destination/'results/day1/nofault/summary.json'
    solver.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(project_root/'configs/frozen_solver.json',solver)
    manifest=json.loads((project_root/'cases/renewable/main/manifest.json').read_text(encoding='utf-8'))
    inventory=manifest['inertia_basis']['inventory']
    # A tiny test fixture copies accepted setup M; it is not a simulated trajectory.
    np.savez(destination/'results/day3a/scenario_smoke/S0/trajectory.npz',
        generator_ids=np.array([r['generator_id'] for r in inventory]),
        generator_bus_ids=np.array([r['bus'] for r in inventory]),
        inertia_weights=np.array([r['M'] for r in inventory]))
    np.savez(destination/'results/day3a/scenario_smoke/S1/trajectory.npz',fixture_only=True)
    return destination
