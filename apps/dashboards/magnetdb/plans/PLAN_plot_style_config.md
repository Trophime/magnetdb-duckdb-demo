# Plot style config: bundled default + overridable style.json

**Status:** Approved and implemented 2026-08-19. All 5 approach steps landed and verified: bundled
`apps/dashboards/magnetdb/src/style.json` generated from and round-trip-verified against the in-code
defaults; `_load_default_file_type_styles()` rewritten with the 4-step resolution (env var →
`~/.config/magnetdb/style.json` → bundled `style.json` → in-code defaults), each precedence level
exercised live with an isolated `$HOME`; `create_plot()`'s title construction fixed to combine
`filename`/`group_name` separately, verified both with and without `group_name`; `file_viewer.py`'s
call site fixed to pass the raw filename, verified live against `test-magnetdb.duckdb` — a real
pupitre `.txt` file now resolves to the `#2ca02c` pupitre color instead of Plotly's default color
cycle, with the title still showing filename + group + algorithm; `PLOT_STYLE.md` updated to match
(new resolution order documented, `file_viewer.py`'s typed-styling verdict flipped to "yes").
`create_annotated_plot()` re-verified with no regression. The "Follow-up" section below (annotation
marker/text customization) remains unscoped and not implemented.

## Goal

`magnetdb_plot.py` resolves trace styles from `$MAGNETDB_FILE_TYPE_STYLES` →
`~/.config/magnetdb/style.json` → a bundled `style.json` shipped next to the module, in that
order. `file_viewer.py` (the renamed `home.py`, see `PLAN_dashboard_hierarchy_rework.md`)
actually gets typed styling instead of always falling back to Plotly's default colors.

## Context / background

Follows directly from `PLAN_dashboard_hierarchy_rework.md`'s `home.py`→`file_viewer.py` rename
(implemented 2026-08-19): renaming surfaced that `file_viewer.py` was the one page that never
got typed styling, because it passes a composite `"<file> - <group>"` string as `create_plot()`'s
`filename` argument — that string never matches `.txt`/`.tdms`, so `_resolve_file_style()`
always returns `None` (documented in `PLOT_STYLE.md`, "Which pages actually get typed styling").

Today's `_load_default_file_type_styles()` already reads `$MAGNETDB_FILE_TYPE_STYLES` as an
override, but its "default" is the in-code `FileTypeStyles()` dataclass, not an actual JSON file
— there is nothing on disk to point users at as a starting template.

Investigated and rejected as precedent: `python_magnetrun`'s `resolve_defs_file()`
(`pupitre-defs.json`/`pigbrother-defs.json`/`hybrid-defs.json`) and `get_housing_config()`
(`M8`/`M9`/`M10`-housing-config.json) both technically support a `~/.config/magnetrun/`
user-override step in code, but per user confirmation neither is actually meant to be
user-customized in practice — those files are fixed defaults, not a real override precedent.
`data_dirs.json` was also considered but has no bundled default at all (purely env-var-driven).
The closest real precedent is the dashboard's own existing `$MAGNETDB_FILE_TYPE_STYLES`
mechanism, extended with a config-dir fallback (mirroring `~/.config/magnetrun/`'s shape without
reusing its files) per user's explicit choice between the two options offered.

**Out of scope for this plan:** customizing the annotation markers (`symbol`/`size`/text styling
in `create_comparison_plot()`/`create_annotated_plot()`) via the same JSON — flagged by the user
as a follow-on ("eventually"), needs its own `TraceStyle` schema extension, not part of this pass.

## Files affected

**Create**
- `apps/dashboards/magnetdb/src/style.json` — bundled default, values taken from today's
  `FileTypeStyles()` dataclass defaults (the table already in `PLOT_STYLE.md`: pupitre / overview
  / archive / default / spike / trigger).

**Edit**
- `apps/dashboards/magnetdb/src/magnetdb_plot.py`
  - Add `_USER_STYLE_CONFIG = Path.home() / ".config" / "magnetdb" / "style.json"` (matches the
    `MAGNETDB_*` env-var prefix already used throughout the dashboard, e.g. `MAGNETDB_DB_PATH`)
    and `_BUNDLED_STYLE_PATH = Path(__file__).parent / "style.json"`.
  - Rewrite `_load_default_file_type_styles()`: try `$MAGNETDB_FILE_TYPE_STYLES` → try
    `_USER_STYLE_CONFIG` → try `_BUNDLED_STYLE_PATH` → last-resort in-code `FileTypeStyles()`
    (defensive; keeps the "never crashes startup" guarantee even if the bundled file is somehow
    missing).
  - Fix `create_plot()`'s title line so filename and group name are separate concerns again:
    `title=f"Visualization : {filename}"` + `f" - {group_name}"` (only if `group_name` is
    non-empty) + `f" (Algo: {method})"`. Confirmed via grep: `create_plot()` has exactly one live
    caller (`file_viewer.py`); `pages_disabled/comparison.py` imports it but never calls it (only
    `create_comparison_plot()`), so this is safe.
- `apps/dashboards/magnetdb/src/pages/file_viewer.py` — the one live caller of `create_plot()`: change
  `filename=f"{selected_file} - {group_name}"` → `filename=selected_file` (the composite string
  was the only thing defeating `_resolve_file_style()`; `group_name` is already passed
  separately and now feeds the title directly).
- `apps/dashboards/magnetdb/PLOT_STYLE.md` — document the new 3-step resolution order (replacing the
  current "env var or code defaults" description), and flip `file_viewer.py`'s "Which pages
  actually get typed styling" verdict from "no" to "yes."

## Approach

1. Write `style.json` → verify: `load_file_type_styles()` round-trips it into a `FileTypeStyles`
   identical to today's in-code defaults.
2. Add the two path constants + rewrite `_load_default_file_type_styles()` → verify: with no env
   var and no `~/.config/magnetdb/style.json`, it loads the bundled file; with
   `$MAGNETDB_FILE_TYPE_STYLES` set, that wins; with only the config-dir file present, that wins
   over the bundled default.
3. Fix `create_plot()`'s title construction → verify: unit check with `group_name=""` (title
   unchanged from today) and `group_name="Courants_Alimentations"` (title includes both parts).
4. Fix the `file_viewer.py` call site → verify: live check against `test-magnetdb.duckdb` — pick
   a real `.txt` pupitre file, confirm the resulting trace's line color is `#2ca02c` (pupitre
   style) instead of a Plotly default-cycle color, and the plot title still shows filename +
   group + algorithm.
5. Update `PLOT_STYLE.md` → verify: re-read against the actual code.

## Assumptions & open questions

- User config path is `~/.config/magnetdb/style.json` (matching the `MAGNETDB_*` env-var family)
  — say if you'd prefer a different directory name.
- `pages_disabled/comparison.py` imports `create_plot` but never calls it, so the title-format
  change is safe with no other live callers affected.

## Follow-up: customizing annotation markers/style/font text (not in this plan)

Once the `style.json` resolution mechanism above lands, extend it to cover the event-marker
annotations (`sources_default`/`sources_spike`/`sources_trigger`) that `create_comparison_plot()`
and `create_annotated_plot()` draw — currently every property is hardcoded inline in both
functions, not read from `FileTypeStyles`/`TraceStyle` at all:

- **Marker:** `size=14`; `symbol='x' if file_type == 'default' else 'star'` (so `spike` and
  `trigger` both currently render as a star — no per-type distinction); `line=dict(width=2,
  color='DarkSlateGrey')`; fill `color=style.color if style else "red"` (the one property that
  *is* already type-aware, reusing the existing line color).
- **Text:** `textposition="top center"`; `textfont=dict(color=style.color if style else "red",
  size=11, family="Arial Black")`.

Needs its own `TraceStyle` schema extension (new fields — e.g. `marker_symbol`, `marker_size`,
`marker_line_color`, `text_font_family`, `text_font_size`, `text_position` — or a parallel
`MarkerStyle` dataclass keyed by the same type names) before `create_comparison_plot()`/
`create_annotated_plot()` can be rewired to read from `FILE_TYPE_STYLES` instead of the current
hardcoded values. Would reuse the same bundled/env-var/config-dir resolution built in this plan,
not a separate mechanism. Not scoped in detail yet — flagged here so it isn't lost.
