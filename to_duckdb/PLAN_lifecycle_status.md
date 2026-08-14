# Plan — lifecycle status for sites, magnets, and parts

Status: **approved (2026-08-14), not yet implemented** — 2 open assumptions
(see below) carried into implementation as current defaults; revisit if
wrong before Phase A/B land.

## Goal

Formalize the `status` columns that already exist (and are already populated)
on `sites`, `magnets`, and `parts` into a rule-driven lifecycle: site status
is derived from `decommissioned_at` with a per-housing no-overlap guarantee;
disassembling a site cascades its magnets to `in_stock`; moving a magnet to
`in_stock`/`retired`/`dead` cascades its parts to `in_stock`; a magnet can
only be marked `dead` by naming at least one dead part in the same call.
Every entity also gets an append-only `status_history` JSON log (status,
date, description, attachments) so incident/maintenance reports and images
can be attached over time. Covers the `TODOs.md` "New features" line *"work
on life cycle of magnets and parts..."* — scope grew during scoping to
include `sites`, since site disassembly is what triggers the magnet→part
cascade and site status can't be kept internally consistent without it.

## Domain rules

- **Site status** ∈ `{in_study, in_operation, disassembled}` — derived, not
  free text: `in_study` = explicit opt-out (skips every rule below);
  otherwise `in_operation` iff `decommissioned_at IS NULL`, else
  `disassembled`. Replaces the ad hoc `decommisioned` (typo) value already
  present in production data.
- **No overlap**: for a given `housing`, no two non-`in_study` sites'
  `[commissioned_at, decommissioned_at)` windows may overlap.
- **Auto-close on add**: adding a new non-`in_study` site to a housing that
  already has an open site auto-sets that open site's `decommissioned_at` to
  the new site's `commissioned_at` (only if not already set).
- **Site disassembly → magnets**: every magnet currently linked to that site
  (`site_magnets`, `decommissioned_at IS NULL`) with status `NULL`/
  `in_operation` is pushed to `in_stock`; the matching `site_magnets`
  row's `decommissioned_at` is auto-closed to the site's `decommissioned_at`
  for consistency.
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
- **No upward cascade** (see open question 2): status only ever moves down
  automatically (toward stock/retired/dead); moving up (e.g. back to
  `in_operation`) is always an explicit `update-status` call, never implied
  by linking a magnet to a site or a part to a magnet.

## Files affected

- `to_duckdb/enums.py` — edit: add `SiteStatus` (`in_study`/`in_operation`/
  `disassembled`) and `LifecycleStatus` (`in_operation`/`in_stock`/
  `in_study`/`retired`/`dead`), mirroring the existing `PartType`/
  `MagnetType` enums.
- `to_duckdb/schema.py` — edit: add `status_history JSON DEFAULT '[]'` to
  `sites`, `parts`, `magnets`; idempotent migration rewriting existing
  `sites.status = 'decommisioned'` rows to `'disassembled'`.
- `to_duckdb/crud.py` — edit: overlap guard + auto-close + status-derivation
  in `insert_site`; new `decommission_site()`; status validation in
  `insert_part`/`insert_magnet`; new `update_part_status`/
  `update_magnet_status` (cascade to parts, `dead_parts` requirement,
  warning); new `view_parts`/`view_part` (parts have no view functions
  today); extend `view_magnet` to print `status_history`; cascade helpers.
- `to_duckdb/checks.py` — edit: new `check_sites` (overlap/consistency
  audit); extend `check_parts`/`check_magnets` for status validity and a
  dead-invariant audit (catches data that predates this rule).
- `to_duckdb/magnetdb.py` — edit: new `site decommission`, `part view`,
  `part update-status`, `magnet update-status` (incl. `--dead-part`); add
  `"site"` to `check --entity` choices.
- `to_duckdb/docs/schema.md` — edit: document enum values, cascade rules,
  and the `status_history` entry shape.
- `to_duckdb/tests/test_crud.py`, `test_schema.py`, `test_magnetdb.py` —
  edit: coverage for all of the above.
- `to_duckdb/TODOs.md` — edit: check off the lifecycle line.

## Approach

**Phase A — Site lifecycle (foundation; magnet/part cascades depend on it)**
1. `SiteStatus` enum in `enums.py`.
2. `status_history` column on `sites`; idempotent `decommisioned` →
   `disassembled` data migration in `ensure_schema()`.
3. `insert_site`: derive `status` from `decommissioned_at` for non-`in_study`
   sites (ignore/override a contradicting caller-supplied value); reject on
   housing overlap; auto-close the previous open site on that housing
   (status + `status_history` event) if one exists.
4. `decommission_site(con, name, decommissioned_at=None, description="",
   attachments=None, verbose=True)`: sets `decommissioned_at`/
   `status='disassembled'`, appends a `status_history` event, closes the
   matching `site_magnets` row(s), and cascades linked magnets to
   `in_stock`.
5. `check_sites(con, name=None)` in `checks.py` (status/decommissioned_at
   consistency, residual per-housing overlaps); add `"site"` to
   `magnetdb.py check --entity` choices.
6. `magnetdb.py site decommission <name> [--decommissioned-at TS]
   [--description TEXT] [--attachment KIND=PATH]`.

**Phase B — Magnet/part status + cascades**
7. `LifecycleStatus` enum; `status_history` column on `parts`/`magnets`
   (idempotent migration).
8. Validate `status` in `insert_part`/`insert_magnet` against
   `LifecycleStatus` when provided (stays optional at insert time).
9. `update_part_status`/`update_magnet_status` in `crud.py`.
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
10. `view_parts`/`view_part` in `crud.py`; extend `view_magnet` to print
    `status_history`.
11. Extend `check_parts`/`check_magnets` for status validity + dead-invariant
    audit (flags a `dead` magnet with zero `dead` parts, for data that
    predates this rule).
12. `part view`, `part update-status`, `magnet update-status` (incl.
    `--dead-part`, repeatable) in `magnetdb.py`.

**Phase C — Docs & cleanup**
13. Update `docs/schema.md`.
14. Check off the `TODOs.md` lifecycle line.
15. Full suite: `to_duckdb/venv-systempackages/bin/python3 -m pytest
    to_duckdb/tests/`.

## Verification

- Phase A: `test_crud.py` covers overlap rejection, auto-close on add,
  `in_study` exemption, and the site→magnet cascade (including that a
  magnet already `retired`/`dead` is left untouched); `test_schema.py`
  covers the new column and the `decommisioned`→`disassembled` migration on
  a DB fixture seeded with the old value; `test_magnetdb.py` covers the
  `site decommission` CLI path end-to-end via the existing `_run`/
  `_fetch_one` harness.
- Phase B: `test_crud.py` covers the magnet→part cascade, all four
  dead-invariant cases (missing `dead_parts`, a `dead_parts` name not
  belonging to the magnet, valid `dead_parts` succeeding, `dead_parts` with
  a non-dead status), the same-status re-call log-without-cascade case, and
  the warning text (via `capsys`) when a dead call has no
  description/attachment; `test_magnetdb.py` covers the new `part`/`magnet`
  CLI subcommands.
- Phase C: full `to_duckdb/tests/` suite stays green throughout; no
  behavior change for any pre-existing test.

## Assumptions & open questions

1. **Auto-closing `site_magnets.decommissioned_at`** alongside the site
   (Phase A, step 4) is an addition made during scoping for consistency, not
   something explicitly requested — flag if `site_magnets` timestamps should
   stay independent of the site's own `decommissioned_at`.
2. **No upward cascade**: linking a magnet to a site, or a part to a magnet,
   does not auto-promote status back to `in_operation` — that's always an
   explicit `update-status` call. Confirm this is correct, since only the
   downward (disassembly/retirement) direction was specified.
