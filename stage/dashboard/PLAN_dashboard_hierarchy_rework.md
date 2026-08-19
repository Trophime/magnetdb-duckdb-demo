# Dashboard hierarchy rework

**Status:** Approved and implemented 2026-08-19. All 8 approach steps landed and verified: schema/crud/migrations for `assembled_at`/`manufactured_at` (13/17 magnets, 160/166 parts backfilled in `test-magnetdb.duckdb`), new `magnetdb_analysis.py` query functions, `create_annotated_plot` in `magnetdb_plot.py`, `overview_record_link`, `comparison`/`metrics`/`summary` moved to `pages_disabled/`, `housing_stats.py` and `overview_records.py` built, `assembly_stats.py`/`magnet_stats.py`/`part_stats.py` retrofitted with Overview-records/history accordions + DB-wide counts + filter-aware text + missing-data banners, and the final nav order (`housing_stats` → `assembly_stats` → `magnet_stats` → `part_stats` → `overview_records` → `home` → `research-area`). Verified against `test-magnetdb.duckdb` via live Dash callbacks, not just unit tests. Deactivated pages moved to `pages_disabled/` (not commented out in place); `parts.manufactured_at` stays write-only (no page displays it).

## Goal

Make `housing_stats` the dashboard landing page, retire `comparison`/`metrics`/`summary` from
the nav without deleting their code, and add an overview-record file-viewer page that
auto-loads its `sources_overview`/`sources_archive`/`sources_pupitre` files and overlays
`sources_default`/`sources_spike` as figure annotations (reusing the event-marker logic from
`magnetdb_plot.create_comparison_plot`). Plus assembly/magnet/part accordion links (Overview
records + Experiments), ordered history drill-downs, DB-wide summary counts (filter-aware),
and missing-data messaging across the reworked pages.

## Context / background

Starting point was `to_duckdb/TODOs.md`'s "rework dashboards to start with housing and then go
down to magnet" item. Investigation found 3 of the 4 proposed tiers already existed
(`assembly_stats.py` at `/`, `magnet_stats.py`, `part_stats.py`) — only the top-level `housing`
page was missing. The FK structure in `to_duckdb/schema.py` (`housing_config` → `assemblies` →
`assembly_magnets` ⋈ `magnets` → `magnet_parts` ⋈ `parts`) confirms the hierarchy is a real DAG
with time-varying membership, not a strict tree, which is why "history of X" accordion tables
(not rigid ownership) are the right shape.

Key data-availability findings from the live databases
(`to_duckdb/test-magnetdb.duckdb`, `to_duckdb/magnetdb.duckdb`):
- `assemblies.commissioned_at` is populated — magnet-level "assembly history" can be ordered correctly
  today.
- `assembly_magnets.commissioned_at` is 0% populated in both databases (0/15, 0/89) and
  `magnet_parts` has no date column at all (only `rank`/`coil_index`) — so part-level "magnet
  history" cannot be date-ordered from existing data.
- Resolution (user decision): add `magnets.assembled_at` to `to_duckdb/schema.py` and order the
  part→magnet history table by that. Existing magnets get it backfilled from their `name` via
  the LNCMI naming convention: `M` + `YYMMDD` (assembly date) + 2-digit serial, e.g.
  `M23012001` → 2023-01-20. Confirmed against both `test-magnetdb.duckdb` and `magnetdb.duckdb`:
  every name matching `^M\d{6}\d{2}$` parses to a valid calendar date (13/17 and 4/7 magnets
  respectively; observed years span 2008–2026, so `20YY` is unambiguous — no century pivot
  needed). The non-conforming names (`M9Bitters`, `M10Bitters`, `M9Bitters-newBi08/09` — the
  hand-built Bitter magnets) don't match and stay NULL, same as before, surfaced via the
  existing missing-data messaging. The same convention holds for parts (`H`/`R` + `YYMMDD` + 2
  digits for helices/rings — 160/166 and 87/92 matched with zero bad dates across both DBs;
  `bitter`-type parts are named after their magnet instead, e.g. `M9Bi`).
  - Reversal (user decision): the magnet JSON files used by `magnetdb.py magnet add` (as
    exported from the source MagnetDB API — confirmed via `notebooks/magnet.json`) do carry
    their own `created_at` field (ISO-8601 timestamp), but it is **not** trusted as a source for
    `assembled_at` — it's the record-creation time in the upstream MagnetDB API, not
    necessarily the physical assembly date (this was flagged as an unverified assumption in an
    earlier revision of this plan; resolved now by not relying on it at all). `assembled_at` is
    derived from `name` only, both at insert time and in the backfill migration — there is no
    JSON-field code path.
  - Extension (user decision): add `parts.manufactured_at` following the same treatment as
    `magnets.assembled_at` — derived from `name` via the `H`/`R` + `YYMMDD` + 2-digit
    convention only, same idempotent backfill-migration shape, same "not trusting JSON
    `created_at`" rule applied by the same reasoning (it's the same kind of record-creation
    timestamp from the same source system). `bitter`-type parts (named after their magnet, e.g.
    `M9Bi`) don't match the convention and stay NULL. No page in this plan currently orders or
    displays by `manufactured_at` — it's added for data-model parity/future use.

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
- `to_duckdb/migrations/migrate_magnets_assembled_at_from_name.py` — idempotent backfill,
  follows the existing `to_duckdb/migrations/migrate_*.py` pattern (`--db`, `--dry-run`).
  Imports the shared `assembled_at_from_name()` helper from `crud.py` (see below) rather than
  duplicating the regex in SQL, loops rows where `assembled_at IS NULL`, and issues per-row
  `UPDATE magnets SET assembled_at = ? WHERE name = ?` for names that parse. Leaves
  non-conforming names (e.g. `M9Bitters`) NULL. Prints match/no-match counts and a sample of
  unmatched names for manual review.
- `to_duckdb/migrations/migrate_parts_manufactured_at_from_name.py` — same shape as the
  magnets migration above: imports `manufactured_at_from_name()` from `crud.py`, loops rows
  where `manufactured_at IS NULL`, issues per-row `UPDATE parts SET manufactured_at = ? WHERE
  name = ?` for names that parse. Leaves `bitter`-type / non-conforming names NULL. Expected
  match counts: 160/166 in `test-magnetdb.duckdb`, 87/92 in `magnetdb.duckdb`.
- `stage/dashboard/src/pages/housing_stats.py` — landing page, `path="/"`, `order=1`.
- `stage/dashboard/src/pages/overview_records.py` — new page, `path="/overview-records"`,
  `order=5`. Assembly dropdown → overview_record dropdown (chronological, reuses
  `get_overview_records_for_assembly`) → X-axis + downsampling selectors → per-group accordion
  (mirrors `home.py`'s `html.Details`/checklist/graph pattern, group list via existing
  `db.get_common_groups`). Each group's graph draws `sources_overview`/`sources_archive`/
  `sources_pupitre` files as lines and `sources_default`/`sources_spike` files as event-marker
  annotations. Missing-data banner if the record has no loadable sources.

**Move (deactivate as pages, keep the code)**
- `stage/dashboard/src/pages/comparison.py` → `stage/dashboard/src/pages_disabled/comparison.py`
- `stage/dashboard/src/pages/metrics.py` → `stage/dashboard/src/pages_disabled/metrics.py`
- `stage/dashboard/src/pages/summary.py` → `stage/dashboard/src/pages_disabled/summary.py`

**Edit**
- `to_duckdb/schema.py` — add `magnets.assembled_at TIMESTAMP` and `parts.manufactured_at
  TIMESTAMP` (idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`, both).
- `to_duckdb/crud.py` — add a shared `_date_from_coded_name(name: str, prefix_pattern: str) ->
  str | None` helper next to the existing `parse_timestamp()` (both `re`/`datetime` already
  imported): matches `^{prefix_pattern}(\d{6})\d{2}$` and parses the captured group with
  `datetime.strptime(..., "%y%m%d")`, returning `None` on no-match or invalid date (e.g.
  month 13). Two thin wrappers: `assembled_at_from_name(name) = _date_from_coded_name(name,
  "M")` and `manufactured_at_from_name(name) = _date_from_coded_name(name, "[HR]")` — one
  parsing/validation path for both, since they differ only in the prefix character class. The
  JSON's own `created_at` field is deliberately ignored for both — not passed to either helper,
  not read by `insert_magnet()`/`insert_part()` for this purpose. Update `insert_magnet()`: add
  `assembled_at` to the INSERT column list, value `assembled_at_from_name(name)`. Update
  `insert_part()`: add `manufactured_at` to the INSERT column list, value
  `manufactured_at_from_name(name)`.
- `stage/dashboard/src/magnetdb_analysis.py` — add `get_db_counts`,
  `get_overview_records_for_magnet`, `get_overview_records_for_part`,
  `get_assembly_history_for_magnet`, `get_magnet_history_for_part`, `get_field_bin_history`, and
  `get_overview_record_sources(filename, db_path=None)` (fetches `housing`, `assembly_name`, and
  the five `sources_*` arrays for one record).
- `stage/dashboard/src/magnetdb_plot.py` — add
  `create_annotated_plot(files_data, x_col, method, group_name)`: single-subplot version of
  the event-vs-line logic from `create_comparison_plot`, no lag/sync/two-row layout.
- `stage/dashboard/src/experiment_links.py` — add `overview_record_link(row)` (same shape as
  the existing `experiment_link`), producing links into `/overview-records`.
- `stage/dashboard/src/pages/assembly_stats.py` — `path` "/" → `/assembly_stats`, `order`→2; add
  "Overview records" accordion (linked via `overview_record_link`); DB-wide summary counts +
  filter-aware text; missing-data banner.
- `stage/dashboard/src/pages/magnet_stats.py` — `order`→3; add "Overview records" accordion;
  add "Assembly history" accordion (`get_assembly_history_for_magnet`, ordered by
  `assemblies.commissioned_at`); summary counts + filter-aware text; missing-data banner.
- `stage/dashboard/src/pages/part_stats.py` — `order`→4; add "Overview records" accordion; add
  "Magnet history" accordion (`get_magnet_history_for_part`, ordered by `magnets.assembled_at`);
  summary counts + filter-aware text; missing-data banner.
- `stage/dashboard/src/pages/home.py` — `order` only (4→6) at the time this plan landed; rename
  deferred ("eventually", per user). **Follow-up, 2026-08-19: renamed to
  `file_viewer.py`, route `/home`→`/file_viewer`, deprecated `site=` alias dropped** (nothing
  generated `?site=...` links anymore since the old `site_stats.py` page was deleted in the
  Site→Assembly rename). `experiment_links.py`'s `experiment_link()` and `magnetdb_plot.py`'s
  comment updated to match.
  **Second follow-up, still pending approval:** the rename surfaced that `file_viewer.py` is the
  one page that never gets typed styling (per `PLOT_STYLE.md`) — it passes a composite
  `"<file> - <group>"` string as `create_plot()`'s `filename`, which never matches `.txt`/`.tdms`.
  Fixing that, plus making the dashboard's plot-style config a real bundled+overridable
  `style.json` (rather than in-code-only defaults), is scoped separately in
  `stage/dashboard/PLAN_plot_style_config.md`.
- `stage/dashboard/src/pages/stats_research_area.py` — `order` only (7→7, confirmed after the
  others move). No content changes — tabled for later discussion per user.

## Approach

1. `magnets.assembled_at` + `parts.manufactured_at` schema additions, `_date_from_coded_name()`
   (+ its two wrappers) and the `insert_magnet()`/`insert_part()` updates in `crud.py`, then run
   `migrate_magnets_assembled_at_from_name.py` and `migrate_parts_manufactured_at_from_name.py`
   → verify: both `ALTER TABLE`s run clean against `test-magnetdb.duckdb`; existing `crud.py`
   tests (`test_crud.py::test_insert_magnet*`, `test_insert_part*`) still pass; new tests
   confirm `insert_magnet()`/`insert_part()` set `assembled_at`/`manufactured_at` purely from
   `name`, and that a `created_at` key present in the input dict has no effect on the result;
   both migrations' `--dry-run` show the expected match counts
   (magnets: 13/17 in `test-magnetdb.duckdb`, 4/7 in `magnetdb.duckdb`; parts: 160/166 and
   87/92) and list the unmatched names; real runs set the column for matched rows and leave the
   rest NULL; re-running either is a no-op (`WHERE ... IS NULL` guard).
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
   energy/magnet-time/commissioning data, links into `/assembly_stats` work.
6. Build `overview_records.py` → verify: pick a record with known `sources_spike`/
   `sources_default` entries, confirm those show as annotated markers (not lines) on the
   relevant group's graph, and a record with empty source arrays shows the missing-data banner
   instead of a blank plot.
7. Retrofit `assembly_stats.py`/`magnet_stats.py`/`part_stats.py` (accordions, history tables,
   summary counts, filter-aware text, missing-data banners) → verify per page: select an
   entity, confirm the "Overview records" accordion shows records with no matching experiment
   (and vice versa), confirm history tables are ordered ascending, confirm summary text
   switches to "1 selected of N" when a filter is active, confirm accordion links land
   correctly on `/overview-records` with the right record pre-selected.
8. Final renumber/link sweep → verify: nav order is housing_stats, assembly_stats, magnet_stats,
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
- `magnets.assembled_at` source: derived from `name` only, for magnets matching the
  `MYYMMDDXX` convention; NULL otherwise. The magnet JSON's `created_at` field is explicitly
  **not** used (reversed from an earlier revision of this plan — it's the source MagnetDB
  API's record-creation timestamp, not a reliable stand-in for physical assembly date). This
  applies uniformly to `insert_magnet()` (new/re-added magnets) and the backfill migration
  (existing rows) — one code path, not two. The handful of non-conforming names (Bitter
  magnets) stay NULL and get the missing-data treatment like any other gap.
- `parts.manufactured_at` mirrors `assembled_at` exactly: derived from `name` only (`H`/`R` +
  `YYMMDDXX` convention), JSON `created_at` not used, NULL for `bitter`-type parts and any
  non-conforming helix/ring names. Currently write-only from this plan's perspective — no page
  reads or orders by it yet; say if you'd like e.g. `part_stats.py` to display it.
