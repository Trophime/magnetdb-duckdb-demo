# Plan — Phase 3: going from site to part (`hoop-stress part-history`)

Status: pending approval, not started. Part of the
[hoop-stress history initiative](PLAN_hoop_stress_history.md) — see that
file for the overall status and links to the other phases. **Depends on**
[PLAN_hoop_stress_parquet_columns.md](PLAN_hoop_stress_parquet_columns.md)
(Phase 2) landing first — `build_part_history_series` reads Parquet columns
by part name. Phase 4
([PLAN_hoop_stress_per_part_tests.md](PLAN_hoop_stress_per_part_tests.md))
and Phase 5
([PLAN_hoop_stress_fatigue_additivity.md](PLAN_hoop_stress_fatigue_additivity.md))
both depend on this one.

## Goal

A new `hoop-stress part-history <part_name>` command aggregates a part's
bin-stats/fatigue-proxy across every site/magnet/experiment it has served
in, and persists a chronologically-ordered concatenation of its raw stress
time series.

## Files affected

- `to_duckdb/compute_hoop_stats.py` — edit
- `to_duckdb/magnetdb.py` — edit (new `hoop-stress part-history` subcommand +
  dispatch entry)
- `to_duckdb/docs/hoop-stress.md` — edit (document the new command)

## Approach

1. **Aggregated per-part report + fatigue proxy** — new
   `part_history_stats(part_name, db_path)` in `compute_hoop_stats.py`,
   summing `hoop_stress_bin_stats` and `hoop_stress_fatigue` (`n_cycles`,
   `sum_range3`) across every experiment where the part contributed, resolved
   via `hoop_stress_bin_stats JOIN experiments`.

2. **Persisted raw concatenated history file** — new
   `build_part_history_series(part_name, db_path, parquet_dir)`: reads each
   relevant experiment's Parquet (via `hoop_stress_processed.parquet_path`),
   pulls the part's column + `t`, reconstructs an absolute timestamp from the
   `t0` table metadata, sorts chronologically across experiments/sites, and
   writes `<parquet_dir>/parts/<part_name>.parquet` (`timestamp`,
   `hoop_stress_MPa`, `experiment_id`, `site_name`). Experiments with
   pre-rename Parquet files (missing the part-named column) are skipped with
   a `[WARN]`.

3. **New CLI command** in `magnetdb.py`:
   `hoop-stress part-history <part_name> [--db ...] [--parquet-dir ...]` —
   prints the sites/experiments list and aggregated stats from step 1, writes
   the file from step 2, reports its path.

4. **Docs** — update `docs/hoop-stress.md`: add the `part-history` section.

## Verification

1. Run `hoop-stress part-history <a part spanning >= 2 experiments>` → verify
   the printed site/experiment list matches a manual `SELECT DISTINCT` query,
   and the output file's row count equals the sum of per-experiment row
   counts, sorted by timestamp.
2. `MPLBACKEND=Agg pytest to_duckdb/tests -k hoop` full pass.

## Assumptions & open questions

- The part-history file stays Parquet, not CSV, for consistency with the
  renamed per-experiment files — flag if CSV is wanted specifically for this
  deliverable.
- `hoop_stress_processed.parquet_path`: when an experiment has multiple
  `bin_config` rows, they share the same Parquet file; dedupe by
  `experiment_id` using latest `processed_at`.
