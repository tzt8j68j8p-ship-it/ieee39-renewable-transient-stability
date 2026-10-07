# GitHub portfolio release checklist

Checked on 2026-10-07 (Asia/Shanghai). **Published: public repository, successful
CI, and v1.0.0 Portfolio Release.** No simulations were added or rerun during publication.

## Delivery state

| Item | Verified state |
|---|---|
| A. Repository URL | [ieee39-renewable-transient-stability](https://github.com/tzt8j68j8p-ship-it/ieee39-renewable-transient-stability) |
| B. Visibility / branch | Public; default branch `main`; normal pushes without history rewriting |
| C. README first screen | English title, Chinese link, three-line introduction, renewable CCT heatmap, six highlights |
| D. Tracked content | 100 files; 1,627,493 bytes (1.552 MiB); raw archives excluded |
| E. Largest file | `docs/assets/renewable_cct_heatmap.png`, 134,418 bytes; largest 20 below |
| F. Privacy | Private source locations generalized; no local drive/profile paths or private project identifiers detected in uploaded files |
| G. Secrets | No credential signature or assignment detected; GitHub secret-scanning alert count was zero |
| H. Clean installation | New Python 3.13.15 virtual environment; pinned requirements installed; pip check passed |
| I. Tests | 99/99 passed in the isolated public source export, without raw results or TDS |
| J. Actions | Enabled: Windows, Python 3.13, dependency install and pure tests; [release-source run](https://github.com/tzt8j68j8p-ship-it/ieee39-renewable-transient-stability/actions/runs/37630279775) passed 99/99; [latest runs](https://github.com/tzt8j68j8p-ship-it/ieee39-renewable-transient-stability/actions/workflows/tests.yml) |
| K. Commit | Release source: `c3369dd04a4d019d9cee62176fb7bbf4bd957b74`; `main` adds this publication record afterward; final main identifier is reported in the delivery handoff |
| L. v1.0.0 | Annotated tag pushed; [v1.0.0 — Portfolio Release](https://github.com/tzt8j68j8p-ship-it/ieee39-renewable-transient-stability/releases/tag/v1.0.0) published; no uploaded binary/raw-data assets |
| M. Images / links | Five PNGs and four SVGs preserved; 51 relative documentation links resolve; all 16 README image/link targets returned HTTP 200; rendered README HTML verified |
| N. Remaining public-content issue | None detected in the audited uploaded content |

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

The release-source GitHub Actions run independently installed dependencies and
reported `Ran 99 tests` followed by `OK`. CI runs only pure tests, with no TDS matrix.
The final publication-record commit changes documentation only.

Git whitespace checks pass. Historical SHA256-sensitive Python/JSON/CSV bytes
are preserved across checkout; generated SVG formatting is preserved separately.
GitHub recognizes the standard root license as GPL-3.0. The project grant remains
GPL-3.0-or-later; upstream ANDES copyright and grant are retained in the third-party notices.

## Remote verification

- The public homepage returned HTTP 200. GitHub's rendered README HTML contains
  the title, tables, main heatmap before Highlights, collapsible share figure,
  and the Mermaid rendering container.
- Remote Git blob identifiers matched every local uploaded file. The default
  branch, exact description, and all nine topics were verified through GitHub.
- Relative documentation targets exist in the remote tree; the 16 distinct
  README image/link destinations were checked over HTTP. Images retain their source hashes.
- Verification used GitHub's server-rendered HTML and HTTP resources. An
  interactive browser screenshot check was not performed because browser automation
  permissions were unavailable. Client-side Mermaid rendering was not visually inspected.
- Secret scanning and push protection are both enabled. No detection was bypassed.
- Release `v1.0.0` targets the verified source commit above. GitHub provides its
  normal source archives; no raw trajectories or duplicate repository archive were uploaded.
  The completed publication checklist is maintained on `main` after release creation.

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
| `LICENSE` | 35,149 |
| `cases/renewable/sources/ieee39_bus37_regcp1_reecb1_pilot.xlsx` | 28,129 |
| `cases/renewable/S0_adapted_sg.xlsx` | 27,583 |
| `cases/renewable/main/S0_adapted_sg.xlsx` | 27,583 |
| `cases/renewable/sources/ieee39_10gen_no_source_shunts.xlsx` | 27,583 |
| `examples/results/renewable_scenario_summary.json` | 27,512 |
| `cases/renewable/S1_bus37_renewable.xlsx` | 27,314 |
| `cases/renewable/main/S1_bus37_renewable.xlsx` | 27,314 |
| `cases/renewable/main/S2_bus37_bus38_renewable.xlsx` | 27,154 |

## Repository presentation

Description:

> Python/ANDES toolkit for IEEE 39-bus transient stability, batch fault analysis,
> CCT estimation and renewable integration studies.

Topics: `power-system`, `transient-stability`, `ieee39`, `renewable-energy`,
`critical-clearing-time`, `andes`, `python`, `power-grid`, `dynamic-simulation`.

No scientific functionality is added during publication. Work stops at this release.
