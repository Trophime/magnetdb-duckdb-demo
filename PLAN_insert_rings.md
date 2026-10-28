# Plan: give rings to insert magnets that have none

Status: **proposed** (2026-10-28), not yet approved or implemented.
Prerequisite: [`PLAN_import_json_dates.md`](PLAN_import_json_dates.md).
Must run **before** the full rebuild that precedes
[`PLAN_missing_dates.md`](PLAN_missing_dates.md) (see "Order of work").

## Goal

Every insert magnet that has no rings gets one ring per gap between
consecutive helices. Rings come from the ring JSON files in
`hifimagnet-projects/magnetdb.json/` when one fits geometrically and the
sharing rule allows it. Otherwise a placeholder ring JSON is created, and as
few placeholders as possible are created. The result is written into the
magnet JSON files so the next rebuild loads it.

**Sharing rule**: a ring cannot belong to two magnets that were in operation
at the same time, nor to a magnet that was in stock at the same time, taking
the target magnet's whole history into account.

## Current state (`magnetdb-2026-10-08.duckdb` + JSON, 2026-10-28)

- 8 insert magnets have no rings: `M09052601`, `M12082401`, `M15061601`,
  `M18110501`, `M19061901`, `M20022001`, `M22011801`, `M23072801`. That is
  102 slots: 13 per 14-helix magnet, plus 11 for `M15061601`.
- 66 ring JSON files. 54 rings are already linked to magnets; 12 are not in
  the database.
- In a magnet's part order, rings come after the helices, from H1H2 to
  H13H14. Coil indices count helices only, so adding rings does not shift
  them.
- `hifimagnet-projects` holds 150 `Ring-*.yaml` geometry files, many more
  than there are ring JSON files.
- Lifetimes (`assembled_at` → first `retired`/`dead` event):

  | Magnet | Lifetime | Role |
  |---|---|---|
  | M09052601 | 2009-05-26 → 2024-12-06 | target |
  | M12082401 | 2012-08-24 → 2024-12-10 | target |
  | M15061601 | 2015-06-16 → 2019-07-11 | target |
  | M18110501 | 2018-11-05 → 2019-02-06 | target |
  | M19061901 | 2019-06-19 → 2020-02-20 | target |
  | M20022001 | 2020-02-20 → 2022-01-18 | target |
  | M22011801 | 2022-01-18 → 2023-07-28 | target |
  | M23072801 | 2023-07-28 → 2025-01-20 | target |
  | M19020601 | 2019-02-06 → 2019-06-19 | ring holder |
  | M19071101 | 2019-07-11 → 2025-01-20 (wrong, see below) | ring holder |
  | M20092801 | 2020-09-28 → now | ring holder |
  | M23012001 | 2023-01-20 → now | ring holder |
  | M25012001 | 2025-01-20 → now (in stock) | ring holder |

- **Existing rule violation**: `R26021005` is linked to both `M19071101` and
  `M25012001`. Because of it, the importer retired `M19071101` on
  2025-01-20 ("Superseded by magnet 'M25012001'"), although it stayed in use
  until 2026-09-30 (`M10_A260626_00`). Fixing the JSON, i.e. deciding which
  magnet really has which H5H6 ring, is a manual decision.

## Rules

1. **Slot**: slot *i* is the gap between helix *i* and helix *i+1*, in rank
   order.
2. **Fit**: a ring fits slot *i* when its geometry `r` equals helix *i*'s `r`
   followed by helix *i+1*'s `r`, within the tolerance (see open question 1).
   Example: `Ring-H1H2` `[19.3, 24.2, 25.1, 30.7]` is H1 `[19.3, 24.2]`
   followed by H2 `[25.1, 30.7]`. This works across design families, which
   matters because several targets mix HL-34, HL-31 and HR-21 helices.
3. **Lifetime** of a magnet: from `assembled_at` to its first
   `retired`/`dead` event, or open-ended if there is none. Periods in stock
   are included, because a magnet in stock keeps its rings.
4. **Sharing**: ring R can go to target T only if T's lifetime does not
   overlap the lifetime of any other magnet holding R. That covers existing
   holders and targets given R earlier in the same run. An end date equal to
   the next start date counts as a handover and is allowed.
5. **Minimal placeholders**: assignments are computed separately for each
   geometry class, i.e. each set of identical required radii.
   1. Real rings first: an exact search uses as many real rings as possible
      under rule 4. With at most 8 targets and a few rings per class, this is
      cheap.
   2. Each slot still uncovered gets a placeholder. Placeholders follow
      rule 4 too, so non-overlapping magnets share one. The minimum number
      of placeholders is the largest number of uncovered lifetimes that
      overlap at any one moment. Assigning them oldest first, each to any
      free placeholder, reaches that minimum.
6. **Tie-break** between solutions with the same number of placeholders:
   1. a ring whose holder starts exactly when T ends, or ends exactly when T
      starts (a likely physical handover). Example: `M15061601` ends
      2019-07-11, the day `M19071101`, with the same 50 mm rings, is
      assembled.
   2. a ring that is in no magnet.
   3. any other valid ring.

   Remaining ties are broken by ring name.

## Expected result (to be recomputed by the tool)

- **Geometry**: on each 34 mm magnet, 10–11 of the 13 slots have a fitting
  ring JSON; `M15061601` has 11 of 11.
- **Time**:
  - The M9 chain `M18110501` → `M19061901` → `M20022001` → `M22011801` →
    `M23072801` runs back to back, so one ring set can pass along it.
  - `M09052601` and `M12082401` overlap every holder except `M25012001`, and
    they overlap each other. They can only use the free rings and
    `M25012001`'s rings.
- **Slots with no fitting ring JSON**:

  | Required radii | Slots | Geometry file | Min. placeholders |
  |---|---|---|---|
  | H10H11 `104.8–135.0` | M09052601, M12082401, M18110501 | `HL-27/Ring-H10H11.yaml` (and 9 others) | 3 |
  | H11H12 `119.8–152.2` | M09052601, M12082401, M18110501 | `HL-27/Ring-H11H12.yaml` (and 9 others) | 3 |
  | H11H12 `119.8–152.3` | M19061901, M20022001, M22011801, M23072801 | `HL-34/Ring-H11H12.yaml` | 1 |
  | H12H13 `135.9–169.6` | M20022001, M22011801, M23072801 | `HL-34/Ring-H12H13.yaml` | 1 |
  | H12H13 `135.9–169.5` | M19061901 | none at ±0.05 mm (see open question 1) | 1, or 0 if merged with the row above |
  | H13H14 `153.1–186.0` | M20022001, M22011801, M23072801 | `HL-34/Ring-H13H14.yaml` | 1 |

  That is 9–10 placeholders. More may be needed for slots where a ring fits
  but every candidate is blocked by the sharing rule.

## Placeholder ring JSON

Written to `hifimagnet-projects/magnetdb.json/`:

| Field | Value |
|---|---|
| `name` | `RX_<family>_<slot>_<NN>`, e.g. `RX_HL-34_H11H12_01` (default; never mistaken for a real `R`+date name) |
| `type` / `status` | `ring` / `in_stock`. The importer only links `in_stock` parts. |
| `geometry` | The matching `Ring-*.yaml`. Prefer the first target's design family folder; otherwise take the first match by path. |
| `design_office_reference` | The `cad` value in that yaml, e.g. `HL-27-029-G`. |
| `material` | Copied from a real ring of the same family and slot if one exists; otherwise the most common ring material, `MA26021002` (CuCrZr, 55 of 66 rings) (default). |
| `manufactured_at` | `assembled_at` of the first magnet it is assigned to, so it never triggers the "made after magnet" warning from `PLAN_import_json_dates.md`. |
| `description` | `"Placeholder ring created by suggest_rings.py — no real ring known."` |

## Files affected

| File | Action | Change |
|---|---|---|
| `to_duckdb/suggest_rings.py` | create | CLI: `--db`, `--json-dir`, `[--magnet NAME]`, `[--tolerance MM]`, `[--write]`. Without `--write` it prints a read-only report covering each target and slot: the chosen ring or placeholder and why, the alternatives, slots left empty and why (no geometry file, or all candidates conflicting), each planned placeholder with the slots it fills, and existing rule violations. With `--write` it appends the chosen ring names, in slot order, to each target's `"parts"` list and creates the placeholder JSON files. Magnets that already have rings are skipped. NumPy docstrings, PEP 8. |
| `to_duckdb/tests/test_suggest_rings.py` | create | Tests: radius fit with tolerance; overlap, with handover allowed; in-stock period counted; overlapping targets never share a ring; a back-to-back chain can share; real rings used before placeholders; non-overlapping magnets share one placeholder; placeholder count equals the largest overlap (3 for three overlapping lifetimes, 1 for a chain); tie-break order; generated placeholder JSON has the fields above and parses; slot with no geometry file is reported and gets no placeholder; existing violation reported; `--write` inserts after the last helix, and running it twice changes nothing. |
| `to_duckdb/README.md` | edit | Document `suggest_rings.py`. |

The tool never writes to the database. `--write` edits only the target
magnet JSON files and adds the `RX_*.json` files.

## Order of work

Ring edits made after a full rebuild would need a second full rebuild, so
the order is:

1. Implement `PLAN_import_json_dates.md` → verify: per that plan.
2. Do a quick partial build into a scratch database with
   `scripts/build_from_scratch.sh --to statuses --db <scratch>`. It skips the
   stats steps and gives correct lifetimes → verify: no `status_history`
   date equals the import time.
3. Write the tests, then `suggest_rings.py` → verify: the new tests pass and
   the full `to_duckdb` suite matches its baseline.
4. Run the report on the scratch database → verify: the user reviews the
   proposal and decides how to fix `R26021005`. The JSON edit is made by the
   user, or by Claude with approval.
5. Run `suggest_rings.py --write` → verify: `git diff` in
   `hifimagnet-projects` shows only ring names added to the 8 target magnet
   JSON files, plus the new `RX_*.json` files.
6. Do another partial build into a scratch database → verify: the report
   shows no rule violations, and there are no unexpected "Superseded by"
   retirements compared with step 2.
7. Do **one** full rebuild, then `PLAN_missing_dates.md`.

## Assumptions & open questions

Decided:

1. A slot with no fitting ring JSON gets a placeholder ring JSON, and the
   number of placeholders is kept to a minimum (rule 5).

Open:

1. **Tolerance (to be double-checked by the user).** At ±0.05 mm,
   `M19061901`'s H12H13 slot (`169.5`) matches no geometry file. At ±0.1 mm
   it matches `HL-34/Ring-H12H13.yaml` (`169.6`) and shares that class's
   placeholder with the chain. The difference may be a rounding difference
   between helix geometry files, e.g. `_catia` variants. The tool takes
   `--tolerance`, and the default is set once this is settled.
2. **Placeholder name** (`RX_<family>_<slot>_<NN>`) and **material
   fallback** (`MA26021002`): to be confirmed.
3. **Ring manufacture dates are ignored when choosing rings.** Ring names
   encode 2020–2026 (`R2006…`, `R2104…`, `R2602…`), which look like JSON
   creation dates. Taking them literally would block every assignment. After
   `PLAN_import_json_dates.md` they trigger the "part made after magnet"
   warning at import. To be confirmed.
4. **Recording that assignments are inferred.** `magnet_parts` has no field
   for it. Options: a note in the ring JSON `description`, a
   `ring_assignments.md` log in `hifimagnet-projects`, or nothing.
   Placeholders are already marked by their name and description.
5. **Import side effect (checked in step 6).** When the importer reloads a
   magnet whose ring is held by a magnet still active at that point, it
   retires that holder ("Superseded by"). The `statuses` step that applies
   known dead/retired dates runs *after* the assemblies are loaded. Reusing a
   ring from a magnet that is retired or dead only through the statuses file
   could therefore create false retirements, as happened for `M19071101`. If
   step 6 shows any, the fix is a re-plan (tool preference or importer
   order), not a workaround.
