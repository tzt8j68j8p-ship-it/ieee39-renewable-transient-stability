# Model and implementation provenance

## Official IEEE39

`cases/ieee39_official.xlsx` is an unchanged copy of ANDES 2.0.0's bundled
`andes/cases/ieee39/ieee39_full.xlsx`.

SHA256: `9c2048dc94201ee48ffe816de65d53831fa1f4b0e7fdf32f24c50f1017edcfe5`.

The [official manifest](../cases/manifest.json) records source version, hash,
39 buses and ten GENROU machines. ANDES attribution remains applicable.

## Adapted baseline and renewable template

The author-maintained adapted SG baseline and Bus37 GFL pilot are bundled in
[sources](../cases/renewable/sources/manifest.json). Their hashes are respectively
`f1a4e0b7a89c87aa5811d36b91aa054ab4638440c8cc3021b085e18ee6539374` and
`6d4b03946c94bbf44fbf246a71f402a797bb4965344894e60bd029b1a3cff7d2`.
Source filesystem locations are omitted from the public manifest; no private
project is read at runtime.

S0 keeps the adapted baseline bytes. Replacements remove each selected SG and its
governor/exciter/PSS foreign-key dependants, retain the network, static generation,
loads and dispatch, and add REGCP1 + PLL2 + REECB1 from the pilot template.
Renewable Sn matches the original SG Sn; gammap=gammaq=1.
Three controller inputs (Kqv/Iqh1/Iql1) retain the documented rating normalization.
Static and dynamic injections are not double-counted when calculating share.

## Main scenario hashes

| Scenario | Replaced buses | SHA256 |
|---|---|---|
| S0 | None | f1a4e0b7a89c87aa5811d36b91aa054ab4638440c8cc3021b085e18ee6539374 |
| S1 | 37 | 97bd9447536889f1a3d61e4956acbec812df8cb031652224610eb1e6f4dab5e4 |
| S2 | 37, 38 | 595cd3a01a05c110fe681e00a4896422a44cb60777e2c008cb22f116ed7764f9 |
| S3 | 37, 38, 32 | 6251363814e114373511fb0c6f258aacd6f9a9289e9e666f5c1e5fa7ab669ef7 |

The [main manifest](../cases/renewable/main/manifest.json) records exact PFlow shares,
setup M accounting, mappings and accepted smoke metadata. Original M totals and
removed fractions are preserved. Bus32 was chosen over Bus35 by deterministic
online-network shortest-path dispersion from Bus37 and Bus38, without dispatch changes.

Bus39 has H=50 s and setup M=1199 in this adapted model. It remains synchronous in
the main sequence, as does Slack Bus31. The original Bus39 replacement workbooks
remain under the [stress manifest](../cases/renewable/stress/manifest.json) and are
excluded from the main comparison.

## Implementation lineage

The independent-loading runner and aligned trajectory extraction were refactored
from author-maintained working prototypes. COI/relative-angle extraction and
quality/evidence timing were separated from execution diagnostics. The existing
integer-grid CCT search was refactored into a callback-based implementation;
bounded discovery and scenario comparison call that same search implementation.
The main fault adapter retains the validated solver and quality rules.

The public release does not import earlier private scripts. Model construction
helpers read only bundled workbooks; historical assembly/identity audits may
consume an archived local validation report. Public execution entry points read
bundled cases and configurations independently of such archives.

Original local workbooks, raw results, plots and frozen simulation/stability/CCT
core files remain unchanged during publication. Public summaries project final
verified fields; [export manifests](../examples/results/manifest.json) and
[figure manifests](assets/manifest.json) record the source/output hashes.

Upstream references: [ANDES](https://github.com/CURENT/andes),
[ANDES CCT example](https://docs.andes.app/en/stable/gallery/critical-clearing-time.html).
See [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) and [LICENSE](../LICENSE).
