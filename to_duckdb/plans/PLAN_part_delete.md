# Plan — `part delete` command

Status: **proposed** (2026-08-28) — not yet approved/implemented. Split out
from [`PLAN_incident_tracking.md`](PLAN_incident_tracking.md), where it came
up as a side note (parts currently have no delete command, unlike
`material`/`magnet`/`assembly`).

## Goal

Add a `part delete <name>` command that removes a part only if it has never
been meaningfully associated with a magnet: not currently linked
(`magnet_parts`) and no magnet-cascade entry in its `status_history`.

## Survey — existing delete commands

Checked before designing `part delete`, so it follows the right existing
pattern rather than inventing a third one:

| Entity | `delete` command | Pattern |
|---|---|---|
| `material` | Yes | **Blocks** if referenced by a `parts.material_name` — prints error, refuses. |
| `magnet` | Yes | **Cascades** — deletes its `magnet_parts` rows, then the magnet. No reference-blocking. |
| `assembly` | Yes | **Cascades** — deletes its `experiments` and `assembly_magnets` rows, then the assembly. No reference-blocking. |
| `experiment` | No | `experiments` only has a `view` subcommand, no delete at all. |
| `overview_records` | No | `overview-records` only has a `view` subcommand, no delete at all. |
| `part` | No (this plan) | — |

`experiment`/`overview_records` having no delete path at all is a side
observation, not something this plan addresses (see assumption 3 below).

## Domain rules (confirmed in conversation)

- Existing `delete_*` commands split into two patterns (see survey above):
  **blocking** (`delete_material`) vs. **cascading** (`delete_magnet`,
  `delete_assembly`).
- `part delete` follows the **blocking** pattern (a part is referenced by
  other things, like a material, rather than owning children), with two
  guards, both required to pass:
  1. **Not currently linked**: no row in `magnet_parts` for this part.
  2. **Empty magnet history**: no `status_history` entry whose
     `description` starts with `"Cascaded from magnet"` — the exact prefix
     `_cascade_parts_status` always writes on any magnet-driven part status
     change (commissioning up, retirement/dead down). This is deliberately
     narrower than "status_history is entirely empty": a part with
     unrelated manual status history but no magnet involvement is still
     deletable. Since `magnet_parts` has no historical rows (a magnet
     deletion wipes its `magnet_parts` rows outright), this cascade-entry
     check is the only remaining trace of a past magnet link once the
     magnet itself is gone.

## Files affected

- `to_duckdb/crud.py` — edit: new `delete_part(con, name)` near
  `delete_material`, with the two guards above before deleting.
- `to_duckdb/magnetdb.py` — edit: new `part delete` subcommand +
  `cmd_part_delete`, mirroring `material delete`; update `part_sub`'s
  `metavar` to include `delete`.
- `to_duckdb/tests/test_crud.py` — edit: tests for `delete_part`.
- `to_duckdb/tests/test_magnetdb.py` — edit: CLI coverage for `part delete`.

## Approach

1. `delete_part(con, name)` in `crud.py`:
   - Not found → print `"Part '{name}' not found."` + return.
   - `magnet_parts` reference exists → print `"Error: part '{name}' is
     linked to magnet '{magnet}'. Remove the link first."` + return.
   - Any `status_history` entry's `description` starts with `"Cascaded from
     magnet"` → print `"Error: part '{name}' has magnet history and cannot
     be deleted."` + return.
   - Else `DELETE FROM parts WHERE name = ?` + confirmation print.
2. `part delete` subparser + `cmd_part_delete` in `magnetdb.py`.
3. Tests per above.

## Verification

- `test_crud.py`:
  - Deleting a pristine part, or one with unrelated manual status history
    but no magnet involvement, succeeds.
  - Deleting a part currently in `magnet_parts` is refused, row stays.
  - Deleting a part whose magnet was since deleted (so `magnet_parts` is
    now empty) but whose `status_history` still carries a `"Cascaded from
    magnet"` entry is refused, row stays.
- `test_magnetdb.py`: CLI round-trip for all three cases above.
- Full suite: `to_duckdb/venv-systempackages/bin/python3 -m pytest
  to_duckdb/tests/` green.

## Assumptions & open questions

1. The `"Cascaded from magnet"` string match is exact-prefix and
   case-sensitive, matching `_cascade_parts_status`'s literal generated
   text — if that text is ever reworded, this check silently stops catching
   old entries (pre-existing entries in the DB keep whatever wording was
   current when they were written).
2. No `incident_parts` guard yet, since that table doesn't exist until
   [`PLAN_incident_tracking.md`](PLAN_incident_tracking.md) lands — revisit
   `delete_part` then to add the same treatment.
3. No delete commands added for `experiment`/`overview_records` — out of
   scope here; flagged only as a side observation during this discussion.
