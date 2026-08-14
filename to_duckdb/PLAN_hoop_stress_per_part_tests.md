# Plan — Phase 4: test hoop-stress stats and bin history per part

Status: **tests written and passing (2026-08-14), uncommitted.** Part of the
[hoop-stress history initiative](PLAN_hoop_stress_history.md) — see that
file for the overall status and links to the other phases. Phase 3
([PLAN_hoop_stress_part_history.md](PLAN_hoop_stress_part_history.md)) had
already landed (commit `c975a5d`, `part_history_stats`/
`build_part_history_series` exist in `compute_hoop_stats.py`) even though
the tracking docs still said "not started" — corrected in this pass.

## Goal

Test coverage for `part_history_stats` (aggregation across experiments) and
`build_part_history_series` (chronological concatenation across
experiments/sites) — currently untested since they don't exist yet.

## Files affected

- Edited: `to_duckdb/tests/test_compute_hoop_stats.py` — extended into the
  existing hoop-stress test file (matches its established one-test-file-per-
  module convention; no new file needed).

## Approach

1. **Done** — `part_history_stats`: `part_history_fixture` (a new
   `_build_part_history_sites` helper + pytest fixture) spans 2 experiments
   across 2 sites (`SITE_A`, `SITE_B`) for one part (`H_NEW`).
   `test_part_history_stats_aggregates_bin_stats_and_fatigue_across_sites`
   asserts summed `n_cycles`/`sum_range3` and binned stats
   (`n_samples`/`sum_dt`/`sum_x_dt`/`sum_x2_dt`/`min_x`/`max_x`) against a
   manual aggregation over the fixture data.
   `test_part_history_stats_empty_for_part_with_no_recorded_data` covers the
   empty/zero path.
2. **Done** — `build_part_history_series`:
   `test_build_part_history_series_concatenates_chronologically_across_sites`
   writes 2 synthetic per-experiment Parquet files via the real
   `save_hoop_parquet()` (part-name-column schema, matching Phase 2) with
   out-of-order `t0` values, and asserts chronological reordering (not just
   append order) and correct row-count concatenation.
   `test_build_part_history_series_returns_none_when_no_data` covers the
   no-contributing-experiments path.
3. **Done** — `test_build_part_history_series_warns_and_skips_pre_rename_parquet`
   covers the `[WARN]`-skip path for an experiment whose Parquet still has
   the raw slot-name column (e.g. `H1_fast`) instead of the part-named one.

## Verification

- **Done** — new tests pass in isolation:
  `MPLBACKEND=Agg venv/bin/pytest to_duckdb/tests/test_compute_hoop_stats.py -k part_history`
  → 5 passed.
- **Blocked (environment)** — full `MPLBACKEND=Agg pytest to_duckdb/tests -k hoop`
  run: 27 passed + the 5 new ones, but 6 pre-existing
  `test_compute_hoop_stress_history_*` orchestration tests
  (`test_compute_hoop_stats.py`) error/fail because `stress_map.py` imports
  `magnettools`, which isn't installed in this machine's `to_duckdb/venv`.
  Unrelated to this phase's changes — confirmed pre-existing (those tests
  predate this work and don't touch `part_history_stats`/
  `build_part_history_series`). Needs the devcontainer (or the office
  machine, where `magnettools` is available) to re-verify the full run.
  `test_stress_map.py` also fails to collect for the same reason.
- **Not done** — cross-check against a real part spanning >= 2 experiments
  in a scratch DB (`test-magnetdb.duckdb`): needs the devcontainer/office
  environment too (real `hoop-stress compute` run requires `magnettools`).

## Assumptions & open questions

- None outstanding for the test-writing itself. Remaining work is purely
  re-verifying the full suite and the real-DB cross-check once
  `magnettools` is available, and then committing (Phase 1–4 are all still
  **uncommitted** per `PLAN_hoop_stress_history.md`).
