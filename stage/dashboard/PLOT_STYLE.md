# Plot style in the dashboard

Trace styling (color, dash, line width, opacity) for the Plotly figures the
dashboard renders is driven by data-file type, not Plotly's default trace
color cycling. Lives entirely in `src/magnetdb_plot.py`.

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

`_load_default_file_type_styles()` resolves `FILE_TYPE_STYLES` in this order, first match wins:

1. `$MAGNETDB_FILE_TYPE_STYLES` — path to a JSON file, if the env var is set.
2. `~/.config/magnetdb/style.json` — a fixed per-user override location, checked if it exists.
3. `style.json` — the bundled default, shipped next to `magnetdb_plot.py`.
4. In-code `FileTypeStyles()` dataclass defaults — last-resort fallback if even the bundled file
   is somehow missing or unreadable; startup never crashes.

`scripts/init_style_config.py` writes a starting-point file (`FileTypeStyles()`'s defaults) to
edit from — defaults to `~/.config/magnetdb/style.json`, refuses to overwrite an existing file
unless `--force` is given:

```bash
# Persist an override across runs, at the config-dir location:
python scripts/init_style_config.py
# edit ~/.config/magnetdb/style.json

# Or write it elsewhere and use the env var instead:
python scripts/init_style_config.py --output my_styles.json
MAGNETDB_FILE_TYPE_STYLES=$(pwd)/my_styles.json python src/magnetdb_app.py
```

Partial files are fine at every level — `FileTypeStyles.from_dict()` only overrides the types you
include, everything else keeps its default. A missing or unreadable file at any step logs a
warning and falls through to the next source in the list.

Example JSON overriding a single type:
```json
{
  "spike": { "color": "#000000", "dash": "longdash", "width": 3, "opacity": 0.5 }
}
```

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
