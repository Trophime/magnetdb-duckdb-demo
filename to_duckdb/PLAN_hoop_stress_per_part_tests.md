# Plan — Phase 4: test hoop-stress stats and bin history per part

Status: **done (2026-08-18), uncommitted.** Tests written and passing since
2026-08-14; full-suite re-verification and the real-DB cross-check
(previously blocked on `magnettools`) completed 2026-08-18 against
`venv-systempackages`, where `magnettools` is now confirmed importable. Part
of the [hoop-stress history initiative](PLAN_hoop_stress_history.md) — see
that file for the overall status and links to the other phases. Phase 3
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
- **Done (2026-08-18)** — full `MPLBACKEND=Agg to_duckdb/venv-systempackages/bin/python3 -m pytest to_duckdb/tests -k hoop`
  run (`magnettools` confirmed importable in `venv-systempackages`): **34
  passed**, 0 failed/errored — includes the 5 `part_history` tests and the
  6 previously-blocked `test_compute_hoop_stress_history_*` orchestration
  tests, all in `test_compute_hoop_stats.py`. `test_stress_map.py` (whose
  test names don't match `-k hoop`, run separately) now collects and passes
  **12/12**, vs. previously failing to collect at all. Unrelated pre-existing
  failures in `test_checks.py`/`test_crud.py`/`test_populate.py` (36 failed,
  40 errored) surfaced in a full non-`-k hoop` run — out of scope for this
  phase, untouched by any hoop-stress change.
- **Done (2026-08-18)** — real-DB cross-check: `python magnetdb.py
  hoop-stress part-history H21102801 --db test-magnetdb.duckdb` against
  part `H21102801` (Helix), which spans 71 real experiments on site
  `M9_A230608_00` already computed in `test-magnetdb.duckdb` (from an
  earlier real `hoop-stress compute` run, 2026-08-13 — no fresh `compute`
  run needed). `part_history_stats`' aggregated bin stats summed to
  664,948 + 337,089 + 281,367 = **1,283,404** samples;
  `build_part_history_series`' output Parquet
  (`hoop_parquet/parts/H21102801.parquet`) independently has **1,283,404
  rows** across all 71 `experiment_id`s, exact match, confirming the two
  functions agree on the same underlying data. Row-wise timestamps are
  monotonically increasing (chronological concatenation verified), and
  `hoop_stress_MPa` max (279.6 MPa) matches the top bin's reported max.

## Assumptions & open questions

- None outstanding. Test-writing, full-suite re-verification, and the
  real-DB cross-check are all complete. Remaining step is committing
  (Phase 1–4 are all still **uncommitted** per
  `PLAN_hoop_stress_history.md`) — left to the user's discretion, not part
  of this phase's scope.
