# Plan — Phase 5: fatigue per part — is it a cumulative stat?

Status: **done (2026-08-18)**. Part of the
[hoop-stress history initiative](PLAN_hoop_stress_history.md) — see that
file for the overall status and links to the other phases. **Depended on**
[PLAN_hoop_stress_part_history.md](PLAN_hoop_stress_part_history.md)
(Phase 3, satisfied) — used `build_part_history_series`'s concatenated raw
series to compare against. Resolves the `TODOs.md` stress-section line
*"test if fatigue can be used like a cumulative stats??"*

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

- **Done** — real-data check (read-only, no DB writes): for 3 real parts
  (`H21102801`, `H22102401`, `H21091701`) spanning the same 71 real
  experiments (site `M9_A230608_00`, `test-magnetdb.duckdb`), summed
  per-experiment `hoop_stress_fatigue` vs. a single `_rainflow_stats` pass
  on `build_part_history_series`'s concatenated output:
  - `sum_range3` agrees to float64 rounding (~1e-6 absolute out of ~1e9) —
    additive in practice.
  - `n_cycles` differs by a small, consistent amount (-8 out of 261,031,
    ~0.003%, concatenated always ≤ summed across all 3 parts).
  - Root cause: all 71 experiments' raw series start/end at exactly 0 MPa,
    but 16 of the 71 leave an internal unresolved half-cycle residual
    (fractional `n_cycles` in `hoop_stress_fatigue`) even so — those
    residuals pair differently across a file boundary when processed as one
    continuous series vs. per-experiment.
- **Done** — 2 new tests added to `to_duckdb/tests/test_compute_hoop_stats.py`
  (extending that file per Phase 4's established convention, not a separate
  `test_part_history.py`):
  - `test_part_history_fatigue_matches_concatenated_rainflow_when_experiments_idle_at_zero`:
    full-pipeline fixture (two zero-boundary, internally self-closed
    synthetic experiments) — asserts exact agreement, mirroring the
    mechanism behind the real-data near-match.
  - `test_rainflow_stats_boundary_discontinuity_breaks_additivity`: a
    synthetic pair whose join isn't at a shared reference value — asserts
    the discrepancy is real and non-trivial (`n_cycles` summed 2.5 vs.
    concatenated 3.0; `sum_range3` summed 618,125 vs. concatenated
    1,118,125), documenting that additivity is not a general guarantee.
- **Done** — `MPLBACKEND=Agg to_duckdb/venv-systempackages/bin/python3 -m
  pytest to_duckdb/tests -k hoop`: 36 passed (34 from Phase 4 + these 2),
  `test_stress_map.py` still 12/12.
- **Done** — finding documented in
  [docs/hoop-stress.md](docs/hoop-stress.md#is-fatigue-additive-across-experiments)
  and `TODOs.md`'s stress-section line checked off.

## Assumptions & open questions

- None outstanding. This phase was exploratory by nature — the deliverable
  was the documented finding (summarized above and in
  `docs/hoop-stress.md`), not a production code change; none was made.
