# Draft Plan: Display Incident-File Data on the Defaults & Spikes Page

**Goal:** When a Default/Spike incident is selected on the Defaults & Spikes
page, its TDMS data is plotted as curves alongside the overview/archive/
pupitre curves (the dashed incident marker stays). No other dashboard
changes.

## Findings (read-only investigation)

- Incident files load fine through the existing `load_mrun_object`
  (`DataType.TDMS` → `"pigbrother"`). A Default file holds 60 s at 4800 Hz
  (288 000 rows); a Spike file 1 s (4 800 rows).
- Groups shared with the overview (e.g. `Courants_Alimentations/Champ_magn`)
  merge automatically into the same checklist entries via
  `get_overview_group_entries` / `collect_group_files_data`. Incident-only
  groups (`HT_default`, `HTC_default`, `Numérique_Alimentation`) would appear
  as extra blocks.
- Legend label and style already handle these files ("Default 20/01 13:51",
  purple dotted).
- In `t` mode every file's `t` starts at 0, so incident data would sit at
  0–60 s, far from its marker — it must be shifted onto the record's t=0
  reference.

## Files affected

| File | Action |
|---|---|
| `apps/dashboards/magnetdb/src/pages/defaults_spikes.py` | edit |
| `apps/dashboards/magnetdb/tests/defaults_spikes_incident_test.py` | create |

Shared modules (`magnetdb_analysis.py`, `magnetdb_plot.py`,
`style_editor.py`, `dash_selectors.py`) and all other pages are **not**
touched.

## Steps

1. **Tests first** for two new private helpers in the page:
   - `_data_files(regular_files, event_files, incident)` → regular files +
     the selected incident (ignores `None` / anything not in `event_files`).
   - `_shift_incident_t(entry, record_t0_utc)` → copy of the entry whose
     `t` = seconds from `record_t0_utc` to each `timestamp`, without
     mutating the cached DataFrame.

   → verify: new tests fail before the helpers exist.
2. **Add the two helpers** (one-line docstrings).
   → verify: new tests pass.
3. **`update_groups`**: add `Input("ds-incident-filter", "value")` and build
   the checklists from `_data_files(...)`, so incident-only groups get
   blocks.
   → verify: manual app check below.
4. **`update_graphs`**: load the selected incident with the regular files;
   in `t` mode, apply `_shift_incident_t` to that file's entries so curves
   line up with the marker/window.
   → verify: manual check in both x-axis modes.
5. **`download_group_csv_defaults_spikes`**: add the incident `State`, same
   file list and `t` shift, so the CSV matches what's on screen.
   → verify: downloaded CSV contains rows for the Default file.
6. **NumPy-style docstrings** on the three modified callbacks (per
   `CLAUDE.md`).
7. **Regression**: run `pytest apps/dashboards/magnetdb/tests/` and
   `git diff --stat`.
   → verify: same pass/fail as before; only the two files above changed.

**Manual check:** run the app on `test-magnetdb.duckdb`, record
`M10_Overview_260120-1345`, incident
`M10_Default_260120-135125_DefautNums.tdms` → a "Default 20/01 13:51"
Champ_magn curve appears in Magnetic_Field; `HT_default` /
`Numérique_Alimentation` blocks appear; in `t` mode the curve ends at the
marker; the Overview Records page is unchanged.

## Assumptions & open questions

1. **Only the selected incident is loaded**, not all of the record's event
   files (a record can have dozens of Default and hundreds of Spike files).
2. **Changing incident resets ticked sensors** to the default
   (Field/Champ_magn), since the blocks are rebuilt. Preserving ticks is a
   few extra lines — wanted?
3. **Performance**: 288 000 points per sensor in "raw data" mode will make
   the browser sluggish (`create_annotated_plot` uses SVG `go.Scatter`).
   Not changing shared plot code; pick LTTB/minmax for Default files. OK?
4. **Window placement**: the Default filename time is ~1 s *after* its data
   ends (data 13:50:24 → 13:51:24, filename 13:51:25), so the default ±2 s
   window only shows the last ~1.5 s; widen the window (e.g. 60) to see the
   whole file. Not changing this unless asked.
5. **Style editor** won't list incident curves (they use their file type's
   default style); including them would mean changing how the style-editor
   context is wired.
6. A record with *only* incident files still shows nothing (existing
   "No overview/archive/pupitre files" early exit is kept).
7. **Test import**: `dash.register_page` needs a pages-enabled Dash app, so
   the test creates a minimal one before importing the page.

## Status

Implemented 2026-10-15. Open questions 2, 3, 5 resolved with the defaults
(ticks reset on incident change; no performance change — use LTTB/minmax for
Default files; style editor unchanged). Tests: 5 new in
`tests/defaults_spikes_incident_test.py`; suite 103 → 108 passed
(`hoop_test.py` excluded — hard-coded `/workspaces/...` DB path).
