# Per-user plot style (browser localStorage) with export/import

**Status:** Approved and implemented 2026-10-22. The user chose the defaults for export (user
layer only) and import (replace), plus a "Reset all" button. `pytest tests/` gives 136 passed
(115 before, plus 21 in `user_style_test.py`). The step-7 manual check was run as a scripted
headless-Chrome session (22 checks), against both `python magnetdb_app.py` and the Docker image
with `WORKERS=2` and a read-only site `style.json`; all passed. Both assumptions held: the
localStorage store is read by the first render after a reload, and nothing is written under
`$HOME/.config`.

## Goal

Each browser keeps its own plot-style customizations (per-group field overrides and per-source
opacity) in `localStorage`, layered over read-only server defaults. A user's edits no longer
affect other users. The dashboard never writes style files at runtime. Users can export their
styles to a JSON file and import them again, on another browser or from a colleague.

## Context / background

Came out of reviewing a Docker deployment on a dedicated machine, where several users share one
container. Today the style editor (⚙ modal, `style_editor.py`) saves to the server's
`~/.config/magnetdb/style.json` (`/home/jovyan/.config/magnetdb/style.json` in the container) and
calls `reload_style_config()`. That causes four problems:

1. **Shared, last-write-wins.** Every user sees every other user's edits.
2. **Stale with `WORKERS>1`.** `reload_style_config()` only refreshes the gunicorn worker that
   handled the save. The other workers keep the old module globals until a restart.
3. **Write permission on the mount.** If the host folder for `-v ~/.config/magnetdb:...` doesn't
   exist, Docker creates it as root. The container user (uid 1000) then can't write, and Save
   fails. The same happens if the host user's uid isn't 1000.
4. **Edits seem lost when `$MAGNETDB_FILE_TYPE_STYLES` is set.** Saves go to the user file, but
   on reload the env-var file wins.

The pages already redraw through a per-page `{prefix}-style-version` store (`fv`, `sv`, `ov`,
`ds`). It is an `Input` of each figure callback and drives the "maintain zoom" logic. This plan
keeps that trigger and adds the style data itself as a `State`.

### Alternatives considered

- **Cookie instead of localStorage.** Simpler plumbing: the plot functions could read
  `flask.request.cookies` directly (like `i18n`), so no page callback would change. Rejected
  because of size. A cookie holds about 4 KB, and the value must be percent- or base64-encoded
  (+30%). The modal saves every sensor of a group with color, dash and width filled in, which is
  roughly 55 B per field. A handful of groups would exceed the limit, and the browser would then
  silently drop the cookie. The cookie would also be sent with every HTTP request, including
  assets.
- **Keep server files, fix #2–#4 in place.** Still one shared style for everyone, so it doesn't
  solve the main problem.
- **Language and database selection stay as they are** (cookies): language must be known when
  the server builds the layout. Out of scope.

## Design

**Resolution order** (later layers override earlier ones):

1. In-code `StyleConfig()` defaults → bundled `src/style.json`. Unchanged.
2. Site layer: `$MAGNETDB_FILE_TYPE_STYLES` or `~/.config/magnetdb/style.json`, loaded once at
   import. Unchanged, but now **read-only**: only edited by hand, by whoever runs the server.
3. User layer: `dcc.Store(id="user-style", storage_type="local")`, per browser.

**User-layer format** is the same schema as `style.json`, but partial, so an exported file is also
a valid site `style.json`:

```json
{
  "pupitre": {"opacity": 0.6},
  "field_overrides": {"Field": {"Ucoil1": {"color": "#d62728", "width": 3}}}
}
```

**Merge rules** (`merge_style_config`), applied to dicts before `StyleConfig.from_dict`.
`FileTypeStyles.from_dict` fills missing keys from in-code defaults, not from the site layer, so
merging must happen at the dict level first:

- Source-type keys: property-by-property update of the site style.
- `field_overrides`: a user group **replaces** the site group as a whole, which matches how Save
  writes a whole group.

## Files affected

**Create**
- `apps/dashboards/magnetdb/tests/user_style_test.py` — merge, plot, and editor-callback tests.

**Edit**
- `apps/dashboards/magnetdb/src/magnetdb_plot.py`
  - Add `merge_style_config(base: StyleConfig, user_data: dict | None) -> StyleConfig`.
  - `_resolve_file_style(filename, config)` and `_resolve_field_override(group_name, sensor,
    config)` take the config explicitly instead of reading module globals.
  - `create_plot`, `create_annotated_plot` and `_add_incident_overlays` gain
    `style_config: StyleConfig | None = None`; `None` means the server config.
    `create_comparison_plot` is only used in `pages_disabled/`; it keeps the `None` default.
  - Remove `reload_style_config()` and the `FILE_TYPE_STYLES` / `FIELD_STYLE_OVERRIDES` globals,
    which this change leaves unused. Keep `_STYLE_CONFIG`, loaded once.
  - Update the NumPy docstrings of every touched function.
- `apps/dashboards/magnetdb/src/magnetdb_app.py` — add
  `dcc.Store(id="user-style", storage_type="local")` to `serve_layout()`.
- `apps/dashboards/magnetdb/src/style_editor.py`
  - `_field_row` and `_source_opacity_row` take the merged config instead of the globals.
    `_open_style_modal` gets `State("user-style", "data")`.
  - Save and Reset output `Output("user-style", "data")` (`allow_duplicate=True`) plus the
    version bump. They no longer call `save_style_config` or `reload_style_config`.
    `_updated_file_type_styles` returns only the opacity delta for the user layer.
  - **Export:** an "Export" button in the modal footer and a `dcc.Download(id=f"{prefix}-style-export")`
    in `modal_component`. It downloads the user layer as `magnetdb-style.json`.
  - **Import:** a `dcc.Upload(id=f"{prefix}-style-import")` "Import" button in the footer. The
    file is validated with `StyleConfig.from_dict` (a `TypeError`, `KeyError` or `ValueError`
    shows an error `dbc.Alert` in the modal and leaves the store unchanged). On success it
    **replaces** the user layer and bumps the version so the page redraws.
  - **Reset all:** a "Reset all" button in the modal footer, next to Reset. Unlike Reset, which
    clears one group, it sets the user layer to `{}` (back to the site defaults for every group
    and source), bumps the version and closes the modal. The button is wrapped in a
    `dcc.ConfirmDialogProvider` ("Discard all your style changes? Export them first to keep a
    copy."), and the callback fires on its `submit_n_clicks`.
- `pages/file_viewer.py`, `pages/stats_viewer.py`, `pages/overview_records.py`,
  `pages/defaults_spikes.py` — the figure callback adds `State("user-style", "data")` and passes
  `style_config=plot.merge_style_config(plot._STYLE_CONFIG, user_style)` to its `create_plot`
  call(s) (3 in `file_viewer`) or `create_annotated_plot` call.
- `apps/dashboards/magnetdb/tests/style_config_test.py` — adapt tests that rely on the removed
  globals or `reload_style_config`, if any.
- `apps/dashboards/magnetdb/README.md` — "User config files": the server `style.json` becomes a
  read-only site default, styles are per browser, and how to export/import. The Docker
  `~/.config/magnetdb` mount becomes `:ro`.
- `apps/dashboards/magnetdb/PLOT_STYLE.md` — the new resolution order and user layer.
- `scripts/run_docker.sh` — mount `~/.config/magnetdb` read-only (`:ro`).

## Approach

1. Write `tests/user_style_test.py` first:
   - merge: source-key property update, group replacement, `None` or `{}` user layer returns
     the base unchanged;
   - `create_plot` and `create_annotated_plot` use an explicit `style_config` color;
   - the editor's save, reset-all, import and export callbacks (called directly, like
     `database_cookie_test.py` exercises the app) return the expected store data, reject a
     malformed import, and never write under `$HOME`.

   → verify: `pytest tests/user_style_test.py` fails for the expected reasons;
   `pytest tests/` (excluding the new file) passes, as a baseline.
2. `magnetdb_plot.py`: merge function, explicit-config resolvers, `style_config` arguments,
   remove the unused globals and `reload_style_config`.
   → verify: the merge and plot tests pass; `pytest tests/style_config_test.py` passes after any
   adaptation.
3. `magnetdb_app.py`: add the `user-style` store.
   → verify: `/_dash-layout` contains `user-style` with `storage_type == "local"` (a test using
   the `_find_component` helper pattern).
4. `style_editor.py`: read the merged config, save and reset into the store, reset all, export
   and import.
   → verify: the editor-callback tests pass; `grep -n "save_style_config\|reload_style_config"
   src/style_editor.py` returns nothing.
5. The four pages: add `State("user-style")` and pass `style_config`.
   → verify: full `pytest tests/` passes; `grep -rn "FILE_TYPE_STYLES\|FIELD_STYLE_OVERRIDES"
   src/` only matches `magnetdb_plot.py` internals or docs.
6. Docs and `run_docker.sh`.
   → verify: re-read the diffs; `bash -n scripts/run_docker.sh`.
7. Manual end-to-end check (`python magnetdb_app.py`, then the Docker image with `WORKERS=2` and
   the `:ro` mount):
   - a style saved in a normal window is not visible in a private window or another browser;
   - after a reload, the style is kept and the zoom-keeping behaviour on save is unchanged;
   - export, clear site data, import: the style comes back;
   - a malformed JSON import shows the error and leaves the style unchanged;
   - "Reset all" asks for confirmation; Cancel changes nothing, OK restores the site defaults on
     every group;
   - Save works with the read-only mount, and nothing is written under `/home/jovyan/.config`.

## Assumptions & open questions

- **Assumption: the stored style is ready before the first page callbacks run.** A
  `dcc.Store(storage_type="local")` loads its saved value when it mounts, so the first figure
  callbacks already see it as `State`. To confirm in step 7. If it doesn't hold, use the store's
  `modified_timestamp` as an extra `Input`.
- **Assumption: existing style edits on the server need no migration.** Edits users already made
  in the server's `~/.config/magnetdb/style.json` become the shared site default and stay
  visible to everyone. They can then only be changed by editing the file.
- **Decided: export the user layer only.** Import then restores exactly what the user set.
- **Decided: import replaces the current user layer** rather than merging into it.
- **Decided: add "Reset all".** Assumption: it asks for confirmation through
  `dcc.ConfirmDialogProvider`, because it discards everything at once. Drop the confirmation if
  you'd rather keep it to one click.
- **Accepted limitation: per browser, not per person.** Another browser or machine starts from
  the site defaults until the user imports their file.
- **Out of scope:** per-user `group_order.json`; language and database persistence; the records
  mount path issue (`MAGNETDB_RECORDS_DIR` is not used).
