# Plan: rename `M8_A230919_00` → `M8_A230913_00`

**Status (2026-11-09): drafted, not approved.** To run after the rebuild from
scratch in progress on calcul22. Needs `approve` before any step.

## Why

Since the M8 fix of 2026-11-09 (data issue #14 in
[PLAN_digital_twin_schema.md](PLAN_digital_twin_schema.md)), the assembly
holding M23012001 + M8Bitters + Hybrid is commissioned on **2023-09-13**,
not 2023-09-19, but it still carries the old name. The code never parses an
assembly name for a date, except
[scripts/list_assembly_configs.sh](scripts/list_assembly_configs.sh), which
sorts the assembly files by their `_AYYMMDD_` date to set the load order of
the build. The order is the same with 230913 (after `M8_A211225_00`); the
rename only makes the name match the date.

## Prerequisite

The M8 fix, done 2026-11-09 and **uncommitted** at the time of writing:

| Repo | Files |
|---|---|
| hifimagnet-projects (`magnetgeo-1.0.0`) | `magnetdb.json/M8_A211225_00.json` (+ M8Bitters, ends 2023-09-13 07:00), `M8_A230919_00.json` (starts 2023-09-13 08:00), `M8Bitters.json` (`assembled_at` 2021-12-25) |
| python_magnetrun (`housing-config-versions`) | `python_magnetrun/M8-housing-config.json` (`M8-211225` 12-slot wiring, new `M8-230913`), 4 test files |
| magnetdb-duckdb-demo | 5 `to_duckdb` test files, data issue #14 |

Phase E of
[PLAN_overview_records_from_operationaldata.md](PLAN_overview_records_from_operationaldata.md)
is also uncommitted and shares `to_duckdb/tests/test_magnetdb.py`.

## Goal

The assembly commissioned on 2023-09-13 is named `M8_A230913_00` in the
source JSON, in every DB built from it, and in the code and tests that name
it.

## Files affected

| Repo | File | Action |
|---|---|---|
| hifimagnet-projects | `magnetdb.json/M8_A230919_00.json` → `M8_A230913_00.json` | `git mv` + edit `"name"` |
| magnetdb-duckdb-demo | `to_duckdb/check_experiment_files.py` | edit: usage example in the docstring (line 29) |
| magnetdb-duckdb-demo | `to_duckdb/tests/test_file_context.py` | edit: 2 mentions; fixture start date → `2023-09-13 08:00:00` |
| magnetdb-duckdb-demo | `to_duckdb/tests/test_etl_spec.py` | edit: 12 mentions |
| magnetdb-duckdb-demo | `to_duckdb/tests/test_tags.py` | edit: 5 mentions; stale comments `# M8-211225` (line 148) → `# M8-230913` |
| magnetdb-duckdb-demo | `PLAN_digital_twin_schema.md` | edit: data issue #14 (new name; load order read from the name) |

Left unchanged, as records of past work under the old name:
`PLAN_pupitre_etl_spec.md` (also holds someone else's uncommitted changes),
`PLAN_pupitre_checks_file.md`, `PLAN_import_json_dates.md`,
`to_duckdb/PLAN_hoop_stress_part_names.md`,
`python_magnetsetup/PLAN_supra_umagnet.md`, and the other mentions in
`PLAN_digital_twin_schema.md`.

Checked 2026-11-09: no other repository under `~/github`, no `~/.config`
file and no exported `*.pupitre-etl.json` names the assembly; the M8 rules
of `pupitre_checks.json` are per housing (no assembly); `record_tags` keys
on `overview_records.filename`.

## Approach

0. The calcul22 rebuild has finished; the M8 fix and phase E are committed,
   pushed, and pulled on the machine of the next build.
   → verify: `git status` clean for those files in the three repositories;
   note the DB the rebuild produced and the current `to_duckdb` test count
   (838 passed, 3 skipped on 2026-11-09).
1. `git mv` the JSON file and change `"name"` in it.
   → verify: the file parses (`python3 -m json.tool`);
   `scripts/list_assembly_configs.sh` lists `M8_A211225_00.json` before
   `M8_A230913_00.json`.
2. Reload a scratch DB from the JSON (`magnetdb.py db create`, then
   `assembly add` both M8 files with `--status-file`).
   → verify: assemblies `M8_A211225_00` and `M8_A230913_00`, none named
   `M8_A230919_00`, no overlap error; `build_pupitre_etl_spec` for
   `M8_A230913_00` at 2023-09-14 10:27:45 (Paris) gives `M8-230913`.
3. Replace the name in the code and tests (exact text, no pattern).
   → verify: `grep -rn M8_A230919_00 to_duckdb` prints nothing; the
   `to_duckdb` suite has the step-0 count.
4. Update data issue #14. → verify: re-read the section.
5. The next rebuild (calcul22 or calcul24) loads the renamed file.
   → verify: `SELECT name FROM assemblies WHERE housing = 'M8'` gives
   `M8_A211225_00`, `M8_A230913_00`.

Commits (hifimagnet-projects, then magnetdb-duckdb-demo) on a separate
go-ahead.

## Assumptions and open questions

- DBs built before the rename (`magnetdb-2026-11-05.duckdb`, the calcul22
  rebuild, the DB deployed on calcul18) keep `M8_A230919_00` until they are
  rebuilt; their `operation_log` keeps the old name as history.
- Dashboard users who bookmarked or filtered on the old name will see it
  disappear after the next deployed DB.
