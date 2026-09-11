# Plan: SUPERVISION `bdd` data in file_viewer.py and overview_records.py

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
    `unit: "megaohm * centimeter"` (MΩ·cm, confirmed).
  - `azote1` / `azote2` — nitrogen pressure, `"group": "Nitrogen_Level"`,
    `symbol: "P"`, `unit: "bar"` (confirmed).
  - `niv1` — nitrogen level, `"group": "Nitrogen_Level"`, `symbol: "%"`,
    `unit: "percent"` (confirmed).

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

- Local `Data/bdd.csv` currently only has 4 columns (`teb`/`tsb`/`ted`/`tsd`);
  the loader is written to also work once the file is regenerated with the
  fuller 10-column schema.
- This reads the local CSV export, not a live SUPERVISION MySQL connection —
  no host/credentials exist anywhere in this repo/environment yet (see
  `to_duckdb/PLAN_users_multi_source.md`, Phase 2, still blocked).

---

## Plan addition: same groups in `overview_records.py`

`overview_records.py` is architecturally better-suited for this than
`file_viewer.py`. It already overlays multiple source files on one graph via
`plot.create_annotated_plot(files_data, ...)`, which loops over a list of
`{file, df, sensors, mrun}` entries and is already `mrun=None`-safe (every
`mrun_obj` use is `if mrun_obj and ...`-guarded) and already tolerates a
synthetic/unrecognized filename (`_resolve_file_style`'s docstring literally
says "or a synthetic/composite name" — falls back to Plotly's default color
cycling). So instead of file_viewer.py's "build two figures, merge traces"
trick, this just means **appending one more entry to the existing
`files_data` list** before the single, unmodified `create_annotated_plot`
call — no `magnetdb_plot.py` changes at all.

The other structural difference: groups here come from
`db.get_overview_group_entries(regular_files, housing)` — a
cross-format-matched `{group_name: [{"label", "value", "channels": {fmt:
{"group","channel"}}}]}` structure spanning every source file of the record,
not a single `mrun.MagnetData.list_groups()`. And the relevant time window is
the whole record's span (`info["t0"]`, `info["duration"]` from
`db.get_overview_record_sources`), not one file's.

### Files affected (in addition to file_viewer.py's)

- `python_magnetrun/python_magnetrun/supervision-bdd-defs.json` — **reused,
  no changes** (shared with the file_viewer.py plan above).

- `apps/dashboards/magnetdb/src/magnetdb_analysis.py` — **edit**, reusing
  `load_supervision_bdd`/`supervision_field_groups` from the file_viewer.py
  plan, plus two new functions specific to this page's data model (kept
  separate from `get_overview_group_entries`/`collect_group_files_data`
  rather than editing those directly — both have precise, already-documented
  contracts unrelated to supervision):
  - `merge_supervision_group_entries(group_entries) -> dict` — returns a copy
    of *group_entries* with `"Refroidissement"` extended (or created fresh,
    for records with no Pupitre source) and `"Water_Resistivity"`/
    `"Nitrogen_Level"` added, each new entry using a pseudo-format key
    `"supervision"` (`{"channels": {"supervision": {"group": group_name,
    "channel": field_key}}}`), value strings prefixed `"supervision:"` (same
    convention as the file_viewer.py plan).
  - `collect_supervision_files_data(group_name, selected_values,
    group_entries, start, end) -> list[dict]` — checks *group_entries* for
    selected values with a `"supervision"` channel; if any, returns one
    `files_data`-shaped entry (`{"file": "SUPERVISION", "df":
    load_supervision_bdd(start, end), "sensors": [...], "mrun": None,
    "native_group": group_name}`); `[]` otherwise.

- `apps/dashboards/magnetdb/src/pages/overview_records.py` — **edit**:
  - `update_groups`: after `group_entries = db.get_overview_group_entries(...)`,
    call `group_entries = db.merge_supervision_group_entries(group_entries)`
    before building the UI blocks — the extended dict is what's stored in
    `dcc.Store(id="overview-records-group-entries")` and reused by
    `update_graphs`.
  - `update_graphs`: alongside the existing `files_data =
    db.collect_group_files_data(...)`, fetch `info =
    db.get_overview_record_sources(selected_record, selected_db)`, compute
    the record's naive-UTC window (`t0 = info["t0"]`, `t1 = t0 +
    timedelta(seconds=info["duration"])`), and extend: `files_data +=
    db.collect_supervision_files_data(group_name, selected_values,
    group_entries, t0, t1)`. The existing `plot.create_annotated_plot(
    files_data, ...)` call is otherwise unchanged.
  - Style editor: left untouched — supervision curves stay non-stylable here
    too, matching the file_viewer.py plan's scope.

### Verification

1. `merge_supervision_group_entries` on a sample `group_entries` dict →
   `"Refroidissement"` gains supervision entries (or is created),
   `"Water_Resistivity"`/`"Nitrogen_Level"` appear.
2. Open an overview record whose `[t0, t0+duration]` overlaps `bdd.csv` →
   checking a supervision-tagged sensor in any of the three groups adds a
   trace to the existing graph, alongside native pupitre/pigbrother curves in
   "Refroidissement" when present.
3. Record with no time overlap → checkbox present, no trace added, no crash.

### Assumption shared with the file_viewer.py plan

Both plans query `bdd.csv` using the run/record's naive-UTC
`start_timestamp`/`t0` directly as the filter bounds, assuming `bdd.csv`'s
own `timestamp` column is also naive UTC (matching `python_magnetrun`'s
convention). If it's actually local Europe/Paris time instead, both
integrations would silently query the wrong window (off by 1–2h) rather than
error — worth a quick real-data check (compare a known session's local start
time against `bdd.csv` rows) before/during implementation.

---

## Future note: `defaults_spikes.py`

Not planned in detail yet — noted for eventual follow-up.
`apps/dashboards/magnetdb/src/pages/defaults_spikes.py` uses the same
`db.get_overview_group_entries` / `db.collect_group_files_data` /
`plot.create_annotated_plot` `group_entries`/`files_data` pattern as
`overview_records.py` (confirmed: same three calls, same shapes, in its own
`update_groups`/`update_graphs` callbacks). So the overview_records.py
approach above — `merge_supervision_group_entries` +
`collect_supervision_files_data`, appended to the existing `files_data` list
before the unmodified `create_annotated_plot` call — should carry over
directly, reusing the same two helper functions with no changes needed to
them. The one thing to re-check when this is actually planned: which time
window this page anchors incidents to (`_resolve_t0_reference`/
`_incident_x_range` suggest it may be keyed off a specific incident's
timestamp rather than the whole record's `[t0, t0+duration]` span used by
overview_records.py) — that determines what `start`/`end` to pass into
`load_supervision_bdd`.
