# Plan — hoop-stress part history, part-name columns, Bitter/Supra fatigue fix

Status: Phase 1 (compute pipeline correctness) implemented and verified
end-to-end (2026-08-13), **uncommitted**. Phases 2–5 (Parquet part-name
columns, `part-history` command, per-part stats/fatigue tests,
fatigue-additivity question) not yet started.

## Phase 1 — done (compute pipeline correctness)

Originally scoped as just the Bitter/Supra regex drop (item 5 below), this
grew substantially during implementation: real-data verification against
`test-magnetdb.duckdb` surfaced a chain of previously-hidden bugs, each only
reachable once the prior one was fixed. `hoop-stress compute` had never
actually succeeded against real data before this pass.

1. **`prepare_geometry_directory()` call fix** (`compute_hoop_stats.py`) — was
   called once per magnet with an invalid `geometry_data` kwarg the function
   doesn't accept, silently swallowed by a bare `except`. Fixed to a single
   per-site call with a `{"name":..., "magnets":[...]}` config dict, matching
   `_load_site()`'s already-working pattern.
2. **Stale docstrings corrected** (`stress_map.py`) — `prepare_geometry_directory`/
   `geometry_config_to_yaml` described a "geometry_data argument" source that
   was never implemented; both now document the real design: geometry is
   always rebuilt on the fly from `parts.geometry_data` (the only geometry
   ever persisted), never from a passed-in argument or `magnets.geometry_data`.
   `magnetdb.py magnet add --geometry`'s help text corrected to match (it
   stores an optional cache, not something the hoop-stress pipeline reads).
3. **`magnets.geometry_data` flagged in `ROADMAP.md`** as a future cleanup
   candidate (vestigial under the on-the-fly design) — not dropped, still has
   real writers (`magnet add --geometry`, `check --fix`).
4. **DuckDB connection-reuse fix** — `compute_hoop_stress_history` held its
   own read-write connection open while `prepare_geometry_directory` tried to
   open a second, read-only connection to the same file (DuckDB disallows
   this). Fixed by threading `con=` reuse through `prepare_geometry_directory`
   → `geometry_config_to_yaml` → `magnet_geometry_config_to_yaml`, the same
   pattern `load_site_config_from_duckdb` already used.
5. **`load_magnettools()` call fix** — was called with a malformed config
   (`_merge_configs()`, now deleted along with its tests) instead of the
   site-shaped `{"name":..., "magnets":[...]}` dict `msite_setup()` actually
   requires (`confdata['magnets']`, unconditionally). Fixed to reuse the same
   `site_config` built for step 1.
6. **Bitter multi-plate crash fix** — a Bitter part can decompose into
   multiple physical plates (`BMagnets`, via `mt.create_Bstack`), but
   `build_part_column_map` assumes one column per DB part, so extra plates
   fell back to using the raw column name as `part_name`, violating the
   `hoop_stress_bin_stats.part_name` foreign key. Fixed by grouping `BMagnets`
   per part via `mt.create_Bstack()` and collapsing to one representative
   value per part in `validate_fast_from_pupitre()` — no schema change,
   `part_name` stays the plain part name (`build_part_column_map` untouched).
7. **Representative-section selection fixed for both Helix and Bitter** — the
   old heuristic (`mid_elem`, an array-index "middle") had a genuine off-by-one
   bug, confirmed against real data (a Bitter part with `turns=[6,158,6]`:
   `mid_elem` picked an end section, not the actual z=0-centered one).
   Replaced with `_section_index_at_z()` (`stress_map.py`), which finds the
   section whose z-extent actually contains an observation point z0 — Bz is
   evaluated at that same point via a reworked `_bz_at(radii, z0s)`. z0 is
   resolved **per magnet** from `site_magnets.z_offset` (new
   `resolve_z0_by_type()` in `compute_hoop_stats.py`, mirroring
   `build_part_column_map`'s traversal), defaulting to `0.0` — matches all
   current real data (0 of 89 `site_magnets` rows have non-zero `z_offset`).
   No CLI flag; fully automatic and DB-driven.
8. **3 `H\d+_fast`-only regexes fixed** (`stress_map.py`: `cmd_fatigue`,
   `plot_stress_history`, `_load_history`'s preview print) → `(H|B|Supra)\d+_fast`,
   matching the pattern `compute_stress_stats` already used correctly.
9. **Tests**: orchestration test added for `compute_hoop_stress_history()`
   (previously completely untested — the deferred `PROMPT_test_hoop_orchestration.md`
   is now obsolete), unit tests for `compute_stress_stats()`,
   `_section_index_at_z()`, `resolve_z0_by_type()`, and regression tests
   locking in the regex fix.

**Verified**: 306/306 tests pass (`MPLBACKEND=Agg pytest tests -k hoop`,
excluding `test_matplotlib.py`); real end-to-end run on site `M9_A241202_00`
against `test-magnetdb.duckdb` — 14 Helix parts + 2 Bitter parts, correct
writes to `hoop_stress_bin_stats`/`hoop_stress_fatigue`/`hoop_stress_processed`,
Parquet output confirmed.

**Not committed.**

## Phase 2+ — remaining (not started)

### Goal

`hoop-stress compute --all` writes Parquet with part-name columns instead of
slot names; a new `hoop-stress part-history <part_name>` command aggregates a
part's bin-stats/fatigue-proxy across every site/magnet/experiment it has
served in and persists a chronologically-ordered concatenation of its raw
stress time series.

### Files affected

- `to_duckdb/compute_hoop_stats.py` — edit
- `to_duckdb/magnetdb.py` — edit (new `hoop-stress part-history` subcommand +
  dispatch entry)
- `to_duckdb/docs/hoop-stress.md` — edit (document the new command and the
  renamed Parquet columns)
- New: `to_duckdb/tests/test_part_history.py` (or extended into an existing
  hoop-stress test file — naming TBD once existing suite convention is
  checked)

### Approach

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

5. **Docs** — update `docs/hoop-stress.md`: note the renamed Parquet columns
   and add the `part-history` section.

### Verification

1. Run `MPLBACKEND=Agg pytest to_duckdb/tests -k hoop` — confirm no
   regressions in bin-stats/fatigue values after the column rename (only
   names change, not numbers).
2. Run `hoop-stress compute <one site> --reprocess --db <scratch db>` →
   verify the Parquet schema has part-name columns with correct
   `unit`/`symbol` metadata (via `pyarrow.parquet.read_schema`).
3. Run `hoop-stress part-history <a part spanning >= 2 experiments>` → verify
   the printed site/experiment list matches a manual `SELECT DISTINCT` query,
   and the output file's row count equals the sum of per-experiment row
   counts, sorted by timestamp.
4. New test(s) for `part_history_stats` (aggregation math on a small
   fixture) and `build_part_history_series` (ordering/concatenation on 2+
   fake per-experiment Parquets).

### Assumptions & open questions

- Part names (e.g. `H24110501`) are safe to use as Parquet column names /
  dict keys — no collision risk since `parts.name` is a primary key.
- The part-history file stays Parquet, not CSV, for consistency with the
  renamed per-experiment files — flag if CSV is wanted specifically for this
  deliverable.
- `hoop_stress_processed.parquet_path`: when an experiment has multiple
  `bin_config` rows, they share the same Parquet file; dedupe by
  `experiment_id` using latest `processed_at`.
- Carried from the original master plan, not yet addressed: testing hoop
  stress stats/bin history per part (Phase 4), and the fatigue-additivity
  question — whether summed per-experiment rainflow (`n_cycles`/`sum_range3`)
  matches single-pass rainflow on a part's full concatenated series (Phase 5,
  resolves the `TODOs.md` "test if fatigue can be used like a cumulative
  stats??" line).
