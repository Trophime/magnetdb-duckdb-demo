# Overview/Archive viewer page

Status: **implemented** (drafted 2026-11-03).

## Original ask

Create a dashboard page that behaves like File viewer
(`apps/dashboards/magnetdb/src/pages/file_viewer.py`) but for `operationaldata`
files of type `Overview` or `Archive`. Besides the type selector, use the same
filters as File viewer.

## Goal

A new `/operational_viewer` page that mirrors File viewer (same filters, same
plotting/analysis features) but lists an assembly's Overview/Archive files from
the `operationaldata` table.

## Findings

- `pages/stats_viewer.py` is already a File viewer copy (`sv-` id prefix, its
  own file lookup, no SUPERVISION/Hybrid overlays) — precedent for this page.
- The dashboard does not read `operationaldata` anywhere yet.
- `magnetdb-2026-10-08.duckdb`: 3339 Overview rows (48 assemblies), 6624
  Archive rows (54 assemblies). `file` holds relative paths, e.g.
  `pbsurv/M9/Overview/M9_Overview_200528-1145.tdms`.
- Basenames are unique across Overview+Archive; every row has an
  `assembly_name`.
- `load_mrun_object` already basenames its input and resolves the
  `Fichiers_Archive` directory, so no loader change is needed.

## Files affected

| File | Action |
|---|---|
| `apps/dashboards/magnetdb/src/magnetdb_analysis.py` | edit — add `get_operational_files_for_assembly(assembly_name, types, db_path=None)` |
| `apps/dashboards/magnetdb/src/pages/operational_viewer.py` | create |
| `apps/dashboards/magnetdb/tests/operational_viewer_test.py` | create |

## Page layout (top to bottom)

1. **Filter row**:
   - Housing, Year, Status — copied from File viewer, same options and same
     semantics (housing prefix, assemblies active in the year, assembly
     status).
   - **Type** — new checklist, `Overview` / `Archive`, both checked by default.
2. Assembly dropdown, narrowed by Housing/Year/Status as in File viewer.
3. Magnets table.
4. File dropdown: the assembly's `operationaldata` files of the checked types,
   newest first, shown as basenames.
5. Rest of File viewer unchanged: file stats banner, Field histogram, x-axis
   choice, sensor groups with SUPERVISION overlay, zoom sync, cursors,
   downsampling, style editor, CSV download, `?assembly=&file=` query params.
   The Hybrid `I_BOB` option is dropped (Pupitre-only lookup).

## Approach (test-first)

1. Write tests → verify: they fail before implementation.
   - The lookup helper, against a temporary DuckDB: type filtering, basename
     output, timestamp order.
   - The file-dropdown callback for Type = Overview / Archive / both / none
     (none → empty list).
   - The assembly callback: Housing filter narrows assemblies.
2. Add the helper to `magnetdb_analysis.py` → verify: helper tests pass.
   - `SELECT DISTINCT file FROM operationaldata WHERE assembly_name = ? AND
     type IN (...)`, basenamed, sorted with the same key as
     `get_files_for_assembly`.
   - NumPy-style docstring.
3. Create `operational_viewer.py` from `file_viewer.py` → verify: callback tests
   pass.
   - `opv-` prefix on every id.
   - `order=10`.
   - Type checklist in the filter row, wired as an input to the file-dropdown
     callback.
   - Hybrid code removed.
4. Run the full dashboard suite from `apps/dashboards/magnetdb`:
   `.venv/bin/python -m pytest tests --ignore=tests/mrun_test.py` → verify:
   the 159 existing tests plus the new ones pass.
5. Smoke test on `magnetdb-2026-10-08.duckdb` → verify each of:
   - Housing = M9 plus a Year narrows the assembly list.
   - Switching Type changes the file list.
   - Loading one Overview and one Archive file shows the sensor groups and
     plots the Field curve.

   Needs the records mount; if rclone stalls, report it rather than skip.

## Assumptions & open questions

- One page with a Type selector, not two separate pages.
- The SUPERVISION overlay is kept, as in File viewer.
- Archive files are about 50× larger than Overview (test pair: 33 MB vs
  0.6 MB), so LTTB stays the default; "raw data" may be slow on Archive.
- No `.po` translation entries (same as `stats_viewer`); untranslated strings
  fall back to English.
