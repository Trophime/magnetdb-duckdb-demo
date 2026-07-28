# Plan — hoop-stress part history, part-name columns, Bitter/Supra fatigue fix

Status: pending approval (not yet implemented)

## Goal

`hoop-stress compute --all` keeps writing one Parquet file per experiment (now
with part-name columns instead of slot names); a new
`hoop-stress part-history <part_name>` command aggregates a part's existing
bin-stats/fatigue-proxy across every site/magnet/experiment it has served in
and persists a chronologically-ordered concatenation of its raw stress time
series; and `hoop-stress history`/`fatigue` no longer silently drop
Bitter/Supra columns.

## Files affected

- `to_duckdb/compute_hoop_stats.py` — edit
- `to_duckdb/stress_map.py` — edit (fix `_column_meta` lookup **and** the
  `H\d+_fast`-only regexes in `cmd_fatigue` and `plot_stress_history`)
- `to_duckdb/magnetdb.py` — edit (new `hoop-stress part-history` subcommand +
  dispatch entry)
- `to_duckdb/docs/hoop-stress.md` — edit (document the new command, the
  renamed Parquet columns, and the Bitter/Supra fix)
- New: `to_duckdb/tests/test_part_history.py` (or extended into an existing
  hoop-stress test file — naming TBD once existing suite convention is
  checked)

## Approach

1. **Rename Parquet columns to part names** (`compute_hoop_stats.py`)
   - In `compute_hoop_stress_history`, build a renamed copy of `df` (via
     `part_map`) right before `save_hoop_parquet`; leave the original `df`
     untouched for bin-stats/fatigue computation, which still relies on
     `H*_fast`/`B*_fast`/`Supra*_fast` naming.
   - Fix `_column_meta` to key off the *original* slot name (via `part_map`)
     instead of parsing the (now renamed) column name directly.

2. **Aggregated per-part report + fatigue proxy** — new
   `part_history_stats(part_name, db_path)` in `compute_hoop_stats.py`,
   summing `hoop_stress_bin_stats` and `hoop_stress_fatigue` (`n_cycles`,
   `sum_range3`) across every experiment where the part contributed, resolved
   via `hoop_stress_bin_stats JOIN experiments`.

3. **Persisted raw concatenated history file** — new
   `build_part_history_series(part_name, db_path, parquet_dir)`: reads each
   relevant experiment's Parquet (via `hoop_stress_processed.parquet_path`),
   pulls the part's column + `t`, reconstructs an absolute timestamp from the
   `t0` table metadata, sorts chronologically across experiments/sites, and
   writes `<parquet_dir>/parts/<part_name>.parquet` (`timestamp`,
   `hoop_stress_MPa`, `experiment_id`, `site_name`). Experiments with
   pre-rename Parquet files (missing the part-named column) are skipped with
   a `[WARN]`.

4. **New CLI command** in `magnetdb.py`:
   `hoop-stress part-history <part_name> [--db ...] [--parquet-dir ...]` —
   prints the sites/experiments list and aggregated stats from step 2, writes
   the file from step 3, reports its path.

5. **Fix the Bitter/Supra drop bug** in `stress_map.py`:
   - `cmd_fatigue` (stress_map.py:1637): change
     `re.match(r"H\d+_fast", c)` → `re.match(r"(H|B|Supra)\d+_fast", c)`,
     matching the pattern already used correctly in `compute_stress_stats`
     (stress_map.py:1236).
   - `plot_stress_history` (stress_map.py:1318): same regex fix, so
     `hoop-stress history` plots all coil types, not just Helix.
   - `_load_history`'s preview-print regex (stress_map.py:1562): fix in the
     same pass for consistency, even though it only affects the console
     preview, not analysis/plotting.

6. **Docs** — update `docs/hoop-stress.md`: note the renamed Parquet columns,
   add the `part-history` section, and mention that `history`/`fatigue` now
   correctly include Bitter/Supra coils.

## Verification

1. Run `pytest to_duckdb/tests -k hoop` (excluding `test_matplotlib.py` — set
   `MPLBACKEND=Agg` or skip it, per known hang) — confirm no regressions in
   bin-stats/fatigue values after the column rename (only names change, not
   numbers).
2. Run `hoop-stress compute <one site> --reprocess --db <scratch db>` →
   verify the Parquet schema has part-name columns with correct
   `unit`/`symbol` metadata (via `pyarrow.parquet.read_schema`).
3. Run `hoop-stress part-history <a part spanning >= 2 experiments>` → verify
   the printed site/experiment list matches a manual `SELECT DISTINCT` query,
   and the output file's row count equals the sum of per-experiment row
   counts, sorted by timestamp.
4. On a site with Bitter or Supra parts, run
   `hoop-stress fatigue <site> --magnet-type all` and
   `hoop-stress history <site> --magnet-type all` before/after the fix →
   confirm B/Supra columns now appear in the rainflow report and the plot
   (previously silently absent).
5. New test(s) for `part_history_stats` (aggregation math on a small
   fixture) and `build_part_history_series` (ordering/concatenation on 2+
   fake per-experiment Parquets).

## Assumptions & open questions

- Part names (e.g. `H24110501`) are safe to use as Parquet column names /
  dict keys — no collision risk since `parts.name` is a primary key.
- The part-history file stays Parquet, not CSV, for consistency with the
  renamed per-experiment files — flag if CSV is wanted specifically for this
  deliverable.
- `hoop_stress_processed.parquet_path`: when an experiment has multiple
  `bin_config` rows, they share the same Parquet file; dedupe by
  `experiment_id` using latest `processed_at`.
