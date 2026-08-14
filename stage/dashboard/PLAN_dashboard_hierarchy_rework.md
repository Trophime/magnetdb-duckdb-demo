# Dashboard hierarchy rework

**Status:** Awaiting approval — do not implement until explicitly approved (`approve`/`approved`/`go`/`proceed`/`LGTM`). Anything else (questions, edits, silence) is not approval; revise and re-present.

## Goal

Make `housing_stats` the dashboard landing page, retire `comparison`/`metrics`/`summary` from
the nav without deleting their code, and add an overview-record file-viewer page that
auto-loads its `sources_overview`/`sources_archive`/`sources_pupitre` files and overlays
`sources_default`/`sources_spike` as figure annotations (reusing the event-marker logic from
`magnetdb_plot.create_comparison_plot`). Plus site/magnet/part accordion links (Overview
records + Experiments), ordered history drill-downs, DB-wide summary counts (filter-aware),
and missing-data messaging across the reworked pages.

## Context / background

Starting point was `to_duckdb/TODOs.md`'s "rework dashboards to start with housing and then go
down to magnet" item. Investigation found 3 of the 4 proposed tiers already existed
(`site_stats.py` at `/`, `magnet_stats.py`, `part_stats.py`) — only the top-level `housing`
page was missing. The FK structure in `to_duckdb/schema.py` (`housing_config` → `sites` →
`site_magnets` ⋈ `magnets` → `magnet_parts` ⋈ `parts`) confirms the hierarchy is a real DAG
with time-varying membership, not a strict tree, which is why "history of X" accordion tables
(not rigid ownership) are the right shape.

Key data-availability findings from the live databases
(`to_duckdb/test-magnetdb.duckdb`, `to_duckdb/magnetdb.duckdb`):
- `sites.commissioned_at` is populated — magnet-level "site history" can be ordered correctly
  today.
- `site_magnets.commissioned_at` is 0% populated in both databases (0/15, 0/89) and
  `magnet_parts` has no date column at all (only `rank`/`coil_index`) — so part-level "magnet
  history" cannot be date-ordered from existing data.
- Resolution (user decision): add `magnets.created_at` to `to_duckdb/schema.py` and order the
  part→magnet history table by that. It will be NULL for existing magnets until backfilled
  separately (out of scope here — a `to_duckdb` ingestion/data-entry task, not a dashboard
  change).

Annotation logic for incident files already exists in `magnetdb_plot.py::create_comparison_plot()`
(not in `comparison.py` itself): files classified `default`/`spike`/`trigger` via
`classify_pigbrother_file()` get a single marker+text at their peak value instead of a line
trace, styled via the existing `FILE_TYPE_STYLES` (which already defines
`overview`/`archive`/`pupitre`/`default`/`spike`/`trigger`). That function also does two-row
raw/aligned-comparison plotting and lag/sync math that the new overview-records page doesn't
need, so the plan extracts just the annotation-vs-line logic into a new, simpler function
rather than reusing or modifying `create_comparison_plot`.

Confirmed via grep: nothing outside `comparison.py`/`metrics.py`/`summary.py` (the *pages*)
imports those page modules, so relocating them out of Dash's auto-discovered `pages/` folder
is safe. Note `src/metrics.py` (shared module, used by `comparison.py` for
`evaluate_metrics`/`generate_metrics_report`) is a different file from `src/pages/metrics.py`
(the page being deactivated) — moving the page does not affect the shared module.

## Files affected

**Create**
- `stage/dashboard/src/pages/housing_stats.py` — landing page, `path="/"`, `order=1`.
- `stage/dashboard/src/pages/overview_records.py` — new page, `path="/overview-records"`,
  `order=5`. Site dropdown → overview_record dropdown (chronological, reuses
  `get_overview_records_for_site`) → X-axis + downsampling selectors → per-group accordion
  (mirrors `home.py`'s `html.Details`/checklist/graph pattern, group list via existing
  `db.get_common_groups`). Each group's graph draws `sources_overview`/`sources_archive`/
  `sources_pupitre` files as lines and `sources_default`/`sources_spike` files as event-marker
  annotations. Missing-data banner if the record has no loadable sources.

**Move (deactivate as pages, keep the code)**
- `stage/dashboard/src/pages/comparison.py` → `stage/dashboard/src/pages_disabled/comparison.py`
- `stage/dashboard/src/pages/metrics.py` → `stage/dashboard/src/pages_disabled/metrics.py`
- `stage/dashboard/src/pages/summary.py` → `stage/dashboard/src/pages_disabled/summary.py`

**Edit**
- `to_duckdb/schema.py` — add `magnets.created_at` (idempotent
  `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`).
- `stage/dashboard/src/magnetdb_analysis.py` — add `get_db_counts`,
  `get_overview_records_for_magnet`, `get_overview_records_for_part`,
  `get_site_history_for_magnet`, `get_magnet_history_for_part`, `get_field_bin_history`, and
  `get_overview_record_sources(filename, db_path=None)` (fetches `housing`, `site_name`, and
  the five `sources_*` arrays for one record).
- `stage/dashboard/src/magnetdb_plot.py` — add
  `create_annotated_plot(files_data, x_col, method, group_name)`: single-subplot version of
  the event-vs-line logic from `create_comparison_plot`, no lag/sync/two-row layout.
- `stage/dashboard/src/experiment_links.py` — add `overview_record_link(row)` (same shape as
  the existing `experiment_link`), producing links into `/overview-records`.
- `stage/dashboard/src/pages/site_stats.py` — `path` "/" → `/site_stats`, `order`→2; add
  "Overview records" accordion (linked via `overview_record_link`); DB-wide summary counts +
  filter-aware text; missing-data banner.
- `stage/dashboard/src/pages/magnet_stats.py` — `order`→3; add "Overview records" accordion;
  add "Site history" accordion (`get_site_history_for_magnet`, ordered by
  `sites.commissioned_at`); summary counts + filter-aware text; missing-data banner.
- `stage/dashboard/src/pages/part_stats.py` — `order`→4; add "Overview records" accordion; add
  "Magnet history" accordion (`get_magnet_history_for_part`, ordered by `magnets.created_at`);
  summary counts + filter-aware text; missing-data banner.
- `stage/dashboard/src/pages/home.py` — `order` only (4→6). No other changes; rename deferred
  ("eventually", per user).
- `stage/dashboard/src/pages/stats_research_area.py` — `order` only (7→7, confirmed after the
  others move). No content changes — tabled for later discussion per user.

## Approach

1. `magnets.created_at` schema addition → verify: `ALTER TABLE` runs clean against
   `test-magnetdb.duckdb`.
2. New query functions in `magnetdb_analysis.py` → verify: exercise each against
   `test-magnetdb.duckdb` directly, sane results (in particular `get_overview_record_sources`
   returns non-empty source arrays for at least one known record).
3. `create_annotated_plot` in `magnetdb_plot.py` → verify: unit-level smoke check — feed it one
   normal file + one `spike`-classified file, confirm the figure has one line trace and one
   marker+text trace.
4. Move `comparison.py`/`metrics.py`/`summary.py` to `pages_disabled/` → verify: `dash` dev
   server starts clean, nav bar no longer lists the three pages, no import errors in the
   server log.
5. Build `housing_stats.py` → verify: loads at `/`, both housings show correct
   energy/magnet-time/commissioning data, links into `/site_stats` work.
6. Build `overview_records.py` → verify: pick a record with known `sources_spike`/
   `sources_default` entries, confirm those show as annotated markers (not lines) on the
   relevant group's graph, and a record with empty source arrays shows the missing-data banner
   instead of a blank plot.
7. Retrofit `site_stats.py`/`magnet_stats.py`/`part_stats.py` (accordions, history tables,
   summary counts, filter-aware text, missing-data banners) → verify per page: select an
   entity, confirm the "Overview records" accordion shows records with no matching experiment
   (and vice versa), confirm history tables are ordered ascending, confirm summary text
   switches to "1 selected of N" when a filter is active, confirm accordion links land
   correctly on `/overview-records` with the right record pre-selected.
8. Final renumber/link sweep → verify: nav order is housing_stats, site_stats, magnet_stats,
   part_stats, overview_records, home (File viewer), research-area; grep for any stray
   `href="/"` assuming the old Assembly-stats page.

## Assumptions & open questions

- Deactivated pages move to a new `stage/dashboard/src/pages_disabled/` directory (outside
  Dash's auto-discovered `pages/` folder) — say if you'd rather just comment out their
  `register_page()` calls in place instead of relocating the files.
- `overview_records.py` does **no** cross-file time alignment/lag correction — it just
  overlays whatever's in `sources_overview`/`archive`/`pupitre` on a shared axis, same as
  `home.py` does per group today. If lag-corrected overlay is wanted here too, that's
  `comparison.py`'s job and stays out of scope for this page.
- Field-bin-history granularity: monthly bins within a year, "on" if any
  `duration_field_on_s > 0` that month (from `exp_run_scalars`), rendered as a small CSS strip
  — no new charting dependency. Will look sparse wherever `exp_run_scalars` hasn't been
  backfilled yet; those months get the missing-data treatment rather than a false "off" cell.
- Table styling: keep `dash_table.DataTable` (already used everywhere) rather than adopting
  the `great_tables` package, which isn't a current dependency.
- Missing-data messaging: keep the existing console `print()` (dev-facing, unchanged) *and*
  add a simple on-page `html.Div` banner when a page's query returns empty (user-facing).
- Per-page summary counts show counts relevant to that page's entity + immediate neighbors
  (e.g. `magnet_stats` shows magnet/part/experiment counts, not every table in the DB), not
  literally every count on every page.
- `magnets.created_at` will be NULL for all existing magnets until backfilled separately (out
  of scope here).
