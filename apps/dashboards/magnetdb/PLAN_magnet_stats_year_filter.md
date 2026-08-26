# Magnet stats: Year filter (tabled)

Status: **tabled, not approved, not implemented** (discussed 2026-08-20).

## Original ask

Add Housing and Year selectors to the Magnet stats page
(`stage/dashboard/src/pages/magnet_stats.py`), matching the Housing/Year
filters already on Assembly stats (`stage/dashboard/src/pages/assembly_stats.py`).

## Decisions made during discussion

- **Housing selector dropped.** Only a Year selector is wanted on this page.
- **Summary line wording** ("Magnets: N selected of TOTAL", "Experiments: ...",
  etc.) is explicitly **out of scope** for this change — left for a separate
  discussion, do not touch `_build_page_content`'s summary logic as part of
  this.
- **Year-filter semantics for the Magnet dropdown** (the part that made this
  non-trivial): when a year is selected, the Magnet dropdown must list
  magnets that have been **part of an assembly whose commissioning window
  overlaps the selected year** — via the `assembly_magnets` link table —
  regardless of whether that magnet has any logged experiments that year.
  This is a structural/assembly-membership check, not a "magnet appears in
  `exp_run_scalars`-backed experiment rows for that year" check.

  This matters because deriving the Magnet dropdown purely from the
  already-loaded experiments dataframe (`load_data()`'s output, which joins
  from `experiments` through `assembly_magnets`) would silently drop magnets
  that were mounted during that year but have no experiment data yet —
  under-listing magnets rather than over-listing them.

## Sketched design (not implemented)

1. **New helper** in `stage/dashboard/src/magnetdb_analysis.py`, near
   `get_magnets_for_assembly`:

   ```python
   def get_magnets_for_assemblies(assembly_names, db_path=None):
       """Return the distinct magnets linked to any of the given assemblies."""
       with duckdb.connect(db_path or DB_PATH, read_only=True) as conn:
           query = "SELECT DISTINCT magnet_name FROM assembly_magnets WHERE assembly_name = ANY(?)"
           return conn.execute(query, [list(assembly_names)]).df()["magnet_name"].tolist()
   ```

2. **Layout**: add a Year `aggregate_filter` next to the existing Magnet
   filter in `layout()`.

3. **Callback `update_magnet_stats`**:
   - Add `Input("magnet-stats-year-filter", "value")` and
     `Output("magnet-stats-year-filter", "options")`.
   - Compute `assemblies_meta = db.load_assemblies_meta(selected_db)`,
     `assemblies_in_year` via `db.assemblies_active_in_year(...)`, and
     `year_options` via `db.assemblies_year_range(...)` — same pattern as
     `assembly_stats.py`.
   - **Magnet dropdown options**: when a year is selected, intersect
     `db.get_all_magnets(selected_db)` (for ordering) with
     `set(db.get_magnets_for_assemblies(assemblies_in_year, selected_db))`.
     Unfiltered (current behavior) when no year is selected.
   - **Chart/table data**: filter the experiments dataframe by
     `Assembly.isin(assemblies_in_year)` before applying the Magnet
     selection — same as before.
   - `_build_page_content` and the summary-line logic stay untouched.

## Why tabled

User said "no longer so sure if I want to do this" after the design above
was worked out — parked rather than abandoned. Pick this back up if asked to
revisit Magnet stats filtering.
