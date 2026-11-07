# Plan: configurable file-check rules, tags and colours

**Status (2026-11-05): approved; steps 1–4 done** (see Results). Steps 5–6
wait for the new DB being rebuilt into `to_duckdb/`.

Related:
- [PLAN_pupitre_etl_spec.md](PLAN_pupitre_etl_spec.md): the spec-driven
  pupitre ETL whose hard-coded current check (`max |IH − Icoil2| ≤ 5 A`) this
  plan replaces with rules; its follow-up "current check tolerance during
  transients" is addressed by `stat: p99_abs`.
- [PLAN_magnet_geometry_check.md](PLAN_magnet_geometry_check.md): the
  geometry-problem colour `#f8d7da`; missing dates use `#fff3cd`.

## Goal

Each pupitre experiment file is checked against the rules defined for its
housing, its assembly and its magnets. A rule is a free expression plus a
tolerance. A failed rule attaches a formatted tag to the file. In the
dashboards, the tag's own colour shows in the file selector, the experiment
tables and the graph viewer. Tag colours never reuse the geometry-problem or
missing-date colours.

## Decisions

| Topic | Decision |
|---|---|
| Rule levels | **housing**, **assembly**, **magnet** (assembly + magnet). A rule applies to every housing version unless it is restricted to one (`--version V`). A file's rule list follows the existing lookup: file → assembly → housing version at the file start → magnets |
| Override | Same rule name at several levels: magnet over assembly over housing; at one level, a version-specific rule over an all-versions one. Two magnets of one assembly cannot share a rule name |
| Expression | Free expression evaluated with `DataFrame.eval` after `rename` and `add`, before `remove`. It may use raw columns (`Idcct1`, `Icoil2`), added fields (`IH`, `IB`, `UH`, `UB`) and renamed names (`FlowH`, `TinH`, …); the original name of a renamed column (`Flow1`) no longer exists. Parsed when the rule is added; `@` variables, assignments and backtick names are refused; at least one column |
| Statistic | `stat` ∈ `max_abs`, `p99_abs`, `mean_abs` of the expression's values (NaN ignored), compared with `tol` (`value ≤ tol` passes). A rule whose columns are missing gives `ok: None` |
| Tag format | `^[a-z]+:[a-z0-9_]+$` (`<category>:<name>`); a rule's tag must exist in `tags`. A rule's tag is optional: without one, its result is only stored in `etl_checks` |
| Seeded tag | `check:channel_not_empty` (`#e2d9f3`, severity 1), created by `ensure_schema`, attached to a failed built-in `channel` check, one row per channel (`rule` = `ch<n>`, `value` = largest non-zero field, `tolerance` = 0). It cannot be removed |
| Colours | `#rrggbb`, one per tag; `tag add`/`tag update` refuse `#f8d7da`, `#fff3cd` and a colour another tag uses |
| Several tags | The highest `severity` sets the colour; the tooltip lists them all |
| `housing_version` check | Not tagged; stays in `etl_checks` |
| Current check | Removed from the spec (format version 2): magnet entries lose `current`; the check becomes a rule, e.g. `IH_vs_Icoil2`: `IH - Icoil2`, `max_abs`, 5 A. No migration: no DB has stored magnet entries (none of the DBs in `to_duckdb/`, and the new DB is built from scratch) |
| Naming | The spec's per-magnet entry (`channels`, `remove`, `add`) is the **magnet wiring**: `set_magnet_part` → `set_magnet_wiring`, `etl set-magnet … <wiring.json>`. **Rules** are the checks; **checks** are their results |
| Sources (later) | Rules carry `sources` (default `["pupitre"]`) and `applies_to` (default `experiments`); anything else is refused for now. A multi-source rule will name columns as `` `pupitre.Idcct1` `` (follow-up) |
| CLI | New top-level domains `tag add\|update\|list\|remove` and `rule add\|remove\|show` (`check` is the consistency check) |

## Storage (DuckDB)

- `tags(name PK, color, severity, description)`
- `check_rules(id PK, name, housing, assembly_name, magnet_name,
  housing_version, expr, stat, tol, unit, tag, sources, applies_to,
  description)`: `housing` set for a housing rule, `assembly_name` for an
  assembly rule, `assembly_name` + `magnet_name` for a magnet rule;
  `housing_version` NULL = all versions
- `record_tags(record_table, record_key, tag, rule, value, tolerance,
  tagged_at)`, PK `(record_table, record_key, tag, rule)`;
  `record_key` is text (`experiments.id`; later `overview_records.filename`).
  Re-checking a file replaces its rows
- The exported JSON spec (format version 2) carries the merged `rules` list,
  each with its `scope` (`housing`, `assembly`, `magnet:<name>`)

No foreign keys on the new tables: references are checked in code (DuckDB
foreign keys don't cascade and restrict updates of referenced rows).

## Files affected

| File | Action |
|---|---|
| `PLAN_file_check_rules.md` | create: this plan |
| `python_magnetrun/python_magnetrun/runetl.py` | edit: `rules` in `PupitreEtlSpec` (format 2), `check_rule`, `rule_columns`, `_rule_checks` replaces `_current_checks`; `ICOIL_CHECK_ATOL` and `current` removed |
| `python_magnetrun/python_magnetrun/etl_cli.py` | edit: `etl show` prints the rules |
| `python_magnetrun/tests/test_runetl.py` | edit |
| `python_magnetrun/README.md` | edit: ETL section (rules instead of the `Icoil` check) |
| python_magnetrun submodule | bump |
| `to_duckdb/schema.py` | edit: `tags` (seeded), `check_rules`, `record_tags` |
| `to_duckdb/etl_spec.py` | edit: `set_magnet_wiring`, tag and rule functions, rules merged into the spec |
| `to_duckdb/magnetdb.py` | edit: `tag`, `rule` domains; `etl set-magnet` wording |
| `to_duckdb/check_experiment_files.py` | edit: `--etl` writes `record_tags` |
| `to_duckdb/tests/test_etl_spec.py`, `test_check_experiment_files.py`, `test_magnetdb.py` | edit |
| `to_duckdb/tests/test_tags.py` | create |
| `to_duckdb/docs/schema.md`, `PLAN_pupitre_etl_spec.md` | edit |
| `apps/dashboards/magnetdb/src/magnetdb_analysis.py` | edit: `get_file_tags(...)` (empty on an older DB) |
| `apps/dashboards/magnetdb/src/dash_selectors.py` | edit: tag colour style and tooltip helpers |
| `apps/dashboards/magnetdb/src/pages/file_viewer.py` | edit: coloured `dd-file` labels, note under the selector |
| `apps/dashboards/magnetdb/src/pages/{assembly_stats,magnet_stats,part_stats,stats_research_area}.py` | edit: Experiment cell colour and tooltip |
| `apps/dashboards/magnetdb/tests/…` | edit / create |

## Approach / verification

1. Baseline → verify: `to_duckdb`, python_magnetrun and dashboard tests
   pass; counts recorded.
2. Tests first (rule evaluation, merging, tag name/colour validation, tag
   replacement on re-check) → verify: they fail.
3. python_magnetrun rule evaluation → verify: `test_runetl` passes; on M9
   `2026.05.15 - 13:05:36`, `IH - Icoil2` gives max_abs ≈ 13.2 A and
   p99_abs < 5 A.
4. Schema, `etl_spec`, CLI, `--etl` writing tags → verify: `to_duckdb`
   tests pass.
5. On a scratchpad copy of the new DB in `to_duckdb/`: add M9 rules
   (`IH_vs_Icoil2`, `A1_vs_A2`, `A3_vs_A4`, tolerances measured first), run
   `check_experiment_files.py --etl --recheck --assembly <M9 assembly>` →
   verify: failing files get `record_tags` rows, passing files none; a
   non-empty removed channel gets `check:channel_not_empty`.
6. Dashboard → verify: dashboard tests pass; the user checks colours,
   tooltips and note in the running app.
7. Docs, this plan → verify: `magnetdb.py tag --help`, `rule --help` read
   correctly.

### Results (2026-11-05)

1. Baseline: `to_duckdb` 709 passed, 3 skipped. python_magnetrun 1409
   passed, plus 10 failed / 24 errors already there (`test_magnetdata.py`,
   `test_magnetdata_polars.py`, `test-plateau.py`, untouched here).
2. New tests failed (no `rules` argument, no `etl_spec` tag/rule functions).
3. python_magnetrun: `test_runetl` 63 passed; full suite 1428 passed, same
   10 failed / 24 errors. On M9 `2026.05.15 - 13:05:36` (housing-only spec +
   rules): `IH - Icoil2` max_abs 13.18 A (fails 5 A), p99_abs 1.18 A, mean_abs
   0.07 A. First measurement for step 5: `Idcct1 - Idcct2` max 36.3 A, p99
   14.1 A, mean 3.6 A; `Idcct3 - Idcct4` max 30.2 A, p99 8.9 A, mean 1.4 A.
4. `to_duckdb`: 755 passed, 3 skipped, after adding `tags`, `check_rules`,
   `record_tags` to `EXPECTED_TABLES` in `tests/test_schema.py` (approved
   separately).

Deviations from the file list above:

- Read-only lookups (`etl show`/`export`, `tag list`, `rule show`) treat a
  missing `tags`/`check_rules` table as empty, so DBs built before this
  change keep working; `tag`/`rule` write commands run `ensure_schema`.
- Tag changes (`add`/`update`/`delete`) are logged in `operation_log` like
  rule changes.

## Follow-ups (each needs its own plan and approval)

- **Rules and tags for `operationaldata` (pigbrother TDMS):** needs a
  pigbrother ETL spec (or rules on raw TDMS channel names) per housing
  version, assembly and magnet. Then `record_tags` rows with
  `record_table = 'operationaldata'`, coloured `opv-file` options and a note
  in the operational viewer.
- **Cross-source checks** (pupitre, pigbrother, Hybrid, SUPERVISION) for
  `overview_records`: a merged DataFrame on a common time base (after
  clock-lag correction, #27 / S2), with columns named `<source>.<name>`.
  Then rules with several `sources` run, and `record_tags` gets rows with
  `record_table = 'overview_records'`. After the pigbrother ETL spec.
- **Manual tags** (a user tags a file by hand), once a tag list exists.
