# GitHub portfolio release checklist

Checked on 2026-10-07 (Asia/Shanghai). **The local public package is audited and
committed-ready; remote publication is blocked by missing CLI authentication.**
No successful push, public repository, remote workflow or Release is claimed.

## Delivery state

| Item | Verified state |
|---|---|
| A. Repository URL | Not created; requested name: `ieee39-renewable-transient-stability` |
| B. Visibility / branch | Public is requested; local default branch will be `main` |
| C. README first screen | English title, Chinese link, three-line introduction, renewable CCT heatmap, six highlights |
| D. Tracked content | 100 files; 1,626,228 bytes (1.551 MiB); raw archives excluded |
| E. Largest file | `docs/assets/renewable_cct_heatmap.png`, 134,418 bytes; largest 20 below |
| F. Privacy | No local drive/profile paths or private project identifiers in staged files |
| G. Secrets | No secret signature or credential assignment detected; credentials are not included |
| H. Clean installation | New Python 3.13.15 virtual environment; pinned requirements installed; pip check passed |
| I. Tests | 99/99 passed in the exported public source tree, without raw results or TDS |
| J. Actions | Workflow prepared: Windows, Python 3.13, dependency install and pure unit tests; remote status unverified |
| K. Commit | Obtain the final local content identifier with `git rev-parse HEAD`; recorded in the handoff |
| L. v1.0.0 | Tag and Release not created; wait for successful push and remote homepage verification |
| M. Images / links | Five PNGs and four SVGs verified; 51 relative documentation links resolve locally; remote rendering pending |
| N. Remaining public-content issue | None detected in the staged payload; remote publication remains incomplete |

## Scope and preservation

- 1,174 original scientific files retain SHA256, including frozen core modules,
  workbooks, original trajectories, summaries, execution snapshots and figures.
- No TDS or power-flow study was rerun. Original physical values and failure
  labels are unchanged. The frozen solver configuration was copied unchanged.
- Public CSV/JSON exports contain the verified final fields; only internal
  directories and execution metadata are omitted. Source digests remain recorded.
- Personal filesystem source locations were replaced with portable attribution
  in two model manifests. The original copies remain in the local private archive.
- Full results, logs, caches, virtual environments, IDE files and internal
  acceptance reports are ignored. There are no tracked NPZ files or files >100 MB.

## Reproducibility evidence

Clean dependency versions: python 3.13.15, andes 2.0.0, numpy 2.5.3, pandas 3.0.6, openpyxl 3.1.5, matplotlib 3.11.2.
The tested source export contains only the Git index, not ignored local results.
All four public entry points also pass `--help`. Unit tests use isolated accepted
metadata fixtures; numerical criteria and real-run cache checks remain unchanged.
The temporary validation environment and detailed audit logs remain local.

Git whitespace checks pass. Historical SHA256-sensitive Python/JSON/CSV bytes
are preserved across checkout; generated SVG formatting is preserved separately.
The full GPL-3.0 license and upstream ANDES notices are included. Recognition by
GitHub will be checked after the repository exists.

## Largest 20 tracked files

| File | Bytes |
|---|---:|
| `docs/assets/renewable_cct_heatmap.png` | 134,418 |
| `docs/assets/bus16_transient_response.png` | 127,548 |
| `docs/assets/reference_voltage_heatmap.png` | 117,815 |
| `docs/assets/baseline_cct_ranking.png` | 98,541 |
| `docs/assets/cct_vs_renewable_share.png` | 82,804 |
| `docs/assets/bus16_transient_response.svg` | 71,481 |
| `docs/assets/renewable_cct_heatmap.svg` | 68,377 |
| `docs/assets/reference_voltage_heatmap.svg` | 64,375 |
| `docs/assets/cct_vs_renewable_share.svg` | 59,883 |
| `cases/ieee39_official.xlsx` | 38,449 |
| `tests/fixtures/model_validation/scenario_summary.json` | 37,318 |
| `LICENSE` | 35,915 |
| `cases/renewable/sources/ieee39_bus37_regcp1_reecb1_pilot.xlsx` | 28,129 |
| `cases/renewable/S0_adapted_sg.xlsx` | 27,583 |
| `cases/renewable/main/S0_adapted_sg.xlsx` | 27,583 |
| `cases/renewable/sources/ieee39_10gen_no_source_shunts.xlsx` | 27,583 |
| `examples/results/renewable_scenario_summary.json` | 27,512 |
| `cases/renewable/S1_bus37_renewable.xlsx` | 27,314 |
| `cases/renewable/main/S1_bus37_renewable.xlsx` | 27,314 |
| `cases/renewable/main/S2_bus37_bus38_renewable.xlsx` | 27,154 |

## Remaining publication steps

The connected GitHub API exposes repository-content operations, but no repository
or Release creation action. The browser denied access because saved browser
permissions could not be verified. The installed official GitHub CLI has no
authenticated host. These are tooling/authentication limitations, not an audit failure.

1. Complete GitHub CLI sign-in through its normal interactive authorization flow.
2. Create/associate the public repository, set the description/topics and `main`.
3. Push without force, verify README rendering, images/links, GPL recognition and CI.
4. Create tag `v1.0.0` and Release `v1.0.0 — Portfolio Release`, without raw data assets.
5. Verify secret scanning and push protection; enable them if repository permissions allow.

Requested description:

> Python/ANDES toolkit for IEEE 39-bus transient stability, batch fault analysis,
> CCT estimation and renewable integration studies.

Requested topics: `power-system`, `transient-stability`, `ieee39`, `renewable-energy`,
`critical-clearing-time`, `andes`, `python`, `power-grid`, `dynamic-simulation`.

No scientific functionality is added during publication.
