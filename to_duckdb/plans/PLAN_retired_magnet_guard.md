# Plan: guard against retired magnets and part-ID collisions

**Status:** awaiting approval

## Goal

`assembly add` refuses to link a `retired` or `dead` magnet to an assembly,
and writes nothing when it refuses. Optionally (part B), `magnet add` also
refuses a part ID that already exists in the DB with a different
`design_office_reference`.

## Background

Two different physical rings were given the same ID, `R26021005`, in
`~/github/hifimagnet-projects/magnetdb.json/`:

| File | Design ref |
|---|---|
| `M19071101.json` | HL-27-033-C |
| `M25012001.json` | HL-27-033-D |

When the build added M25012001, `_reclaim_reused_parts`
(`crud.py:842`) assumed the ring had been moved to the new magnet. It
retired M19071101 ("Superseded by magnet 'M25012001'", backdated to
2025-01-20). Nothing then stopped later assemblies from using the retired
magnet: M10_A250429_00, M10_A251112_00, M9_A260505_00 and M10_A260626_00
all link M19071101.

The source data has been fixed: the D ring in `M25012001.json` is now
`R26021031`, and `R26021005.json` describes the C ring. The DB has not been
rebuilt yet. This plan adds the code checks that would have caught the
problem.

## Data findings

- **Where retirements come from during a build.** During `assembly add`,
  the only source is `_reclaim_reused_parts`. The statuses in
  `magnet_status.json` are applied after every `assembly add`
  (`scripts/build_from_scratch.sh:261`), so they never trigger the guard.
- **Impact on the current data** (`magnetdb-2026-10-08.duckdb`). M19071101
  is the only retired or dead magnet linked to assemblies dated after its
  retirement. The JSON fix removes that case, so the guard should not block
  a clean rebuild.
- **Part design refs.** After the fix, no part ID in any `M*.json` has
  conflicting design refs, so part B is also safe to turn on.

## Files affected

| Path | Action |
|---|---|
| `to_duckdb/crud.py` | edit |
| `to_duckdb/magnetdb.py` | edit |
| `to_duckdb/tests/test_crud.py` | edit |
| `to_duckdb/tests/test_add_assembly.py` | edit |
| `to_duckdb/tests/test_add_magnet.py` | edit (part B only) |

## Approach

Tests are written first.

1. **Write the failing tests.**
   - In `test_crud.py`, `insert_assembly_magnets` raises `ValueError` for a
     magnet that is `retired` and for one that is `dead`.
     - The message names the magnet, its status, and the reason from its
       last status-history entry (e.g. "Superseded by magnet 'M25012001'").
     - With `[MAG_OK, MAG_RETIRED]`, zero rows are inserted, because the
       check runs before any insert.
     - Re-adding a retired magnet that is already linked to that same
       assembly is still skipped silently, so re-adding an existing
       assembly keeps working.
   - In `test_add_assembly.py`, `assembly add` with a retired magnet exits
     with code 1 and writes nothing:
     - no `assemblies` row is created;
     - the open assembly already in that housing is not auto-closed;
     - `--dry-run` reports the same error.
   - Part B, in `test_add_magnet.py`: `magnet add` with a part that already
     exists under a different `design_office_reference` exits with code 1.
     It writes nothing, and the magnet currently holding that part is not
     retired.

   → verify: run the full suite before writing the tests (all pass), then
   after (only the new tests fail).

2. **Shared check in `crud.py`.**
   - Add a public helper,
     `retired_magnet_errors(con, assembly_name, magnet_entries) -> list[str]`,
     with a NumPy docstring. It skips magnets already linked to
     *assembly_name*.
   - `_insert_assembly_magnets` calls it before its loop and raises if
     anything comes back.
   - Update the `insert_assembly_magnets` docstring to match.

   → verify: the new `test_crud.py` tests pass.

3. **Pre-check in `_add_assembly`** (`magnetdb.py:587`).
   - Use a read-only connection, placed after `_ensure_magnets` (loading a
     new magnet can retire another one) and before the dry-run return.
   - It prints the errors plus "Nothing written." and exits with code 1,
     the same way the existing conflict check does.
   - The pre-check is needed because `insert_assembly` runs first and can
     auto-close the previous assembly in the same housing. An error raised
     only inside crud would leave that change behind.

   → verify: the new `test_add_assembly.py` tests pass.

4. **Part B: add `_part_conflicts(con, parts)` in `magnetdb.py`.**
   - It sits next to `_magnet_conflicts` in `_add_magnet`, read-only,
     before any write.
   - It flags an existing part whose design ref and the JSON's are both set
     but differ, using an exact string comparison.

   → verify: the new `test_add_magnet.py` test passes.

5. **Full suite.** Run `.venv/bin/python -m pytest` from `to_duckdb/`.

   → verify: everything passes, including the two existing reuse tests
   (`test_crud.py:357-412`). Their behaviour does not change.

## Assumptions and open questions

- **Status rule or date rule.** The recommendation is to reject based on
  the magnet's current status, regardless of the assembly's date. "Later"
  could also mean comparing the assembly's `commissioned_at` with the
  retirement date, which would allow an older assembly to be backfilled
  after the magnet's retirement. The build adds assemblies in date order,
  so the simpler status rule gives the same result there.
- **`dead` magnets** are treated the same as `retired`.
- **Part B in or out, and reject or warn.** The recommendation is to
  include it and reject.
- **Out of scope:** `_reclaim_reused_parts` itself does not change. Genuine
  part reuse, like M23072801's shared helices, still retires the previous
  magnet.
