# Plan — scope the loading spinner per-region instead of app-wide

Status: implemented and verified (2026-09-07), uncommitted.

## Goal

Replace the single, app-wide `dcc.Loading` wrapper (currently around
`dash.page_container` in `magnetdb_app.py`) with local `dcc.Loading`
wrappers scoped to just the specific slow-loading regions on each page
that actually needs one — so that switching a record/file/part never
blanks or blocks interaction with the rest of the page, only the region
that is genuinely being reloaded.

## Context — how we got here

1. **Original bug report**: on `overview_records.py`, selecting an
   overview record made the duration/Field-stats banner (and the whole
   page) disappear for several seconds.
2. **Root cause #1**: `magnetdb_app.py` wraps `dash.page_container` —
   i.e. *every* page's *entire* content — in one
   `dcc.Loading(dash.page_container, type="circle")`. Dash's default
   `overlay_style` is `{"visibility": "hidden"}`, so *any* callback
   running anywhere on the current page blanks the *whole* page for as
   long as that callback runs. `overview_records.py`'s `update_groups`
   callback loads every source file for a record (overview `.tdms` +
   several pupitre `.txt`) via `db.get_overview_group_entries` — timed
   at ~10-13s — so the fast `update_file_stats` banner (already
   resolved) stayed hidden behind the blanked page for that whole
   window.
3. **First fix attempt**: override `overlay_style` on the global
   wrapper to `{"visibility": "visible", "filter": "blur(2px)"}` so
   content stays visible (blurred) instead of hidden while loading.
   This fixed the visual "disappearing" symptom.
4. **Regression this introduced**: `dcc.Loading` *always* renders a
   separate, absolutely-positioned, `pointer-events: auto` overlay div
   over its entire wrapped subtree while any callback beneath it is
   loading — independent of `overlay_style`, which only restyles the
   wrapped *content*, not this blocking layer. So content now *looked*
   readable and clickable during load, but clicks anywhere on the page
   (not just the slow region) were silently swallowed by that invisible
   overlay. Confirmed empirically via Playwright
   (`document.elementFromPoint` over a checkbox mid-load resolved to an
   anonymous `<div style="position:absolute">` with
   `pointer-events: auto`, not the checkbox itself).
5. **Why `file_viewer.py` "worked smoothly" under the same blur change**:
   confirmed the *same* blocking div appears there too, but its
   equivalent callback (`update_sensors_menus`) loads only **one** file
   (~2.5s) vs. overview_records' several files (~10-13s) — the window is
   short enough that a human click essentially never lands in it, so the
   underlying issue was invisible in practice, not absent.
6. **Nesting a local `dcc.Loading` inside the still-present global one
   does not fix this** — confirmed empirically with a throwaway probe
   app: an *outer* `dcc.Loading` still blanks/blocks its entire subtree
   whenever anything inside is loading, regardless of inner `Loading`
   wrappers. The only way to keep fast content both visible *and*
   interactive during an unrelated slow callback is for that content to
   not be wrapped by the outer `Loading` at all.

Conclusion: the global wrapper has to go. Replace it with local
`dcc.Loading` wrappers, each scoped to just the region that is actually
slow on its page, using Dash's *default* `overlay_style` (hide + spinner)
for each local wrapper — appropriate there, since that specific content
really is being replaced and shouldn't look interactive while it does.

## Survey — which pages need a local `dcc.Loading`

Determined by checking whether a page's checklist/data-refresh callback
does real per-file/time-series work (`db.load_mrun_object`,
`db.get_group_dataframe`, `db.get_overview_group_entries`, a full
Parquet read + downsample, etc.) vs. pure aggregate SQL / metadata
lookups (fast regardless of DB size).

| Page | Slow callback | Output(s) to wrap | Verdict |
|---|---|---|---|
| `overview_records.py` | `update_groups` — `db.get_overview_group_entries` over every source file of a record (~10-13s) | `overview-records-missing-banner`, `overview-records-groups-container` | **needs local Loading** |
| `defaults_spikes.py` | `update_groups` — same pattern, archive included by default so likely slower | `ds-missing-banner`, `ds-groups-container` | **needs local Loading** |
| `file_viewer.py` | `update_sensors_menus` — one file, ~2.5s | `sensors-selectors-container` | not needed for correctness, but included for a consistent experience with the two pages above |
| `part_stats.py` | `update_part_stats` (21 outputs) — the hoop-stress section (`_hoop_stress_section`) does `pd.read_parquet` on a per-part file (up to ~17.6MB, all experiments) + LTTB downsample | the inner `html.Div` inside `part-stats-hoop-stress-details` wrapping `part-stats-hoop-stress-banner` / `-table` / `-fig` / `-history-fig` (leave the `html.Details`/`Summary` toggle itself unwrapped) | **needs local Loading** |
| `housing_stats.py` | `update_housing_stats` — aggregate `GROUP BY`/join queries only | — | fast, no change |
| `assembly_stats.py` | `update_assembly_stats` — aggregate joins over `experiments`/`exp_run_scalars`/`exp_assembly_bin_stats` | — | fast, no change |
| `magnet_stats.py` | `update_magnet_stats` — same pattern as assembly_stats | — | fast, no change |
| `stats_research_area.py` | `update` — aggregate CTE/`UNNEST` queries | — | fast, no change |

## Concrete edits

1. `apps/dashboards/magnetdb/src/magnetdb_app.py`: replace
   ```python
   dcc.Loading(
       dash.page_container,
       type="circle",
       overlay_style={"visibility": "visible", "filter": "blur(2px)"},
   ),
   ```
   with plain
   ```python
   dash.page_container,
   ```
2. `apps/dashboards/magnetdb/src/pages/overview_records.py`: wrap
   `overview-records-missing-banner` + `overview-records-groups-container`
   (currently ~lines 210-211) in one `dcc.Loading(type="circle")`.
3. `apps/dashboards/magnetdb/src/pages/defaults_spikes.py`: wrap
   `ds-missing-banner` + `ds-groups-container` (currently ~lines
   263-264) in one `dcc.Loading(type="circle")`, same pattern.
4. `apps/dashboards/magnetdb/src/pages/file_viewer.py`: wrap
   `sensors-selectors-container` (currently ~lines 85-89) in one
   `dcc.Loading(type="circle")`.
5. `apps/dashboards/magnetdb/src/pages/part_stats.py`: wrap the inner
   (currently unnamed) `html.Div` at ~lines 644-659 — containing
   `part-stats-hoop-stress-banner`, `-table`, `-fig`, `-history-fig` —
   in one `dcc.Loading(type="circle")`, inside the existing
   `html.Details(id="part-stats-hoop-stress-details", ...)`.

No callback/Output changes anywhere — every edit only adds a
`dcc.Loading(...)` wrapper around existing components in each page's
`layout()`.

## Verification

1. `overview_records.py` / `defaults_spikes.py`: select assembly →
   record; confirm filters/banner/dropdowns/table stay visible and
   interactive throughout the slow load, and only the groups-checklist
   area shows a contained spinner. Confirm checking a sensor checkbox
   right after load displays its graph (regression check for the
   click-eating bug). Re-run the "switch record, immediately click"
   race check.
2. `file_viewer.py`: confirm the sensor checklist area shows a
   contained spinner during its (shorter) load, rest of the page
   unaffected — mainly a consistency check, not a bug fix.
3. `part_stats.py`: select a part with hoop-stress history data;
   confirm the rest of the page (summary, magnet-time graph, fatigue
   section) stays visible/interactive while the hoop-stress section
   loads, and that section shows its own contained spinner.
4. Spot-check `housing_stats.py` (or another untouched page) still
   renders normally with no global wrapper at all.

## Trade-off accepted

Pages without a local `dcc.Loading` (housing/assembly/magnet stats,
research areas) get **no** loading indicator at all now, instead of the
previous blank-page-during-load. This is fine per the survey above —
none of them do per-file/time-series work, so their callbacks are fast
regardless of DB size.

## Blur retry (2026-10-15)

Status: implemented and verified, uncommitted.

### Findings

1. **"No graph after the spinner stops" was not a spinner bug.**
   `python_magnetrun.magnetdata_base._make_ureg()` was an unlocked lazy
   singleton; building a `UnitRegistry` is slow (~2 s for 4 concurrent
   builds), so parallel Dash callbacks on a cold start (direct page
   load → `update_groups` / `update_file_stats` / `update_graphs` all
   loading files at once) each got their own registry. `lru_cache` then
   kept those mixed `MagnetRun` objects, so every later
   `convert_values_to_unit` raised `Cannot operate with Unit and Unit of
   different registries` until restart — figures never arrived.
   Intermittent: an app whose first unit lookup happened without
   concurrency was unaffected. Fixed with a lock + double check in
   `_make_ureg()`; test in `python_magnetrun/tests/test_magnetdata_base.py`.
2. **Region wrappers reacted to every graph update.** The wrapped
   containers also hold the dynamic graphs, updated by `update_graphs`,
   `sync_zoom_*`, `pin_cursor_*`, `clear_cursors_*`. Fixed with
   `target_components` (only the slow rebuild callback's outputs).
3. **Gap after the region spinner.** `update_graphs` runs *after*
   `update_groups` (it needs the new checklists), so a region-only
   spinner stops while graphs are still empty placeholders. Fixed with a
   per-graph wrapper around each dynamic `dcc.Graph`.

### Implementation

- `dash_selectors.loading_region(children, target_components=None)`:
  `dcc.Loading` with `overlay_style` blur(3px) + opacity 0.5 +
  `minHeight: 80px` (room for the card in an empty region, only while
  loading), a 0.2 s fade, `delay_show=300` / `show_initially=False`, and
  a `custom_spinner` card (`dbc.Spinner` + translated label "Be patient
  while data are processed…", sticky near the region top).
- Region wrappers (with `target_components`): overview_records,
  defaults_spikes, file_viewer, stats_viewer, part_stats (hoop stress).
- Per-graph wrappers (no target): overview_records / defaults_spikes
  `update_groups`, file_viewer / stats_viewer `_sensor_group_block`.
- Label added to `magnetdb.pot` and en/fr/de/nl `.po`; `.mo` recompiled
  (`python -m babel.messages.frontend compile -f -d src/locales -D magnetdb`).

### Verified (Playwright, cold-started app)

- overview_records: region card 1.7–16.6 s, per-graph cards
  17.2–18.6 s, then Magnetic_Field has 4 traces; no registry errors.
- Zoom on a graph: no blur. Rebuild over existing content (archive
  toggle): content blurred under the card.
- file_viewer first load: card does not overlap the "5." label;
  French label shown.
- part_stats / stats_viewer render, no stuck spinner, no console or
  server errors. Dashboard tests: 108 passed before and after.

### Known limitations

- Ticking a sensor checkbox blurs **all** graphs for ~1 s, not just that
  one: `update_graphs` outputs every figure (`ALL`). Narrowing it would
  need a callback restructure.
- During a rebuild that also re-runs `update_graphs` (archive/incident
  toggles), the per-graph card shows blurred under the region card.
