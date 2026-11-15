# Plan: `magnet add` and `assembly add` are all or nothing

Status: **done** (2026-10-29), checked on real data after the rings
`--write` of [`PLAN_insert_rings.md`](PLAN_insert_rings.md).

## Goal

If `magnet add` or `assembly add` fails, nothing from that call stays in the
database: magnets loaded on the way, their parts and links, status changes
made while reclaiming reused parts, the assembly and its experiments. The
failure is still recorded in `operation_log`, and the command prints
`Error: …` and exits 1 instead of a traceback.

## Why

Loading wrote step by step and kept whatever was written before a failure.
The 2026-10-29 rebuild (dead rings `R20061902`–`904` still assigned to
`M25012001`) left `M25012001` in the database with 0 parts and no
`M9_A250121_00` assembly.

`_add_assembly` opened several connections in turn (a read-only conflict
check, one in `_ensure_magnets` and one per magnet in `_add_magnet`, plus its
own), so a single transaction needs a single connection. DuckDB also refuses
to open a file read-only in a process that already has it open for writing.

## Changes

| File | Change |
|---|---|
| `to_duckdb/magnetdb.py` | `_all_or_nothing(con, table, name, write)`: one transaction; on an error roll back, log it in `operation_log` (after the rollback), print `Error: …`, exit 1; a `sys.exit` from a validation step also rolls back. `_add_magnet` and `_ensure_magnets` take an optional open `con` (used for the conflict check and the writes; the caller owns the transaction). `_add_assembly` opens one connection and runs the conflict check, then the missing magnets, assembly, links and records through `_all_or_nothing`. Dry runs are unchanged (read-only, nothing written). |
| `to_duckdb/tests/test_add_magnet.py` | A failing `magnet add` (dead part) writes no magnet, part or link, logs the error and exits 1; a failure also rolls back the reclaim of the old holder (its known death). |
| `to_duckdb/tests/test_add_assembly.py` | A failing second magnet leaves neither the first magnet nor the assembly, with one error row; a failing records insert leaves nothing. |
| `to_duckdb/docs/loading.md` | Documents both behaviours. |

Dropped from the approved plan: making `crud._apply_update` tolerate an open
transaction. Only the `update` commands call it, never a load, so the nested
`BEGIN` cannot happen.

## Verification

1. ~~Baseline~~: 624 passed.
2. ~~Tests first~~: the 4 new tests failed (the partial writes stayed).
3. ~~Implementation~~: 628 passed.
4. ~~Docs~~.
5. ~~After the rings `--write`, rebuild `--to statuses`~~ (2026-10-29,
   `magnetdb-scratch-rings`): all 58 assemblies loaded, no magnet without
   parts.

## Notes

- A rolled-back reclaim also undoes the holder's known death (e.g.
  `M09052601`); the `statuses` step then sets it as a new change rather than
  "already applied", which is correct.
- The `operation_log` rows of steps that succeeded inside a failed call are
  rolled back too; only the final error row stays.
