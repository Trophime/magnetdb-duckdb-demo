# Plan: name hoop-stress columns by part, Parquet subdirectory per assembly

**Status:** proposed 2026-10-15, not yet approved.

**Depends on:** [`python_magnetsetup/PLAN_supra_umagnet.md`](../python_magnetsetup/PLAN_supra_umagnet.md)
— fixes `magnet_setup()`'s Supra branch. Not required for this refactor, but
best executed first: until it lands, assemblies with a Supras magnet
(`M8_A211225_00`, `M8_A230919_00`) fail at `load_magnettools`, so step 6 below
cannot check them.

## Goal

`validate_fast_from_pupitre` returns one hoop-stress column per part, named
after the part, with names taken from the same ordered config that builds the
magnettools objects — consistent by construction. A count mismatch between
parts and magnettools objects stops that assembly with a clear `[ERROR]`
instead of silently misattributing. Parquet files go to
`<parquet_dir>/<assembly>/<exp_name>.parquet`.

## Context

- **Slot names and a second query.** magnettools objects (`Tube`,
  `BitterMagnet`, `UnifMagnet`) have no name attribute, so
  `validate_fast_from_pupitre` (`stress_map.py`) numbers its output columns
  `H{k}_fast`, `B{k}_fast`, `Supra{k}_fast`. The link back to parts is rebuilt
  afterwards by independent DB queries:

  | What | Where | Order |
  |---|---|---|
  | Config handed to `assembly_setup` (fixes Tube/BMagnet/UMagnet order) | `stress_map.load_assembly_config_from_duckdb` | magnets by `commissioned_at DESC`, parts by `mp.rank` |
  | Column → part map | `compute_hoop_stats.build_part_column_map` | its own query, same intent |
  | z0 per part | `compute_hoop_stats.resolve_z0_by_type` | a third query |

  `assembly_magnets.commissioned_at` is NULL in all rows of the current DB, and
  the mapping is purely positional.
- **Counts can diverge from parts.** Helix: one Tube per `Insert.helices` entry
  (matches). Bitter: each part yields several BMagnets, regrouped by the C++
  `mt.create_Bstack` — "one Bstack per Bitter part" is an assumption. Supra: with
  a detail level, one part yields many UMagnets. An unmapped column is stored
  under its slot name (`part_map.get(col, col)`), which violates the
  `part_name → parts(name)` FK and aborts the assembly's run.
- **Parquet name collisions.** `exp_name` is the pupitre file stem (e.g.
  `2019.12.04 - 00:46:53`), without housing. In `magnetdb-2026-10-08.duckdb`,
  24 file names are registered in two assemblies of different housings
  (M10/M5, M10/M9), so `pq_dir / f"{exp_name}.parquet"` overwrites one
  experiment's file with the other's and leaves a wrong `parquet_path`.

## Files affected

| File | Action |
|---|---|
| `to_duckdb/stress_map.py` | **edit** — new `assembly_coil_parts()` and `check_coil_counts()`; `validate_fast_from_pupitre` names columns by part; CLI helpers take explicit column lists |
| `to_duckdb/compute_hoop_stats.py` | **edit** — use the new helpers; remove `build_part_column_map`, `resolve_z0_by_type`, `_HOOP_COL_RE` and the rename step; Parquet to the `<assembly>/` subdirectory |
| `to_duckdb/tests/test_compute_hoop_stats.py` | **edit** — replace the 5 map/z0 tests, adapt fakes and Parquet assertions, add new tests |
| `to_duckdb/tests/test_stress_map.py` | **edit** — new helper tests; adapt the 4 tests that rely on `_fast` columns |
| `to_duckdb/docs/hoop-stress.md` | **edit** — column naming, Parquet layout |

Unchanged: `magnetdb.py`, the dashboard, the DB schema — `part_name` values and
Parquet column names are already part names today.

## Design

- **`assembly_coil_parts(assembly_name, magnet_configs, db_path, con=None)`**
  (`stress_map.py`) → `{"H": [(part, z0), …], "B": […], "S": […]}`.
  Walks `magnet_configs` (output of `load_assembly_config_from_duckdb`, exactly
  what `assembly_setup` iterates) in order and reads each config's `Helix` /
  `Bitter` / `Supra` entries (`geom: "<part>.yaml"`, rank order); rings and
  leads are naturally excluded. `z0` comes from `assembly_magnets.z_offset`
  looked up **by magnet name**, so it depends on no ordering.
- **`check_coil_counts(data, coil_parts)`** raises `ValueError` unless
  `len(Tubes) == len(H)`, `len(create_Bstack(BMagnets)) == len(B)` and
  `len(UMagnets) == len(S)`; the message names the families and both counts.
- **`validate_fast_from_pupitre(data, file, housing, coil_parts, *, magnet_type, check, use_mrun, assembly)`**
  — `coil_parts` replaces `z0_h` / `z0_b`; calls `check_coil_counts` first;
  writes one column per part name instead of `H{k}_fast`; the `--check`
  printout labels rows by part name.
- **`compute_hoop_stress_history`** — builds `coil_parts` and calls
  `check_coil_counts` once per assembly, right after `load_magnettools`; a
  mismatch prints `[ERROR]` and returns early (like a magnettools load failure),
  so the error is not repeated per experiment. Hoop columns are taken from
  `coil_parts` (those present in the DataFrame). Parquet is written to
  `pq_dir / assembly_name / f"{exp_name}.parquet"`.
- **`save_hoop_parquet(…, coil_parts=…)`** replaces `part_map`: field metadata
  `unit=MPa`, `symbol=σ_H|σ_B|σ_S`; table metadata `coil_parts` (JSON) instead of
  `part_map`. Nothing reads `part_map` today (grep over `to_duckdb/` and
  `apps/`). Old Parquet files stay readable — `part-history` only needs `t`, the
  part column and `t0`.
- **stress_map CLI** (`history` / `stats` / `fatigue`): `cmd_*` builds
  `coil_parts` from `_load_assembly`'s `magnets`; `_load_history(args, data, housing, coil_parts)`
  returns `(df, hoop_cols)`; `compute_stress_stats(df, hoop_cols)`,
  `plot_stress_history(df, name, hoop_cols)` and `cmd_fatigue` use that list
  instead of the `(H|B|Supra)\d+_fast` regex. `barchart` is unaffected (uses
  `bmap.getHoop`).
- Docstrings of new and modified functions in NumPy style, with units.

## Steps

0. Baseline: `pytest tests/test_compute_hoop_stats.py tests/test_stress_map.py`.
   → verify: all pass; record the count.
1. **Reference run, before any code change** — copy
   `magnetdb-2026-10-08.duckdb` to a scratch directory and run the current
   `compute_hoop_stats.py --assembly <A>` on one assembly with an Insert and a
   Bitters magnet and few experiments (chosen by query, e.g. `M9_A250121_00`).
   Export `hoop_stress_bin_stats` and `hoop_stress_fatigue` to CSV.
   → verify: rows exist for every helix and Bitter part.
2. **Tests first** — new or adapted tests:
   - `assembly_coil_parts`: order follows `magnet_configs`; `z0` by magnet name;
     rings and leads excluded;
   - `check_coil_counts`: raises on mismatch (`mt.create_Bstack` monkeypatched);
   - `compute_hoop_stress_history`: count mismatch → `[ERROR]`, `errors`
     non-empty, no hoop rows written;
   - two assemblies sharing an experiment name → two Parquet files, different
     `parquet_path`;
   - full run: fake `validate` returns an `H_NEW` column; files at
     `pq/HOOP_ASSEMBLY/exp1.parquet`;
   - `_column_meta` / `save_hoop_parquet` and the `test_stress_map` tests
     adapted to explicit column lists.

   → verify: new and adapted tests **fail** against the current code; untouched
   tests still pass.
3. Implement `assembly_coil_parts`, `check_coil_counts` and the new
   `validate_fast_from_pupitre` in `stress_map.py`; adapt the CLI helpers.
   → verify: `pytest tests/test_stress_map.py` passes.
4. Implement the `compute_hoop_stats.py` changes; remove the dead helpers.
   → verify: `pytest tests/test_compute_hoop_stats.py tests/test_stress_map.py`
   passes, total = baseline − removed + added; `ruff check compute_hoop_stats.py stress_map.py`
   clean.
5. **Regression check on real data** — on a fresh copy of the same DB, run the
   new code on the same assembly as step 1.
   → verify: `hoop_stress_bin_stats` / `hoop_stress_fatigue` CSVs **identical**
   to step 1 (same `part_name`, same values); Parquet under `<pq>/<assembly>/`;
   `python magnetdb.py hoop-stress part-history <one helix part> --db <copy> --parquet-dir <pq>`
   writes its file.
6. **Count check across all assemblies (read-only)** — for every assembly in the
   copy: `assembly_coil_parts` + `load_magnettools` + `check_coil_counts`,
   without computing stress.
   → verify: report the assemblies, if any, that fail — notably Bitter
   `create_Bstack` groups and supras (see "Depends on"). This answers whether
   the old positional mapping was ever wrong in practice.
7. Update `docs/hoop-stress.md` and module docstrings.
   → verify: `grep -rn '_fast' to_duckdb --include=*.py --include=*.md` only
   matches historical PLAN / NOTES files.

## Assumptions and open questions

- **Bitter grouping** — "one Bstack per Bitter part" remains an assumption about
  the C++ `create_Bstack` rule; step 6 tests it on real data. If it fails: stop
  and re-plan.
- **Supras** — `magnet_setup`'s Supra branch is broken in python_magnetsetup;
  fixed separately in
  [`python_magnetsetup/PLAN_supra_umagnet.md`](../python_magnetsetup/PLAN_supra_umagnet.md).
  This plan does not touch python_magnetsetup.
- **API change** — `validate_fast_from_pupitre` gets a new required `coil_parts`
  parameter and loses the `H{k}_fast` naming, without a shim. Its only callers
  are `compute_hoop_stats.py` and `stress_map.py` (grep over `to_duckdb/` and
  `apps/`).
- **Step 1 runtime** — the reference run processes real pupitre files; pick an
  assembly with few experiments.

## Follow-up (separate plan)

- `scripts/build_from_scratch.sh`: `hoop-stats` and `part-history` steps,
  per-DB Parquet directory `${DB%.duckdb}.hoop_parquet`, magnettools safeguard
  (SKIP both steps when `import magnettools` fails).
- Dashboard: `apps/dashboards/magnetdb/src/magnetdb_analysis.py` reads part
  history from a hard-coded `<db dir>/hoop_parquet/parts/`; decide between the
  per-DB directory (edit that line) and keeping `hoop_parquet/`.
- Duplicated pupitre files across housings (24 identical files under M10/M5
  and M10/M9): records-tree issue, out of scope; the wrong-housing copies give
  their assembly's parts load history they never saw.
