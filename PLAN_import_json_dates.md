# Plan: importer reads `manufactured_at` / `assembled_at` from the JSON

Status: **done**: implemented 2026-10-28 (`195732c`), addendum 2026-10-29
(`84d0079`); follow-ups closed 2026-11-03 (see [Follow-ups](#follow-ups)).
Related: [`PLAN_missing_dates.md`](PLAN_missing_dates.md) reports and fixes
missing dates in an *existing* database. This plan makes the importer stop
producing them in the first place.

## Goal

When a part or magnet is imported, `manufactured_at` / `assembled_at` comes
from its JSON. If the JSON has no date, the importer falls back to the date
coded in the name, with a warning. If neither gives a date, the import stops
with an error. Implausible dates are errors, and dates out of order produce
warnings.

## Current state

- [`crud.py:651`](to_duckdb/crud.py#L651) (`insert_part`) and
  [`crud.py:765`](to_duckdb/crud.py#L765) (`insert_magnet`) only use
  `manufactured_at_from_name` / `assembled_at_from_name`
  (`[HR]YYMMDDXX` / `MYYMMDDXX`). Hand-named Bitters and supra parts and
  magnets silently get `NULL`, even when their JSON has a date.
- The same name-derived date timestamps status events:
  [`crud.py:989`](to_duckdb/crud.py#L989) ("Attached to magnet") and
  [`crud.py:855`](to_duckdb/crud.py#L855) ("Superseded" plus automatic
  closure of the assembly). For Bitters names it is `None`, so those events
  get the import time. This is where the `2026-10-08T10:3x` entries in
  `status_history` come from, together with a third path missed here (see
  "Addendum").
- `magnetdb-2026-10-08.duckdb`: 9 / 23 magnets and 12 / 172 parts have no
  date. All of them are Bitters or supra items.
- Source JSON (`hifimagnet-projects/magnetdb.json/`, fixed 2026-10-28, not
  committed yet): all 196 files parse.
  - 12 part and 9 magnet files carry a date.
  - 97 parts and 14 magnets are dated only by their coded name.
  - No item has neither, and no file's JSON date disagrees with its name
    date.

## Behaviour

| Case | Result |
|---|---|
| JSON date present and valid | used, no message |
| JSON date missing / `null` / `""` / `"None"`, and the name gives a date | name date used, **`[WARN]`** |
| neither gives a date | **error** (`ValueError`), nothing written for that magnet |
| JSON date not in `YYYY-MM-DD[ HH:MM:SS]` format | **error** |
| date after today or before 1980-01-01 | **error** |
| JSON and name both give a date and they differ | **`[WARN]`**, the JSON date is used |
| part made after the magnet it is linked to (any part type) | **`[WARN]`** at import, in `insert_magnet_parts` |
| magnet assembled after the commissioning of an assembly it is linked to | **`[WARN]`** at import, in the assembly-linking code *(default, to confirm)* |
| "Attached to magnet" / "Superseded" / automatic-closure events | dated with the magnet's **stored** `assembled_at` instead of the name-derived date |

Message format follows the codebase, e.g.
`  [WARN] part 'H23012001': no manufactured_at in JSON — using 2023-01-20 from its name.`
Errors are `ValueError`s, like `_check_material_exists`.

Expected warning volume per rebuild with today's data:
- about 111 fallback lines, one per item *(default, to confirm)*
- 63 part-after-magnet lines: 55 rings over 6 inserts, plus 8 helices in
  `M09052601` / `M12082401`, whose name date predates their helices
- 2 magnet-after-commissioning lines, both `M19071101`

## Files affected

| File | Action | Change |
|---|---|---|
| `to_duckdb/crud.py` | edit | New public `resolve_manufactured_at(part)` / `resolve_assembled_at(magnet)` built on a private `_resolve_date`, plus range constants. `insert_part` / `insert_magnet` use them and print the warnings. `insert_magnet_parts` warns about parts made after the magnet. The assembly-linking code warns about magnets assembled after commissioning. A new `_magnet_assembled_at(con, name)` replaces `assembled_at_from_name` at lines 855 and 989. NumPy docstrings. |
| `to_duckdb/magnetdb.py` | edit | `_validate_magnet` runs both resolvers on the magnet and each part, so date errors are reported as "Validation errors" and exit 1 **before anything is written**, also with `--dry-run`. |
| `to_duckdb/tests/conftest.py` | edit | Add dates to the fixtures with uncoded names (`HELIX_01`, `RING_01`, `MAG_01`, `MAG_JSON`, `H_JSON_01`, `R_JSON_01`), which would otherwise raise. |
| `to_duckdb/tests/test_crud.py` | edit | Turn the two "leaves NULL for non-conforming name" tests into "raises". New tests: JSON date used; fallback warns; JSON/name disagreement warns; bad format raises; out-of-range raises; part-after-magnet warns; magnet-after-commissioning warns; events use the stored `assembled_at`. |
| `to_duckdb/tests/test_add_magnet.py` | edit | An undated part makes `magnet add` exit 1 with nothing written. |
| `to_duckdb/docs/schema.md` | edit | Document the JSON `manufactured_at` / `assembled_at` fields, the fallback, the errors and the warnings. |

## Approach / verification

All commands use `<repo>/.venv/bin/python`, with pytest run from `to_duckdb/`.

1. Run the baseline `pytest` → verify: record the pass/fail list.
2. Write the new and changed tests → verify: they fail for the expected
   reason (missing functions or old behaviour).
3. Add the resolvers and use them in `insert_part`, `insert_magnet` and
   `_validate_magnet` → verify: resolver and insert tests pass.
4. Add the ordering warnings and switch event dates to
   `_magnet_assembled_at` → verify: those tests pass.
5. Update fixtures and docs → verify: the full suite matches step 1 plus the
   new tests.
6. Run `magnetdb.py magnet add <file> --dry-run` on every magnet JSON in
   `hifimagnet-projects/magnetdb.json/` → verify: 0 validation errors.
7. No rebuild and no commit. Both are follow-ups.

## Assumptions & open questions

Decided:

1. A fallback to the name date always warns. A failed fallback is an error.
2. Ordering problems only warn, whatever the part type. No error, no
   `check` report.

Defaults, confirmed by the implementation:

3. **Magnet assembled after commissioning** is treated like the part rule:
   warning at import.
4. **Fallback warnings:** one line per item (about 111 per rebuild).

Assumptions:

5. An error stops only that magnet or assembly file. The build's
   `assemblies` step reports a failed file and continues.
6. Plausible range is 1980-01-01 to today. The earliest real date in the
   data is 1993-08-23 (`M5Bi`).
7. Out of scope: refreshing dates in an existing database (`part update` /
   `magnet update` don't touch dates, and re-adding a magnet with a
   different date isn't reported as a conflict).

## Follow-ups

- **Done:** commit the JSON fixes in `hifimagnet-projects`, including
  `M9_A250401_00.json` (magnet `M9Bitters-newBi09` → `M9Bitters-newBi08`).
  Committed as `hifimagnet-projects` `4a926d88`.
- **Done:** rebuild with `scripts/build_from_scratch.sh`. This fixes the missing
  dates, the `M9_A250401_00` link and its 270 misattributed
  `exp_part_bin_stats` rows, and the import-time event dates.
  Rebuilt as `magnetdb-2026-10-29.duckdb`.
- **Done:** after the rebuild, `PLAN_missing_dates.md`'s counts for magnets and parts
  should drop to 0. They did: 0 / 23 magnets, 0 / 201 parts.
- **Done (2026-11-03, not committed in `hifimagnet-projects`):** give
  `M09052601` and `M12082401` a real `assembled_at` in their JSON to
  remove the 8 helix ordering warnings. Set to the latest helix's
  manufacturing date (the earliest date consistent with the helices, still
  before the first commissioning): `M09052601` → `2009-07-09 08:00:00`
  (`H09070901`), `M12082401` → `2013-09-17 08:00:00` (`H13091701`).
  Checked by loading both into a fresh scratch DB: no helix warning left.
  Takes effect in the database at the next rebuild.
- **Open, out of scope:** 5 rings guessed with IA help carry a name date of
  2026-02-10 and still warn "made after magnet": `R26021001`,
  `R26021002`, `R26021014`, `R26021030` (`M09052601`) and `R26021028`
  (`M12082401`). The other guessed rings (`R261029xx`) carry a JSON
  `manufactured_at` equal to the magnet's name date and do not warn.

## Addendum (2026-10-29): "Commissioned into assembly" events

The scratch build `magnetdb-scratch` (`--to statuses`, after this plan) still
had 8 magnet events dated with the import time: every magnet of the 4
active assemblies (`M5_A140101_00`, `M8_A230919_00`, `M9_A260707_00`,
`M10_A260930_00`), all "Commissioned into assembly …". The commissioning
cascade in `_insert_assembly_magnets` called `_set_magnet_status` without
`changed_at`, so the event, and any event it cascades to the parts, got
`datetime.now()`.

Fixed: the event is now dated with the link's `commissioned_at`, else the
assembly's, the same date the magnet-after-commissioning warning uses. Tests:
`test_insert_assembly_magnets_commissioning_events_use_commissioned_at`
(both cases) in `to_duckdb/tests/test_crud.py`. The next rebuild picks it up.
