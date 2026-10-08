# Plan: Track the impact of `update` commands on derived results

**Status (2026-10-08).** Approved 2026-10-08. Follow-ups at the end each
need their own plan and approval.

## Goal

Every `update` command records what it changed (old → new) and marks the
hoop-stress results that depend on it as **stale**; `hoop-stress compute`
recomputes exactly those, with one bin configuration per experiment.
Correcting a part's material works on linked parts, `material update`
exists, and `magnet add` refuses to change an existing magnet.

## Background

- `part update` with a `material` block failed on any part linked to a
  magnet (`ConstraintException … key "part_name: HybridSupra" is still
  referenced`). `parts.material_name` is a foreign key, hence indexed;
  DuckDB runs an `UPDATE` of an indexed column as DELETE + INSERT, and the
  DELETE trips the `magnet_parts → parts` foreign key — even when the value
  is unchanged. Detaching the child rows inside one transaction does not
  help (DuckDB checks foreign keys eagerly).
- A material change is the correction of a wrong assignment: no history is
  needed, so the foreign key is dropped and the check moves to Python
  (`delete_material` already guards in Python).
- Stored hoop-stress results depend on more than the part itself: the total
  field B couples every coil of an assembly, so a change on one part can
  affect the stresses of all parts of every assembly containing it.
- `hoop_stress_bin_stats` / `hoop_stress_fatigue_bins` have no `bin_config`
  column and are written with `INSERT OR REPLACE` only, so a run with other
  bins left overlapping rows, and `--reprocess` left rows of bins that
  became empty. Readers sum every row, so durations and means were inflated.

## Decisions

| Topic | Decision |
|---|---|
| Stale results | **Marked**, not deleted: `stale_since` / `stale_reason` (an `operation_log.id`) on `hoop_stress_processed`. `compute` recomputes stale rows. |
| Bin configurations | One per experiment. Same bins and not stale → skip. Different bins without `--reprocess` → skip with a warning. With `--reprocess` (or stale) → delete all hoop rows of the experiment, then insert, in one transaction after the computation succeeded. |
| `parts.material_name` | No foreign key; `insert_part` / `update_part_from_json` check the material exists. |
| `material update` | New. Any property change marks results stale (refinement per property is a follow-up). |
| `magnets.geometry_data` | A change through `magnet update` marks results stale. |
| `magnet add` on an existing magnet | Refused when its parts (names or order) differ; identical content is accepted. |
| Change journal | Every update logs `{"changes": {field: [old, new]}, "stale": {...}}` to `operation_log`; `geometry_data` is logged as `"changed"`. Unchanged fields are neither rewritten nor logged. |
| Geometry changes | Detected on content (`geometry_data`), not on the path (`geometry`). |

## Impact of each command

| Command | Changes that mark results stale | Scope |
|---|---|---|
| `material update` | any property | hoop stats of every assembly containing a part made of that material |
| `part update` | `material_name`, `geometry_data` | assemblies of every magnet holding the part |
| `magnet update` | `geometry_data` | assemblies containing the magnet |
| `assembly update-magnet` | `z_offset`, `commissioned_at` | that assembly |
| `assembly update` | — (description only) | logged only |
| `assembly decommission` | — | report: experiments, operational data and overview records dated after the new `decommissioned_at` still assigned to the assembly |
| `*-status` | — | status is read live, nothing stored depends on it |

## Files

| File | Action |
|---|---|
| `to_duckdb/schema.py` | edit — drop FK on `parts.material_name`; add `stale_since`, `stale_reason` to `hoop_stress_processed`; update its comment |
| `to_duckdb/impact.py` | create — dependency map, scope resolvers, `mark_hoop_stale`, `decommission_report` |
| `to_duckdb/crud.py` | edit — `_log_operation` returns the id; `insert_part` check; diff/log/stale in the update functions; `update_material_from_json`; decommission report |
| `to_duckdb/compute_hoop_stats.py` | edit — `_delete_hoop_rows`; stale-aware skip; one bin configuration per experiment |
| `to_duckdb/magnetdb.py` | edit — `material update` subcommand; `_magnet_conflicts` refusal in `_add_magnet` |
| `to_duckdb/tests/test_impact.py` | create |
| `to_duckdb/tests/test_crud.py`, `test_compute_hoop_stats.py`, `test_add_magnet.py` | edit |

## Steps

0. Write this file → verify: exists, 15 follow-ups.
1. FK and `insert_part` check → verify: material change on a linked part succeeds; unknown material raises `ValueError`.
2. `_log_operation` returns the id → verify: new test, existing log tests pass.
3. Hoop compute: replace semantics, stale-aware skip → verify: different bins skip / replace, emptied bin leaves no old row, stale row recomputed and cleared.
4. `impact.py` → verify: resolvers find assembly A and not B; `mark_hoop_stale` marks only A; `dry_run` changes nothing.
5. Wire `part`, `magnet`, `assembly`, `update-magnet` updates → verify: diff in `operation_log`, stale marks, no-dependency fields mark nothing, identical values log no change.
6. `material update` (crud + CLI) → verify: all assemblies using the material marked; unknown material raises; identical is a no-op.
7. `magnet add` refusal → verify: extra part / other order → exit 1, nothing written; identical accepted.
8. Decommission report → verify: experiment after `decommissioned_at` listed, before it not.
9. Full suite → `pytest to_duckdb/tests`.
10. End-to-end in a scratch DB: `material update` → marks → `hoop-stress compute` (mocked pipeline) → recomputed, marks cleared.

## Assumptions

- `magnet update` geometry marks results stale although the hoop code does
  not use `magnets.geometry_data` yet (follow-up 5): a recompute gives the
  same values until then.
- `check --fix` marks nothing stale: it only fills missing values.
- `material update` takes the same JSON as `material add`.
- Only `hoop_stress_processed` gets stale columns: no update in this plan
  affects `op_*` / `exp_*`.
- Existing DBs keep the FK on `parts.material_name` (follow-up 12); the
  stale columns are added automatically by `ensure_schema`.

## Follow-ups (not in this plan; each needs its own plan and approval)

**Show and detect**

1. **Show stale results** in the dashboards (`magnet_stats.py`,
   `magnetdb_analysis.py`), and count experiments with stale results in
   `magnetdb.py check`.
2. **Detect drift from source files in `check`**: `parts.geometry_data`
   vs. the current YAML content (a YAML edited in place is never noticed
   today); DB values vs. the magnet/part JSON in `hifimagnet-projects`.

**Geometry**

3. **Insert angles** (option A): `magnet_parts.angle` in degrees; `"parts"`
   entries accept `{"name", "angle"}`; correction through `magnet update`
   (re-sync from the JSON) and `magnet update-part --angle`; accepted only
   for helix/ring parts of an `insert`; logged; one rebuild function
   replacing `stress_map.magnet_geometry_config_to_yaml` and
   `checks._rebuild_magnet_assembly`. Used by 3D tools only, not by the
   analytical model.
4. **Magnet bores**: `magnets.innerbore` / `magnets.outerbore`, nullable
   (NULL = computed automatically).
5. **Use `magnets.geometry_data` in the hoop-stress computation**: it is
   read and then ignored (`stress_map.geometry_config_to_yaml`).
6. **Portability of `parts.geometry`**: paths are absolute into a home
   directory.

**Coverage of updates**

7. **Update commands, with tracking, for inputs that cannot be updated
   today**: `magnet_parts.rank` / `coil_index` (these also affect `op_*` /
   `exp_*`, so `op_stats_processed` / `exp_stats_processed` need stale
   columns), `parts.type`, `magnets.type`, `assemblies.housing`,
   `assemblies.commissioned_at`, `housing_config.coil_assignment`.
8. **Finer material dependency**: mark stale only for properties actually
   used (today only `electrical_conductivity`).
9. **`material update` from materials inline in part JSON files.**
10. **`insert_part` warns instead of silently skipping** when a part
    already exists with *different* content: the message names the part and
    the differing fields (e.g. `material_name: MA21122500 → CuAg01`) and
    points to `part update`; the existing part is not changed. Identical
    content stays silent (shared parts such as `M9_Be` are re-read on every
    `magnet add` during a rebuild).
11. **Decommission**: go beyond the report and reassign files dated outside
    the window (`populate` never reassigns).

**Existing data**

12. **Drop the FK on `parts.material_name` in existing DBs** with an
    EXPORT/IMPORT migration, like `migrate_rename_site_to_assembly.py`.
13. **Clean up existing DBs that mix bin configurations**: `--reprocess` per
    assembly, or detection in `check`.

**Miscellaneous**

14. **DuckDB 1.5.5**: opening `magnetdb-2026-10-07.duckdb` read-only fails
    while replaying its WAL (internal error). Investigate, report upstream.
15. **`stage/README.md`**: outdated comments (old `M9_Bi` / `M9_Bi09`
    names, fixed errors, and the "seems broken" note once the FK fix is in).
