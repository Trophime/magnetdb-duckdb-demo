# Plan: SUPERVISION `bdd` data in file_viewer.py

Status: pending approval (not yet implemented)

**Goal.** For the selected file/experiment in `file_viewer.py`, show the
matching SUPERVISION `bdd` time-series (cooling temperatures + utility
channels) as a new "Supervision" sensor group alongside the existing
Pigbrother/Pupitre groups, time-sliced to the file's run window, reading from
`Data/bdd.csv` today in a way that's easy to swap for a live SUPERVISION DB
query later.

Scope note: an earlier version of this plan also surfaced the matching
`EXPERIENCES_LOG` session (user/HStart/HStop) in the file-stats banner, via a
`get_supervision_session()` join against the already-populated
`users`/`experiments` tables (`users.experiments_ids` is linked by
`update_experiments_ids` in `to_duckdb/demos/users_table_demo.py`, matching
housing + `[hstart, hstop]` against each experiment's file-embedded
timestamp — so no new EXPERIENCES_LOG parsing was ever needed for that part).
That part is **dropped for now** at the user's request; this plan covers only
the `bdd.csv` temperature/utility group. The `users`/`experiments` join
approach is worth revisiting later if the session banner is wanted again.

## Files affected

- **Create** `python_magnetrun/python_magnetrun/supervision-bdd-defs.json` —
  field defs for the `bdd` table/CSV, same `{description, symbol, unit}`
  shape as `pigbrother-defs.json` (no `aliases`):
  - `teb` / `tsb` / `ted` / `tsd` — temperature, °C (confirmed by current
    data range).
  - `res_lm1` / `res_r1` / `res_bypass` — cooling-water resistivity (magnet
    coolant circuit). `unit: null` for now — exact unit (kΩ·cm / MΩ·cm /
    µS/cm conductivity?) unconfirmed; fixable later via
    `field_defs.py update`.
  - `azote1` / `azote2` / `niv1` — meaning unconfirmed (nitrogen
    supply/level?); `unit: null` placeholder, same fix-later path.

- **Edit** `apps/dashboards/magnetdb/src/magnetdb_analysis.py` — add
  `load_supervision_bdd(start, end) -> pd.DataFrame`:
  - DuckDB-filtered read: `SELECT * FROM read_csv_auto(?) WHERE timestamp
    BETWEEN ? AND ?` against `Data/bdd.csv` — filters on read instead of
    loading the multi-million-row CSV fully into memory.
  - Path resolved from `MAGNETDB_SUPERVISION_BDD_CSV` env var, defaulting to
    `Data/bdd.csv` relative to the repo root (mirrors `DB_PATH`'s existing
    env-override pattern).
  - Adds a `t` column (seconds elapsed from `start`) so the existing
    timestamp/`t` x-axis toggle in `file_viewer.py` works unmodified.
  - Returns only columns that are both in `supervision-bdd-defs.json` and
    present in the CSV — tolerates the current 4-column file and the fuller
    schema once regenerated.
  - Cached via `functools.lru_cache`, matching the existing
    `get_group_dataframe` pattern.
  - Signature (`start, end -> DataFrame`) is source-agnostic: no file path
    or CSV-specific parameter reaches `file_viewer.py`, so swapping the CSV
    read for a live SUPERVISION MySQL query later (via `mysql_scanner`, as
    `mysql_connect.py` already does) only touches this one function's body.

- **Edit** `apps/dashboards/magnetdb/src/pages/file_viewer.py`:
  - `update_sensors_menus`: after the existing loop over
    `mrun.MagnetData.list_groups()`, append one more `html.Details` block for
    a synthetic `"Supervision"` group, whose checklist options are built from
    `field_defs.load_defs("supervision-bdd-defs.json")` (not from `mrun`).
  - `update_outputs`: special-case `group_name == "Supervision"` — build its
    `df` via `db.load_supervision_bdd(*mrun.MagnetData.get_time_range())`
    instead of `mrun.MagnetData.get_group_data(...)`, then call
    `plot.create_plot(df, ..., mrun=None, group_name="Supervision")`
    (`create_plot` already handles `mrun=None` gracefully — falls back to a
    generic y-axis label instead of unit-converting).
  - The style-editor gear icon still renders for the new block, but its
    modal stays empty (existing no-op fallback in `_style_context_fn` for
    any group not in `mrun.MagnetData.list_groups()`) — no crash, just no
    per-sensor styling for Supervision in this first pass.

## Approach summary

Dashboard-layer only (`apps/dashboards/...`), not touching the
`python_magnetrun` package's `MagnetData`/`DataType` machinery — reuses the
existing group/sensor-checklist/graph UI mechanism as-is, since the
callbacks already loop generically over `{type, index}` pattern-matched
components.

## Verification

1. `field_defs.load_defs("supervision-bdd-defs.json")` parses.
2. `load_supervision_bdd(start, end)` against real `Data/bdd.csv` for a known
   time window → correct rows/columns.
3. Run the dashboard, open `/file_viewer`, pick a file whose run window
   overlaps `bdd.csv`'s range (post-2026-06-18, since that's when the local
   export starts) → a "Supervision" group appears in the sensor picker and
   plots.
4. Pick a file with no time overlap → group still appears, plots empty, no
   crash.

## Assumptions & open questions

- `res_lm1` / `res_r1` / `res_bypass` unit still unconfirmed — confirm now if
  known, otherwise ships `null` and is fixable later via
  `field_defs.py update`.
- `azote1` / `azote2` / `niv1` meaning still unconfirmed, same treatment.
- Local `Data/bdd.csv` currently only has 4 columns (`teb`/`tsb`/`ted`/`tsd`);
  the loader is written to also work once the file is regenerated with the
  fuller 10-column schema.
- This reads the local CSV export, not a live SUPERVISION MySQL connection —
  no host/credentials exist anywhere in this repo/environment yet (see
  `to_duckdb/PLAN_users_multi_source.md`, Phase 2, still blocked).
