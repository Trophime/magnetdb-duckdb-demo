# Plan: every state-changing `magnetdb.py` subcommand writes to `operation_log`

## Goal

Every `magnetdb.py` subcommand that changes the database appends at least
one `operation_log` row (status `ok`, or `error` with
`details={"error": ...}`) describing what it changed, so the About-page
log is a complete audit trail. Read-only subcommands keep writing nothing.
`operation_log` stays append-only: no code updates or deletes its rows.

## Audit (2026-10-23, `to_duckdb/magnetdb.py` `_DISPATCH`)

### Already logged — no change

| Subcommand | Logged by |
|---|---|
| `material add / update / delete` | `insert_material`, `update_material_from_json` (`_apply_update`), `delete_material` |
| `part update / update-status` | `update_part_from_json`, `update_part_status` |
| `magnet update / delete / update-status / update-status-from-file` | `update_magnet_from_json`, `delete_magnet`, `update_magnet_status` |
| `assembly add / update / delete / update-magnet / decommission` (+ `site` aliases) | `insert_assembly`, `insert_assembly_magnets`, `insert_experiments`, `update_assembly_from_json`, `delete_assembly`, `update_assembly_magnet`, `decommission_assembly` |
| `populate operationaldata` | `populate.find_and_register_pupitre` / `_tdms` (one row per assembly, with counts) |
| `populate experiments` | `insert_experiments` |
| `populate overview-records` | handler, one `ok`/`error` row per file |

### Read-only — no log by design

`list`, `check` (without `--fix`), `log view`, every `* view`,
`magnet check-geometry`, `hoop-stress barchart / history / stats / fatigue`
(DB opened `read_only=True`; they write plots/files only),
`hoop-stress part-history` (read-only).

### Not applicable

`db delete` — removes the DB file itself, so there is no `operation_log`
left to write to. Unchanged.

### Gaps — to fix

| # | Subcommand | What it writes today, unlogged |
|---|---|---|
| G1 | `check --fix` | `checks.check_parts` / `check_magnets`: raw `UPDATE ... SET geometry_data` |
| G2 | `magnet add` | `insert_material` / `insert_part` / `insert_magnet` are logged, but `insert_magnet_parts` (the `magnet_parts` links) is not |
| G3 | `db create` | creates the schema; nothing logged |
| G4 | `db drop-table` | raw `DROP TABLE`; nothing logged |
| G5 | `populate overview-records-from-archive` | inserts/upserts `overview_records`; nothing logged |
| G6 | `populate overview-records-from-json` | `insert_overview_record_from_dict`; nothing logged |
| G7 | `populate overview-records-infer` | `infer_overview_record_fields` (`UPDATE` `t0`/`assembly_name`/`housing`/`duration`/…, `mode`) and `merge_duplicate_pupitre_records` (`UPDATE ... merged_into`); nothing logged |
| G8 | `hoop-stress compute` | `compute_hoop_stats.compute_hoop_stress_history`: `hoop_stress_processed`, `hoop_stress_bin_stats`, `hoop_stress_fatigue(_bins)`, `experiments.status`; nothing logged |

## Files affected

1. `to_duckdb/checks.py` — edit (G1). Write the `geometry_data` fixes
   through `crud._apply_update` (`fields={"geometry_data": loaded}`), which
   logs `{"changes": {"geometry_data": "changed"}}` in the same transaction
   as the write. `geometry_data` *is* a hoop-stress input, so any existing
   results get marked stale (correct: their geometry input changed).
2. `to_duckdb/crud.py` — edit.
   - G2: `insert_magnet_parts` logs one `insert` / `magnet_parts` row
     (record = magnet name, `details={"parts": [...]}`), `error` row on
     failure — same shape as `insert_assembly_magnets`.
   - G7: `infer_overview_record_fields` logs one `infer` /
     `overview_records` row per call with `details={"result": <resolved |
     bad_filename | no_assembly_match | not_found>, "changes": {...}}`;
     `merge_duplicate_pupitre_records` logs one `merge` /
     `overview_records` row per merge (record = kept filename,
     `details={"merged": [...]}`).
   - Docstrings updated (NumPy style) to mention the log row.
3. `to_duckdb/magnetdb.py` — edit.
   - G3: `cmd_db_create` logs one `create` / `database` row after
     `ensure_schema`, only when the file was newly created.
   - G4: `cmd_db_drop_table` logs one `drop_table` row per table
     (`details={"rows": count}`) in the same transaction as the `DROP`.
     Dropping `operation_log` itself cannot be logged into itself: print a
     warning and log nothing for that table (see open question 2).
   - G5 / G6: `cmd_populate_overview_records_from_archive` and
     `cmd_populate_overview_records_from_json` log one `populate` /
     `overview_records` row per file/record, `ok` or `error` — same
     pattern as `cmd_populate_overview_records` (lines ~1385–1398).
4. `to_duckdb/compute_hoop_stats.py` — edit (G8). `compute_hoop_stress_history`
   logs one `compute` / `hoop_stress_processed` row per assembly run
   (record = assembly, `details={"bin_config", "processed", "skipped",
   "errors"}`), `error` row on failure. Logging inside the function covers
   both `magnetdb.py hoop-stress compute` and the standalone
   `compute_hoop_stats.py` CLI.
5. `to_duckdb/tests/test_magnetdb.py`, `tests/test_crud.py`,
   `tests/test_checks.py`, `tests/test_compute_hoop_stats.py` — edit.
   One test per gap, written first, following
   `test_cli_populate_overview_records_logs_operation_log_row`: run the
   subcommand/function, assert the expected `(operation, table_name,
   record_name, status)` row(s) appear.
6. `to_duckdb/tests/test_magnetdb.py` — edit. A **coverage guard** test:
   every key of `magnetdb._DISPATCH` must be listed in either a
   `_LOGGED_SUBCOMMANDS` or `_READ_ONLY_SUBCOMMANDS` set in the test
   (plus `("db", "delete")` as N/A), so a new subcommand added without a
   logging decision fails CI.
7. `to_duckdb/PLAN_operation_log.md` — not edited; `to_duckdb/README.md` —
   edit: one line in the `log view` section stating which subcommands log.

## Approach / verification

All Python commands use `$PY = <repo>/.venv/bin/python` (pytest installed
per the earlier plans' step 0).

1. Baseline: `cd to_duckdb && $PY -m pytest` → verify: record pass/fail
   count before any change.
2. Write the 8 gap tests + coverage guard → verify: the 8 gap tests fail,
   guard passes once the sets are filled from the audit.
3. G1 (`checks.py`) → verify: its test passes; existing `test_checks.py`
   `--fix` tests still pass.
4. G2, G7 (`crud.py`) → verify: their tests pass.
5. G3–G6 (`magnetdb.py`) → verify: their tests pass.
6. G8 (`compute_hoop_stats.py`) → verify: its test passes (computation
   mocked as in existing `test_compute_hoop_stats.py`).
7. Full suite → verify: `$PY -m pytest` matches the baseline plus the new
   tests.
8. Manual, on a scratchpad **copy** of `magnetdb-2026-10-08.duckdb`:
   `populate overview-records-infer` (fixes `M10_Overview_220422-0930`),
   then `log view --table overview_records` shows the `infer` row → the
   real DB is not touched.

## Assumptions & open questions

1. **Scope = state-changing subcommands.** Read-only subcommands
   (`view`, `list`, plot/stats commands) are not logged, to keep the log an
   audit of changes. OK, or do you also want reads logged?
2. **`db drop-table operation_log`.** Can't log into the table being
   dropped. Default: warn and proceed (it already asks for confirmation).
   Alternative: refuse to drop `operation_log` unless `--force`.
3. **G1 stale marks.** Routing `check --fix` geometry fixes through
   `_apply_update` may mark hoop-stress results stale. Default: accept
   (it's the correct semantics). Alternative: log only, no stale marks.
4. **G7 granularity.** One row per inferred record and per merge (could be
   many on `--reprocess`). Alternative: one summary row per run with
   counts, like `populate operationaldata`.
5. **G8 granularity.** One row per assembly run, not per experiment.
6. **Standalone scripts** outside `magnetdb.py` (`compute_exp_stats.py`,
   `compute_op_stats.py`, `migrations/*.py`, `populate.py` `main`) are out
   of scope except where they share a function changed above (G8).
7. The working tree has uncommitted dashboard changes; this plan only
   touches `to_duckdb/`. Nothing is staged or committed.
