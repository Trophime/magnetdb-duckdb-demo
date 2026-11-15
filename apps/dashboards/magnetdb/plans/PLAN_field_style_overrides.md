# Per-field style overrides + style-editing gear icon

**Status:** Proposed, not yet implemented.

## Goal

Each group block in `file_viewer` and `overview-records` gets a gear icon that opens a modal to
edit and save, per field, color/dash/width/marker/marker-spacing, plus per-source opacity —
persisted to the existing `~/.config/magnetdb/style.json`, applied live without a restart.

## Context / background

Follows on from `PLAN_plot_style_config.md` (implemented 2026-08-19), which gave the dashboard
per-*source-type* trace styling (`pupitre`/`overview`/`archive`/`default`/`spike`/`trigger`) via
`FILE_TYPE_STYLES`, resolved from `$MAGNETDB_FILE_TYPE_STYLES` → `~/.config/magnetdb/style.json` →
bundled `style.json` → in-code defaults. Every trace from a given source file shares that source's
style regardless of which sensor/field it is.

The user wants finer control: per-field color/dash/marker styling within a group (not just per
source type), while opacity stays a pure per-source knob, exposed through a gear icon on each
group block rather than hand-editing `style.json`.

## Design decisions (from user Q&A)

- **Override key:** `(group_name, raw_sensor_name)`, source-agnostic — one style per field,
  applied regardless of which file it came from.
- **Opacity stays purely per-source** (today's `TraceStyle.opacity`), *not* part of the field
  override — the modal exposes it as a separate section, keyed by source type, not by field.
- **Marker spacing:** full `markevery`-style stride (matplotlib-equivalent), implemented via a
  per-point `marker.size` array (0 = hidden) on the existing trace — no second trace, no change to
  legend/hover wiring.
- **UI:** one `dbc.Modal` per page (not per group), opened and repopulated by whichever gear was
  clicked; Save writes the full merged config back to `~/.config/magnetdb/style.json`.

## Files affected

**Create**
- `apps/dashboards/magnetdb/src/style_editor.py` — shared Dash UI: gear button, modal, and a
  `register_callbacks()` factory each page calls once with its own id prefix.
- `apps/dashboards/magnetdb/tests/style_config_test.py` — schema round-trip, merge-on-save, and
  marker-masking tests.

**Edit**
- `apps/dashboards/magnetdb/src/magnetdb_plot.py` — schema + resolution changes (see Approach).
- `apps/dashboards/magnetdb/src/pages/file_viewer.py` — wire in the gear/modal, add a
  style-version store as a redraw trigger.
- `apps/dashboards/magnetdb/src/pages/overview_records.py` — same wiring.
- `apps/dashboards/magnetdb/PLOT_STYLE.md` — document the new schema and UI.

**Untouched** — `scripts/init_style_config.py` (still writes a valid, backward-compatible file:
only the 6 source-type keys, no `field_overrides`, which the new loader defaults to `{}`).

## Approach

### Phase A — schema & resolution (`magnetdb_plot.py`)

1. Extend `TraceStyle` with `marker_symbol: str | None = None`, `marker_every: int | None = None`.
   Add `FieldStyleOverride` (`color`/`dash`/`width`/`marker_symbol`/`marker_every`, all optional)
   and `StyleConfig` (`file_type_styles: FileTypeStyles`, `field_overrides: dict[str,
   dict[str, FieldStyleOverride]]`) with `to_dict`/`from_dict`/`load_style_config`/
   `save_style_config`.
   → verify: unit test round-trips a populated `StyleConfig`; confirms today's unmodified 6-key
   `style.json` loads fine with `field_overrides == {}`.
2. Extract `resolve_file_type_key(filename)` out of `_resolve_file_style()`. Rewrite
   `_load_default_file_type_styles()` → `_load_default_style_config()` (same env-var →
   user-config → bundled → in-code order, now for `StyleConfig`). Add globals `_STYLE_CONFIG`,
   `FIELD_STYLE_OVERRIDES`, and `reload_style_config()`.
   → verify: re-run the three precedence checks from `PLAN_plot_style_config.md` step 2 against
   the new loader; confirm no-config-file startup still yields today's in-code defaults with empty
   overrides.
3. Add `_resolve_field_override()` + `_apply_style()` (merges base source style with an optional
   field override, builds `line_kwargs`/`marker`/`mode`). Rewire the non-event branches of
   `create_plot()`, `create_comparison_plot()`, `create_annotated_plot()` to use it; leave the
   `is_event` (spike/default/trigger marker) branches untouched, per the existing out-of-scope
   note in `PLAN_plot_style_config.md`.
   → verify: unit tests for `_apply_style()` — no override reproduces today's output exactly; a
   color-only override leaves dash/width/marker/opacity from the source style; a width-only
   override leaves color/dash/marker/opacity from the source style; `marker_every=3` on 10
   points yields nonzero `marker.size` at indices 0,3,6,9 only. Live check: open a real pupitre
   file with no overrides configured — plot must look identical to before this change.

### Phase B — gear UI

4. Write `style_editor.py`: `gear_button(id_prefix, group_name)`, `modal_component(id_prefix)`,
   `register_callbacks(id_prefix, context_fn)` — `context_fn(group_name, ...)` returns the raw
   sensor names and source-type keys relevant to that group, supplied by each page.
   → verify: `python -c "import style_editor"` from `src/` with no errors; confirm its row ids
   can't collide with `{"type": "group-sensors-checklist", ...}` /
   `{"type": "ov-group-sensors-checklist", ...}`.
5. Wire into `file_viewer.py`: gear next to each `html.Summary`, one modal placed in `layout()`,
   `register_callbacks("fv", ...)` at import time, `fv-style-version` store added as an `Input`
   to `update_outputs()`.
   → verify: live check — edit one sensor's color + marker_every in a group, Save, confirm the
   plot redraws with markers every N points on only that sensor's trace.
6. Wire into `overview_records.py` identically (`id_prefix="ov"`), context resolver drawing from
   `db.get_overview_group_entries()`'s `channels` and each contributing file's
   `resolve_file_type_key()`.
   → verify: live check on a record combining pupitre + overview sources — gear lists one row per
   raw channel actually present, and one opacity row per source type contributing to that group.
7. Confirm Save always writes the *entire* merged `StyleConfig`, not just the edited group.
   → verify: with group A already overridden on disk, edit and save group B; confirm the
   resulting JSON still has group A untouched.

### Phase C

8. Update `PLOT_STYLE.md`.
   → verify: re-read against the final code.

## Assumptions & open questions

- **Merged overview-records entries get styled per raw channel, not per merged concept.** E.g.
  `Idcct1` (pupitre) and its aliased `Courant_A1` (pigbrother) are two separate override
  rows/entries, since the field-override key is the raw sensor name. Styling the *merged* concept
  as one entry would require threading each sensor's canonical entry-key through to
  `create_annotated_plot()` — real extra plumbing not obviously worth it here. Say if you'd
  rather have that.
- **"Reset" in the modal** clears only the open group's field overrides, leaving other groups and
  the source-type table untouched.
- **Color picker** uses a plain `dcc.Input(type="color")` (native browser picker) — no new
  dependency.
