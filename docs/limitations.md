# Limitations

- IEEE39 and the adapted IEEE39 system are educational benchmarks; results are not
  a validation of an operating power grid or a protection setting recommendation.
- REGCP1 + PLL2 + REECB1 is a system-level generic GFL representation, not a
  validated manufacturer-specific converter or electromagnetic-transient model.
- The 180° criterion screens the remaining synchronous-machine rotor-angle
  subsystem. It is not sufficient to establish converter internal stability.
- Results depend on the 8 s observation horizon, 1/128 s grid, one-grid final
  interval and bounded 500 ms discovery. Binary search assumes local monotonicity.
- Numerical failures prevent some comparisons. Replacement location, SG set,
  inertia and controls vary together; no monotonic renewable-share effect or
  isolated causal effect is claimed.

An unresolved estimate remains null. A stable 500 ms trial establishes a tested
lower bound, not an exact CCT. A short failed prefix cannot be compared as a full
8 s response. No automatic solver recovery was used to fill missing cells.
