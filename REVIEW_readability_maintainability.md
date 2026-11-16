# Readability and maintainability review: to_duckdb and apps/dashboards/magnetdb

Reviewed 2026-11-15 on branch `housing-config-versions` at commit `a15eb7c`.

**Verdict:** both are readable line by line and well tested (about 900 test functions), but the structure is costly to maintain. The main costs are copy-pasted sibling files, a few very large modules and three unrelated styles of database access.

This is based on function-length and duplication measurements, a ruff run, and reading samples of the main modules — not all ~35k non-test lines. I did not run the test suites, and nothing was changed.

## What is in good shape

- **Docstrings**: NumPy style is applied in most modules. [etl_spec.py](to_duckdb/etl_spec.py), [populate.py](to_duckdb/populate.py), [impact.py](to_duckdb/impact.py), [style_editor.py](apps/dashboards/magnetdb/src/style_editor.py) and [magnetdb_analysis.py](apps/dashboards/magnetdb/src/magnetdb_analysis.py) have none or one undocumented public function.
- **Comments explain why**: for example the `supervision:` prefix rationale in [file_viewer.py:680-690](apps/dashboards/magnetdb/src/pages/file_viewer.py#L680-L690).
- **Naming**: no camelCase functions in either tree, and no `global` statements.
- **Small focused modules exist**: [file_context.py](to_duckdb/file_context.py), [record_io.py](to_duckdb/record_io.py), [parallel.py](to_duckdb/parallel.py), [enums.py](to_duckdb/enums.py), [experiment_links.py](apps/dashboards/magnetdb/src/experiment_links.py) and [i18n.py](apps/dashboards/magnetdb/src/i18n.py).
- **Tooling is configured**: ruff, ty and bandit in both `pyproject.toml` files, with comments explaining the flat-import layout.

## Main problems, by maintenance cost

### 1. Copy-pasted sibling files

| File pair | Shared lines |
|---|---|
| [file_viewer.py](apps/dashboards/magnetdb/src/pages/file_viewer.py) / [operational_viewer.py](apps/dashboards/magnetdb/src/pages/operational_viewer.py) | 774 (81% / 86%) |
| [file_viewer.py](apps/dashboards/magnetdb/src/pages/file_viewer.py) / [stats_viewer.py](apps/dashboards/magnetdb/src/pages/stats_viewer.py) | 632 (66% / 83%) |
| [overview_records.py](apps/dashboards/magnetdb/src/pages/overview_records.py) / [defaults_spikes.py](apps/dashboards/magnetdb/src/pages/defaults_spikes.py) | 623 (67% / 60%) |
| [compute_exp_stats.py](to_duckdb/compute_exp_stats.py) / [compute_op_stats.py](to_duckdb/compute_op_stats.py) | 436 (72% / 74%) |
| [magnet_stats.py](apps/dashboards/magnetdb/src/pages/magnet_stats.py) / [part_stats.py](apps/dashboards/magnetdb/src/pages/part_stats.py) | 425 (66% / 46%) |
| [magnet_stats.py](apps/dashboards/magnetdb/src/pages/magnet_stats.py) / [assembly_stats.py](apps/dashboards/magnetdb/src/pages/assembly_stats.py) | 354 (55% / 49%) |

Every fix to zoom handling, CSV download or sensor menus has to be made in up to three places. The copies have already drifted: `compute_scalars` uses `field.abs() > FIELD_THRESHOLD` in the exp version and a signed comparison in the op version. I can't tell whether that difference is intended, which is itself the problem.

### 2. Very large modules and functions

- [crud.py](to_duckdb/crud.py) is 4619 lines and 115 functions covering materials, parts, magnets, assemblies, housing config, overview records, the operation log and printing. Its hand-maintained "Public API" docstring is another thing to keep in sync.
- [magnetdb.py](to_duckdb/magnetdb.py) is 3123 lines, and `build_parser` alone is 869 lines ([magnetdb.py:2240](to_duckdb/magnetdb.py#L2240)).
- [magnetdb_analysis.py](apps/dashboards/magnetdb/src/magnetdb_analysis.py) is 3144 lines mixing SQL queries, file loading, signal processing, group ordering and a timing decorator.
- Dash callbacks are long: `update_housing_stats` is 235 lines, `update_outputs` in the file viewer 198, `update_graphs` in defaults/spikes 180 with 13 parameters.
- Elsewhere: `validate_fast_from_pupitre` is 329 lines and `compute_hoop_stress_history` 234.
- Ruff's complexity rules (not enabled in your config) flag 67 functions as too complex and 83 with too many arguments.

### 3. Database access has no single home

- [magnetdb_analysis.py](apps/dashboards/magnetdb/src/magnetdb_analysis.py) opens 54 separate `duckdb.connect` calls with inline SQL.
- Four pages bypass it and open their own connections; [housing_stats.py](apps/dashboards/magnetdb/src/pages/housing_stats.py) does so 7 times.
- The dashboard shares no code with to_duckdb, so table and column names and status lists are duplicated. `ASSEMBLY_STATUSES` at [magnetdb_analysis.py:437](apps/dashboards/magnetdb/src/magnetdb_analysis.py#L437) repeats [enums.py](to_duckdb/enums.py).
- A schema change therefore means grepping SQL strings across both trees. Checks like `_geometry_problem_column(conn)` suggest the dashboard is already compensating for schema versions by hand.

### 4. Private names used across modules

There are about 56 uses of underscore-prefixed names from another module. Examples:

- [crud.py:74](to_duckdb/crud.py#L74) imports `_NAME_ONLY_TYPES` from populate.
- [etl_spec.py:24](to_duckdb/etl_spec.py#L24) and [compute_hoop_stats.py:48](to_duckdb/compute_hoop_stats.py#L48) import `_log_operation` and `_housing_config_dict` from crud.
- Pages read `plot._STYLE_CONFIG`.

These names are public in practice. Either rename them or move them to a shared module ([config.py](to_duckdb/config.py) for `_RECORDS_BASE`, `_SRV_SUBDIR`, `_PBSURV`).

### 5. `print` instead of logging

[crud.py](to_duckdb/crud.py) has 147 `print` calls, and only three modules import `logging`. Dashboard callbacks print to stdout and there is a hand-rolled `chrono_callback` timer. This makes output hard to silence in tests and hard to filter on the server.

### 6. Broad exception handling

There are 40 `except Exception` handlers, 21 of them in [crud.py](to_duckdb/crud.py). Ruff's `BLE` rule is selected in your config, so these are live lint failures today.

## Smaller items

- **Mixed comment language**: French comments remain in [file_viewer.py](apps/dashboards/magnetdb/src/pages/file_viewer.py) (18), [operational_viewer.py](apps/dashboards/magnetdb/src/pages/operational_viewer.py) (17) and [magnetdb_plot.py](apps/dashboards/magnetdb/src/magnetdb_plot.py) (13); the rest is English.
- **Lint debt**: 219 ruff findings under your own rule set, 105 auto-fixable (import order, trailing whitespace). [magnetdb.py:166-193](to_duckdb/magnetdb.py#L166-L193) has nine separate `from populate import (` blocks.
- **Undeclared dependencies**: the dashboard imports `pint`, `scipy` and `natsort`, none of which are in its [pyproject.toml](apps/dashboards/magnetdb/pyproject.toml). They probably arrive through python_magnetrun, but I did not confirm that.
- **Stale paths in UI text**: pages show `to_duckdb/venv-systempackages/bin/python3 ...` hints, and the default `DB_PATH` points at `/workspaces/...`.
- **Likely dead code**: [magnetdb_metrics.py](apps/dashboards/magnetdb/src/magnetdb_metrics.py) is a 3-line stub and `pages_disabled/` holds about 900 lines. [inspect_summary.py](to_duckdb/inspect_summary.py) and [test_assembly_stats.py](to_duckdb/test_assembly_stats.py) are top-level scripts with no functions.
- **Page docstrings**: the three viewer pages each have 13 undocumented public functions, mostly callbacks.
- **Repository clutter**: 26 `PLAN_`/`PROMPT_`/`NOTES_` files and five `.duckdb` files sit next to the source in to_duckdb, and 16 PLAN files in the dashboard. A `plans/` folder would make the code easier to find.

## Recommended order of work

1. **Extract shared viewer code**: one module for the zoom, CSV download and sensor-menu logic used by the three viewer pages, then the same for overview/defaults-spikes. This removes the most lines for the least risk, since the tests already exist.
2. **Merge the common part of the two stats scripts** into one module, and settle the `field.abs()` difference while doing it.
3. **Split [crud.py](to_duckdb/crud.py) by entity** (materials/parts, magnets, assemblies, overview records, operation log), keeping `crud` as a re-exporting facade so callers don't break. Split `build_parser` the same way, one function per entity.
4. **Give the dashboard one connection helper** and move the page-level SQL into the analysis layer.
5. **Run `ruff check --fix`** for the 105 mechanical fixes, then decide whether to enable a complexity rule to stop new 200-line callbacks.
6. **Replace `print` with `logging`** module by module, as you touch each file.

None of this is urgent for correctness. Items 1 and 2 are the place to start because the duplication is where a bug is most likely to be fixed in one copy and missed in the others.
