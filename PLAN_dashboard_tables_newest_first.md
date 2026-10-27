# Plan: newest-first dashboard tables + collapsible About operation log

## Goal

Every dashboard `DataTable` whose rows carry a date — a timestamp column
(`t0`, `commissioned_at`, `assembled_at`, …) or a timestamp embedded in a
filename (experiments, via `parse_magnet_filename`) — opens newest row
first. Tables that are currently grouped (experiments by magnet / assembly /
part) keep their grouping and group order; rows are newest first *within*
each group. The About page's operation log moves into a collapsible
`html.Details` section (same pattern as the Magnet dashboard), collapsed by
default, paginated 10 per page so the first page shows the 10 latest
entries.

## Key design choice

Charts must keep their oldest-first order, and several loaders feed both a
chart and a table (e.g. `load_overview_records` → `overview_plot_df`,
`get_hoop_stress_fatigue_for_part` → bar `category_orders`). So:

- **Re-sort at table-build time**, not in shared loaders.
- **Exception:** SQL that only feeds a table (callers verified) gets its
  `ORDER BY` flipped to `DESC NULLS LAST` directly.
- Sorting always happens **before** `i18n.format_date` stringifies dates.

## Files affected

1. `apps/dashboards/magnetdb/src/magnetdb_analysis.py` — edit.
   - `sort_by_file_timestamp(df, group_columns=None, file_column="file", newest_first=False)`:
     new `newest_first` kwarg applied to the parsed-timestamp key only;
     *group_columns* stay ascending
     (`ascending=[True] * len(group_columns) + [not newest_first]`). With
     `newest_first=True`, unparseable filenames (`datetime.min` key)
     naturally sort last within their group. Update NumPy docstring.
   - `get_assembly_history_for_magnet`, `get_magnet_history_for_part`,
     `get_assembly_history_for_part`: `ORDER BY ... DESC NULLS LAST`
     (only callers are the history table sections). Update docstrings.
2. `apps/dashboards/magnetdb/src/pages/about.py` — edit.
   - Wrap the filters row + `about-log-table` in an `html.Details` with
     `html.Summary(f"📜 {i18n._('Operation log')}")` (replacing the `H3`),
     same border/radius style as `magnet_stats.py`, `open=False`.
   - `page_size=20` → `page_size=10`; all rows kept. Order is already
     newest first (`get_operation_log` is `ORDER BY id DESC`), so no
     sorting change needed.
3. `apps/dashboards/magnetdb/src/pages/magnet_stats.py` — edit.
   - `_build_page_content`: re-sort `table_source_df` with
     `db.sort_by_file_timestamp(..., group_columns=["Magnet"], file_column="File", newest_first=True)`
     before building `table_df` (same grouping as `load_data`).
   - `_overview_records_section`: `sort_values("t0", ascending=False, na_position="last")`
     before formatting.
   - `_assembly_history_section` docstring: "ascending" → "most recent first".
4. `apps/dashboards/magnetdb/src/pages/assembly_stats.py` — edit.
   - `_build_page_content`: re-sort `table_source_df` with the loader's
     grouping — `assign(_housing_n=_housing_sort_key(...))`, then
     `sort_by_file_timestamp(group_columns=["_housing_n", "Assembly"], file_column="File", newest_first=True)`,
     then drop `_housing_n`.
   - `_overview_records_section`: `t0` descending, NULLs last.
5. `apps/dashboards/magnetdb/src/pages/part_stats.py` — edit.
   - Experiments table: re-sort with `group_columns=["Part"]`,
     `newest_first=True` (same grouping as `load_data`).
   - Overview records: `t0` descending, NULLs last.
   - Fatigue section (single part, no grouping): table rows via
     `sort_by_file_timestamp(fatigue_df, file_column="File", newest_first=True)`;
     `plot_df` / `experiment_order` unchanged.
   - `_magnet_history_section` / `_assembly_history_section` docstrings:
     "ascending" → "most recent first".
6. `apps/dashboards/magnetdb/src/pages/housing_stats.py` — edit.
   `load_commissioning_history` (table-only): `ORDER BY housing, commissioned_at DESC NULLS LAST`;
   update docstring.
7. `apps/dashboards/magnetdb/src/pages/stats_research_area.py` — edit.
   - `_experiments_section` (ungrouped today): `db.sort_by_file_timestamp(source_df, file_column="File", newest_first=True)`.
   - `_overview_records_section`: `t0` descending, NULLs last.
8. `apps/dashboards/magnetdb/tests/summary_stats_test.py` — edit.
   Add `test_sort_by_file_timestamp_newest_first` (mixed Pupitre/PigBrother,
   one unparseable filename → last) and
   `test_sort_by_file_timestamp_newest_first_keeps_group_order` (groups
   stay ascending, timestamps descending within each group).

### Intentionally unchanged

- Magnet → Parts (`mp.rank` order) and Assembly → Magnets (composition
  order): structural, not chronological.
- Research-area statistics table and hoop-stress summary: aggregates, no
  per-row date.
- file_viewer, stats_viewer, overview_records, defaults_spikes: no
  `DataTable`s; their dropdowns already use `selectors.newest_first`.

## Approach / verification

All Python commands use the repo's `.venv` (`$PY = <repo>/.venv/bin/python`).

0. Install pytest into `.venv` (`$PY -m pip install pytest`; not present
   today) → verify: `$PY -m pytest --version`.
1. Write failing tests for `sort_by_file_timestamp(..., newest_first=True)`,
   then add the kwarg
   → verify: `$PY -m pytest apps/dashboards/magnetdb/tests/summary_stats_test.py` passes
   (existing ascending tests still pass).
2. Flip `ORDER BY` in the three history queries and `load_commissioning_history`
   → verify: tests pass; Magnet/Part history and Housing commissioning
   tables open newest first, undated rows at the bottom.
3. Table-time sorting for experiments, fatigue and overview-records tables
   → verify: each table on Magnet / Assembly / Part / Research-area pages
   opens newest first (grouped experiments tables: same group order as
   before, newest first inside each group); chart x-axis order unchanged.
4. About page `html.Details` + `page_size=10`
   → verify: section collapsed on load; when opened, page 1 shows the 10
   latest entries and older entries are reachable via pagination; filters
   still work.
5. Final: `$PY -m pytest apps/dashboards/magnetdb/tests/summary_stats_test.py apps/dashboards/magnetdb/tests/dash_selectors_test.py`
   plus a manual click-through of each page.

## Assumptions & open questions

Decided:

1. **Experiments tables grouping:** keep current grouping and group order;
   newest first within each group.
2. **About log:** keep all entries, `page_size=10` (first page = 10 latest).
3. **About section default state:** collapsed (`open=False`).

Remaining assumptions:

4. **Undated rows** (no `t0`, not yet commissioned, unparseable filename):
   placed at the bottom.
5. **Header clicks** still sort client-side on the displayed (formatted)
   strings, as today; this plan only sets the initial order.
6. The working tree already has uncommitted changes in most of these files;
   edits layer on top, nothing is staged or committed.
