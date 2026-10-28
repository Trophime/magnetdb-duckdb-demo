# Plan: helpers for rows with no date (highlight + `check --entity dates --fix`)

## Goal

Make rows with a missing date easy to spot and, where the date can be
derived, easy to fix:

1. **Dashboard:** in every dated table, empty date cells are highlighted so
   undated rows stand out (they already sort to the bottom per
   `PLAN_dashboard_tables_newest_first.md`).
2. **CLI:** `python magnetdb.py check --entity dates [--name ...] [--fix]`
   reports every row with a missing (or unparseable) date, with a suggested
   value when one can be derived; `--fix` writes the derivable ones, logged
   in `operation_log`.

The dashboard stays read-only (`duckdb.connect(..., read_only=True)`);
fixing happens only through the `to_duckdb` CLI.

## Dates covered

| Table.column | Missing when | Derivable fix (`--fix`) | Otherwise |
|---|---|---|---|
| `magnets.assembled_at` | `NULL` | `crud.assembled_at_from_name(name)` (`MYYMMDDXX`) | report, with hint "first assembly <name> commissioned <date>" (earliest `assemblies.commissioned_at` via `assembly_magnets`; upper bound, never written) |
| `parts.manufactured_at` | `NULL` | `crud.manufactured_at_from_name(name)` (`[HR]YYMMDDXX`) | report, with hint "first assembly <name> commissioned <date>" (via `magnet_parts` → `assembly_magnets`; upper bound, never written) |
| `overview_records.t0` (live rows, `merged_into IS NULL`) | `NULL` | none — a NULL `t0` comes with NULL `assembly_name`/`mode` (inferred from `t0`), so writing `t0` alone would leave the record half-fixed | report, with suggested `t0` from `crud._parse_overview_filename(filename)` and hint "run `magnetdb.py populate overview-records-infer`" (fills `t0`, `assembly_name`, `mode` together) |
| `assemblies.commissioned_at` (non-`in_study`) | `NULL` | none — report only, with hint "earliest experiment: <date>" (an upper bound, not the real date) | report |
| `experiments.name` / `experiments.file` | name not a datetime, or file timestamp unparseable (`parse_magnet_filename` → `None`) | none — renaming an experiment is a key change | report |

`assemblies.decommissioned_at` is **not** checked: `NULL` means "still in
operation", not missing.

## Current state (`to_duckdb/magnetdb-2026-10-08.duckdb`, read-only, 2026-10-23)

| Date | Missing | Fixable by `--fix` | Hint available |
|---|---|---|---|
| `magnets.assembled_at` | 9 / 23 (`Hybrid`, `M5/M8/M9/M10Bitters`, `M9Bitters-newBi08/_01/09/10`) | 0 — names don't follow `MYYMMDDXX` | 9 / 9 |
| `parts.manufactured_at` | 12 / 172 (`HybridSupra`, `M5/M8/M9/M10 Be/Bi`, `M9_newBi08/09/10`) | 0 — names don't follow `[HR]YYMMDDXX` | 12 / 12 |
| `overview_records.t0` (live) | 1 / 1915 (`M10_Overview_220422-0930`; also `assembly_name`/`mode` NULL; `t0` window matches `M10_A220422_00`) | 0 — report + infer hint | 1 / 1 |
| `assemblies.commissioned_at` | 0 / 58 | — | — |
| experiments (name / file timestamp) | 0 / 6483 | — | — |

So today `--fix` writes nothing; it covers future name-coded magnets/parts.
The current gaps are hand fixes guided by the hints (existing
`magnet update` / `part update` JSON commands, and
`populate overview-records-infer` for the overview record).

## Files affected

### Dashboard (`apps/dashboards/magnetdb/`)

1. `src/dash_selectors.py` — edit. New public helper:
   ```python
   def missing_date_style(*columns: str) -> list[dict]:
       """Build ``style_data_conditional`` rules highlighting blank date cells. ..."""
   ```
   One rule per column: `{"if": {"filter_query": "{col} is blank", "column_id": col}, "backgroundColor": "#fff3cd"}`.
   For the `Experiment` markdown column (label is `"NaT"` when the name
   doesn't parse, see `experiment_links.experiment_link`) the rule uses
   `{Experiment} contains "NaT"` instead. Full NumPy docstring.
   Also use it in `magnets_table_section` (`Assembled`).
2. `src/pages/magnet_stats.py` — edit. Add `style_data_conditional=selectors.missing_date_style(...)`
   to: experiments table (`Experiment`), overview records (`t0`), assembly
   history (`commissioned_at`), parts (`Manufactured`).
3. `src/pages/assembly_stats.py` — edit. Experiments table, overview records.
4. `src/pages/part_stats.py` — edit. Experiments, overview records, magnet
   history (`assembled_at`), assembly history (`commissioned_at`), fatigue
   (`Experiment`).
5. `src/pages/housing_stats.py` — edit. Commissioning table (`Commissioned`).
6. `src/pages/stats_research_area.py` — edit. Matching experiments,
   matching overview records.
7. `tests/dash_selectors_test.py` — edit. Test `missing_date_style` output
   (blank rule per column, `NaT` rule for `Experiment`).

### CLI (`to_duckdb/`)

8. `checks.py` — edit.
   - New `check_dates(con, name=None, fix=False) -> list[dict]`, one result
     dict per checked row (`entity` = `"magnet"`, `"part"`,
     `"overview_record"`, `"assembly"`, `"experiment"`), problems like
     `"assembled_at is not set (suggested: 2023-01-20 from name)"`.
   - With `fix=True`, derivable values (magnet `assembled_at`, part
     `manufactured_at` from coded names — nothing else) are written through
     `crud._apply_update` (same path as the `update_*_from_json`
     commands → one appended `operation_log` row, write + log in one
     transaction; these fields are not in `impact.HOOP_STRESS_INPUTS`, so
     no stale marks); the row is then reported OK with a `+ fixed` line,
     like `check_parts`.
   - `parse_filename_timestamp` (python_magnetrun) imported lazily inside
     `check_dates` to keep `checks.py` cheap to import (module docstring
     constraint).
   - Register `"dates"` in `_ENTITY_CHECKS`, but **skip it for
     `entity="all"`** (see open question 2).
9. `magnetdb.py` — edit. Add `"dates"` to `--entity` choices; extend the
   `--fix` help text; update the module usage docstring line.
10. `README.md` — edit. Document `check --entity dates [--fix]` in the
    `check` section.
11. `tests/test_checks.py` — edit. Tests (write first):
    - missing `assembled_at` / `manufactured_at` reported with suggestion;
      `--fix` fills it and writes an `operation_log` row;
    - unmatched name (e.g. `M9Bitters`) reported with the first-assembly
      hint, not fixed;
    - overview record with NULL `t0` reported with suggested `t0` and the
      `overview-records-infer` hint; `--fix` leaves it unchanged and
      writes no `operation_log` row for it;
    - non-`in_study` assembly without `commissioned_at` reported with
      earliest-experiment hint, never fixed; `in_study` exempt;
    - experiment with unparseable name/file reported;
    - `run_checks(con, "all")` does not include date results.

## Approach / verification

All Python commands use the repo's `.venv` (`$PY = <repo>/.venv/bin/python`).

0. Install pytest into `.venv` (`$PY -m pip install pytest`; not present
   today) → verify: `$PY -m pytest --version`.
1. Write the `test_checks.py` tests → verify: they fail
   (`cd to_duckdb && $PY -m pytest tests/test_checks.py`).
2. Implement `check_dates` + registration → verify:
   `$PY -m pytest tests/test_checks.py` passes, and the full
   `$PY -m pytest` in `to_duckdb` still passes.
3. CLI wiring + README → verify on a **scratchpad copy** of
   `magnetdb-2026-10-08.duckdb`:
   `$PY magnetdb.py check --entity dates --db <copy>` lists 9 magnets,
   12 parts, 1 overview record (matching the table above) with their
   hints; `--fix` on the copy reports the same rows and writes nothing
   (`$PY magnetdb.py log view --db <copy>` shows no new row). The fix
   path itself is covered by the unit tests. The real DB is not touched.
4. Write the `missing_date_style` test, then the helper → verify:
   `$PY -m pytest apps/dashboards/magnetdb/tests/dash_selectors_test.py`.
5. Add `style_data_conditional` to each table → verify in the running app:
   blank date cells are highlighted on Magnet / Assembly / Part / Housing /
   Research-area pages; dated cells unchanged.

## Assumptions & open questions

Decided:

1. **Logged fixes:** `--fix` writes through `crud._apply_update`, so every
   fix is recorded in `operation_log` (and visible on the About page).
2. **`check` with no `--entity`:** `dates` is skipped for `entity="all"`;
   existing `check` exit status unchanged.
3. **Hints only:** earliest-experiment (assemblies) and first-assembly
   (magnets/parts) dates are shown as hints, never written.
4. **Highlight color:** light amber `#fff3cd`.
5. **Order:** implement `PLAN_dashboard_tables_newest_first.md` first,
   then `PLAN_operation_log_coverage.md`, then this plan.
6. **Overview records:** option (a) — report + suggest
   `populate overview-records-infer`; `--fix` never touches
   `overview_records`.
7. **`operation_log` safety:** `--fix` only appends rows (never updates or
   deletes existing ones) and never checks or fixes `operation_log` itself.

Remaining assumptions:

8. `crud._apply_update` needs an `impact_key`; a date change has no hoop
   stress impact (`hoop_stress_inputs_changed` returns `[]` before the key
   is used), so the impact report is empty. If that turns out otherwise,
   I'll stop and re-plan.
9. `check --fix` opens the DB read-write; DuckDB refuses that while
   another process (e.g. the dashboard) holds the file — the command
   fails with a lock error, no corruption.
10. Installing pytest into `.venv` (step 0) is a state change included in
   this plan's approval.
