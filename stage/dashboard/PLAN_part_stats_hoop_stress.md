# Plan — hoop-stress bin history in the Part stats dashboard

Status: implemented and verified (2026-08-21), uncommitted.

## Goal

Wire the already-stubbed "📈 Hoop stress history" accordion in
`part_stats.py` (`/part_stats`) to real per-part data — a summary stats
table, a stress-bin histogram, and a raw hoop-stress-vs-time history plot —
sourced from `hoop_stress_bin_stats`/`hoop_stress_fatigue` and the per-part
Parquet files already produced by `hoop-stress part-history`
(`to_duckdb`'s hoop-stress pipeline, see `to_duckdb/PLAN_hoop_stress_history.md`,
Phases 1–5, done). No hours/"Operating Time" framing anywhere in this new
section — see [Context](#context) below.

## Context

- The accordion layout stub already exists
  (`stage/dashboard/src/pages/part_stats.py:374-403`, ids
  `part-stats-hoop-stress-fig` / `part-stats-hoop-stress-table`) but has no
  loader function and isn't wired into the page's callback.
- Backing data already exists in `test-magnetdb.duckdb`: 2409
  `hoop_stress_bin_stats` rows / 1152 `hoop_stress_fatigue` rows / 72
  processed experiments; 4 parts already have a pre-built
  `hoop_parquet/parts/<part>.parquet` (e.g. `H21102801.parquet`, ~1.28M
  rows across 71 experiments) from earlier `hoop-stress part-history` runs.
  Production `magnetdb.duckdb` has none of this yet.
- `exp_part_bin_stats` (a separate, older table — Icoil/Ucoil/hoop_stress_proxy
  field-binned stats, populated by `compute_exp_stats.py`) is **not** touched
  by this plan. It currently backs `part_stats.py`'s "Operating time (h)"
  column, "Peak hoop stress proxy (A²)" column, and the "Operating Time per
  Part" chart — all three channels it stores are slated for removal, tracked
  separately below in [Follow-up (deferred)](#follow-up-deferred--drop-exp_part_bin_stats).
  There is no dependency between `exp_part_bin_stats` and
  `hoop_stress_bin_stats`/`hoop_stress_fatigue` (the tables this plan reads),
  so the two efforts are fully decoupled.

## Files affected

- `stage/dashboard/src/magnetdb_analysis.py` — edit: add 3 read-only
  data-access functions.
- `stage/dashboard/src/pages/part_stats.py` — edit: extend the accordion
  layout, add a `_hoop_stress_section()` helper, wire 4 new callback
  outputs.

## Approach

1. `magnetdb_analysis.py`: `get_hoop_stress_summary_for_part(part_name,
   db_path=None)` — SQL aggregate over `hoop_stress_bin_stats` +
   `hoop_stress_fatigue` (same shape as `compute_hoop_stats.part_history_stats()`'s
   two queries, reimplemented here so the dashboard doesn't import the
   `to_duckdb` package). Returns `n_experiments`, `n_samples`, `mean_MPa`
   (time-weighted, computed internally from `sum_x_dt/sum_dt` but **not**
   displayed as hours), `stddev_MPa`, `peak_MPa`, `n_cycles`, `sum_range3`
   — zeroed/`None` if the part has no rows.
2. `magnetdb_analysis.py`: `get_hoop_stress_bin_stats_for_part(part_name,
   db_path=None)` — per-bin `GROUP BY stress_bin_low, stress_bin_high`,
   returns a DataFrame with `stress_bin_low`, `stress_bin_high`, `n_samples`
   only (no time/hours field), sorted by `stress_bin_low`.
3. `magnetdb_analysis.py`: `load_hoop_stress_history_for_part(part_name,
   db_path=None)` — reads `Path(db_path).parent / "hoop_parquet" / "parts" /
   f"{part_name}.parquet"` via `pd.read_parquet` if present, else `None`.
4. `part_stats.py` layout: repurpose `part-stats-hoop-stress-table` for the
   summary row (columns: Experiments, Samples, Mean (MPa), Std dev (MPa),
   Peak (MPa), Cycles, Fatigue proxy (MPa³)); repurpose
   `part-stats-hoop-stress-fig` as the bin histogram (`n_samples` per bin);
   add a new `dcc.Graph(id="part-stats-hoop-stress-history-fig")` for the
   raw series; add `html.Div(id="part-stats-hoop-stress-banner")` for status
   messages (reusing the gray-italic style already used elsewhere on this
   page).
5. `part_stats.py`: new `_hoop_stress_section(selected_part, db_path)`
   helper, mirroring `_magnet_history_section` — handles "no part selected",
   "no hoop-stress data for this part" (names the `hoop-stress compute`
   command to run), "bin stats present but no raw-history Parquet yet"
   (names the `hoop-stress part-history` command; history graph shows an
   inline message instead of erroring), and the full-data case.
6. Bin histogram via `px.bar` (bin range on x, `n_samples` on y) — matches
   this page's existing `fig_hours`/`fig_magnet_time` bar-chart idiom, no
   forced template.
7. History plot via `go.Scattergl` (WebGL) for performance. Before
   plotting, run the loaded `(timestamp, hoop_stress_MPa)` DataFrame through
   `python_magnetrun.utils.downsampling.downsample_dataframe(df,
   time_col="timestamp", value_cols=["hoop_stress_MPa"],
   config=DownsampleConfig(n_out=1000, method="lttb"))` — the same
   function/defaults `magnetdb_plot.py`'s `create_plot()` already uses for
   File Viewer's "LTTB" downsampling option, so a part like `H21102801`
   (~1.28M rows) reduces to 1000 shape-preserving points instead of a naive
   stride subsample. `downsample_dataframe` already no-ops when the input
   has ≤ `n_out` rows.
8. Wire the 4 new `Output`s into `update_part_stats`, calling
   `_hoop_stress_section` alongside the existing magnet/assembly-history
   calls, threading results through both the early-return and
   normal-return branches.

## Verification

1. Launch the dashboard (`MAGNETDB_DB_PATH=.../to_duckdb/test-magnetdb.duckdb
   stage/dashboard/venv/bin/python3 stage/dashboard/src/magnetdb_app.py`),
   open `/part_stats` in a browser:
   - No part selected → prompt banner, no errors.
   - Select `H21102801` (165 bin-stat rows + prebuilt `H21102801.parquet`,
     ~1.28M rows) → table, histogram, and history plot all render; history
     plot stays responsive.
   - Select a part with `hoop_stress_bin_stats` rows but no file under
     `hoop_parquet/parts/` → table/histogram populate, history graph shows
     the "run part-history" message.
   - Select a part with no hoop-stress data at all → "not computed" banner,
     no crash.
2. Re-exercise the page's existing filters/charts once to confirm no
   regression.

## Assumptions & open questions

- Bin histogram uses **sample count** (`n_samples`), not time-in-bin —
  flag if you'd rather see something else non-hours-based (e.g. cumulative
  % of samples).
- History plot design is unaffected by the Operating-Time discussion — same
  raw MPa-vs-time plot as originally scoped.
- Downsampling reuses File Viewer's existing LTTB pipeline
  (`python_magnetrun.utils.downsampling.downsample_dataframe`/
  `DownsampleConfig`, `n_out=1000`) rather than a bespoke method, so this
  plot's reduction behavior matches the rest of the dashboard exactly.
- No dashboard-level pytest suite exists for `part_stats.py` or its sibling
  pages — verification above is manual/browser-based, matching how the
  sibling pages (`magnet_stats.py`, `assembly_stats.py`, `housing_stats.py`)
  were apparently verified. Flag if you want unit tests added for the 3 new
  `magnetdb_analysis.py` query functions (straightforward against a scratch
  DuckDB fixture).

---

## Follow-up (deferred) — drop `exp_part_bin_stats`

Not part of this plan's execution scope; tracked here for its own future
plan+approval cycle.

**Scope**: drop the entire table — all three channels it stores (`Icoil`,
`Ucoil`, `hoop_stress_proxy`) are unwanted: `hoop_stress_proxy` is
superseded by the real MPa pipeline (`hoop_stress_bin_stats`/
`hoop_stress_fatigue`, what this plan reads), and `Icoil`/`Ucoil` are to be
dropped too.

**Known touch points** (from investigation during this plan's discussion):

- `to_duckdb/compute_exp_stats.py` — remove `compute_part_bin_stats()`/
  `insert_part_bin_stats()` and their calls inside `ingest_assembly()`'s
  per-experiment loop (`compute_exp_stats.py:462-466`). Note: the loop's
  single `try` block means `insert_scalars`/`insert_assembly_bin_stats`
  currently commit even if the part-bins insert fails (no transaction
  wrapping), and `mark_processed()`/`status = 'STATS DONE'` never run in
  that case — so simply dropping the table without editing the script would
  silently half-process every experiment, forever. This needs an actual
  code change, not just a table drop.
- `to_duckdb/schema.py` — remove the `exp_part_bin_stats` `CREATE TABLE`
  block from `ensure_schema()`. A real `DROP TABLE` still needs to run
  against each live `.duckdb` file separately (schema.py only governs
  future `ensure_schema()` calls).
- `stage/dashboard/src/pages/part_stats.py` — remove the
  `exp_part_bin_stats` LEFT JOIN, `_warn_exp_part_bin_stats`, the
  "Operating time (h)" / "Peak hoop stress proxy (A²)" columns, and the
  "Operating Time per Part" chart (or repoint `fig_hours` at something
  else).
- Docs/tests referencing the table: `to_duckdb/docs/statistics.md`,
  `to_duckdb/docs/query_cumstats.md`, `to_duckdb/tutorials/query_cumstats.py`
  (has live queries against it), `to_duckdb/tests/test_schema.py` (asserts
  it exists), `to_duckdb/schema_diagram.py`, `stage/NOTICE_DASHBOARD.md`.
- Out of scope for this follow-up: `exp_run_scalars` and
  `exp_assembly_bin_stats` — same script, but separate tables with other
  consumers, untouched by this drop.
