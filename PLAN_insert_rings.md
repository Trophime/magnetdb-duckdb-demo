# Plan: give rings to insert magnets that have none

Status: **done** (2026-10-29), option C for the fit; rings written to
`hifimagnet-projects` and checked on a rebuild. Remaining: step 7.
Prerequisite: [`PLAN_import_json_dates.md`](PLAN_import_json_dates.md)
(implemented in `195732c`, plus the addendum fix of 2026-10-29).
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

## Current state (`magnetdb-scratch` + JSON, 2026-10-29)

`magnetdb-scratch` (repo root) is a `--to statuses` build of the JSON after
the `R26021005` fix. It is the database the tool runs on.

- 8 insert magnets have no rings: `M09052601`, `M12082401`, `M15061601`,
  `M18110501`, `M19061901`, `M20022001`, `M22011801`, `M23072801`. That is
  102 slots: 13 per 14-helix magnet, plus 11 for `M15061601`.
- 66 ring JSON files. 55 rings are linked to magnets; 11 are not in the
  database.
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
  | M19071101 | 2019-07-11 → now (in stock) | ring holder |
  | M20092801 | 2020-09-28 → now | ring holder |
  | M23012001 | 2023-01-20 → now | ring holder |
  | M25012001 | 2025-01-20 → now (in stock) | ring holder |
  | M25032101 | 2025-03-21 → now | excluded holder (rule 7) |

- Fixed before this plan:
  - `R26021005` was linked to both `M19071101` and `M25012001`, which made
    the importer retire `M19071101` on 2025-01-20. `M25012001` now has
    `R26021031` (`hifimagnet-projects` `4a926d88`); `M19071101` is no longer
    retired in `magnetdb-scratch`.
  - Drawing `HL-27-042-D` did not exist; it is `HL-27-041-D` in the 4 ring
    JSONs `R26021014/028/040/047` and in 5 `Ring-*.yaml` files.
    `HR-21/Ring-H9H10.yaml` has `n: 24`, like `HL-34/Ring-H13H14.yaml`.
  - `HL-23/Ring-H5H6.yaml` drawing is `HL-27-035-A`.
- `R26021042`–`046` are held by both `M19020601` and `M20092801`. Their
  lifetimes do not overlap, so this is a valid reuse, not a violation.
- Known, left as is: `HL-23/Ring-H4H5.yaml` says `HL-27-304-A`, and six
  HL-23 ring files have a lower `n` than other families at the same radii.
  Neither affects ring choice.

## Rules

1. **Slot**: slot *i* is the gap between helix *i* and helix *i+1*, in rank
   order.
2. **Fit** (option C): a ring fits slot *i* when
   1. its geometry `r` equals helix *i*'s `r` followed by helix *i+1*'s `r`,
      each radius within **±0.1 mm**. Example: `Ring-H1H2`
      `[19.3, 24.2, 25.1, 30.7]` is H1 `[19.3, 24.2]` followed by H2
      `[25.1, 30.7]`. This works across design families, which matters
      because several targets mix HL-34, HL-31 and HR-21 helices; and
   2. its drawing matches the slot's drawing. The slot's drawings are the
      `cad` values of the `Ring-*.yaml` files closest to the required radii
      (smallest maximum deviation). The ring's drawing is its JSON
      `design_office_reference`, else its geometry's `cad`. Drawings are
      compared by number, without the revision letter (`HL-27-041-A` ≡
      `HL-27-041-D`). A slot or ring with no known drawing skips this check.

   HL-27 and HL-34 radii differ by exactly 0.1 mm on several helices, while
   their rings share drawings `HL-27-038` to `HL-27-041`; ±0.05 mm left 17
   slots with no fitting ring. Within ±0.1 mm the deviations found are 0 or
   0.1 mm; the next ones are 0.4 mm (HL-37 rings).
3. **Lifetime** of a magnet: from `assembled_at` to its first
   `retired`/`dead` event, or open-ended if there is none. Periods in stock
   are included, because a magnet in stock keeps its rings.
4. **Sharing**: ring R can go to target T only if T's lifetime does not
   overlap the lifetime of any other magnet holding R. That covers existing
   holders and targets given R earlier in the same run. An end date equal to
   the next start date counts as a handover and is allowed.

   **4b. Death is final** (user rule, 2026-10-29): when a magnet dies, all its
   parts die with it, rings included. So a ring cannot go to T if one of its
   magnets died on or before T's assembly, and a dead T cannot take a ring
   held by a magnet assembled on or after T's death. Placeholders follow the
   same rule. Lifetimes end at the *earliest* retired/dead event, so a false
   "Superseded" event logged before a known death cannot move the end.

   Found after the first `--write`: `M09052601` (dead 2024-12-06) had been
   given `R20061902`/`903`/`904`, still held by `M25012001` (assembled
   2025-01-20). The rebuild marked them dead inside `M25012001`. The write
   was reverted and the rule added.
5. **Minimal placeholders**: assignments are computed separately for each
   geometry class, i.e. each set of slots with the same candidate rings.
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
7. **Excluded holders**: rings held by `M25032101` (`R26021101`–`R26021113`)
   are never candidates, even when they fit and rule 4 allows them (user
   decision, 2026-10-29). Today they fit no slot within ±0.1 mm (they are
   0.4 mm off on H1H2–H6H7), so the rule is a safeguard. The report lists
   them as excluded, with the reason.

## Expected result (to be recomputed by the tool)

- **Geometry**: with rule 2, every one of the 102 slots has at least one
  fitting real ring. The 17 slots that only fit at 0.1 mm are H10H11 and
  H11H12 of `M09052601`, `M12082401` and `M18110501`; H11H12 and H12H13 of
  `M19061901`; and H11H12 to H13H14 of `M20022001`, `M22011801` and
  `M23072801`. They take HL-23 rings (`R26021010`–`013`, `024`–`027`,
  `036`–`039`, `043`–`046`) and, on H13H14, the free HL-27 rings
  `R26021014/028/040/047`.
- **Time**:
  - The M9 chain `M18110501` → `M19061901` → `M20022001` → `M22011801` →
    `M23072801` runs back to back, so one ring set can pass along it.
  - `M09052601` and `M12082401` overlap every holder except `M25012001`, and
    they overlap each other. They can only use the free rings and
    `M25012001`'s rings.
- **Placeholders** are only needed where targets that overlap in time
  compete for the same rings, e.g. `R26021036`/`037` are the only free
  candidates for H10H11/H11H12 of `M09052601` and `M12082401`. The report
  gives the final count.

## Placeholder ring JSON

Written to `hifimagnet-projects/magnetdb.json/`:

| Field | Value |
|---|---|
| `name` | `R<YYMMDD><NN>` with the creation date, like the other ring files (user decision, 2026-10-29), e.g. `R26102901`; the serial skips existing names. The importer reads 2026-10-29 from the name and warns that it differs from `manufactured_at` (one line per placeholder per rebuild). |
| `type` / `status` | `ring` / `in_stock`. The importer only links `in_stock` parts. |
| `geometry` | The closest matching `Ring-*.yaml`. Prefer the first target's design family folder; otherwise take the first match by path. |
| `design_office_reference` | The `cad` value in that yaml, e.g. `HL-27-029-G`. |
| `material` | Copied from a real ring of the same drawing if one exists; otherwise the most common ring material, `MA26021002` (CuCrZr, 55 of 66 rings). |
| `manufactured_at` | `assembled_at` of the first magnet it is assigned to, so it never triggers the "made after magnet" warning from `PLAN_import_json_dates.md`. |
| `description` | `"IA guessed: placeholder ring created by suggest_rings.py, no real ring known."` (marks them for now, user decision 2026-10-29) |

## Files affected

| File | Action | Change |
|---|---|---|
| `to_duckdb/suggest_rings.py` | create | CLI: `--db`, `--json-dir`, `[--magnet NAME]`, `[--tolerance MM]` (default 0.1), `[--write]`. Without `--write` it prints a read-only report covering each target and slot: the chosen ring or placeholder and why, the alternatives (each shown with its current magnets, e.g. `R26021010 [M19071101]`), slots left empty and why (no geometry file, or all candidates conflicting), excluded rings, each planned placeholder with the slots it fills, and existing rule violations. With `--write` it appends the chosen ring names, in slot order, to each target's `"parts"` list and creates the placeholder JSON files. Magnets that already have rings are skipped. `EXCLUDED_HOLDERS = ("M25032101",)` is a module constant. NumPy docstrings, PEP 8. |
| `to_duckdb/tests/test_suggest_rings.py` | create | Tests: radius fit within ±0.1 mm, rejected beyond; drawing match ignores the revision letter, a different drawing number is rejected; overlap, with handover allowed; in-stock period counted; overlapping targets never share a ring; a back-to-back chain can share; real rings used before placeholders; non-overlapping magnets share one placeholder; placeholder count equals the largest overlap (3 for three overlapping lifetimes, 1 for a chain); tie-break order; an excluded holder's ring is never chosen, even as the only fit, and is reported; candidates are shown with their current magnets; generated placeholder JSON has the fields above and parses; slot with no geometry file is reported and gets no placeholder; existing violation reported; `--write` inserts after the last helix, and running it twice changes nothing. |
| `to_duckdb/README.md` | edit | Document `suggest_rings.py`. |

The tool never writes to the database. `--write` edits only the target
magnet JSON files and adds the placeholder ring files.

## Order of work

Ring edits made after a full rebuild would need a second full rebuild, so
the order is:

1. ~~Implement `PLAN_import_json_dates.md`~~ (done, `195732c`; commissioning
   event dates fixed 2026-10-29).
2. ~~Quick partial build into a scratch database~~ (done: `magnetdb-scratch`,
   `--to statuses`, 2026-10-29).
3. ~~Write the tests, then `suggest_rings.py`~~ (done; full suite 628 after
   the importer and all-or-nothing fixes).
4. ~~Run the report on `magnetdb-scratch`~~ (approved by the user, rule 4b
   version: 81 real rings, 21 placeholders), kept in
   [`rings_report.txt`](rings_report.txt).
5. ~~Run `suggest_rings.py --write`~~ (done: additions only in the 8 magnet
   files, 21 `R261029xx.json`; a second run changes nothing).
6. ~~Partial build into a new scratch database~~ (`magnetdb-scratch-rings`):
   only inserts hold rings; every insert has helices − 1 rings; no ring of a
   dead magnet in a later magnet; no ring held by overlapping magnets; no new
   "Superseded by" event (two old false ones gone); all 58 assemblies loaded;
   no magnet without parts; no event dated at build time.
7. Commit in `hifimagnet-projects` (on request), then do **one** full
   rebuild, then `PLAN_missing_dates.md`.

## Assumptions & open questions

Decided:

1. A slot with no fitting ring JSON gets a placeholder ring JSON, and the
   number of placeholders is kept to a minimum (rule 5).
2. Fit uses option C: ±0.1 mm plus a drawing-number match (rule 2).
3. Rings of `M25032101` are excluded (rule 7).
4. Placeholder name `R<YYMMDD><NN>` with the creation date (`R261029NN`),
   description starting with "IA guessed", and material fallback
   `MA26021002`.
5. Ring manufacture dates are ignored when choosing rings. Ring names encode
   2020–2026 (`R2006…`, `R2104…`, `R2602…`), which look like JSON creation
   dates; taking them literally would block every assignment.
6. Nothing extra records that assignments are inferred. Placeholders are
   marked by their name and description, and git history records the change.
7. A dead magnet is the last holder of its rings (rule 4b).
8. Checks after each rebuild: only `insert` magnets hold rings; each insert
   has helices − 1 rings; no ring of a dead magnet is held by a later magnet;
   no ring is held by two magnets whose lifetimes overlap.
9. The importer applies known retirements/deaths from `magnet_status.json`
   when it reclaims reused parts (`assembly add --status-file`, see
   `to_duckdb/docs/schema.md`), so reuse no longer creates false
   "Superseded" events, and reusing a dead magnet's part fails the import.

Open:

1. **Import side effect (checked in step 6).** When the importer reloads a
   magnet whose ring is held by a magnet still active at that point, it
   retires that holder ("Superseded by"). The `statuses` step that applies
   known dead/retired dates runs *after* the assemblies are loaded. Reusing a
   ring from a magnet that is retired or dead only through the statuses file
   could therefore create false retirements, as happened for `M19071101`. If
   step 6 shows any, the fix is a re-plan (tool preference or importer
   order), not a workaround.
   **Resolved 2026-10-29**: step 6 showed one (`M09052601`, "Superseded by
   M25012001"); fixed in the importer (decided item 9). The same fix also
   removed the false "Superseded" events of `M9Bitters` and
   `M9Bitters-newBi09`.
