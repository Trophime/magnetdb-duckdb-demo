# Plan: SUPERVISION `bdd` data in file_viewer.py

Status: pending approval (not yet implemented)

**Goal.** Add a new `supervision-bdd-defs.json`, grouped like
`pupitre-defs.json` (via a `"group"` key):

- `teb` / `tsb` / `ted` / `tsd` → `"Refroidissement"` — merged into the
  existing Pupitre temperature/cooling group when the selected file has one,
  shown as its own fresh block when it doesn't (e.g. Pigbrother/`.tdms`
  files, which have no native temperature group at all).
- `res_lm1` / `res_r1` / `res_bypass` → new **`"Water_Resistivity"`** group.
- `azote1` / `azote2` / `niv1` → new **`"Nitrogen_Level"`** group.

All three sourced from `Data/bdd.csv`, time-sliced to the selected file's run
window ([`mrun.MagnetData.get_time_range()`]).

Scope note: an earlier version of this plan also surfaced the matching
`EXPERIENCES_LOG` session (user/HStart/HStop) in the file-stats banner, via a
`get_supervision_session()` join against the already-populated
`users`/`experiments` tables (`users.experiments_ids` is linked by
`update_experiments_ids` in `to_duckdb/demos/users_table_demo.py`). That part
is **dropped for now** at the user's request; this plan covers only the
`bdd.csv` groups above. Worth revisiting later if the session banner is
wanted again.

## Files affected

- **Create** `python_magnetrun/python_magnetrun/supervision-bdd-defs.json` —
  `{description, symbol, unit, group}` per field, same shape as
  `pigbrother-defs.json`/`pupitre-defs.json` (no `aliases`):
  - `teb` / `tsb` / `ted` / `tsd` — temperature, °C (confirmed by current
    data range), `"group": "Refroidissement"` — the same group name Pupitre
    already uses for its own cooling-loop temperatures.
  - `res_lm1` / `res_r1` / `res_bypass` — cooling-water resistivity (magnet
    coolant circuit), `"group": "Water_Resistivity"`, `symbol: "ρ"`,
    `unit: null` for now — exact unit (kΩ·cm / MΩ·cm / µS/cm conductivity?)
    unconfirmed; fixable later via `field_defs.py update`.
  - `azote1` / `azote2` / `niv1` — nitrogen supply/level channels,
    `"group": "Nitrogen_Level"`, `unit: null` — exact meaning/unit
    unconfirmed, same fix-later path.

- **Edit** `apps/dashboards/magnetdb/src/magnetdb_analysis.py` — add:
  - `load_supervision_bdd(start, end) -> pd.DataFrame` — DuckDB-filtered read
    of `Data/bdd.csv` (`SELECT * FROM read_csv_auto(?) WHERE timestamp
    BETWEEN ? AND ?`), path resolved from `MAGNETDB_SUPERVISION_BDD_CSV` env
    var (default `Data/bdd.csv` relative to the repo root, mirroring
    `DB_PATH`'s existing override pattern). Adds a `t` column (seconds
    elapsed from `start`) so the existing timestamp/`t` x-axis toggle works
    unmodified. Returns only columns that are both in
    `supervision-bdd-defs.json` and present in the CSV — tolerates the
    current 4-column file and the fuller schema once regenerated. Cached via
    `functools.lru_cache`, matching `get_group_dataframe`. Signature
    (`start, end -> DataFrame`) is source-agnostic, so swapping the CSV read
    for a live SUPERVISION MySQL query later only touches this function's
    body.
  - `supervision_field_groups() -> dict[str, list[str]]` — small helper
    mirroring `PandasMagnetData._build_groups`: reads
    `supervision-bdd-defs.json` once and returns `{group_name: [field_keys]}`
    (`{"Refroidissement": ["teb","tsb","ted","tsd"], "Water_Resistivity":
    [...], "Nitrogen_Level": [...]}`).

- **Edit** `apps/dashboards/magnetdb/src/pages/file_viewer.py`:
  - `update_sensors_menus`: for each group already in
    `mrun.MagnetData.list_groups()`, if its name matches a supervision group
    (currently only `"Refroidissement"`), append extra checklist options for
    that group's supervision fields, each tagged with a `"supervision:"`-
    prefixed value (e.g. `"supervision:teb"`) so it can't collide with a
    same-named native column, labeled distinctly (e.g. `"teb [SUPERVISION]
    (T [°C])"`). After the native-groups loop, append fresh blocks for any
    supervision group not already covered — `"Refroidissement"` when the
    file has no native cooling group, plus `"Water_Resistivity"` and
    `"Nitrogen_Level"`, which never have a native counterpart in either
    format.
  - `update_outputs`: for each group, split the checked sensor list by the
    `"supervision:"` prefix into native vs. supervision sensors.
    - If there are native sensors: build `fig = plot.create_plot(
      mrun.MagnetData.get_group_data(group_name), ..., mrun=mrun,
      group_name=group_name)` as today.
    - If there are supervision sensors: build `sup_fig = plot.create_plot(
      db.load_supervision_bdd(*mrun.MagnetData.get_time_range())[...], ...,
      mrun=None, group_name=group_name)`.
    - Merge with `fig.add_traces(sup_fig.data)` when both exist; use
      whichever one exists otherwise. **No changes to `plot.create_plot`
      itself** — it's called twice (once per data source) and the resulting
      traces are combined into one figure.
  - Style-editor gear icon: unchanged behavior — its modal stays empty for
    sensors not in `mrun.MagnetData.list_groups()`'s own columns (existing
    no-op fallback in `_style_context_fn`), so supervision-sourced curves
    aren't stylable in this first pass.

## Approach summary

The "merge into Refroidissement" happens at the **trace level** — combining
two independently-built Plotly figures — not by mutating `MagnetData`
itself. This matters because:

- Pupitre's `MagnetData` stores one flat DataFrame + a `Groups` dict of
  column-name lists (technically mergeable), but Pigbrother/TDMS's
  `MagnetData` stores `dict[group_name -> DataFrame]` and its
  `define_group`/`add_to_group` methods explicitly raise
  `NotImplementedError` — "TDMS groups are defined by the file format and
  cannot be modified." Reaching into its internals to fake a group would
  fight that guard directly.
- `load_mrun_object` is `functools.lru_cache`d, so mutating the returned
  `mrun` in place would leak into every other dashboard page that loads the
  same file — out of scope for a change requested only for `file_viewer.py`.

Building both figures via the existing, unmodified `plot.create_plot` and
combining their `.data` traces avoids both problems and works identically
for Pupitre and Pigbrother files.

## Verification

1. `supervision_field_groups()` returns the three expected groups with the
   right fields.
2. Open a Pupitre file whose run window overlaps `bdd.csv`'s range (post-
   2026-06-18) → "Refroidissement" block shows both native (Tin1/Tout/
   teb/tsb…) and `[SUPERVISION]`-labeled curves, checkable together and
   plotted on one shared graph.
3. Open a Pigbrother (`.tdms`) file with the same window → "Refroidissement"
   block appears fresh, supervision-only.
4. "Water_Resistivity" and "Nitrogen_Level" blocks appear for any file type,
   supervision-only.
5. File with no `bdd.csv` time overlap → blocks still appear, checking a
   sensor just plots empty, no crash.

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
