# Plot style in the dashboard

Trace styling (color, dash, line width, opacity) for the Plotly figures the
dashboard renders is driven by data-file type, not Plotly's default trace
color cycling. On top of that, individual fields within a group can get
their own color/dash/width/marker override, editable from the dashboard
itself via a gear icon on each group block. Lives entirely in
`src/magnetdb_plot.py` (resolution) and `src/style_editor.py` (the gear/modal UI).

## Where a trace's style comes from

`create_plot()` calls `_resolve_file_style(filename)` before building any
traces:

1. `filename` ends in `.txt` → `pupitre` style.
2. `filename` ends in `.tdms` → `classify_pigbrother_file(filename)` (from
   `python_magnetrun/utils/files.py`) extracts the acquisition mode — the
   2nd underscore-part of the filename, e.g. `M9_Archive_251202-1430.tdms`
   → `"archive"` — normalized to one of `overview` / `archive` / `default`
   / `spike` / `trigger`.
3. Anything else (unrecognised extension, or a synthetic/composite name) →
   `None`, and the trace falls back to Plotly's own default color cycling,
   unstyled.

All sensors plotted from the same file share that file's style — color
identifies the *file type*, not the individual sensor. To tell sensors from
the same file apart, use the legend/hover, not color.

## Default styles

| type     | color     | dash    | width | opacity |
|----------|-----------|---------|-------|---------|
| pupitre  | `#2ca02c` | solid   | 2     | 1.0     |
| overview | `#1f77b4` | solid   | 2     | 1.0     |
| archive  | `#ff7f0e` | solid   | 2     | 1.0     |
| default  | `#9467bd` | dot     | 1.5   | 0.8     |
| spike    | `#d62728` | dash    | 1.5   | 0.9     |
| trigger  | `#8c564b` | dashdot | 1.5   | 0.8     |

Defined in `magnetdb_plot.py` as two dataclasses: `TraceStyle` (one type's
color/dash/width/opacity) and `FileTypeStyles` (one `TraceStyle` per type,
exposed as the module-level `FILE_TYPE_STYLES`).

## Overriding without touching code

`_load_default_style_config()` resolves a `StyleConfig` (source-type styles + field overrides,
see below) in this order, first match wins:

1. `$MAGNETDB_FILE_TYPE_STYLES` — path to a JSON file, if the env var is set.
2. `USER_STYLE_CONFIG_PATH` (`~/.config/magnetdb/style.json`) — a fixed per-user override
   location, checked if it exists. This is also where the dashboard's own gear-icon editor
   (see below) always saves to.
3. `style.json` — the bundled default, shipped next to `magnetdb_plot.py`.
4. In-code `StyleConfig()` dataclass defaults — last-resort fallback if even the bundled file
   is somehow missing or unreadable; startup never crashes.

`scripts/init_style_config.py` writes a starting-point file (`FileTypeStyles()`'s defaults, no
field overrides) to edit from — defaults to `~/.config/magnetdb/style.json`, refuses to
overwrite an existing file unless `--force` is given:

```bash
# Persist an override across runs, at the config-dir location:
python scripts/init_style_config.py
# edit ~/.config/magnetdb/style.json

# Or write it elsewhere and use the env var instead:
python scripts/init_style_config.py --output my_styles.json
MAGNETDB_FILE_TYPE_STYLES=$(pwd)/my_styles.json python src/magnetdb_app.py
```

Partial files are fine at every level — `FileTypeStyles.from_dict()` only overrides the types you
include, everything else keeps its default; `field_overrides` defaults to `{}` if absent
entirely, so every style.json written before this feature (source-type keys only) still loads
unchanged. A missing or unreadable file at any step logs a warning and falls through to the next
source in the list.

Example JSON overriding a single source type:
```json
{
  "spike": { "color": "#000000", "dash": "longdash", "width": 3, "opacity": 0.5 }
}
```

## Per-field overrides

On top of the per-source-type table, an individual field within a group can override its
color/dash/width/marker — keyed by `(group_name, raw_sensor_name)`, in the same JSON file's
`field_overrides` section:

```json
{
  "pupitre": { "...": "..." },
  "field_overrides": {
    "Courants_Alimentations": {
      "Idcct1": { "color": "#ff00ff", "marker_symbol": "circle", "marker_every": 3 }
    }
  }
}
```

- **Source-agnostic key.** The override applies to every trace named `Idcct1` in the
  `Courants_Alimentations` group, regardless of which file it came from. On overview-records,
  where one checklist entry can merge two differently-named raw channels across formats (e.g.
  pupitre's `Idcct1` aliased to pigbrother's `Courant_A1`), each raw name needs its own override
  entry — styling `Idcct1` does not automatically style `Courant_A1`.
- **Opacity stays per-source-type only** — it is deliberately not a `FieldStyleOverride`
  property, so it's never overridable per field, only via the top-level source-type table above
  (or the "Opacity by source" section of the gear-icon modal, which edits that same table).
- **Partial overrides.** Any property left out (or `null`) falls back to the resolved
  source-type `TraceStyle`. `width` behaves the same way; `color`/`dash` fall back to the
  source style's; `marker_symbol`/`marker_every` are `None` by default, meaning no markers
  (`mode="lines"`, matching today's default) unless a `marker_symbol` is set.
- **`marker_every`** draws a marker only every Nth *plotted* point (after downsampling), via a
  per-point `marker.size` mask (`0` hides that point's marker) on the same trace — there is no
  native Plotly `markevery`, so this is implemented in `_apply_style()`.
- Resolution: `_resolve_field_override(group_name, sensor)` looks up the override;
  `_apply_style(style, override, n_points)` merges it with the resolved source-type `TraceStyle`
  and returns the final `mode`/`line`/`opacity`/`marker` kwargs. Used by `create_plot()`,
  `create_comparison_plot()`, and `create_annotated_plot()` — but only for their regular line
  traces. The `spike`/`default`/`trigger` event-marker annotations in
  `create_comparison_plot()`/`create_annotated_plot()` are untouched by field overrides (flagged
  as a separate, unscoped follow-up in `PLAN_plot_style_config.md`).

## Editing style from the dashboard (gear icon)

Each group block on `file_viewer` and `overview-records` has a ⚙ gear icon (top-right of the
group's header bar) that opens a modal — one row per field actually plotted in that group (a hex
color text field backed by a clickable swatch palette, dash dropdown, width, marker symbol,
marker-every), plus an "Opacity by source" section for the source types actually contributing
files to that group. Implemented in `src/style_editor.py`:

- `gear_button()` / `modal_component()` build the UI; `register_callbacks(id_prefix, context_fn,
  extra_states)` wires open/save/reset/cancel — each page supplies its own `context_fn` that
  resolves the current group's raw sensor names and source-type keys (`file_viewer.py`: the one
  loaded file's own columns; `overview_records.py`: the union of raw channels across that
  record's regular — non-event — source files).
- **Save** always writes a full `color`/`dash`/`width` for every row shown (not a diff against
  what was pre-filled) — editing a field's style via the modal takes explicit ownership of it,
  decoupled from the source-type table from then on. It writes the *entire* merged
  `StyleConfig` — every other group's overrides and the full source-type table — to
  `USER_STYLE_CONFIG_PATH`, then calls `reload_style_config()` so the change applies immediately,
  and bumps a per-page `dcc.Store` (`fv-style-version` / `ov-style-version`) that's wired into
  the page's figure-building callback purely as a redraw trigger.
- **Reset** clears the open group's field overrides only (other groups and the source-type table
  are untouched), saves, reloads, and closes.
- **Cancel** just closes the modal, discarding unsaved edits.

## Which pages actually get typed styling

- `comparison.py` — yes, passes the raw filename straight through to
  `create_plot()`.
- `file_viewer.py` — yes, passes the raw filename straight through to
  `create_plot()`. The plot title, previously built from a composite
  `"<file> - <group>"` string passed as `filename` (which defeated typed
  styling), is now built inside `create_plot()` from `filename` and
  `group_name` as separate arguments.
- `overview_records.py` — yes, calls `create_annotated_plot()` (not `create_plot()`),
  but resolves styling the same way, passing each file's raw filename through to
  `_resolve_file_style()`.

## Adding a new PigBrother acquisition mode

If a new mode shows up on disk, two places need updating together:

1. `_TDMS_MODE_STYLE_KEYS` in `python_magnetrun/utils/files.py` — maps the
   raw filename token (e.g. `"NewMode"`) to a normalized key.
2. `FileTypeStyles` in `magnetdb_plot.py` — add a matching field with a
   default `TraceStyle`.

`_resolve_file_style()` silently no-ops (falls back to unstyled) for any
mode present in one but not the other, so a mismatch fails quiet rather
than loud — check both when adding a mode.

## Related, but not the same thing

`python_magnetrun/plotting/style.py` has its own `PlotColors`/`PlotConfig`
+ `load_plot_config`/`save_plot_config`, used by the `python_magnetrun`
CLI's matplotlib/Plotly-resampler plotting commands. It's colors only (no
dash/width/opacity) and backend-agnostic. The dashboard's `FileTypeStyles`
is Plotly-specific (`dash`, `opacity` are Plotly trace properties) and
deliberately kept local to `magnetdb_plot.py` rather than merged into that
shared config, to avoid touching the actively-used CLI config path.
