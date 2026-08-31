# Draft Plan: Cross-Graph Cursor Sync

**Goal:** Clicking a sensor-group graph on the File viewer or Overview
records page pins a persistent dotted vertical line at that x-position;
clicking near an already-pinned line removes it instead. Multiple lines can
coexist. A page-level toggle controls whether a click's pin/unpin also
applies to every other graph on the page (they live in separate
`html.Details` accordion blocks) or only to the clicked graph. A "Clear
cursors" button resets every graph's lines at once.

## History: why click, not hover

The first version of this feature synced a line on **hover**
(`hoverData` + `clear_on_unhover=True`), propagated via a
`dash.clientside_callback` calling `Plotly.relayout()` directly (a plain
Python `Patch()` callback raced: the hover-set and unhover-clear requests
were two separate HTTP round trips with no ordering guarantee, so a fast
mouse movement could let the "clear" response land after the "set" one and
erase a still-valid line — confirmed with a minimal standalone Dash app
outside this project).

In practice, even race-free, hover-triggered propagation felt "flaky" and
distracting: `hoverData` fires continuously as the mouse crosses data points
(many times a second), so every other graph was being asked to redraw
constantly just from scanning one graph with the mouse. Click fixes this at
the source — it's a single, deliberate, low-frequency event — which also
means the original race is moot (a click has no automatic follow-up event
the way `clear_on_unhover` had for hover), so this version is back to a
plain server-side `@dash.callback` with `Patch()`, avoiding the clientside
JS entirely.

## Files affected

- `apps/dashboards/magnetdb/src/pages/file_viewer.py` — edit:
  - `layout()`: add a "6. Cursor sync:" row (reusing the previously-unused
    slot before "7. Downsampling Method") with a `dcc.Checklist` toggle
    (`fv-sync-cursor-toggle`, default checked) and a `html.Button`
    (`fv-clear-cursors-btn`).
  - Remove `clear_on_unhover=True` from the `dynamic-graph` `dcc.Graph` (no
    longer relevant now that this is click-based).
  - Replace the old clientside hover callback with `pin_cursor_home`
    (`@dash.callback`, `clickData` Input) and a new `clear_cursors_home`
    (`@dash.callback`, button `n_clicks` Input).
- `apps/dashboards/magnetdb/src/pages/overview_records.py` — edit: the same
  four changes, using `ov-dynamic-graph` ids,
  `overview-records-sync-cursor-toggle` /
  `overview-records-clear-cursors-btn`, `pin_cursor_overview`, and
  `clear_cursors_overview`.

## Approach

1. `pin_cursor_home` takes `Input({"type": "dynamic-graph", "index": ALL},
   "clickData")`, `State(..., "id")`, `State(..., "figure")`,
   `State("fv-sync-cursor-toggle", "value")`, `State("dd-x-axis", "value")`,
   and `Output(..., "figure", allow_duplicate=True)`.
2. Find the clicked graph via `ctx.triggered_id` (same lookup style as
   `sync_zoom_home`); `raise PreventUpdate` if its `clickData` has no
   `points`.
3. Read the *clicked* graph's own current `layout.shapes` from its
   `State(..., "figure")` — no new `dcc.Store` needed, mirrors how
   `sync_zoom_home` already reads current state via `State(...,
   "relayoutData")` rather than tracking it separately.
4. If the clicked x is within `_CURSOR_MATCH_THRESHOLD` of an existing
   pinned line's x, remove that line; otherwise append a new one. The
   threshold is a small fixed value per x-axis mode (2s for `"timestamp"`,
   0.5 for `"t"`), compared via `pandas.Timestamp` difference or plain
   float difference depending on `dd-x-axis`'s value.
5. Always apply the resulting shape list to the clicked graph via `Patch()`.
   If the sync toggle is checked, apply the *same* list to every other
   graph too (`Patch()`), making all graphs identical; otherwise leave
   other graphs as `dash.no_update`, so each keeps accumulating its own
   independent set.
6. `clear_cursors_home` is a second callback keyed off the button's
   `n_clicks`; it unconditionally sets every graph's `layout.shapes` to
   `[]`, regardless of the toggle state (a global reset).
7. Repeat 1-6 identically in `overview_records.py`.

**Verification**
- `python -m py_compile apps/dashboards/magnetdb/src/pages/file_viewer.py
  apps/dashboards/magnetdb/src/pages/overview_records.py`.
- Manual, File viewer: click two different points on one graph (sync on) →
  both lines appear on every graph. Click near one of those lines again →
  it disappears everywhere. Uncheck sync, click a point on graph A then a
  different point on graph B → each keeps its own line, independent of the
  other. Click "Clear cursors" → every graph's lines are gone regardless of
  toggle state. Repeat on Overview records. Spot-check zoom sync
  (`sync_zoom_home` / `sync_zoom_overview`, untouched) still works.

## Assumptions & open questions

- All pinned lines share the same gray dotted style — no distinct per-line
  colors.
- The match threshold is a small **fixed** value per x-axis mode, not
  scaled to the current zoom level; may feel imprecise at very low or very
  high zoom. Shipping simple first, will tune the constant (or make it
  zoom-aware) if it proves annoying in practice.
- "Clear cursors" resets *all* graphs unconditionally, even graphs with
  independently-accumulated local lines when sync is off.
- Toggle defaults to checked (sync on) on both pages.
- "Isolated inside separate accordion blocks" refers to each page's
  `html.Details` grouping; pattern-matching ids make the accordion nesting
  irrelevant to the callback logic itself.
