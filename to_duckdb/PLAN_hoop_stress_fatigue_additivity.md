# Plan — Phase 5: fatigue per part — is it a cumulative stat?

Status: pending approval, not started. Part of the
[hoop-stress history initiative](PLAN_hoop_stress_history.md) — see that
file for the overall status and links to the other phases. **Depends on**
[PLAN_hoop_stress_part_history.md](PLAN_hoop_stress_part_history.md)
(Phase 3) — needs `build_part_history_series`'s concatenated raw series to
compare against. Resolves the `TODOs.md` stress-section line *"test if
fatigue can be used like a cumulative stats??"*

## Goal

Determine whether summing per-experiment rainflow fatigue proxies
(`hoop_stress_fatigue.n_cycles`/`sum_range3`, as aggregated by
`part_history_stats`) is equivalent to running rainflow counting once on a
part's full chronologically-concatenated raw stress series
(`build_part_history_series`'s output) — and document the answer, whichever
way it comes out.

## Files affected

- New: test/validation script or addition to
  `to_duckdb/tests/test_part_history.py` (exact location TBD alongside
  Phase 4)
- `to_duckdb/docs/hoop-stress.md` — edit (document the finding)

## Approach

1. For a real part spanning >= 2 experiments (or a synthetic multi-file
   fixture), compute:
   - (a) the DB-aggregated sum of per-experiment `n_cycles`/`sum_range3`
     (via `part_history_stats`), and
   - (b) rainflow counted once on the full concatenated series (via
     `build_part_history_series`'s output Parquet).
2. Compare (a) and (b). Rainflow cycle-counting is not generally additive
   across arbitrary segment boundaries — a cycle straddling two experiment
   files could be counted differently (or missed) when done per-file vs. on
   the joined series — so this is a real, open question, not a foregone
   "yes."
3. Document whichever outcome holds in `docs/hoop-stress.md`: exact
   agreement, or a bounded/characterized discrepancy from boundary effects.
   If they diverge, do **not** silently force agreement — record the
   discrepancy and let it inform whether per-experiment summing is
   acceptable for fatigue-tracking purposes going forward.

## Verification

- A test asserting the two aggregation paths agree on a small synthetic
  multi-file fixture, or — if they don't — asserting the discrepancy stays
  within a documented, understood bound.
- `MPLBACKEND=Agg pytest to_duckdb/tests -k hoop` full pass.

## Assumptions & open questions

- This phase is exploratory by nature — the answer isn't known in advance.
  The deliverable is the documented finding, not a specific code change.
