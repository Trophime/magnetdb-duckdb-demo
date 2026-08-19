# Draft Plan: Clickable Event-Marker Detail View

**Goal:** Clicking a default/spike/trigger marker on an overview-records group
graph reveals a detail view showing just that one event file overlaid with
the group's archive TDMS, loaded lazily at click time rather than eagerly
with everything else.

## Files affected

- `stage/dashboard/src/magnetdb_plot.py` — edit `create_annotated_plot()`:
  add `customdata=[filename]` to each event marker's
  `go.Scatter(mode='markers+text', ...)` trace, so a click event carries the
  source filename without needing to parse `name`/`legendgroup`.
- `stage/dashboard/src/pages/overview_records.py` — edit:
  - `update_groups()`: stop scanning `event_files` when building each
    group's sensor checklist — derive options from `regular_files` only
    (event files carry the same channel names, so nothing is lost),
    removing the current eager parse of every `sources_default`/
    `sources_spike` file on record selection.
  - `update_graphs()`: keep event files out of the eager `files_data` build
    for the main per-group graph; the main graph should now load only
    `regular_files` for lines plus whichever event files are needed purely
    for marker placement (or, if marker placement itself proves cheap/
    necessary, keep that part but drop full per-file group/sensor loading —
    this is the one open point, see below).
  - Add `dcc.Store(id="overview-records-selected-event")` to `layout()`.
  - Add a new callback: `Input({"type": "ov-dynamic-graph", "index": ALL},
    "clickData")` → reads `clickData["points"][0]["customdata"]` → writes
    `{filename, group_name}` into the store.
  - Add a new callback keyed off the store: lazily calls
    `db.load_mrun_object(filename, housing)` for just the clicked file,
    pairs it with the already-loaded archive file for that group (already
    in memory from the main graph's line traces), and renders a detail
    figure — either via a scoped `create_annotated_plot([archive_entry,
    clicked_event_entry], ...)` call or `create_comparison_plot` if the
    two-row raw/aligned layout is preferred there.
  - Add the detail panel itself to the layout: an `html.Div`/`dcc.Graph`
    that stays empty/hidden until the store has a value.

## Approach

1. Add `customdata` to event traces in `create_annotated_plot()` → verify:
   unit-level check (same shape as the existing smoke test) — feed one
   spike file, confirm the resulting trace's `customdata` equals `[filename]`.
2. Strip event files out of `update_groups()`'s checklist-building scan →
   verify: re-run the group callback against the same event-heavy record
   used earlier; checklist options unchanged, wall-clock time drops close
   to the `regular_files`-only cost (no longer scaling with
   `sources_default`/`sources_spike` count).
3. Add the store + click callback → verify: manually POST a `clickData`
   payload with a known `customdata` filename to the callback endpoint,
   confirm the store updates to that filename.
4. Add the lazy detail-load callback + panel → verify: trigger via the
   store, confirm exactly one additional file gets parsed (check server log
   for a single new `addTdmsTime` burst, not the full event-file set), and
   the resulting figure contains both the archive line trace and the
   clicked event's marker/line.
5. Wire the panel into the layout and confirm it clears/hides appropriately
   when the user picks a different overview record.

## Assumptions & open questions

- Panel placement: inline collapsible panel on the same page (keeps
  context) vs. navigating to `/file_viewer` pre-seeded with the file. Assumed
  inline, per the "dashboard like experiment" framing — say if `/file_viewer`
  redirect is actually preferred.
- "The archive TDMS" assumes exactly one relevant archive file per group;
  if a record's `sources_archive` has more than one, needs a rule (all of
  them? the one covering the event's timestamp?).
- Whether marker placement on the *main* group graph still requires
  touching event files at all before any click (i.e., do markers need to
  appear before load, or can the main graph legitimately show zero event
  markers until the user does something else to reveal "there are N events
  here" — e.g. a count badge instead of live markers). This changes how
  much of the eager-load problem step 2 actually removes, and isn't fully
  settled yet.
- Whether `trigger`-classified files participate in the same click flow as
  `default`/`spike`, or are out of scope.
- Selection-reset behavior across record/group switches (clear store, or
  leave the last detail view showing).

