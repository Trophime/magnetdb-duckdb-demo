# Plan: wide-format CSV download

Status: proposed (2026-11-03), not yet approved.

## Problem

Clicking a graph's download button exports a "tidy" (long) CSV:
`<x>, file, sensor, value [unit]`. All checked sensors are there, but
stacked vertically in a single `value` column. Each sensor can have tens of
thousands of rows, so a spreadsheet opened at the top shows only the first
one, and the export looks like it holds a single field.

## Goal

Each graph's download button exports the group's checked fields in wide
format, one column per field (`timestamp, file, Q1 [l/s], Q2 [l/s], ...`),
on all five dashboards that have the button. Scope stays one group per
button.

## Files affected

| File | Action |
|---|---|
| `tests/csv_export_test.py` | create (tests written first) |
| `src/magnetdb_plot.py` | edit: add `wide_csv_frame()`, remove `value_column_header()` (it will no longer be used) |
| `tests/unit_conversion_test.py` | edit: remove `test_value_column_header` |
| `src/pages/file_viewer.py` | edit: `download_group_csv` |
| `src/pages/stats_viewer.py` | edit: `download_group_csv` |
| `src/pages/operational_viewer.py` | edit: `download_group_csv` |
| `src/pages/overview_records.py` | edit: `download_group_csv_overview` |
| `src/pages/defaults_spikes.py` | edit: `download_group_csv_defaults_spikes`, and update its docstring's "Returns" to the new columns |

Paths are relative to `apps/dashboards/magnetdb/`.

## Approach

1. Write `tests/csv_export_test.py` for a new helper
   `plot.wide_csv_frame(blocks, x_col, target_unit)`. Each block is
   `(file, x_values, {label: values})`, i.e. one data source (one file's
   DataFrame, or SUPERVISION). The tests check:
   - one block with 3 sensors → columns
     `[x, file, "Q1 [l/s]", "Q2 [l/s]", "Q3 [l/s]"]`, one row per sample;
   - two blocks with different sensors (e.g. a file plus SUPERVISION) →
     union of columns, blank (NaN) cells where a source has no such field,
     rows = sum of both;
   - `target_unit=None` → header is the bare label;
   - repeated x values are kept, not merged.

   → verify: the tests fail (helper doesn't exist yet).
2. Implement `wide_csv_frame` in `src/magnetdb_plot.py` with a NumPy-style
   docstring. It builds one DataFrame per block and concatenates them;
   pandas lines up the columns.
   → verify: the new tests pass.
3. In each of the 5 callbacks, replace the "one tidy frame per sensor" loop
   with one block per data source, then
   `csv_df = plot.wide_csv_frame(blocks, selected_x, target_unit)`. Zoom
   range, unit conversion, SUPERVISION labels (`"<field> [SUPERVISION]"`)
   and filenames stay unchanged.
   → verify: each page module imports cleanly.
4. Remove `value_column_header` and its test.
   → verify: `grep -rn value_column_header` finds nothing.
5. Run the full dashboard test suite:
   `.venv/bin/python -m pytest apps/dashboards/magnetdb/tests`.
   → verify: same pass count as before the change (record it first).
6. Manual check in the browser: on file_viewer, check 3 fields in a group,
   download, and open the CSV.
   → verify: 3 value columns; fewer rows when zoomed.

## Assumptions & open questions

- **A `file` column is kept.** On overview_records and defaults_spikes,
  several files (Overview/Archive tdms, pupitre, incident) can overlap in
  time with different sampling. Rows are keyed by (x, file), not merged onto
  one time axis, so nothing is interpolated or collides. On single-file
  pages, the column tells file rows from SUPERVISION rows. The catch is that
  rows from different files don't line up into one shared row.
- **Units:** each column header shows the graph's y-axis unit, as the single
  `value [unit]` header does today. Fields that can't be converted, and
  SUPERVISION fields, keep their native values, so their header can be
  wrong. That issue already exists and is out of scope here.
- **Scope stays one group per button** (option A). Exporting all selected
  fields across groups, or adding a page-level "download all" button, was
  considered and not chosen.
- `src/pages/operational_viewer.py` is still untracked (work in progress).
