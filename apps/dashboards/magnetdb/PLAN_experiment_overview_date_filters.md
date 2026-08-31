# Plan — date-range filters for Experiments/Overview records tables

Status: implemented and verified (2026-08-31), uncommitted.

## Original ask

Add a date selector within each "Experiments table" and "Overview records"
table across the dashboards, so each table can be filtered down to rows
matching a selected date.

## Decisions made during discussion

- **Date range, not a single day.** Experiment dates come from
  `experiments.name` (e.g. `"2018.02.21 - 10:18:54"`) and overview records'
  `t0` are exact timestamps, so an exact-day match would usually show
  nothing. A `dcc.DatePickerRange` (inclusive start/end) is used instead.
- **Table rows only.** The date filter affects only the rows shown in the
  table it's attached to. It does not touch that page's charts, summary
  counts, or any other section — those keep being driven by the existing
  Magnet/Assembly/Part/Status/Housing/Year filters.
- **One picker per table, not one per page.** Each Experiments table and
  each Overview records section gets its own independent
  `dcc.DatePickerRange`, since the two tables filter on different columns
  (`Experiment` vs `t0`) and can be opened/used independently.

## Scope

Only pages that have both an "Experiments table" and an "Overview records"
accordion section got new pickers:

- `apps/dashboards/magnetdb/src/pages/magnet_stats.py`
- `apps/dashboards/magnetdb/src/pages/assembly_stats.py`
- `apps/dashboards/magnetdb/src/pages/part_stats.py`

Housing stats, the overview-record viewer (`/overview-records`), and
Research areas don't have these table sections and were left untouched.

## Design

Two new helpers in `apps/dashboards/magnetdb/src/dash_selectors.py`:

- `date_range_filter(id, label, style=None)` — builds a labeled, clearable
  `dcc.DatePickerRange` (`YYYY-MM-DD` display format), mirroring the
  existing `aggregate_filter` builder.
- `filter_by_date_range(df, column, start_date, end_date)` — returns `df`
  unchanged if it's empty or both bounds are `None`; otherwise returns the
  rows whose `column` date falls in the closed `[start_date, end_date]`
  range (open-ended if only one bound is set). Rows with a null `column`
  value are excluded once a bound is set.

Per page (`magnet_stats.py` / `assembly_stats.py` / `part_stats.py`), same
pattern in each:

- `layout()`: a `date_range_filter(...)` placed above the Experiments
  `DataTable`, and another above the Overview records `Div`, each with a
  page-prefixed id (e.g. `magnet-stats-table-date-filter`,
  `magnet-stats-overview-date-filter`).
- `_build_page_content(...)`: gained `table_start_date`/`table_end_date`
  parameters. Right before the `Experiment` column is turned into a
  markdown link, the source dataframe is passed through
  `selectors.filter_by_date_range(df, "Experiment", table_start_date, table_end_date)`
  and only the filtered copy feeds the table. Figures and the summary text
  keep using the unfiltered `df`.
- `_overview_records_section(...)`: gained `start_date`/`end_date`
  parameters, applied via `selectors.filter_by_date_range(overview_df, "t0", start_date, end_date)`
  before the empty-check/table build.
- The page's main `update_*_stats` callback: four new `Input`s
  (`start_date`/`end_date` for both pickers) threaded into the two calls
  above.

## Verification performed

- `python -m py_compile` on all four changed files.
- `pytest apps/dashboards/magnetdb/tests` (excluding the pre-existing
  standalone scripts `hoop_test.py`/`lag_test*.py`/`mrun_test.py`, which
  fail on an unrelated hardcoded devcontainer path): 21 passed, unaffected
  by this change.
- Launched the dashboard against `to_duckdb/test-magnetdb.duckdb` and drove
  it directly via `/_dash-update-component` POSTs (no headless browser was
  available in this sandbox):
  - Confirmed both new `DatePickerRange` components render in the layout
    of all three pages.
  - Assembly stats Experiments table: 5419 rows with no filter, narrowed to
    49 rows for `[2018-02-01, 2018-03-01]`, all falling inside that range.
  - Assembly stats Overview records: 1801 rows with no filter, narrowed to
    8 rows for `[2026-01-20, 2026-01-31]`, all falling inside that range.
  - In both cases, the page's figures and summary text were byte-identical
    between the filtered and unfiltered calls — confirming the "table rows
    only" scope holds.
  - Magnet stats Experiments table: spot-checked the same `[2018-02-01,
    2018-03-01]` filter, narrowed to 98 rows.

## Files changed

- `apps/dashboards/magnetdb/src/dash_selectors.py`
- `apps/dashboards/magnetdb/src/pages/magnet_stats.py`
- `apps/dashboards/magnetdb/src/pages/assembly_stats.py`
- `apps/dashboards/magnetdb/src/pages/part_stats.py`
