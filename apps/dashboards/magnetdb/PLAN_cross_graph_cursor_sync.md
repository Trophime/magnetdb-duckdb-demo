# Draft Plan: Cross-Graph Cursor Sync

**Goal:** Hovering over any sensor-group graph on the File viewer or Overview
records page draws a synchronized vertical cursor/marker line at the same
x-position on every other graph on that page, even though each graph lives in
its own `html.Details` accordion block, and the line clears when the mouse
leaves the source graph.

## Files affected

- `apps/dashboards/magnetdb/src/pages/file_viewer.py` — edit:
  - `clear_on_unhover=True` on the `dcc.Graph(id={"type": "dynamic-graph",
    "index": group_name}, ...)` definition, so unhovering fires
    `hoverData=None` instead of leaving the last value stuck.
  - A `dash.clientside_callback(...)` (not a Python `@dash.callback`), placed
    next to the existing `sync_zoom_home`, with the same
    `Output({"type": "dynamic-graph", "index": ALL}, "figure",
    allow_duplicate=True)` / `Input(..., "hoverData")` / `State(..., "id")`
    signature — see Approach for why it's clientside.
- `apps/dashboards/magnetdb/src/pages/overview_records.py` — edit:
  - Same two changes, using `{"type": "ov-dynamic-graph", "index": ...}` ids
    and placed next to the existing `sync_zoom_overview` callback.

## Approach

**Why clientside, not a Python `Patch()` callback (as first implemented):**
verification found that a Python callback here needs two separate HTTP
round trips — one for the hover event, one for the `clear_on_unhover`-driven
unhover event — with no guarantee they resolve in order. A fast mouse
movement can make the "clear" response land *after* the "set" response and
silently erase a still-valid cursor line; this was confirmed reproducible
with a minimal standalone Dash app outside this project, independent of any
project code. A `dash.clientside_callback` runs synchronously in the browser
with no network round trip, so the hover and unhover invocations execute in
the same order the events actually fired in, removing the race.

1. The clientside JS reads `window.dash_clientside.callback_context.triggered_id`
   to find which graph's `hoverData` fired (mirrors `ctx.triggered_id` used
   by `sync_zoom_home` / `sync_zoom_overview`).
2. If that graph's hover data has no `points`, treat the cursor position as
   cleared (mouse left); otherwise take `points[0].x` as the shared cursor
   x-position.
3. For every graph *other than* the source (which already shows Plotly's own
   unified hover line via `hovermode="x unified"`), look up its wrapper DOM
   node by `document.getElementById(JSON.stringify(id, Object.keys(id).sort()))`
   (confirmed empirically: Dash renders pattern-matching component wrappers
   with an `id` attribute equal to the sorted-key JSON of the id dict), find
   its `.js-plotly-plot` child, and call `Plotly.relayout(gd, {shapes: [...]})`
   directly — either the single full-height vertical line shape
   (`x0=x1=cursorX, xref="x", y0=0, y1=1, yref="paper"`) or `[]` to clear.
4. The callback's actual `Output` (`figure`, `allow_duplicate=True`) is only
   present because Dash requires one for callback registration; the function
   always returns `dash_clientside.no_update` for it, since the visual update
   already happened via the direct `Plotly.relayout` call.
5. Repeat identically in `overview_records.py` with its own pattern-matching
   id type.

**Verification**
- `python -m py_compile apps/dashboards/magnetdb/src/pages/file_viewer.py
  apps/dashboards/magnetdb/src/pages/overview_records.py`.
- Manual: run the dashboard; on File viewer, expand ≥2 sensor-group
  accordions with data plotted, hover one graph → a vertical line appears on
  the other graph(s) at the matching x, and disappears on mouse-leave.
  Repeat on Overview records with ≥2 groups. Spot-check that the existing
  zoom sync (`sync_zoom_home` / `sync_zoom_overview`) still behaves
  correctly after the change. Also specifically re-test the fast
  interpolated-mouse-move pattern that reproduced the original race, to
  confirm the line now renders reliably through a hover/unhover flicker.

## Assumptions & open questions

- Hover-tracking cursor (not click-to-pin) on both pages, for a consistent
  feel between them. A click-to-pin marker that persists after the mouse
  leaves would instead need `clickData` plus a `dcc.Store` to hold the
  pinned x-value — different design, not what's planned here.
- "Isolated inside separate accordion blocks" refers to each page's
  `html.Details` grouping; pattern-matching ids make the accordion nesting
  irrelevant to the callback logic itself.
