# Plan — incident tracking for assemblies, magnets, and parts

Status: **proposed** (2026-08-28) — not yet approved/implemented. Drafted in
conversation following a question about modeling why an assembly was
disassembled (normal vs. incident-driven).

## Goal

Add a standalone `incidents` entity that records why something happened
(free-text narrative + attachments, mirroring `status_history`'s shape) and
links it, optionally, to the one assembly it disassembled, the magnet(s)
involved, and the part(s) involved — queryable independently of the existing
lifecycle/cascade machinery ([`PLAN_lifecycle_status.md`](PLAN_lifecycle_status.md)),
which stays untouched. Also let an optional `incident_id` be stamped onto the
`status_history` entries that record/cascade from the actual status changes,
so either side (the relational `incidents` links, or a raw `status_history`
entry) can point back to the other.

## Domain rules — cardinality (confirmed in conversation)

- **Incident ↔ assembly: 1:1.** A disassembly happens once per assembly row
  (no re-opening in the current lifecycle model), so this needs no junction
  table — just a nullable, `UNIQUE` `assembly_name` column on `incidents`.
- **Incident ↔ magnet: M:N.** A single incident can involve more than one
  magnet (e.g. a fault affecting two magnets in the same assembly), and a
  magnet can accumulate several incidents over its life, not all necessarily
  related to a specific part. Needs a real `incident_magnets` junction table.
- **Incident ↔ part: M:N, optional.** An incident isn't necessarily tied to
  any part at all; when it is, it can involve more than one. Needs a real
  `incident_parts` junction table.
- **`incidents` is standalone**, not wired into `decommission_assembly()` /
  `update_magnet_status()`: those functions and their cascade logic are
  unchanged. An incident is recorded as an explicit, separate step, linking
  whichever assembly/magnets/parts apply — chosen over auto-creating/linking
  incidents from within the existing lifecycle calls, to keep this addition
  low-risk and decoupled.
- **`status_history.incident_id` is a separate, complementary mechanism**:
  an optional cross-reference stamped onto individual `status_history`
  entries by the caller (via `--incident-id` on `part update-status` /
  `magnet update-status` / `assembly decommission`), *after* the incident
  already exists. `status_history` remains the full audit trail of every
  status transition (including routine, non-incident ones); `incidents`
  covers only the subset worth a cross-entity narrative. No retroactive
  backfill: `incident_id` must be passed at the time of the status-changing
  call.
- **Propagation**: when `--incident-id` is passed to `assembly decommission`
  or `magnet update-status`, it propagates into every `status_history` entry
  the resulting cascade writes (e.g. magnets pulled to `in_stock` by a
  disassembly, or parts pulled to `in_stock` by a `retired`/`dead` magnet) —
  not just the entry for the entity named on the command line.

## Files affected

- `to_duckdb/schema.py` — edit: add `incidents_id_seq`, `incidents`,
  `incident_magnets`, `incident_parts`.
- `to_duckdb/crud.py` — edit:
  - New: `insert_incident`, `view_incident`, `view_incidents`,
    `_validate_incident_id(con, incident_id)` helper (raises `ValueError` if
    given a non-`None` id that doesn't exist in `incidents`).
  - `_append_status_history`: new `incident_id: int | None = None` param;
    always writes the `"incident_id"` key (default `null`), matching how
    `description`/`attachments` already default rather than being omitted.
  - `update_part_status`: new `incident_id` param, validated, threaded to
    `_append_status_history`.
  - `_set_magnet_status`, `_cascade_parts_status`: new `incident_id` param,
    threaded through so a magnet's own entry *and* every part entry its
    cascade writes carry the same id.
  - `update_magnet_status`: new `incident_id` param, validated once,
    threaded to the magnet's own status change, to each named `dead_parts`
    entry, and to the cascade.
  - `decommission_assembly`, `_cascade_assembly_disassembly`: new
    `incident_id` param, validated once in `decommission_assembly`, threaded
    to the assembly's own entry and to every magnet (and, when applicable,
    part) entry the disassembly cascade writes.
  - `_resolve_housing_overlap`'s internal auto-close call to
    `decommission_assembly` keeps `incident_id=None` (routine housing
    succession, not incident-taggable from the CLI).
- `to_duckdb/magnetdb.py` — edit:
  - New `incident add` / `incident view` subcommands.
  - `part update-status`, `magnet update-status`, `assembly decommission`
    each gain an optional `--incident-id INT`, passed through to the
    corresponding `crud` call.
- `to_duckdb/docs/schema.md` — edit: document the new tables; update the
  `status_history` entry shape example to include `"incident_id": null`;
  note the propagation behavior.
- `to_duckdb/tests/test_crud.py` — edit: incident CRUD tests + cases for
  `incident_id` validation and propagation (direct call, cascade-to-magnet,
  cascade-to-part).
- `to_duckdb/tests/test_magnetdb.py` — edit: CLI coverage for
  `--incident-id` on all three commands, and `incident add`/`view`.

## Schema

```sql
CREATE SEQUENCE IF NOT EXISTS incidents_id_seq START 1;

CREATE TABLE IF NOT EXISTS incidents (
    id            INTEGER PRIMARY KEY DEFAULT nextval('incidents_id_seq'),
    description   VARCHAR,
    date          TIMESTAMP,
    attachments   JSON DEFAULT '[]',
    assembly_name VARCHAR UNIQUE REFERENCES assemblies(name)
);

CREATE TABLE IF NOT EXISTS incident_magnets (
    incident_id INTEGER REFERENCES incidents(id),
    magnet_name VARCHAR REFERENCES magnets(name),
    PRIMARY KEY (incident_id, magnet_name)
);

CREATE TABLE IF NOT EXISTS incident_parts (
    incident_id INTEGER REFERENCES incidents(id),
    part_name   VARCHAR REFERENCES parts(name),
    PRIMARY KEY (incident_id, part_name)
);
```

## Approach

1. Schema: add the three tables + sequence.
2. `_validate_incident_id` helper in `crud.py`.
3. Thread `incident_id` through `_append_status_history` →
   `update_part_status`, `_set_magnet_status` → `_cascade_parts_status`,
   `update_magnet_status` (incl. `dead_parts` entries), `decommission_assembly`
   → `_cascade_assembly_disassembly`.
4. `insert_incident`, `view_incident`, `view_incidents`:
   `insert_incident(con, description="", date=None, attachments=None,
   assembly_name=None, magnet_names=None, part_names=None, verbose=True) ->
   int`. Validates up front (assembly exists and has no incident yet; every
   magnet/part name exists) before writing anything, mirroring
   `insert_magnet_parts`'s two-pass no-partial-write pattern; draws
   `nextval('incidents_id_seq')` for the id so it can populate the junction
   rows in the same call; returns the new id.
5. CLI: `--incident-id` on the three existing subcommands; new `incident
   add`/`view` subcommands:
   ```
   magnetdb.py incident add --description TEXT [--date TS] [--attachment KIND=PATH]
                             [--assembly NAME] [--magnet NAME ...] [--part NAME ...]
   magnetdb.py incident view [ID] [--assembly NAME] [--magnet NAME]
   ```
6. Docs: `schema.md` new-tables section + `status_history` shape update.
7. Tests per the list above.

## Verification

- `test_crud.py`: `insert_incident` with an unknown assembly/magnet/part
  name → `ValueError`, zero rows written; a second `insert_incident` naming
  an assembly that already has one → `ValueError`; a valid call with
  multiple magnets/parts → row + junction rows created, `view_incident`
  prints all links; unknown `incident_id` on `update_part_status`/
  `update_magnet_status`/`decommission_assembly` → `ValueError`, no partial
  write; `magnet update-status --status dead --dead-part P1 --incident-id
  12` stamps `incident_id=12` on the magnet's entry *and* P1's dead-part
  entry; `assembly decommission --incident-id 12` stamps it on the assembly
  and on every magnet (and, for a `retired`/`dead` magnet, part) the cascade
  touches; a call with no `--incident-id` still writes `incident_id: null`
  everywhere (existing tests asserting on `status_history` shape need
  updating for the new key).
- `test_magnetdb.py`: CLI round-trip for `--incident-id` on all three
  commands, and `incident add`/`view`.
- Full suite: `to_duckdb/venv-systempackages/bin/python3 -m pytest
  to_duckdb/tests/` green.

## Assumptions & open questions

1. `incident_id` must be passed at the time of the status-changing call;
   there's no retroactive backfill into `status_history` entries written
   before the incident existed.
2. `incident_magnets`/`incident_parts` (the explicit links set via `incident
   add`) and `status_history.incident_id` (the automatic stamp) are
   independent — nothing cross-checks that a magnet stamped via cascade is
   also explicitly linked in `incident_magnets`, or vice versa.
3. No incident status/type/severity vocabulary — just free-text
   `description` + `date` + `attachments`.
4. No cross-validation between `incident_parts` and `incident_magnets` (a
   part doesn't have to belong to one of the incident's named magnets via
   `magnet_parts`).
5. No `incident delete` command for now (parts had no delete command either,
   until [`PLAN_part_delete.md`](PLAN_part_delete.md) — see side note below).

## Side note — `part delete` split out as its own plan

While discussing this plan, a related but independent need came up: a `part
delete` command for removing a part added by mistake. That's tracked
separately in [`PLAN_part_delete.md`](PLAN_part_delete.md) since it doesn't
depend on anything here. One follow-up to revisit once *this* plan lands:
`delete_part`'s guard should then also check `incident_parts` for a
reference (today it only checks `magnet_parts` and `status_history`, since
`incident_parts` doesn't exist yet).
