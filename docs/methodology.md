# Methodology

## Models and experimental conditions

The official ANDES IEEE39 case is the 15-bus benchmark. Renewable scenarios use
their own adapted synchronous S0 baseline; the two baseline families are not
interchangeable caches or direct CCT-difference comparators.

| Condition | Fixed value |
|---|---|
| Disturbance | Three-phase bus-to-ground fault; xf=1e-4 pu |
| Fault application | 1.0 s |
| Post-fault topology | Original network retained; no line trip |
| Observation end | 8.0 s |
| Clearing-time grid | 1/128 s = 7.8125 ms |
| Screening threshold | Simultaneous remaining-SG separation >=180° |
| Integration | Frozen trapezoidal configuration |

[frozen_solver.json](../configs/frozen_solver.json) copies the validated solver
values unchanged, including Newton tolerance 1e-4 and max_iter=15. The model
manifests and [provenance](model_provenance.md) identify the exact input workbooks.

## Trajectory and rotor-angle screening

The runner loads a fresh model, configures the Fault before setup, runs PFlow,
initializes TDS and extracts aligned delta, omega and all 39 bus voltages.
Inertia uses setup-time GENROU.M.v on the common system base:

```text
delta_COI(t) = sum(M_i * delta_i(t)) / sum(M_i)
delta_rel_i(t) = delta_i(t) - delta_COI(t)
separation(t) = max(delta_rel_i(t)) - min(delta_rel_i(t))
```

Only remaining synchronous generators participate. Continuous rotor states are
not unwrapped, and raw machine-base 2H values are not mixed. PLL states are
diagnostics; they do not participate in COI or add a stability threshold.

Quality checks and evidence timing determine the accepted prefix. A credible
angle crossing before an abnormal tail can establish UNSTABLE while retaining
failure metadata. A numerical failure before any credible crossing is
NON_CONVERGENT. Completed, valid 8 s observations without a crossing are STABLE.
`simulation_status` records run termination independently.

## Bounded bracket discovery and CCT

The renewable matrix verifies its own 31.25 ms stable candidate and 195.3125 ms
upper candidate for each scenario/fault bus. If the upper candidate is stable,
discovery tests 250, 312.5, 375 and 500 ms in order. The first credible unstable
trial and nearest verified stable trial are passed to the existing binary search.
Search uses integer grid indices rather than floating-point duration subdivision.

- STABLE updates only the stable lower endpoint.
- UNSTABLE updates only the unstable upper endpoint.
- NON_CONVERGENT or rejected quality stops the search; neither endpoint moves.
- If 500 ms is still stable, only a tested lower bound is reported.
- RESOLVED requires both verified endpoints and width <= one grid step.

The estimate is `(stable_lower_s + unstable_upper_s) / 2`. An unresolved estimate
is null in JSON and blank in CSV, never zero or the scan cap. Binary search assumes
a locally monotonic boundary within the verified bracket.

## Fixed-duration comparison and caching

Each of the 20 cells first runs an independent 125 ms reference fault. Failure of
that reference terminates the cell's CCT workflow, preserving its reference data.
Angle/speed metrics describe the remaining SG set. Voltage metrics use the same
39 buses. Post-fault voltage minima use valid samples after the clearing event.
Early-failure peaks describe an accepted prefix, not a complete 8 s response.

Endpoint reuse is restricted to the same scenario, fault bus, model, program,
environment and configuration identity. Official trials and cross-scenario
trajectories are not reused for the renewable matrix. There is no automatic
solver change, iteration increase, recovery, failed-case deletion or TDS.reinit.

## Public result and test packaging

Published [summaries](../examples/results/) project verified final fields without
recalculating physical values. Internal directories and execution metadata are
omitted; source digests identify the original local archives. [Figure assets](assets/)
are byte-for-byte copies of saved final figures, not newly simulated results.

The 99 unit tests use synthetic trajectories and compact accepted model metadata.
Historical identity tests create an isolated temporary archive and copy the
accepted ten-machine M inventory into a tiny test-only array. They do not execute
ANDES PFlow/TDS or require private archives. The historical Python patch version
is a mocked identity-test input; it does not relax real-run cache checks.

Model assembly audit scripts retain their original behavior and may require a
full local validation archive. The four main workbooks are already included;
the public fault/CCT/batch/comparison entry points do not require that archive.
