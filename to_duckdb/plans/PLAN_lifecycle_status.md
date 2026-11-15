# Plan — lifecycle status for assemblies, magnets, and parts

Status: **implemented (2026-08-19), Phases A+B+C complete** — approved
2026-08-14, updated to `Assembly` vocabulary 2026-08-18 following the
site→assembly rename (`PLAN_site_to_assembly_rename.md`, Track A implemented
and committed 2026-08-18), extended and re-approved 2026-08-18 with
default-status and commissioning-cascade rules (see "Domain rules — creation
defaults and commissioning cascade" below). All three phases landed
2026-08-19: enums/schema/crud/checks/CLI + full test coverage (Phase A+B),
`docs/schema.md` lifecycle section + `TODOs.md` checkoff (Phase C). 4 open
assumptions (see below) remain as shipped defaults; revisit if wrong.

## Goal

Formalize the `status` columns that already exist (and are already populated)
on `assemblies`, `magnets`, and `parts` into a rule-driven lifecycle:
assembly status is derived from `decommissioned_at` with a per-housing
no-overlap guarantee; disassembling an assembly cascades its magnets to
`in_stock`; moving a magnet to `in_stock`/`retired`/`dead` cascades its
parts to `in_stock`; a magnet can only be marked `dead` by naming at least
one dead part in the same call. Every entity also gets an append-only
`status_history` JSON log (status, date, description, attachments) so
incident/maintenance reports and images can be attached over time. Covers
the `TODOs.md` "New features" line *"work on life cycle of magnets and
parts..."* — scope grew during scoping to include `assemblies`, since
assembly disassembly is what triggers the magnet→part cascade and assembly
status can't be kept internally consistent without it.

## Domain rules

- **Assembly status** ∈ `{in_study, in_operation, disassembled}` — derived,
  not free text: `in_study` = explicit opt-out (skips every rule below);
  otherwise `in_operation` iff `decommissioned_at IS NULL`, else
  `disassembled`. Replaces the ad hoc `decommisioned` (typo) value already
  present in production data.
- **No overlap**: for a given `housing`, no two non-`in_study` assemblies'
  `[commissioned_at, decommissioned_at)` windows may overlap.
- **Auto-close on add**: adding a new non-`in_study` assembly to a housing
  that already has an open assembly auto-sets that open assembly's
  `decommissioned_at` to the new assembly's `commissioned_at` (only if not
  already set).
- **Assembly disassembly → magnets**: every magnet currently linked to that
  assembly (`assembly_magnets`, `decommissioned_at IS NULL`) with status
  `NULL`/`in_operation` is pushed to `in_stock`; the matching
  `assembly_magnets` row's `decommissioned_at` is auto-closed to the
  assembly's `decommissioned_at` for consistency.
- **Magnet → in_stock/retired/dead → parts**: any of these three magnet
  status transitions pushes every part in `magnet_parts` with status
  `NULL`/`in_operation` to `in_stock`.
- **Magnet/part status vocabulary**: `in_operation | in_stock | in_study |
  retired | dead` (the TODO's 4 values plus `in_study`, which is already in
  production data for parts and denotes a part/magnet still being designed).
- **Dead invariant**: `magnet update-status <name> --status dead --dead-part
  PART [--dead-part PART2 ...]` — at least one `--dead-part` is required;
  each named part is set (or confirmed, if already dead) to `status="dead"`
  as part of the *same* call, before the magnet itself is marked dead.
  `--dead-part` is rejected with any other `--status`. If neither
  `--description` nor `--attachment` is supplied on a dead call, the CLI
  prints a prominent (non-blocking) multi-line warning nudging toward
  attaching an incident report.
- **No upward cascade, except commissioning** (see open question 2):
  status only ever moves down automatically (toward stock/retired/dead) —
  *except* the commissioning cascade below, which is the one deliberate
  upward exception. Moving up any other way (e.g. `in_stock` back to
  `in_operation` outside of commissioning) is always an explicit
  `update-status` call.

## Domain rules — creation defaults and commissioning cascade

Added 2026-08-18 after the rules above were already approved; resolves open
question 2 (partially — see its updated text) and surfaces three
consistency gaps in the original rules, all confirmed in scope.

- **Part creation default**: `insert_part` defaults `status` to `"in_stock"`
  when the caller supplies none; an explicit value (e.g. `in_study`, for a
  part still being designed) is still honored as-is.
- **Magnet creation default** (open assumption 3): `insert_magnet` likewise
  defaults `status` to `"in_stock"` when unspecified, mirroring parts.
- **Magnet-parts linkage requires in-stock parts**: `insert_magnet_parts`
  validates *all* parts being linked up front, before inserting any row (so
  a rejected call leaves zero `magnet_parts` rows, never a partial set), and
  raises `ValueError` if any part's current `status != "in_stock"` — applies
  even when the magnet itself is `in_study`. `insert_magnet_part_row` (the
  low-level pre-computed-row helper — its docstring's "used by
  seeds_to_duckdb" is stale, since `to_duckdb/deprecated/seeds_to_duckdb.py`
  has no live callers, only test fixtures) is *not* subject to this check;
  docstring corrected to stop pointing at dead code.
- **Commissioning cascade**: `insert_assembly_magnets`, at link time, checks
  whether the target assembly is currently active
  (`decommissioned_at IS NULL AND status != 'in_study'`, via a new shared
  helper `_assembly_is_active()` also used by the auto-close fix below). If
  active: the magnet is promoted `in_stock → in_operation` (only if
  currently `NULL`/`in_stock` — never un-retires a `dead`/`retired`
  magnet), *and* its linked parts currently `NULL`/`in_stock` cascade to
  `in_operation` too (symmetric with the existing downward part cascade —
  closes the double-linking gap below). If not active: the magnet keeps its
  current/default status.
- **One-active-assembly-per-magnet guard**: `insert_assembly_magnets` raises
  `ValueError` if the magnet already has an open link
  (`decommissioned_at IS NULL`) to a *different* assembly — nothing in the
  schema (`assembly_magnets` PK is `(assembly_name, magnet_name)`) otherwise
  prevented one physical magnet being "active" in two assemblies at once.
- **Auto-close now fully cascades**: the original "auto-close on add" rule
  above only set the old assembly's `status`/`status_history`, not its
  magnets — an inconsistency (a `disassembled` assembly whose magnets still
  said `in_operation`) that predates this addendum but is fixed here:
  `insert_assembly`'s auto-close branch now calls the same cascade logic as
  `decommission_assembly()` (factored into a shared internal helper) for
  the assembly being closed, so it also closes that assembly's
  `assembly_magnets` rows and pushes its magnets (and, transitively, their
  parts) to `in_stock`.

## Files affected

- `to_duckdb/enums.py` — edit: add `AssemblyStatus` (`in_study`/
  `in_operation`/`disassembled`) and `LifecycleStatus` (`in_operation`/
  `in_stock`/`in_study`/`retired`/`dead`), mirroring the existing
  `PartType`/`MagnetType` enums.
- `to_duckdb/schema.py` — edit: add `status_history JSON DEFAULT '[]'` to
  `assemblies`, `parts`, `magnets`; idempotent migration rewriting existing
  `assemblies.status = 'decommisioned'` rows to `'disassembled'`.
- `to_duckdb/crud.py` — edit: overlap guard + auto-close (now via the
  shared cascade helper, see above) + status-derivation in the existing
  `insert_assembly`; new `decommission_assembly()` and shared
  `_assembly_is_active()` / disassembly-cascade helpers; status validation
  + in-stock default in `insert_part`/`insert_magnet`; hard in-stock
  validation (two-pass, no partial writes) in `insert_magnet_parts`;
  docstring fix in `insert_magnet_part_row`; commissioning cascade +
  one-active-assembly-per-magnet guard in `insert_assembly_magnets`; new
  `update_part_status`/`update_magnet_status` (cascade to parts,
  `dead_parts` requirement, warning); new `view_parts`/`view_part` (parts
  have no view functions today); extend `view_magnet` to print
  `status_history`.
- `to_duckdb/checks.py` — edit: new `check_assemblies` (overlap/consistency
  audit); extend `check_parts`/`check_magnets` for status validity and a
  dead-invariant audit (catches data that predates this rule).
- `to_duckdb/magnetdb.py` — edit: new `assembly decommission`, `part view`,
  `part update-status`, `magnet update-status` (incl. `--dead-part`); add
  `"assembly"` to `check --entity` choices.
- `to_duckdb/docs/schema.md` — edit: document enum values, cascade rules,
  and the `status_history` entry shape.
- `to_duckdb/tests/test_crud.py`, `test_schema.py`, `test_magnetdb.py` —
  edit: coverage for all of the above.
- `to_duckdb/TODOs.md` — edit: check off the lifecycle line.

## Approach

Phase A and B are implemented together: the commissioning cascade needs
both the assembly-active derivation (originally Phase A) and the
`LifecycleStatus` vocabulary (originally Phase B), so they can no longer
ship as independently-reviewable increments. Phase C (docs/cleanup) follows.

**Phase A+B — Assembly, magnet, part lifecycle + cascades**
1. `AssemblyStatus` enum in `enums.py`.
2. `LifecycleStatus` enum in `enums.py`.
3. `status_history` column on `assemblies`, `parts`, `magnets`; idempotent
   `decommisioned` → `disassembled` data migration in `ensure_schema()`.
4. `_assembly_is_active(con, name) -> bool` internal helper in `crud.py`:
   `decommissioned_at IS NULL AND status != 'in_study'`.
5. `decommission_assembly(con, name, decommissioned_at=None, description="",
   attachments=None, verbose=True)`: sets `decommissioned_at`/
   `status='disassembled'`, appends a `status_history` event, closes the
   matching `assembly_magnets` row(s), and cascades linked magnets (and
   their parts) to `in_stock`. Its cascade body is factored into a shared
   internal helper so step 6 can reuse it.
6. `insert_assembly`: derive `status` from `decommissioned_at` for
   non-`in_study` assemblies (ignore/override a contradicting
   caller-supplied value); reject on housing overlap; auto-close the
   previous open assembly on that housing by calling the shared cascade
   helper from step 5 (not a bare status update) if one exists.
7. `insert_part`/`insert_magnet`: validate `status` against
   `LifecycleStatus` when provided; default to `"in_stock"` when
   unspecified.
8. `insert_magnet_parts`: two-pass — validate every part's
   `status == "in_stock"` before inserting any row; raise `ValueError`
   (naming the offending part and its actual status) otherwise. Correct
   the stale docstring on `insert_magnet_part_row` (not validated).
9. `insert_assembly_magnets`: reject (via `ValueError`) if the magnet
   already has an open link to a different assembly; otherwise, if
   `_assembly_is_active()` is true for the target assembly, cascade the
   magnet (if `NULL`/`in_stock`) to `in_operation` and its `NULL`/`in_stock`
   parts to `in_operation`.
10. `update_part_status`/`update_magnet_status` in `crud.py`.
    `update_magnet_status(con, name, status, description="", changed_at=None,
    attachments=None, dead_parts=None, verbose=True)`:
    - `status == "dead"` requires `dead_parts`: a non-empty list of part
      names belonging to this magnet (validated against `magnet_parts`);
      each is set/confirmed dead first (own `status_history` event), then the
      magnet's own status/history is updated. Missing/empty `dead_parts` →
      `ValueError`.
    - `dead_parts` given with a non-`dead` status → `ValueError`.
    - Transition to `in_stock`/`retired`/`dead` cascades remaining parts (not
      in `dead_parts`) with `NULL`/`in_operation` status to `in_stock`.
    - No `description`/`attachments` on a dead call → prints the prominent
      warning; still succeeds.
11. `view_parts`/`view_part` in `crud.py`; extend `view_magnet` to print
    `status_history`.
12. `check_assemblies(con, name=None)` in `checks.py` (status/
    decommissioned_at consistency, residual per-housing overlaps); add
    `"assembly"` to `magnetdb.py check --entity` choices. Extend
    `check_parts`/`check_magnets` for status validity + dead-invariant
    audit (flags a `dead` magnet with zero `dead` parts, for data that
    predates this rule).
13. `magnetdb.py assembly decommission <name> [--decommissioned-at TS]
    [--description TEXT] [--attachment KIND=PATH]`; `part view`,
    `part update-status`, `magnet update-status` (incl. `--dead-part`,
    repeatable).

**Phase C — Docs & cleanup**
14. Update `docs/schema.md`.
15. Check off the `TODOs.md` lifecycle line.
16. Full suite: `to_duckdb/venv-systempackages/bin/python3 -m pytest
    to_duckdb/tests/`.

## Verification

- Phase A+B: `test_crud.py` covers overlap rejection, auto-close on add now
  cascading the old assembly's magnets to `in_stock`, `in_study` exemption,
  the assembly→magnet cascade on `decommission_assembly` (including that a
  magnet already `retired`/`dead` is left untouched), part/magnet status
  defaults on insert, `insert_magnet_parts` rejecting a non-`in_stock` part
  with zero rows written (partial-application case), the commissioning
  cascade promoting both a magnet and its parts on `insert_assembly_magnets`,
  rejection of linking a magnet already actively linked to a different
  assembly, the magnet→part cascade on `update_magnet_status`, all four
  dead-invariant cases (missing `dead_parts`, a `dead_parts` name not
  belonging to the magnet, valid `dead_parts` succeeding, `dead_parts` with
  a non-dead status), the same-status re-call log-without-cascade case, and
  the warning text (via `capsys`) when a dead call has no
  description/attachment. `test_schema.py` covers the new columns and the
  `decommisioned`→`disassembled` migration on a DB fixture seeded with the
  old value. `test_magnetdb.py` covers the `assembly decommission` CLI path
  and the new `part`/`magnet` CLI subcommands end-to-end via the existing
  `_run`/`_fetch_one` harness.
- Phase C: full `to_duckdb/tests/` suite stays green throughout; no
  behavior change for any pre-existing test.

## Assumptions & open questions

1. **Auto-closing `assembly_magnets.decommissioned_at`** alongside the
   assembly (Phase A, step 4) is an addition made during scoping for
   consistency, not something explicitly requested — flag if
   `assembly_magnets` timestamps should stay independent of the assembly's
   own `decommissioned_at`.
2. **No upward cascade, except commissioning** — updated 2026-08-18:
   originally, linking a magnet to an assembly, or a part to a magnet, was
   assumed not to auto-promote status. Resolved (partially) by the
   commissioning cascade above: linking a magnet to an *active* assembly
   does promote `in_stock → in_operation` for the magnet and its parts.
   Everything else about the original assumption still holds — no other
   linking action auto-promotes status.
3. **Magnet creation default to `in_stock`** (2026-08-18, not yet field-
   tested): assumed to mirror the part default; flag if magnets should keep
   no default at insert time.
4. **`insert_magnet_part_row` left unvalidated** (2026-08-18): the seed/
   pre-computed-row path does not enforce the in-stock-parts rule, since it
   has no live production caller (only test fixtures) — flag if it should
   validate too, e.g. if it ever gains a real caller.

## Follow-up — 2026-08-28: parts stay `in_operation` through assembly disassembly

Status: **implemented 2026-08-28** — approved 2026-08-28. Amends, without
rewriting, the "Magnet → in_stock/retired/dead → parts" rule above.

### Goal

Rebalance the downward cascade: assembly disassembly no longer pulls a
magnet's parts down to `in_stock` — only an explicit magnet-level transition
to `retired` or `dead` does. Also closes a related latent bug: `magnet add`
(JSON import) could crash mid-write if a part's JSON `status` wasn't
`in_stock`.

### Domain rule changes (supersedes "Magnet → in_stock/retired/dead → parts")

- **Magnet → `in_stock` → parts: no longer cascades.** A magnet transitioning
  to `in_stock` — whether via assembly disassembly or a direct
  `update_magnet_status` call — leaves its linked parts' status untouched.
  In practice, parts commissioned into `in_operation` stay `in_operation`
  after their magnet is disassembled/stocked, until the magnet is explicitly
  `retired` or marked `dead`.
- **Magnet → `retired`/`dead` → parts: unchanged.** Both still cascade
  `NULL`/`in_operation` parts to `in_stock` (`retired`: all linked parts;
  `dead`: all except the explicitly-named `dead_parts`), and the
  dead-invariant (`--dead-part` required) is unchanged.
- **`insert_magnet_parts`'s in-stock-only linkage rule is unchanged** —
  parts must still be exactly `in_stock` to be linked to a magnet (new or
  existing). Explicitly decided not to loosen this to also accept
  `in_operation`, even though disassembly can now leave parts at
  `in_operation`.
- **New: `magnet add` (JSON import) fails fast on a non-`in_stock` part
  status.** Previously, a JSON part with e.g. `"status": "in_operation"` was
  written to the `parts` table by `insert_part` before `insert_magnet_parts`
  rejected the link, leaving a partial write and an unhandled `ValueError`
  traceback. `_validate_magnet` now rejects such payloads up front, before
  any DB writes.

### Files affected

- `to_duckdb/crud.py` — edit: `_DOWN_CASCADE_STATUSES` drops `in_stock`,
  keeping only `{retired, dead}`; docstring fixes on `_set_magnet_status`
  and `_cascade_assembly_disassembly`.
- `to_duckdb/docs/schema.md` — edit: "## Lifecycle" diagram edge corrected.
- `to_duckdb/magnetdb.py` — edit: `_validate_magnet` gains a per-part status
  check.
- `to_duckdb/tests/test_crud.py` — edit: disassembly-cascade test now
  asserts parts stay `in_operation`; added tests that `retired` still
  cascades and that a direct `in_stock` update does not.
- `to_duckdb/tests/test_magnetdb.py` — edit: new test for the `magnet add`
  fail-fast validation.

### Approach

1. Remove `LifecycleStatus.IN_STOCK.value` from `_DOWN_CASCADE_STATUSES`
   (`crud.py`).
2. Update the two stale docstrings referencing the old `in_stock` cascade
   behavior (`_set_magnet_status`, `_cascade_assembly_disassembly`).
3. Add the up-front per-part status check to `_validate_magnet`
   (`magnetdb.py`), erroring on any part whose JSON `status` is present and
   not `"in_stock"`.
4. Update `docs/schema.md`'s lifecycle diagram.
5. Update/add the tests listed above.

### Verification

- `to_duckdb/venv-systempackages/bin/python3 -m pytest to_duckdb/tests/`
  stays green, including the updated/new cases above.
- Manual check: `magnet add` with a part JSON `status: "in_operation"` exits
  non-zero with a clear message and writes zero rows.

### Assumptions

- `dead`'s existing behavior for non-named parts (still cascading to
  `in_stock`) is intentionally unchanged.
- The original numbered rules/phases (1–16) and the 2026-08-18 addendum
  above are left as a historical record of what shipped 2026-08-19; this
  section layers an amendment on top rather than editing them.
- No SQL/schema changes needed.
