# Plan: CSV download button beside the graph style gear icon

## Goal

Add a small download icon next to the gear icon on every group block
(file_viewer, overview_records, defaults_spikes), which exports that group's
currently-checked sensors as full-resolution CSV — restricted to the zoomed
x-range when the graph is zoomed, full range otherwise.

## Files affected

1. `apps/dashboards/magnetdb/src/magnetdb_analysis.py` — edit. Rename
   `_filter_by_x_range` → `filter_by_x_range` (drop the leading underscore)
   so it's a legitimate public helper callable from page modules; update its
   two internal call sites (currently lines 1033, 1100). No behavior change.
2. `apps/dashboards/magnetdb/src/style_editor.py` — edit. Add two small
   shared UI helpers next to `gear_button`/`modal_component`:
   - `download_button(id_prefix, group_name)` — a "⬇" `html.Button`,
     absolutely positioned next to the gear (`right: "40px"` vs. the gear's
     `right: "15px"`), id `{"type": f"{id_prefix}-download-btn", "index": group_name}`.
   - `download_store(id_prefix)` — returns `dcc.Download(id=f"{id_prefix}-download-data")`.
3. `apps/dashboards/magnetdb/src/pages/file_viewer.py` — edit.
   - `_sensor_group_block` (line 328): add `style_editor.download_button("fv", group_name)`
     beside the existing gear call.
   - `layout()` (line 106): add `style_editor.download_store("fv")` beside
     `modal_component("fv")`.
   - New callback near `update_outputs`: triggered by
     `Input({"type": "fv-download-btn", "index": ALL}, "n_clicks")`, resolves
     the clicked group via `ctx.triggered_id` (same pattern as
     `style_editor._open_style_modal`). Reuses the same data path as
     `update_outputs` (native sensors via `mrun.MagnetData.get_group_data(group_name)`,
     supervision sensors via `db.load_supervision_bdd`), reads that group's
     own `relayoutData` for a zoom range (converted local→UTC via
     `local_to_utc_naive` when `x_mode == "timestamp"`, matching
     `update_file_stats`), filters each source with `db.filter_by_x_range`,
     melts the selected columns into tidy rows `[x_col, file, sensor, value]`,
     concatenates, and returns
     `dcc.send_data_frame(df.to_csv, f"{selected_file}_{group_name}.csv", index=False)`.
4. `apps/dashboards/magnetdb/src/pages/overview_records.py` — edit. Same
   shape: `download_button("ov", ...)` beside line 516's gear call,
   `download_store("ov")` beside line 218's `modal_component`, and a new
   callback mirroring `update_graphs`'s data assembly
   (`db.collect_group_files_data(mruns, housing, group_name, selected_values, group_entries)`,
   via `State("overview-records-group-entries", "data")`), tidy-melting each
   file's selected sensors after `filter_by_x_range`, concatenating across files.
5. `apps/dashboards/magnetdb/src/pages/defaults_spikes.py` — edit. Same
   shape: `download_button("ds", ...)` beside line 492's gear call,
   `download_store("ds")` beside line 265's `modal_component`, callback
   mirroring `update_graphs`'s `db.collect_group_files_data` assembly (via
   `State("ds-group-entries", "data")`). Only the graph's own live
   `relayoutData` counts as "zoomed" — the incident-window default range
   (`_incident_x_range`) is *not* used to restrict the download when no
   manual zoom is active, so "no zoom" exports the full checked data, not
   just the incident window.

## Approach

1. Rename `_filter_by_x_range` → `filter_by_x_range` in
   `magnetdb_analysis.py`, update its 2 call sites → verify:
   `grep -rn _filter_by_x_range apps/dashboards/magnetdb/src` finds nothing.
2. Add `download_button`/`download_store` to `style_editor.py` → verify:
   `python -c "import style_editor"` from the app's src dir succeeds.
3. Wire button + store + callback into `file_viewer.py` → verify: app
   launches (`run` skill), zoom a graph, click the new icon, downloaded
   CSV's rows fall within the zoomed range and only contain checked sensors;
   unzoomed click downloads full data.
4. Same for `overview_records.py` → verify: same manual check, plus
   multi-file overlay group produces one row block per file.
5. Same for `defaults_spikes.py` → verify: same manual check; confirm an
   unzoomed download is NOT clipped to the incident window.
6. Run `pytest apps/dashboards/magnetdb/tests` → verify: no regressions
   (nothing currently references the renamed helper outside its own module,
   per grep already done).

## Assumptions & open questions

- **CSV shape**: tidy/long format (`x_col, file, sensor, value`) rather than
  one-column-per-sensor wide format. Wide format can't safely represent
  overview_records/defaults_spikes' multi-file overlays (different files'
  timestamps don't align row-for-row) or file_viewer's native+supervision
  merge (different sampling), so tidy format is used uniformly across all
  three pages. If wide format is preferred for the (simpler) file_viewer
  case specifically, that page can be adjusted.
- **Filename**: `{group_name}.csv` for overview_records/defaults_spikes;
  `{selected_file}_{group_name}.csv` for file_viewer.
- **Icon**: reusing a plain "⬇" text button styled like the existing "⚙"
  gear, not a new icon library — keeps this dependency-free and visually
  consistent.
- Data source is full-resolution raw data (not the downsampled display
  data), re-queried from the existing DuckDB-backed loaders and filtered to
  the zoomed range. All three pages (file_viewer, overview_records,
  defaults_spikes) are in scope.
