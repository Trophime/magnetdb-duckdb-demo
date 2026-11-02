# Plan: rebuildable magnet geometry (check, warning, dashboard colour)

Status: **implemented** (2026-11-02); the dashboard look awaits the user's
check (step 5).

## Goal

A magnet's geometry is never stored: it is rebuilt from its parts'
`geometry_data` (and an assembly's from its magnets plus the
`assembly_magnets` offsets), as the hoop-stress code already does. Whether
that rebuild works is checked:

- when a magnet is added (warning, the magnet is still loaded);
- when a part's geometry is edited (refused if it breaks a magnet that
  rebuilds today);
- by `check --entity magnet`.

The outcome is stored in `magnets.geometry_problem`, and the dashboard shows
those magnets in light red. On `to_duckdb/magnetdb-2026-10-29.duckdb`,
`check` then reports 0 problems.

## Why

- `check` still treats a NULL `magnets.geometry_data` as a problem, and
  `check --fix` would write it. Every magnet fails the check (23 of 23 in the
  2026-10-29 build), so `check` cannot stop a setup script.
- `magnets.geometry_data` and assembly geometry stay unset by design: see
  `to_duckdb/NOTES_hoop_stress_implementation.md` and the docstrings of
  `stress_map.geometry_config_to_yaml` / `prepare_geometry_directory`.
  This settles ROADMAP open question Q2 (A11 follow-up 5 vs A13) in favour
  of A13.
- Today a magnet that cannot be rebuilt is only found during the hoop-stress
  run. A CLI warning alone is easily missed (the 2026-10-29 build printed
  "Check database consistency … FAILED" and exited 0), hence the dashboard
  colour.

## Decisions

1. **Warn on add, don't refuse.** A magnet is a real object with a history
   (assemblies, experiments, statuses) that does not need its geometry. With
   all-or-nothing loading, refusing would drop the whole assembly file.
   Geometry may also be known later than the physical facts.
2. **Refuse a breaking `part update`.** If a `geometry_data` change makes a
   magnet that rebuilt before fail, the update is refused: it is a
   deliberate edit, nothing else is lost, and it protects a working magnet.
3. **Report in `check`.** It catches data loaded before this change, or a
   python_magnetgeo upgrade that changes what builds. `--fix` refreshes the
   stored result; nothing else is filled.
4. **Store the result, not the geometry.** The dashboard does not depend on
   `to_duckdb` and opens the DB read-only, so it reads a stored status
   instead of rebuilding. Only three things change the result: `magnet add`,
   `part update` of `geometry_data`, a python_magnetgeo upgrade (covered by
   `check --fix`).
5. **Colour** `#f8d7da` (light red), distinct from the amber `#fff3cd`
   planned for missing dates in `PLAN_missing_dates.md`.
6. **Hoop stress needs no change.** `compute_hoop_stats.py:787-795` already
   catches a geometry failure per assembly, prints
   `[ERROR] geometry prep for '<assembly>': Part '<part>' has no geometry_data …`
   and moves on.

Checked on the 2026-10-29 DB (read-only): all 23 magnets rebuild with the
existing `checks._rebuild_magnet_assembly`, about 0.02 s each after a one-off
0.8 s python_magnetgeo import.

## Files affected

| File | Action | Change |
|---|---|---|
| `to_duckdb/magnet_geometry.py` | create | `rebuild_magnet_geometry(con, name, type)`, moved from `checks._rebuild_magnet_assembly`; silences python_magnetgeo's INFO and bore-WARNING logging during the rebuild. `geometry_problem(con, name) -> str \| None`. `refresh_geometry_problem(con, name)`: stores the result and appends an `operation_log` row when it changes. NumPy docstrings. |
| `to_duckdb/schema.py` | edit | `magnets.geometry_problem VARCHAR` (NULL = OK), plus an `ADD COLUMN IF NOT EXISTS` migration. |
| `to_duckdb/checks.py` | edit | `check_magnets`: drop the `geometry_data` check and the reconstruct-on-`--fix`; add a fresh rebuild (failure = problem) and a stale-stored-value problem; `--fix` refreshes the stored value. Delete `_rebuild_magnet_assembly` and any import only it used. |
| `to_duckdb/magnetdb.py` | edit | `_write_magnet` refreshes `geometry_problem` after linking the parts and prints `[WARN]` when set (the magnet is still loaded). `cmd_check` runs `ensure_schema` with `--fix`. Help texts of `check` and `--fix`. |
| `to_duckdb/crud.py` | edit | `_apply_update` gets an optional `after_write(con)` hook run inside its transaction. `update_part_from_json` uses it when `geometry_data` changes: rebuild each magnet holding the part; raise (rollback, nothing written) if a magnet that rebuilt before no longer does; otherwise refresh their `geometry_problem`. |
| `to_duckdb/tests/test_magnet_geometry.py` | create | Rebuild OK; part without `geometry_data` → problem; refresh stores the result and logs once. |
| `to_duckdb/tests/test_checks.py` | edit | Change the 4 magnet-geometry tests (lines 91–131) and the docstring at line 354: NULL `geometry_data` is OK. Add tests for the rebuild problem, the stale stored value, and `--fix` refreshing it. |
| `to_duckdb/tests/test_add_magnet.py` | edit | A magnet whose part lacks `geometry_data` loads, gets `geometry_problem` set and a warning. |
| `to_duckdb/tests/test_crud.py` | edit | A `part update` that breaks a working magnet is refused with nothing written; one that repairs a broken magnet clears its `geometry_problem`. |
| `apps/dashboards/magnetdb/src/magnetdb_analysis.py` | edit | `get_magnets_for_assembly` returns `geometry_problem` (None when an older DB lacks the column). New `get_geometry_problem(name, db_path)`. |
| `apps/dashboards/magnetdb/src/dash_selectors.py` | edit | `magnets_table_section` (used by the Assembly, Stats viewer, File viewer and Overview records pages): Magnet cell in `#f8d7da` with the error as a hover tooltip. |
| `apps/dashboards/magnetdb/src/pages/magnet_stats.py` | edit | A light red note under the magnet selector when the selected magnet has a problem. |
| `apps/dashboards/magnetdb/tests/dash_selectors_test.py` | edit | Style rule and tooltip present only for a magnet with a problem. |
| `to_duckdb/README.md`, `to_duckdb/docs/schema.md`, `to_duckdb/docs/loading.md` | edit | The rule (geometry rebuilt from parts, never stored), the new column, the `check` / `magnet add` / `part update` behaviour. |
| `ROADMAP.md`, `PLAN_update_impact_tracking.md` | edit | Q2 resolved; follow-up 5 dropped. |
| `PLAN_magnet_geometry_check.md` | edit | This plan: status kept up to date. |
| memory | create | Project memory recording the rule. |

## Approach / verification

1. Baseline → verify: `to_duckdb` pytest passes (628) and the dashboard
   tests pass.
2. Write the `to_duckdb` tests → verify: the new and changed tests fail.
3. `magnet_geometry.py` and the schema change, then `checks.py`,
   `magnetdb.py`, `crud.py` → verify: all `to_duckdb` tests pass.
4. On a scratchpad copy of `magnetdb-2026-10-29.duckdb` (the real DB is not
   touched):
   - `check --entity magnet` (column not there yet) → verify: 23 OK;
   - `check --fix` → verify: column added, all NULL;
   - `check` → verify: 282 OK, exit 0;
   - `part update` setting one part's `geometry_data` to NULL → verify:
     refused, nothing changed.
5. Dashboard test, then dashboard code → verify: dashboard tests pass; start
   the app on a copy where one magnet has `geometry_problem` set, and the
   user confirms the red cell and the note.
6. Docs, ROADMAP, this plan, memory → verify: `magnetdb.py check --help`
   reads correctly.

### Results (2026-11-02)

1. Baseline: `to_duckdb` 628 passed; dashboard 149 passed + 1 collection
   error already there (`tests/mrun_test.py` looks for its `.tdms` file
   relative to the working directory).
2. The new tests failed (no `magnet_geometry` module, no column).
3. `to_duckdb`: 639 passed.
4. On a scratchpad copy of `magnetdb-2026-10-29.duckdb`:
   - `check --entity magnet` before the column: 23 OK, exit 0;
   - `check --entity magnet --fix`: column added, 0 stored problems,
     `magnets.geometry_data` still unset;
   - `check --entity part|magnet|assembly`: 201 + 23 + 58 = 282 OK. The full
     `check` was not run: its experiment/operationaldata file checks read
     the rclone data mount, which was failing (`Input/output error`);
   - `part update` giving `H08060601` a broken geometry: refused, exit 1
     (`breaks magnet 'M09052601' ('Helix' object has no attribute 'odd')`),
     part and `operation_log` unchanged.
5. Dashboard: 151 passed + the same collection error.
   `get_magnets_for_assembly` / `get_geometry_problem` read NULL on a DB
   without the column and the stored error on a copy where
   `M9Bitters-newBi10` has one. Visual check in the running app: pending.
6. Docs, ROADMAP (Q2 resolved, A11 #5 dropped), impact plan follow-up 5,
   memory.

Deviations from the file list above:

- `magnetdb.py cmd_part_update` also runs `ensure_schema` (not on a dry
  run), so an older DB gets the column before the rebuild stores into it.
- `schema.py`: only the `ADD COLUMN IF NOT EXISTS` migration, as for the
  other `magnets` columns added after the table.
- `PLAN_update_impact_tracking.md` follow-up 3 names the moved function.
- python_magnetgeo checks more than object construction: an `Insert`
  refuses a ring count ≠ helices − 1, and a malformed part raises
  `AttributeError`, so `geometry_problem` catches any exception.

## Assumptions & open questions

- **Out of scope (A13):** `magnets.geometry_data` stays in the schema, and
  `magnet add --geometry` still writes it. Nothing reads it.
- **`part update --dry-run`** does not run the rebuild check; only the real
  write does.
- **Magnets loaded by an older version** have a NULL `geometry_problem`
  until `check --fix`, so the dashboard shows them as OK: run
  `check --fix` once on existing DBs. The next full rebuild fills it
  directly.
- **Cost:** about 0.8 s once per process that adds a magnet (python_magnetgeo
  import), then about 0.02 s per magnet.
- **Magnet page:** a note rather than coloured dropdown entries, which would
  change the options from strings to objects for every caller.
