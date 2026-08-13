# Plan — Phase 4: test hoop-stress stats and bin history per part

Status: pending approval, not started. Part of the
[hoop-stress history initiative](PLAN_hoop_stress_history.md) — see that
file for the overall status and links to the other phases. **Depends on**
[PLAN_hoop_stress_part_history.md](PLAN_hoop_stress_part_history.md)
(Phase 3) — `part_history_stats`/`build_part_history_series` must exist
before they can be tested.

## Goal

Test coverage for `part_history_stats` (aggregation across experiments) and
`build_part_history_series` (chronological concatenation across
experiments/sites) — currently untested since they don't exist yet.

## Files affected

- New: `to_duckdb/tests/test_part_history.py` (or extended into an existing
  hoop-stress test file — naming TBD once Phase 3 lands and the existing
  suite convention at that point is checked)

## Approach

1. `part_history_stats` — fixture spanning >= 2 experiments across >= 2
   sites for one part; assert the summed `n_cycles`/`sum_range3` and binned
   stats match a manual aggregation over the fixture data.
2. `build_part_history_series` — fixture with 2+ synthetic per-experiment
   Parquet files (matching the Phase 2 part-name-column schema); assert
   correct chronological ordering (via `t0` reconstruction) and correct
   row-count concatenation across experiments/sites.
3. Cover the `[WARN]`-skip path for experiments with pre-rename Parquet
   files (missing the part-named column).

## Verification

- New tests pass; `MPLBACKEND=Agg pytest to_duckdb/tests -k hoop` full pass.
- Cross-check against a real part spanning >= 2 experiments in a scratch DB
  (`test-magnetdb.duckdb`): printed site/experiment list matches a manual
  `SELECT DISTINCT` query, and the output file's row count equals the sum
  of per-experiment row counts, sorted by timestamp.

## Assumptions & open questions

- None yet — will firm up once Phase 3's actual function signatures exist.
