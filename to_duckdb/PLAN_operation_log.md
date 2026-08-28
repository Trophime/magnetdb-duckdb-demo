# Plan: `operation_log` table

## Goal

Every mutating crud.py/populate.py operation writes an audit row into a new
`operation_log` table on both success and failure, queryable via
`magnetdb.py log view`.

## Files affected

- `to_duckdb/schema.py` — edit: add `operation_log` table + sequence
  (pattern at the existing `operationaldata_id_seq`).
- `to_duckdb/crud.py` — edit: add
  `_log_operation(con, operation, table, record_name, status="ok", details=None)`
  next to `_append_status_history`, using `getpass.getuser()` for
  `username`; add `view_operation_log(con, ...)`; wrap each in-scope
  function in try/except (success → `ok`, exception → `error` +
  `{"error": str(exc)}`, re-raise unchanged).
- `to_duckdb/populate.py` — edit: one `_log_operation` call inside
  `find_and_register_pupitre` and `find_and_register_tdms`, at their
  existing `new_count`/`skipped` computation.
- `to_duckdb/magnetdb.py` — edit:
  (a) add `log view [--table T] [--operation OP] [--record NAME]
      [--status ok|error] [--from ...] [--to ...] [--limit N]` subcommand
      + `cmd_log_view`;
  (b) log one row per file in `cmd_populate_overview_records`'s loop,
      around the existing `process_overview_file`/`insert_fn` try/except.
- `to_duckdb/tests/test_crud.py` — edit: tests for `ok`/`error` rows on
  representative CRUD functions and `insert_experiments`' aggregate row.
- `to_duckdb/tests/test_magnetdb.py` — edit: CLI test for `log view`,
  including a populate-driven row.
- `to_duckdb/docs/schema.md` — edit: add `operation_log` to "Table
  overview".

## In-scope CRUD functions (crud.py)

`insert_material`, `delete_material`, `insert_part`, `insert_magnet`,
`delete_magnet`, `insert_assembly`, `delete_assembly`,
`decommission_assembly`, `update_part_status`, `update_magnet_status`,
`update_assembly_magnet`, `insert_assembly_magnets`,
`insert_housing_config_from_magnetrun`, `insert_experiments`.

## Schema

```sql
CREATE SEQUENCE IF NOT EXISTS operation_log_id_seq START 1;

CREATE TABLE IF NOT EXISTS operation_log (
    id          INTEGER PRIMARY KEY DEFAULT nextval('operation_log_id_seq'),
    ts          TIMESTAMP DEFAULT current_timestamp,
    operation   VARCHAR,
    table_name  VARCHAR,
    record_name VARCHAR,
    username    VARCHAR,   -- getpass.getuser()
    status      VARCHAR DEFAULT 'ok',
    details     JSON       -- minimal: old/new status, aggregate counts, or {"error": "..."}
);
```

## Logging granularity

One row per call, at each function's existing unit of work — never per
underlying record:

| Function | Location | Row = |
|---|---|---|
| CRUD verbs (material/part/magnet/assembly add, update-status, delete, decommission, update-magnet, housing) | crud.py | one CLI invocation |
| `insert_experiments` | crud.py | one call (aggregate inserted/skipped) |
| `find_and_register_pupitre`, `find_and_register_tdms` | populate.py | one call per assembly (aggregate inserted/skipped) |
| overview-records populate loop | magnetdb.py `cmd_populate_overview_records` | one file |

## Verification

- `pytest to_duckdb/tests/ -k operation_log` plus full `pytest to_duckdb/tests/`.
- Manual: `material add` → `log view` shows `ok`; invalid
  `magnet update-status` → `log view --status error` shows it; a populate
  run shows aggregate/per-file rows as designed above.

## Resolved decisions

- **Scope**: populate-driven inserts are logged too (not just CLI CRUD verbs).
- **`username` source**: `getpass.getuser()` (OS login), no CLI override.
- **`details` verbosity**: minimal — old/new status, aggregate counts, or
  `{"error": "..."}` on failure — not full JSON payloads.
- **Failed attempts**: logged with `status="error"` and the exception
  message in `details`; the original exception is still re-raised
  unchanged so existing CLI error handling is unaffected.
