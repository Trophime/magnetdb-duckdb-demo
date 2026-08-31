# Sensor group display order: bundled default + overridable group_order.json

**Status:** Approved and implemented 2026-08-31. `order_groups()` + 2-tier config resolution
(`~/.config/magnetdb/group_order.json` > bundled `src/group_order.json` > no reordering) added to
`magnetdb_analysis.py`; applied in `get_overview_group_entries()` and in `file_viewer.py:170`.
Bundled `group_order.json` seeded `[]` (no-op). `init_group_order.py` helper added and verified
end-to-end against real data in `to_duckdb/test-magnetdb.duckdb` (`M10`, pupitre file
`2018.02.21 - 10:18:54.txt`) — correctly wrote 10 discovered group names
(`Courants_Alimentations`, `Donnees_Calculees_Monitoring`, `Donnees_Calculees_Refroidissement`,
`Hydraulics`, `Magnetic_Field`, `Pressures_Hydraulics`, `Puissances`, `Pumps`, `Refroidissement`,
`Tensions_Aimant`). `group_order_test.py` (3 tests) plus the full existing suite (24 total,
excluding the pre-existing, unrelated `hoop_test.py` collection failure caused by a hardcoded
`/workspaces/...` path) pass.

## Goal

`file_viewer.py` and `overview_records.py` display sensor-group blocks (the `📂 <group>`
`html.Details` sections) in a configurable order, instead of `file_viewer.py`'s current raw
file-insertion order and `overview_records.py`'s current alphabetical order. Groups not listed in
the config keep their current relative order and are appended after the listed ones.

## Context / background

- `file_viewer.py:170` loops `for group_name in mrun.MagnetData.list_groups():` — that list is
  just the insertion order of `MagnetData.Groups` (`magnetdata_base.py:251-259`), itself whatever
  order the TDMS/pandas parser produced. No sorting happens today.
- `overview_records.py:190` loops `group_entries.items()`, where `group_entries` comes from
  `magnetdb_analysis.get_overview_group_entries()` (`magnetdb_analysis.py:792-902`), which builds
  its `entries` dict via `sorted(pupitre_columns)` then `sorted(tdms_columns)` — alphabetical,
  pupitre-vocabulary groups first.
- User-confirmed design choices (2026-08-31):
  - Order lives in a **JSON config file**, following the existing `style.json` precedent
    (`magnetdb_plot.py:276-312`, documented in `PLOT_STYLE.md`): a bundled default shipped next to
    the module, overridable by `~/.config/magnetdb/group_order.json`. No YAML — nothing else in
    this app uses YAML.
  - **Fallback rule:** a group absent from the config list keeps its original relative order and
    is appended after all explicitly-ordered groups (not re-sorted alphabetically).
  - Added on approval: a small helper script (mirroring
    `apps/dashboards/magnetdb/scripts/init_style_config.py`) to generate a real, populated starting
    `group_order.json` from actual data, since there's no in-code canonical list of group names to
    seed the bundled file from (unlike `style.json`'s `FileTypeStyles()` dataclass defaults).
- The two pages don't necessarily share group-name vocabulary (`file_viewer.py` uses the raw
  per-file TDMS/pandas group names; `overview_records.py` is keyed on pupitre's group vocabulary
  first, tdms-only leftovers under their own tdms names). Both spellings need to be present in
  `group_order.json` for consistent ordering across both pages if they diverge for the same
  physical group — a config-content concern for the user to resolve when editing the file, not a
  code one.

## Files affected

**Create**
- `apps/dashboards/magnetdb/src/group_order.json` — bundled default, seeded as `[]` (a no-op:
  preserves today's behavior until populated).
- `apps/dashboards/magnetdb/scripts/init_group_order.py` — helper script: loads one or more real
  data files via `magnetdb_analysis.get_overview_group_entries()`, writes the discovered group
  names (today's natural order) to a JSON file. `--file` (repeatable), `--housing`, `--output`/`-o`
  (default `~/.config/magnetdb/group_order.json`, matching `init_style_config.py`'s convention of
  writing the user-override location), `--force`/`-f`.
- `apps/dashboards/magnetdb/tests/group_order_test.py` — unit tests for `order_groups()`.

**Edit**
- `apps/dashboards/magnetdb/src/magnetdb_analysis.py`
  - Add `_USER_GROUP_ORDER_PATH` / `_BUNDLED_GROUP_ORDER_PATH` + `_load_group_order()` (2-tier:
    user path, else bundled path, else `[]`; errors reported via `print(...)`, matching this
    file's existing convention rather than `magnetdb_plot.py`'s `logger`-based one).
  - Add `_GROUP_ORDER = _load_group_order()` module constant.
  - Add `order_groups(group_names)`: listed groups first in config order, unlisted groups keep
    original relative order and are appended after. Full NumPy-style docstring.
  - Apply `order_groups()` at the end of `get_overview_group_entries()` before returning; update
    its `Returns` docstring section (currently claims alphabetical ordering).
- `apps/dashboards/magnetdb/src/pages/file_viewer.py`
  - `file_viewer.py:170`: `for group_name in mrun.MagnetData.list_groups():` →
    `for group_name in db.order_groups(mrun.MagnetData.list_groups()):`.

## Approach

1. Write this plan note. → verify: file exists at the path above.
2. Add `order_groups()` + config-loading constants to `magnetdb_analysis.py`, apply in
   `get_overview_group_entries()`. → verify: `group_order_test.py` passes.
3. Create bundled `group_order.json` seeded `[]`. → verify: `_load_group_order()` returns `[]` by
   default (no user override present), so `order_groups()` is a no-op — existing dashboard
   behavior unchanged.
4. Update `file_viewer.py:170` to call `db.order_groups(...)`. → verify: manual check — page still
   renders all groups with `_GROUP_ORDER` empty.
5. Add `init_group_order.py` helper script. → verify: run it against a real file/housing from
   `test-magnetdb.duckdb`, confirm it writes a JSON list of the file's actual group names.
6. Add `group_order_test.py` covering: listed groups win in config order; unlisted groups keep
   relative order and land after; empty config is a no-op.

## Verification

- `pytest apps/dashboards/magnetdb/tests/group_order_test.py` → all pass.
- Run `init_group_order.py` against a real record, then hand-edit the output to reorder two
  groups; reload `file_viewer` and `overview_records` for that record/file and confirm the
  `Details` blocks render in the edited order, with any group left out of the file still appearing
  (after the ordered ones).

## Assumptions & open questions

- No hot-reload/UI editor for this config (unlike the style editor's Save-triggered
  `reload_style_config()`) — not requested, out of scope.
- `init_group_order.py`'s default `--output` writes the **user override** path
  (`~/.config/magnetdb/group_order.json`), not the bundled `src/group_order.json` — matching
  `init_style_config.py`'s existing convention. Editing the bundled file directly is also
  possible via `--output`.
