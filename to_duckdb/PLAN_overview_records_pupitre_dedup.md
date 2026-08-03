# Plan — overview_records pupitre-duplicate merge, done as a sweep in overview-records-infer

Status: pending approval (not yet implemented)

## Goal

When two `overview_records` rows of the same `housing` + `site_name` share a
`sources_pupitre` file, consolidate them into one row. The merge runs **only**
as a dedicated, table-wide sweep inside `populate overview-records-infer`
(after `housing`/`t0`/`site_name`/`duration`/`teb`/`bp` are resolved) — never
at insert time, and never based on `housing` alone. The absorbed row is
tombstoned (`merged_into = <survivor filename>`), never deleted, so a later
`populate overview-records` re-run of the same raw file cannot resurrect it
and get double-counted into the survivor again. A row is "live" iff
`merged_into IS NULL`; no separate boolean flag is needed.

Context / history that led here (see conversation, no separate doc):

- An earlier iteration implemented this merge *inline*, inside
  `insert_overview_record` / `upsert_overview_record` /
  `insert_overview_record_from_dict`, scoped by `housing` alone (because
  `site_name` is frequently `NULL` at insert time), and physically `DELETE`d
  the absorbed row. That version is already merged into `crud.py` and must be
  **reverted** as part of this plan.
- Moving the merge to `overview-records-infer` removes the `housing`-only
  limitation for free, since `site_name` is always resolved by the time the
  sweep runs there.
- Deleting the absorbed row broke the "does this filename already exist"
  idempotency check that `populate overview-records` relies on to avoid
  reprocessing files — a merged-away file would silently come back on the
  next run and get merged (and double-counted) again. The `merged_into`
  tombstone fixes this by keeping the row (and its filename) in place.
- `populate overview-records` was separately made independent of
  `operationaldata` (done, already implemented) — it now discovers Overview
  files by scanning the filesystem directly via
  `find_and_register_tdms(..., dry_run=True, type_filter=["Overview"])`,
  mirroring `cmd_populate_experiments`'s existing pattern. That work is
  unaffected by this plan.
- Intended workflow once this plan lands:
  ```
  populate overview-records          # ingest raw files, one row each, no merge
  populate overview-records-infer    # resolve fields, then sweep + merge duplicates
  ```

## Files affected

- `to_duckdb/schema.py` — edit: add a `merged_into VARCHAR` column (nullable,
  no `REFERENCES` constraint) to `overview_records`, with an idempotent
  `ALTER TABLE overview_records ADD COLUMN IF NOT EXISTS ...` migration
  matching the existing pattern used for `site_name`/`plateaux`. `NULL` means
  live; non-`NULL` holds the surviving filename this row was merged into —
  no separate `skipped` boolean.
- `to_duckdb/crud.py` — edit:
  - Revert `insert_overview_record`, `upsert_overview_record`,
    `insert_overview_record_from_dict` to plain exact-filename skip/replace
    writes — remove all calls into the sibling-search/merge machinery.
  - Remove (or repurpose) `_find_pupitre_sibling`, `_write_overview_record_row`,
    `_execute_overview_record_write`, `_overview_record_to_columns` — these
    were built for the insert-time version; keep `_merge_overview_rows`'s
    *math* (union+dedupe source lists, summed duration, duration-weighted
    teb/bp, dict-merged JSON columns) but re-home it under the new sweep.
  - Add `merge_duplicate_pupitre_records(con, verbose=True) -> dict` — the
    standalone sweep (see Approach).
  - Update `view_overview_records` to exclude rows where
    `merged_into IS NOT NULL` by default.
- `to_duckdb/magnetdb.py` — edit: `cmd_populate_overview_records_infer` calls
  `merge_duplicate_pupitre_records` once, unconditionally, after its existing
  per-row field-resolution loop; prints a merge summary.
- `to_duckdb/demos/users_table_demo.py` — edit: `update_overview_records_ids`'s
  query (~line 715) adds an `AND o.merged_into IS NULL` condition so a
  tombstoned row's filename never lands in `users.overview_records_ids`.
- `to_duckdb/tests/test_crud.py` — edit: remove/replace the 5 tests written
  for the insert-time merge version (`test_insert_overview_record_from_dict_*`
  merge tests) since that code path is reverted; add new tests for
  `merge_duplicate_pupitre_records` and for `view_overview_records`'s
  `merged_into` exclusion.
- `to_duckdb/tests/test_magnetdb.py` or `test_populate.py` — add coverage for
  the sweep being invoked from `overview-records-infer` (if practically
  testable without real TDMS files/`python_magnetrun`).

## Approach

1. **Schema**: add `merged_into` (`VARCHAR`, nullable, no `REFERENCES`
   constraint — a tombstoned row may get re-pointed if its survivor itself
   later gets absorbed, see step 3) to `overview_records`. `merged_into IS NULL`
   *is* the "live" signal — no separate boolean column.

2. **Revert insert-time merge**: `insert_overview_record`, `upsert_overview_record`,
   `insert_overview_record_from_dict` go back to a plain "does this exact
   filename exist → skip" / "INSERT OR REPLACE" write, with **no** cross-row
   sibling search. `populate overview-records` and
   `populate overview-records-from-json` become pure ingestion: one row per
   source file/record, no merging, no deletions.

3. **Standalone sweep** — new `merge_duplicate_pupitre_records(con, verbose=True) -> dict`
   in `crud.py`:
   - Selects all rows `WHERE merged_into IS NULL`, grouped by
     `(housing, site_name)`. Rows with `site_name IS NULL` form their own
     `(housing, NULL)` group — they can still dedupe against each other, but
     never against a row that already has a resolved `site_name` (open
     question below).
   - Within each group, repeatedly find any pair sharing at least one
     `sources_pupitre` entry (both with `merged_into IS NULL`) and merge them:
     - The row with the **lower `t0`** is the survivor and is updated
       **in place** (`UPDATE`, never a different primary key) with: unioned
       + de-duplicated `sources_*` lists, summed `duration`, duration-weighted
       `teb`/`bp`, and dict-merged JSON columns (lower-`t0` wins on key
       conflicts) — reusing `_merge_overview_rows`'s existing math.
     - The higher-`t0` row is tombstoned: `merged_into = <survivor filename>`.
       Its own columns are left untouched otherwise (audit trail of what it
       originally contained).
   - Repeats within each group until no more pairs are found (handles chains:
     if A–B share a file and B–C share a *different* file, merging B into A
     makes A a match for C too). When a survivor that already has other rows
     pointing `merged_into` at it gets absorbed into a third row, **flatten**
     those pointers to the new final survivor rather than leaving a multi-hop
     chain — so `merged_into` is always exactly one hop from any tombstoned
     row to the current live row.
   - Returns a summary dict (counts of groups checked / merges performed) for
     the CLI to print.

4. **Wire into `overview-records-infer`**: `cmd_populate_overview_records_infer`
   calls the sweep once at the end of every invocation (independent of its
   existing `site_name IS NULL` / `--reprocess` row-selection, which only
   governs the field-resolution part).

5. **Patch the two known readers**:
   - `view_overview_records` — add `AND ovr.merged_into IS NULL` to its
     default query.
   - `update_overview_records_ids` — add `AND o.merged_into IS NULL` to its
     housing + time-range join.

## Verification

1. New sweep tests (`merge_duplicate_pupitre_records`):
   - Two rows, same `(housing, site_name)`, share a pupitre file → lower-`t0`
     row updated with merged fields; higher-`t0` row now has
     `merged_into = <lower's filename>`; both rows still physically present
     in the table.
   - Different `housing` or different `site_name` → no merge.
   - No shared `sources_pupitre` entry → no merge.
   - Three-way chain (A–B share file1, B–C share file2, A and C share
     nothing directly) → all three consolidate onto one surviving filename;
     `merged_into` pointers are single-hop to that survivor, not chained.
   - Running the sweep a second time with no new data → no further changes
     (idempotent).
   - A row with `merged_into IS NOT NULL` is never re-examined as a merge
     candidate.
2. `view_overview_records` test: a row with `merged_into IS NOT NULL` is
   absent from the printed listing.
3. `update_overview_records_ids` test: a row with `merged_into IS NOT NULL`
   never appears in any `users.overview_records_ids` array.
4. Full existing test suite re-run — confirm no regressions, including the
   5 insert-time-merge tests being cleanly removed/replaced rather than left
   dangling on reverted code.
5. Manual: `populate overview-records` (ingest only, confirm two rows with a
   shared pupitre file both land as separate rows with `merged_into IS NULL`)
   → `populate overview-records-infer` (confirm they merge, one gets
   `merged_into` set) → re-run `populate overview-records` again (confirm the
   tombstoned file is *not* reprocessed/resurrected, since its filename still
   exists) → re-run `populate overview-records-infer` again (confirm no
   further change, i.e. no double-counted duration).

## Assumptions & open questions

- **`site_name IS NULL` rows**: the plan above dedupes them only against each
  other (grouped under `(housing, NULL)`), never against a row that already
  has a resolved `site_name` for that housing — since two truly-duplicate
  rows should end up with the *same* site_name once both are resolved, and
  merging before resolution risks conflating rows from different site eras of
  the same housing. Flag if you'd rather have unresolved rows wait entirely
  (excluded from the sweep) until `site_name` is set.
- **`view_overview_records`** always excludes rows with `merged_into IS NOT NULL`
  with no way to see them from the CLI — flag if an explicit
  `--show-merged`/audit mode is wanted instead of a hard exclusion.
- **`merged_into` has no FK constraint** — deliberate, since a survivor can
  itself later become a tombstoned row (chain flattening in step 3), which
  would otherwise require constantly re-validating/updating the constraint.
- No separate `skipped` boolean: `merged_into IS NULL` is the sole "is this
  row live" signal, and `merged_into`'s value (when set) also gives the
  survivor's filename directly — one column instead of two redundant ones.
- Out of scope for this plan (previously discussed, not yet decided/approved
  separately): the `check_sites` overlapping-commissioned-window check, and
  the `_resolve_site_names`/`--all` alphabetical-order attribution edge case
  for sites sharing a housing with overlapping windows.
- This plan does not change `cmd_populate_overview_records_infer`'s existing
  default row-selection (`site_name IS NULL` unless `--reprocess`) for the
  *field-resolution* half of that command — only adds the merge sweep as an
  unconditional extra step at the end of every invocation.
