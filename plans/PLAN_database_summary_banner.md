# Plan: shared database-summary banner for the magnetdb dashboard

## Goal

Add one reusable, DB-wide counts summary (housings, assemblies, magnets,
parts, experiments, overview_records, manips) and:

1. Show it as a **global banner** in the app shell — after the dashboard
   title (`H1`), before any filter or page title — so it appears,
   unfiltered, on every page.
2. Show the **same function/renderer**, scoped to each page's current
   filter selection, **after that page's filters**, replacing the bespoke
   summary blocks on the Manips, Housings, Assemblies, Magnets and Parts
   dashboards.

## Files affected

| File | Change |
|---|---|
| `apps/dashboards/magnetdb/src/magnetdb_analysis.py` | edit — add `get_database_summary(db_path=None, assembly_names=None)` |
| `apps/dashboards/magnetdb/src/dash_selectors.py` | edit — add `database_summary_banner(summary)` |
| `apps/dashboards/magnetdb/src/magnetdb_app.py` | edit — global (unfiltered) banner, after `H1`, before the DB dropdown |
| `apps/dashboards/magnetdb/src/pages/housing_stats.py` | edit — replace `top_summary` with the filtered banner |
| `apps/dashboards/magnetdb/src/pages/assembly_stats.py` | edit — replace `summary` with the filtered banner |
| `apps/dashboards/magnetdb/src/pages/magnet_stats.py` | edit — replace `summary` with the filtered banner |
| `apps/dashboards/magnetdb/src/pages/part_stats.py` | edit — replace `summary` with the filtered banner |
| `apps/dashboards/magnetdb/src/pages/stats_research_area.py` ("Manips") | edit — turn the static `_housing_summary()` into a callback-driven filtered banner |
| `apps/dashboards/magnetdb/tests/summary_stats_test.py` | edit — tests for unfiltered and `assembly_names`-restricted cases |

## `get_database_summary(db_path=None, assembly_names=None)`

Everything is keyed off one restriction parameter: `assembly_names=None`
means DB-wide (unfiltered); otherwise every category is scoped to rows
reachable from that set of `assemblies.name` values.

- **housings** — `{"total", "names"}`.
  - Unfiltered: `get_housings(db_path)` (from `housing_config`, natsorted) — reused as-is.
  - Filtered: `SELECT DISTINCT housing FROM assemblies WHERE name = ANY(?) AND housing IS NOT NULL`, natsorted.
- **assemblies** — `{"total", "by_status"}`.
  - Unfiltered: `get_db_counts()["assemblies"]` / `get_status_counts("assemblies", db_path)` (both reused).
  - Filtered: `total = len(assembly_names)`, `by_status = get_status_counts("assemblies", db_path, names=assembly_names)`.
- **magnets** — `{"total", "by_status"}`.
  - Unfiltered: `get_db_counts()["magnets"]` / `get_status_counts("magnets", db_path)`.
  - Filtered: magnet names via `SELECT DISTINCT magnet_name FROM assembly_magnets WHERE assembly_name = ANY(?)`, then `get_status_counts("magnets", db_path, names=magnet_names)`.
- **parts** — `{"total", "coil_total", "by_status"}`. `total` = all part types; `coil_total`/`by_status` restricted to the module's existing `_COIL_PART_TYPES = ("helix", "bitter", "supra")`.
  - Unfiltered: `total = get_db_counts()["parts"]`; coil names via existing `get_all_parts(db_path, types=_COIL_PART_TYPES)`; `coil_total = len(names)`; `by_status = get_status_counts("parts", db_path, names=names)`.
  - Filtered: `total` = distinct parts reachable from `assembly_magnets → magnet_parts → parts` for `assembly_names`, any type; `coil_total`/`by_status` = same join additionally filtered to `p.type = ANY(_COIL_PART_TYPES)`.
- **experiments** — `{"total", "by_year_housing"}` (`by_year_housing`: pandas `DataFrame`, index=year, columns=housing, values=count).
  - Query: `SELECT a.housing AS housing, e.file AS file FROM experiments AS e JOIN assemblies AS a ON a.name = e.assembly_name` (+ `WHERE a.name = ANY(?)` when `assembly_names` given). Year parsed per-row via the existing `parse_magnet_filename()` (all 5419 test-DB rows parse successfully). Rows with unresolvable housing/year are dropped from the pivot only; `total` stays DB-wide/scope-wide regardless.
- **overview_records** — same shape as experiments.
  - Query: `SELECT housing, EXTRACT(YEAR FROM t0) AS year FROM overview_records WHERE merged_into IS NULL` (+ `AND assembly_name = ANY(?)` when given). Live rows only, matching `get_db_counts()`'s existing convention. Rows with `NULL t0` excluded from the pivot only.
- **manips** — `{"total", "from_date", "to_date"}`. `users` has no direct assembly column; sessions link to data via `users.experiments_ids` (INTEGER[] → `experiments.id`) and `users.overview_records_ids` (VARCHAR[] → `overview_records.filename`) — the same arrays `get_experiments_for_filters`/`get_overview_records_for_filters` already unnest. Many `users` rows have both arrays `NULL` (no linked data).
  - Query 1: `users, UNNEST(experiments_ids) AS t(eid) JOIN experiments AS e ON e.id = t.eid` (+ `AND e.assembly_name = ANY(?)` when given) → `(acronym, file)`; parse date via `parse_magnet_filename()`.
  - Query 2: `users, UNNEST(overview_records_ids) AS t(ovid) JOIN overview_records AS o ON o.filename = t.ovid AND o.merged_into IS NULL` (+ `AND o.assembly_name = ANY(?)` when given) → `(acronym, t0)`.
  - `total` = count of acronyms appearing in either result (i.e. acronyms with at least one in-scope linked experiment/overview_record — acronyms with no link, or whose only links fall outside scope, don't count).
  - `from_date`/`to_date` = min/max across the parsed experiment dates and the overview_records' `t0`, restricted to the same in-scope rows; `None`/`None` if nothing matches.

## `database_summary_banner(summary)` (in `dash_selectors.py`)

Single reusable renderer, used for both the global and every per-page
filtered banner:

- Housings: `"Housings: {total} ({', '.join(names)})"`.
- Assemblies: `"Assemblies: {total}"` + `status_breakdown_text(by_status, db.get_distinct_statuses("assemblies"))` (existing helper, reused).
- Magnets: same pattern via `db.get_distinct_statuses("magnets")`.
- Parts: `"Parts: {total} (helix/bitter/supra: {coil_total})"` + `status_breakdown_text(by_status, db.get_distinct_statuses("parts"))` — label makes the type restriction visible.
- Experiments / Overview records: each as `html.Details([html.Summary(f"...: {total}"), <pivot DataTable>])`, collapsed by default (`open=False`) — matches the `html.Details` convention already used in `part_stats.py`/`file_viewer.py`/etc. Pivot rendered as a `DataTable` (year as first column, one column per housing), or a placeholder message if empty.
- Manips: `"Manips: {total} unique users ({from_date:%Y-%m-%d} → {to_date:%Y-%m-%d})"`, or `"Manips: 0"` when `from_date` is `None`. Placed last.

## App-shell placement (`magnetdb_app.py`)

```python
app.layout = html.Div([
    html.H1("Dashboard MagnetDB - LNCMI monitoring"),   # title — stays first
    html.Div(id="db-summary-banner"),                    # NEW — right after title, before any filter
    html.Div([...db dropdown...]),                       # DB filter — now after the summary
    html.Div([...nav links...]),
    dash.page_container,
])
```

New callback: `Input("dd-database", "value") -> Output("db-summary-banner", "children")`,
returning `[]` when no DB selected, else
`selectors.database_summary_banner(db.get_database_summary(selected_db))`
(unfiltered — `assembly_names` omitted). DOM order is independent of the
Dash callback graph, so the banner can sit above the dropdown that feeds
it, and this also means the summary precedes every per-page title/filter,
since those all render inside `dash.page_container`, which comes after
the banner.

## Per-page filtered banners

Each page computes its own `scope_assembly_names` (`None` when
unfiltered) and calls
`selectors.database_summary_banner(db.get_database_summary(db_path, assembly_names=scope_assembly_names))`
in place of its current summary block, positioned after that page's own
filter controls (same `Output` id each page already uses for its summary
`Div`).

- **housing_stats.py** — `scope_assembly_names = assemblies_in_year` (already `None` when no year picked — no extra logic needed). The per-housing experiment/overview **date-range** lines (`per_housing_lines`) are kept, appended after the new banner — they show start/end dates, not counts, so they're outside this summary's scope.
- **assembly_stats.py** — `scope_assembly_names = in_scope_assemblies` (already the full list when unfiltered — no special-casing needed).
- **magnet_stats.py** — `scope_assembly_names = None if (not selected_status or selected_status == ALL) and not magnet_selected else db.get_assembly_names_for_magnets(in_scope_magnets, db_path)`. The `None` case is required: converting *all* magnets to assembly names would silently drop assemblies with zero magnets, so the unfiltered case must stay `None`, not a computed "all" list — this guarantees the unfiltered filtered-banner numbers for magnets/parts (and everything else) are identical to the global banner's numbers, since it's the same code path. The `"Processed: N"` (STATS DONE) line is page-specific and kept as a trailing line after the new banner.
- **part_stats.py** — same pattern via `db.get_assembly_names_for_parts(in_scope_parts, db_path)`, same `None`-when-unfiltered reasoning (confirmed: `part_selected`/status-narrowed `part_options` mirror `magnet_stats.py` exactly), same treatment of its `"Processed: N"` line.
- **stats_research_area.py** ("Manips") — `_housing_summary()` is deleted; the `html.Div(id="ra-summary")` becomes a real `Output` in the main `update` callback (currently **not wired at all** — the existing summary is static and never reacts to the page's own filters, confirmed by investigation). `scope_assembly_names = None if not filters_active else (set(exp_df["assembly_name"].dropna()) | set(ov_df["assembly_name"].dropna()))`, reusing the `exp_df`/`ov_df` already computed there (via `get_experiments_for_filters`/`get_overview_records_for_filters`) — computed unconditionally when needed, not only inside the current `if filters_active` branch (needs a small restructure of that guard).

## Tests (`summary_stats_test.py`)

Against `test-magnetdb.duckdb`, values already verified read-only during planning:

**Unfiltered:**
- housings: total `2`, names `["M9", "M10"]`
- assemblies: total `49`, by_status `{"in_operation": 2, "disassembled": 47}`
- magnets: total `17`, by_status `{"in_operation": 7, "in_stock": 10}`
- parts: total `166`, coil_total `112`, by_status `{"in_study": 6, "in_operation": 40, "in_stock": 66}`
- experiments: total `5419`, pivot sums to `5419`, e.g. `by_year_housing.loc[2018, "M10"] == 403`
- overview_records: total `1801`, pivot sums to `1764` (37 rows have no `t0`), e.g. `by_year_housing.loc[2022, "M9"] == 220`
- manips: total `363`, `from_date == pd.Timestamp("2018-02-21 10:18:00")`, `to_date == pd.Timestamp("2026-07-21 10:57:00")`

**Filtered** (`assembly_names=["M10_A180220_00"]`, reusing an assembly name already used elsewhere in this test file):
- manips: total `9`, `from_date == pd.Timestamp("2018-02-21 10:18:00")`, `to_date == pd.Timestamp("2018-05-18 16:56:00")`
- plus spot-checks for the other categories restricted to this assembly.

## Verification

1. `pytest apps/dashboards/magnetdb/tests/summary_stats_test.py -k database_summary -v` → passes, unfiltered and filtered cases.
2. Existing tests in that file still pass.
3. Manual: start the dashboard, confirm the global banner appears once (before all filters), and on each of the 5 pages confirm the filtered banner appears after that page's filters and updates when filters change — including Manips, which currently doesn't update on filter change at all today.

## Assumptions & open questions

- Magnets/parts stay excluded from... *(n/a — now included per later turns)*. Magnets are unrestricted-by-type; parts restrict `coil_total`/`by_status` to helix/bitter/supra but `total` counts all part types (in or out of scope).
- "Count per year" uses each record's own timestamp: `overview_records.t0` directly; for `experiments`, the timestamp embedded in `file` via `parse_magnet_filename()` — not e.g. assembly commissioning year.
- `overview_records` counts/breakdown are live rows only (`merged_into IS NULL`), matching existing convention elsewhere in the file.
- housing_stats.py's per-housing date-range lines, and the `"Processed: N"` (STATS DONE) lines on magnet_stats.py/part_stats.py, are page-specific extras outside the 6-category summary and are kept, appended after the new banner rather than folded into it.
- On magnet_stats.py/part_stats.py, "no filter selected" passes `assembly_names=None` rather than a computed "every assembly reachable from every magnet/part" list — confirmed necessary and sufficient to make the unfiltered filtered-banner numbers match the global banner exactly.
- On stats_research_area.py, an assembly counts as "in scope" if it appears via either the filtered experiments or the filtered overview_records (union), since either could independently be empty for a given filter combination.
- "Manips" total counts unique acronyms reachable via an in-scope linked experiment or overview_record — acronyms with no link at all (81 of 444 raw acronyms in the test DB), or whose only links fall outside the current filter scope, are excluded.
