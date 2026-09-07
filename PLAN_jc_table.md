# Plan — `jc` table + supra-only Jc linkage

Status: **awaiting approval** (2026-09-02) — not yet implemented.

## Goal

A `jc` table exists in the DuckDB schema for critical-current-density
(supraconductor) records, with CRUD/CLI parity to the existing `materials`
table. Every `supra`-type part carries a `jc_name` reference — required for
supra parts, inapplicable/ignored for every other part type — mirroring how
every part already carries `material_name`. `jc` also appears in
`magnetdb.py list` alongside materials/magnets/assemblies/housings.

## Assumptions

- `jc(name VARCHAR PRIMARY KEY, symbol, unit, parameters JSON DEFAULT '{}',
  variables VARCHAR[], expression VARCHAR, tabulated_file VARCHAR DEFAULT '',
  metadata JSON DEFAULT '{}')`, in that column order (`name` first, matching
  the `materials`/`parts`/`magnets` convention).
- `jc` table is created before `parts` in `schema.py` so
  `parts.jc_name VARCHAR REFERENCES jc(name)` resolves inline; the column is
  nullable, plus an idempotent
  `ALTER TABLE parts ADD COLUMN IF NOT EXISTS jc_name VARCHAR;` for databases
  that predate it (no FK clause on the ALTER path — no precedent in this
  file for adding a constraint that way).
- `jc_name` is set **only** when `part["type"] == PartType.SUPRA.value`
  (`"supra"`) — enforced inside `insert_part` itself (not just CLI
  validation), so it holds regardless of call path. A `jc`/`jc_name` value
  supplied on a non-supra part is silently not persisted (no error — this
  isn't an invariant violation, just inapplicable data).
- `_validate_magnet` requires `jc.name` only for supra parts; no
  requirement or consideration for other types.
- `delete_jc` blocks deletion when a `parts` row references it, mirroring
  `delete_material`'s guard against `parts.material_name`.
- New public functions get full NumPy-style docstrings per `CLAUDE.md`,
  even though sibling `materials` functions only carry one-liners.
- `schema_diagram.py` (hand-laid-out ER diagram with hardcoded
  coordinates/colors) is left untouched — a separate visual-layout task.

## Files affected

1. **`to_duckdb/schema.py`** (edit) — `jc` table DDL placed after
   `materials`, before `parts`; `jc_name` column + FK added to the `parts`
   CREATE TABLE; idempotent
   `ALTER TABLE parts ADD COLUMN IF NOT EXISTS jc_name VARCHAR;`.
2. **`to_duckdb/crud.py`** (edit) — add `insert_jc`, `view_jcs`, `view_jc`,
   `delete_jc`; `insert_part` gains supra-gated `jc_name` resolution
   (`jc_name = part.get("jc_name") or (part.get("jc") or {}).get("name")`
   only when `type == "supra"`, else `None`); `view_part` prints a `jc` line
   when set; `list_objects()` gains a `"jc"` entry; module "Public API"
   docstring list updated.
3. **`to_duckdb/magnetdb.py`** (edit) — `jc add/view/delete` CLI (imports,
   handlers, argparse subparser, `_DISPATCH` entries, usage docstring);
   `_validate_magnet` requires `jc.name` for supra parts only;
   `_add_magnet`'s nested-object auto-insert loop inserts nested `jc` dicts
   from supra parts only (dedup by name, mirroring the existing
   `seen_materials` loop); dry-run summary gets a `jcs: N` line; `cmd_list`
   output/`list_objects` includes `jc`.
4. **`to_duckdb/tests/test_schema.py`** (edit) — add `"jc"` to
   `EXPECTED_TABLES` (the exact-set check in
   `test_ensure_schema_creates_all_tables` would otherwise fail).
5. **`to_duckdb/tests/test_jc_db.py`** (new) — table/columns exist;
   insert/idempotency; view listing/detail; delete + not-found +
   blocked-by-referencing-part, mirroring `test_material_db.py`'s
   structure with inline synthetic fixture data (no reference-JSON corpus
   exists for `jc` the way it does for materials).
6. **`to_duckdb/tests/test_crud.py`** (edit, additive only — this file has
   uncommitted user changes) — `insert_part` tests: nested `jc` on a supra
   part sets `jc_name`; a `jc`/`jc_name` value on a non-supra part is
   ignored (`jc_name` stays `NULL`).
7. **`to_duckdb/tests/test_add_magnet.py`** (edit, additive only) — supra
   part missing `jc` fails validation; supra part with nested `jc` inserts
   a `jc` row and links `parts.jc_name`; a stray `jc` block on a non-supra
   part is a no-op; shared jc across supra parts doesn't duplicate-key.
8. **`to_duckdb/docs/schema.md`** (edit) — `jc` row added to the table
   overview; new "Jc JSON format" section mirroring "Material JSON
   format"; a note that `jc_name` applies only to `supra` parts.

## Approach

`schema.py` → `crud.py` → `magnetdb.py` (CLI + validation + import + list)
→ tests (`test_schema.py`, `test_jc_db.py`, `test_crud.py`,
`test_add_magnet.py`) → `docs/schema.md`, running the affected test files
after each stage.

## Verification

1. `python -m pytest tests/test_schema.py tests/test_jc_db.py
   tests/test_crud.py tests/test_add_magnet.py tests/test_material_db.py -q`
   → all green.
2. `python -m pytest tests/ -q` → full suite, no regressions.
3. Manual: `magnet add --dry-run` on a JSON with one supra part carrying a
   nested `jc` (see `jcs: 1` in the summary), then a real `magnet add`,
   `jc view`, `jc view <name>`, `part view <supra-part>` (shows the `jc`
   line), `magnetdb.py list` (shows the jc), `jc delete <name>` while still
   referenced (blocked).
