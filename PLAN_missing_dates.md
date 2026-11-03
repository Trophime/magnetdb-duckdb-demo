# Plan: helpers for rows with no date (highlight + report-only `check --entity dates`)

Status: **done** (2026-11-02, scope option 2: no `--fix`); the dashboard
look (step 6) was confirmed by the user on 2026-11-03. Results under
[Verification results](#verification-results-2026-11-02). The first
version (2026-10-23) is summarised under
[What changed](#what-changed-since-2026-10-23).

## Goal

Make rows with a missing date easy to spot:

1. **Dashboard:** in every dated table, empty date cells are highlighted in
   light amber (`#fff3cd`), so undated rows stand out (they already sort to
   the bottom per `PLAN_dashboard_tables_newest_first.md`). The colour is
   distinct from the geometry-problem red (`#f8d7da`).
2. **CLI:** `python magnetdb.py check --entity dates [--name ...]` reports
   every row with a missing (or unparseable) date, with a hint on how to fix
   it. It only reads; it writes nothing.

The dashboard stays read-only (`duckdb.connect(..., read_only=True)`).

## What changed since 2026-10-23

- Since the import-dates work, `insert_magnet` / `insert_part` refuse a
  magnet or part with neither a JSON date nor a date coded in its name
  (`resolve_assembled_at` / `resolve_manufactured_at`). A NULL
  `assembled_at` / `manufactured_at` can no longer enter a new database,
  so the planned `--fix` (date from a coded name) would never write
  anything. **Dropped.** The magnet and part checks stay, report-only, as a
  safety net for older databases.
- Prerequisites done: `PLAN_dashboard_tables_newest_first.md`,
  `PLAN_operation_log_coverage.md`.
- With no writes, the `operation_log`, `_apply_update`, `impact_key` and
  read-write lock points of the first version no longer apply.
- Experiment names carry no extension, so the timestamp is parsed from
  `experiments.file`, not `name`.
- Step 0 (install pytest) is already done.

## Dates covered

| Table.column | Missing when | Hint printed |
|---|---|---|
| `magnets.assembled_at` | `NULL` | "first assembly `<name>` commissioned `<date>`" (earliest `assemblies.commissioned_at` via `assembly_magnets`; an upper bound) + "set it with `magnet update`" |
| `parts.manufactured_at` | `NULL` | "first assembly `<name>` commissioned `<date>`" (via `magnet_parts` → `assembly_magnets`; an upper bound) + "set it with `part update`" |
| `overview_records.t0` (live rows, `merged_into IS NULL`) | `NULL` | suggested `t0` from `crud._parse_overview_filename(filename)` + "run `magnetdb.py populate overview-records-infer`" (fills `t0`, `assembly_name`, `mode` together) |
| `assemblies.commissioned_at` (not `in_study`) | `NULL` | "earliest experiment: `<date>`" (an upper bound) + "set it with `assembly update`" |
| `experiments.file` timestamp | file set, but `parse_filename_timestamp(file)` → `None` | none (renaming an experiment is a key change) |

Not checked:
- `assemblies.decommissioned_at`: `NULL` means "still in operation".
- `in_study` assemblies without `commissioned_at`: normal.
- Experiments with no `file`: `check --entity experiment` already reports them.

## Current state (`to_duckdb/magnetdb-2026-10-29.duckdb`, read-only, 2026-11-02)

| Date | Missing |
|---|---|
| `magnets.assembled_at` | 0 / 23 |
| `parts.manufactured_at` | 0 / 201 |
| `overview_records.t0` (live) | 1 (`M10_Overview_220422-0930`; also `assembly_name` / `mode` NULL) |
| `assemblies.commissioned_at` (not `in_study`) | 0 / 58 |
| experiment file timestamps | 0 / 6532 unparseable |

Repairing `M10_Overview_220422-0930` (`populate overview-records-infer`)
reads its pupitre file through the rclone mount. It is **not part of this
plan**; run it once rclone is back. This plan needs no rclone access.

## Files affected

### CLI (`to_duckdb/`)

1. `checks.py` — edit.
   - New `check_dates(con, name=None) -> list[dict]`: one `PROBLEM` result
     per undated row (`entity` = `"magnet"`, `"part"`, `"overview_record"`,
     `"assembly"`, `"experiment"`, problem like
     `"assembled_at is not set (first assembly M9_A2019 commissioned 2019-06-20; set it with 'magnet update')"`),
     plus one `OK` summary row per date column
     (e.g. `name = "assembled_at: 23 rows dated"`) so a clean DB does not
     print ~6,800 OK lines. `--name` filters on the row name.
   - `parse_filename_timestamp` (python_magnetrun) imported lazily inside
     `check_dates`, to keep `checks.py` cheap to import (module docstring).
   - Register `"dates"` in `_ENTITY_CHECKS` (the lambda ignores `fix`), and
     **skip it for `entity="all"`**, so the plain `check` output and exit
     status are unchanged.
   - Full NumPy docstring; `run_checks` docstring updated.
2. `magnetdb.py` — edit. Add `"dates"` to the `--entity` choices; `--fix`
   help: "no effect on `dates`"; update the module usage docstring line.
3. `README.md` — edit. Document `check --entity dates` in the `check`
   section.
4. `tests/test_checks.py` — edit. Tests (written first):
   - NULL `assembled_at` / `manufactured_at` reported with the
     first-assembly hint;
   - overview record with NULL `t0` reported with the suggested `t0` and
     the `overview-records-infer` hint; merged rows ignored;
   - non-`in_study` assembly without `commissioned_at` reported with the
     earliest-experiment hint; `in_study` exempt;
   - experiment with an unparseable file timestamp reported; NULL file
     not reported here;
   - a fully dated DB gives only `OK` summary rows;
   - `check_dates` with `fix=True` (through `run_checks`) writes nothing:
     table contents and `operation_log` row count unchanged;
   - `run_checks(con, "all")` contains no date results.

### Dashboard (`apps/dashboards/magnetdb/`)

5. `src/dash_selectors.py` — edit.
   - `MISSING_DATE_COLOR = "#fff3cd"`.
   - New public helper:
     ```python
     def missing_date_style(*columns: str, exempt_in_study: bool = False) -> list[dict]:
         """Build ``style_data_conditional`` rules highlighting blank date cells. ..."""
     ```
     One rule per column:
     `{"if": {"filter_query": "{col} is blank", "column_id": col}, "backgroundColor": MISSING_DATE_COLOR}`.
     Date cells are rendered by `i18n.format_date`, which returns `""` for
     `None`/`NaT`, so `is blank` matches them. For the `Experiment`
     markdown column (label `"NaT"` when the name doesn't parse, see
     `experiment_links.experiment_link`) the rule is
     `{Experiment} contains "NaT"`. With `exempt_in_study=True` the rule
     adds `&& {status} != "in_study"` (column named `status` or `Status`,
     given by the caller), for commissioning columns. Full NumPy docstring.
   - `magnets_table_section`: append `missing_date_style("Assembled")` to
     its existing `style_data_conditional` (geometry rule kept).
6. `src/pages/magnet_stats.py` — edit. Add `style_data_conditional` to:
   experiments (`Experiment`), overview records (`t0`), assembly history
   (`commissioned_at`, exempt `in_study`), parts (`Manufactured`).
7. `src/pages/assembly_stats.py` — edit. Experiments (`Experiment`),
   overview records (`t0`).
8. `src/pages/part_stats.py` — edit. Experiments (`Experiment`), overview
   records (`t0`), magnet history (`assembled_at`), assembly history
   (`commissioned_at`, exempt `in_study`), fatigue (`Experiment`).
9. `src/pages/housing_stats.py` — edit. Commissioning table
   (`Commissioned`, exempt `in_study` via `Status`).
10. `src/pages/stats_research_area.py` — edit. Matching experiments
    (`Experiment`), matching overview records (`t0`).
11. `tests/dash_selectors_test.py` — edit. Tests for `missing_date_style`:
    blank rule per column, `NaT` rule for `Experiment`, `in_study`
    exemption; and that `magnets_table_section` keeps the geometry rule.

Where a table already sets `style_data_conditional`, the date rules are
appended to it, never replace it.

## Approach / verification

`$PY = <repo>/.venv/bin/python`.

1. Baseline → verify: `cd to_duckdb && $PY -m pytest` (653 expected) and
   `$PY -m pytest apps/dashboards/magnetdb/tests/dash_selectors_test.py`;
   record the counts.
2. Write the `test_checks.py` tests → verify: they fail.
3. Implement `check_dates` + registration → verify:
   `tests/test_checks.py` passes; the full `to_duckdb` suite = baseline +
   new tests.
4. CLI wiring + README → verify on a **scratchpad copy** of
   `magnetdb-2026-10-29.duckdb`:
   - `$PY magnetdb.py check --entity dates --db <copy>` → 1 problem
     (`M10_Overview_220422-0930`, suggested `t0` 2022-04-22 09:30 + infer
     hint), the rest `OK` summary rows, exit status 1;
   - `--fix` on the copy → same output, `log view --db <copy>` shows no
     new row;
   - plain `check --entity magnet --db <copy>` output unchanged.
   The real DB is not touched. No experiment/operationaldata file check is
   run (those read the rclone mount).
5. Write the `missing_date_style` tests, then the helper → verify:
   `dash_selectors_test.py` passes.
6. Add the rules to each table → verify: dashboard suite = baseline + new
   tests; then in the running app on a scratchpad copy where I blank one
   date per table type (`assembled_at`, `manufactured_at`, `t0`,
   `commissioned_at` on a non-`in_study` assembly) — you check that those
   cells are amber, dated cells unchanged, `in_study` blanks not
   coloured, the geometry red still shows.

### Verification results (2026-11-02)

1. Baseline: `to_duckdb` 653 passed; `dash_selectors_test.py` 7 passed
   (dashboard suite without `mrun_test.py`: 151).
2. 10 new `test_checks.py` tests failed (no `check_dates`).
3. `to_duckdb` suite: **663 passed**.
4. Scratchpad copy: `check --entity dates` → 1 problem
   (`M10_Overview_220422-0930`, suggested `t0` 2022-04-22 09:30 + infer
   hint), 5 `OK` summaries (23 magnets, 201 parts, 1832 overview records,
   58 assemblies, 6532 experiment files), exit 1; with `--fix`: same, exit
   1, `operation_log` still 1352 rows; `check --entity magnet`: 23 OK.
5. 5 new selector tests failed, then passed (12).
6. Dashboard suite: **156 passed**. Visual check copy: `M20092801`
   `assembled_at`, `H09031204` `manufactured_at`, `M10_A260626_00`
   `commissioned_at` blanked; `M10_A251112_00` set `in_study` with no
   `commissioned_at` (must stay uncoloured). The `Experiment` `NaT` rule is
   covered by tests only: an unparseable experiment name breaks the page's
   `pd.to_datetime`, so no such row can be shown.

Deviation: `missing_date_style` takes `status_column=` (the status column
name) instead of `exempt_in_study=True` plus a separate column name.

## Assumptions & open questions

Decided:

1. **Scope:** option 2 (2026-11-02): highlight + report-only check; no
   `--fix` for dates.
2. **`check` with no `--entity`:** `dates` is skipped for `entity="all"`.
3. **Hints only:** first-assembly and earliest-experiment dates are shown
   as hints, never written.
4. **Highlight colour:** light amber `#fff3cd`.
5. **Overview records:** report + suggest `populate overview-records-infer`.

Remaining assumptions:

6. **Output size:** problems are listed one per row, but clean date
   columns give one `OK` summary row each instead of one per row. Say if
   you prefer one `OK` line per row like the other checks.
7. **`check --entity dates --fix`:** accepted and ignored (nothing to
   fix), rather than an error.
8. **Exit status:** `check --entity dates` exits 1 while any date is
   missing — today 1, until `M10_Overview_220422-0930` is re-inferred.
9. **Visual check data:** the scratchpad copy used in step 6 has a few
   dates blanked by hand (an `UPDATE` on the copy only), since the real DB
   has just one undated row.
10. The `PLAN_magnet_geometry_check.md` status line still says
    "implemented"; it will be set to "done" (visual check confirmed) as part
    of this plan, with no other change to that file.
