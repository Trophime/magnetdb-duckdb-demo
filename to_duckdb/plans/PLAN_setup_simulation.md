# Plan: `setup_simulation.py`, a Feel++ setup from DuckDB

**Status (2026-11-25): ✅ done, not committed** (revised the same day for
option F, see [Relation to option F](#relation-to-option-f)). Open questions
1–5 take their defaults: no CAD/mesh commands, explicit currents,
`to_duckdb/`, independent of `export_inductance_matrix.py`, no DB results.

Requested by: magnet-scipy
[prompts/numerical_commissioning_M23072801.md](../../../magnet-scipy/prompts/numerical_commissioning_M23072801.md),
"Setup from duckdb instead of python_magnetapi", option A. Related:
[PLAN_hoop_stress_part_names.md](PLAN_hoop_stress_part_names.md) (same DB →
geometry chain), `export_inductance_matrix.py` (structure copied here,
magnet-scipy F1), [../../plans/PLAN_digital_twin_schema.md](../../plans/PLAN_digital_twin_schema.md)
L3 / L5 (where results would be stored later).

## Goal

`python setup_simulation.py --db DB --assembly A [--magnet M] --current M=I …
--method cfpdes --model thmag_hcurl --geom Axi --cooling gradHZ --wd DIR`
writes a self-contained Feel++ setup directory for a DuckDB assembly, or for
one of its magnets. It holds the cfg, the json model, the generic material
jsons, the csv files written by python_magnetsetup, and the geometry YAMLs the
CAD step needs. No magnetdb server and no Postgres are needed: the script calls
`python_magnetsetup.setup.setup()` locally, which is what python_magnetapi's
server does today.

First use: the numerical commissioning of `M9_A230801_00` (insert
`M23072801` + `M9Bitters-newBi08`). It needs one setup per magnet for L_H and
L_B, and one for the assembly for M_HB.

## Context (checked 2026-11-25, read-only)

- `stress_map.load_assembly_config_from_duckdb(assembly, db, con=)` returns
  `(housing, [(magnet_name, config, geometry_data), …])`, ordered by
  `commissioned_at DESC`. Each `config` is a **flat** magnet config. On
  `M9_A230801_00` in `magnetdb-2026-11-16-m8hybrid.duckdb`:
  - `M23072801` → `{"geom": "M23072801.yaml", "Helix": [14], "Ring": [13]}`;
  - `M9Bitters-newBi08` → `{"geom": "M9Bitters-newBi08.yaml", "Bitter": [2]}`.

  Each item has `geom`, `material` and `insulator`. `MAT_ISOLANT` is found,
  since build step `materials` (`e72ad6e`, not pushed yet).
- `stress_map.prepare_geometry_directory(assembly, config, db, con=)` makes a
  temporary tree `<tmp>/data/{geometries,cad}` with `<assembly>.yaml`, one
  `<magnet>.yaml` per magnet and the part YAMLs, all rebuilt from
  `parts.geometry_data`. `load_magnettools` shows how to build the `appenv`
  on that tree.
- `python_magnetsetup.setup.setup(MyEnv, args, confdata, jsonfile, currents,
  session=None)` (`python_magnetsetup` `42a0c56`) has two branches:
  - **Magnet:** when `"geom" in confdata`, it reads that YAML and needs
    exactly one entry in `currents`. The flat config above can be passed as
    is.
  - **Assembly:** otherwise it reads `<confdata["name"]>.yaml` and calls
    `assembly_setup`, which expects `confdata["magnets"]` as a list of
    **`{magnet_name: config}`** and takes `cad.magnets[i]` by **position**.
    This is not the flat list that `export_inductance_matrix.py` passes to
    the magnettools `ana.assembly_setup`.
  - `args` needs `method`, `time`, `geom`, `model`, `cooling`, `nonlinear`,
    `wd`, `debug` and `verbose`.
  - `currents` is `{magnet: {"value": I [A], "type": …}}`.
  - `session` is never used.
  - It calls `os.chdir(args.wd)` and **never changes back**, then writes the
    cfg, the json, `conductor`/`insulator` jsons and csv files into the
    current directory.
  - It returns `(yamlfile, cfgfile, jsonfile, xaofile, meshfile, csvfiles)`.
- Templates and `magnetsetup.json` ship with the package. Available Axi
  cfpdes models: `mag`, `mag_hcurl`, `mqs`, `mqs_hcurl`, `thelec`, `thmag`,
  `thmag_hcurl`, `thmagel`, `thmagel_hcurl`, `thmqs`, `thmqs_hcurl`,
  `thmqsel`, `thmqsel_hcurl`.
- `python_magnetsetup.setup` imports and runs in `.venv` **without
  magnettools** (checked), and with python_magnetgeo 1.0.1. The script
  therefore does not depend on F4.
- Flow params are not read by `setup()`. They go into the workflow's
  `--mdata` later (magnet-scipy plan, step 2), so they are out of scope here.
- `setup_cmds` (CAD, mesh, partition and run commands) names stale images in
  `magnetsetup.json` (`feelpp-v0.110.2-ubuntu-20.04.sif`,
  `hifimagnet-salome-9.10.0.sif`), and its "Workflow" commands are broken
  (risk 2 of the magnet-scipy plan). It is not called here; see decision 1.
- The Supra branch of python_magnetsetup is broken until **E1**: an M8
  assembly will fail. The script reports the error and does not work around
  it.

## Design

| Topic | Choice |
|---|---|
| DB access | `setup_simulation(..., db_path=None, con=None)`: either a path, opened with `duckdb.connect(db_path, read_only=True)` and closed in `finally`, or an open connection or cursor from the caller, which is not closed; no `operation_log` row (the script does not write the DB, like `export_inductance_matrix.py`) |
| Target | `--assembly` alone → assembly setup; `--magnet M` → setup of magnet `M` of that assembly (refused if `M` is not linked to it) |
| Currents | `--current NAME=VALUE` [A], repeatable, required for every magnet of the target; `type` is `magnets.type` unchanged, as python_magnetdb's `run_simulation_setup` passes it (`setup()` only reads `value`) |
| Assembly config | `{"name": assembly, "magnets": [{name: config}, …]}` in the order of the magnets in `<assembly>.yaml`; refused if the names don't match one to one |
| Return value | a dict with the keys of python_magnetdb's `Simulation.setup_state`: `yamlfile`, `cfgfile`, `jsonfile`, `xaofile`, `meshfile`, `csvfiles` (paths relative to `--wd`) |
| Output | `--wd DIR`, created if missing, refused if not empty unless `--force`; after `setup()`, the geometry YAMLs (`data/geometries/*.yaml`) are copied to `DIR/geometries/` so the CAD step finds them |
| `setup.json` | `uid` (a new UUID4); the simulation record's descriptors under the field names shared by python_magnetdb's `simulations` and L5 `simulation_results`: `kind` (`"fem"`), `target_type` (`magnet` \| `assembly`), `target_name`, `method`, `model`, `geometry`, `cooling`, `static`, `non_linear`, `currents` (`{magnet_name: value}` [A]); provenance: DB path and sha256 (or `null` when called with `con`), python_magnetsetup and python_magnetgeo versions, creation time; `geometry_fingerprint` (sha256 of the geometry YAMLs copied to `DIR/geometries/`, in sorted name order), so a mesh made from this setup can be matched to its geometry later; and the return value above |
| Working directory | saved before `setup()` and restored in `finally`; the temporary geometry tree is removed in `finally` |
| Errors | `ImportError` / `ValueError` / python_magnetsetup exceptions → `error: …` and exit 1, as in `export_inductance_matrix.py` |
| Out of scope | CAD, mesh, solve, flow params, writing results to the DB, M8 / Supra (E1), the python_magnetsetup fixes listed in the magnet-scipy plan, looking up or checking a stored mesh (no mesh store outside python_magnetdb yet) |

## Relation to option F

[../../plans/PLAN_duckdb_master_control_plane.md](../../plans/PLAN_duckdb_master_control_plane.md)
(option F) keeps the job state of a simulation in Postgres, its kept results
in DuckDB and its files in rustfs (section "Simulation runs and meshes"
there). This script fits that design as follows.

- **It is the planned replacement of python_magnetdb's setup inputs.** Today
  `python_magnetdb/actions/run_simulation_setup.py` builds `config.json` and
  `data/geometries/` from the Django models (`generate_magnet_directory`,
  `generate_site_directory`), then calls `setup()`. Option F phase 5 removes
  the Django entity models, so the worker will call `setup_simulation()`
  instead, with the returned dict as `setup_state`. Nothing in
  python_magnetdb changes in this plan.
- **Snapshot or copy only.** In production the API owns the DuckDB file and
  no other process can open it. The command line runs on the dashboard
  snapshot or on a local copy; the worker reads the snapshot.
- **Never inside an API request thread.** `setup()` calls `os.chdir`, which
  changes the working directory of the whole process. Run it in its own
  process: the command line, or the worker.
- **Exploratory runs.** A setup made with this script is an exploratory run.
  It is recorded nowhere shared. Its `setup.json` (UUID, inputs, versions,
  geometry fingerprint) lets an admin import its results later, through
  `write_results`, under the same UUID.
- **Confidentiality.** A setup directory contains geometry and material
  values from the DB: it is as confidential as the DuckDB file itself.

## Files affected

| File | Action |
|---|---|
| `to_duckdb/plans/PLAN_setup_simulation.md` | create: this plan and its results |
| `to_duckdb/setup_simulation.py` | create: `setup_simulation(...)` (NumPy docstrings), `_parse_args`, `main` |
| `to_duckdb/tests/test_setup_simulation.py` | create: unit tests with a fake `setup()`; one integration test with the real `setup()` on `test-magnetdb.duckdb` (skipped if missing) |
| `to_duckdb/README.md` | edit: one section, "Feel++ setup from DuckDB" |

## Steps

1. Write this plan file → verify: the file exists. ✅ 2026-11-25
2. Baseline: `to_duckdb` tests (`.venv/bin/python -m pytest` from
   `to_duckdb/`) → verify: all pass, count recorded.
3. Tests first, against a fake `python_magnetsetup.setup.setup`:
   - assembly vs magnet branch and the `confdata` passed;
   - assembly order matching the YAML, and a refusal on mismatch;
   - currents parsing, a missing current, an unknown magnet;
   - `--wd` not empty without `--force`;
   - cwd restored and the temp tree removed, also when `setup()` raises;
   - `setup.json` content: `uid`, descriptor field names, provenance,
     `geometry_fingerprint` stable across two runs on the same DB;
   - the returned dict has the `setup_state` keys;
   - the DB opened read-only from a path; a caller's `con` used and left
     open.

   → verify: they fail (module missing).
4. `setup_simulation.py` → verify: the step-3 tests pass; the full
   `to_duckdb` suite passes; `ruff check` is clean on the new files.
5. Integration test: the real `setup()` on the **latest** DuckDB file (the
   newest `to_duckdb/magnetdb-*.duckdb`, skipped if none; user, 2026-11-25:
   not `test-magnetdb.duckdb`), `M9_A230801_00`, `--magnet M23072801`
   (`thelec`, Axi, static) → verify: the cfg and json exist, and the json
   `Parameters` contain `U_*`, `N_*` and `Area_*` for every part.
6. Real run, read-only, into scratch directories:
   - `M9_A230801_00`, `--magnet M23072801 --current M23072801=31000`;
   - `--magnet M9Bitters-newBi08 --current M9Bitters-newBi08=33000`;
   - the assembly with both currents;
   - each with `--model thmag_hcurl --cooling gradHZ`.

   → verify: same checks as step 5. Results recorded below. **Stop and
   report if `setup()` fails** (expected sources: templates or materials):
   fixes in python_magnetsetup are a separate plan, possibly with E1.
7. README section → verify: the documented command runs as written.

The setups of step 6 are the inputs of the magnet-scipy plan's "Order of
work", steps 2–4 (CAD, mesh, then L_H, L_B, M_HB). Those steps are not part
of this plan.

## Assumptions and open questions

1. **Commands:** should the script also write the CAD / mesh / partition
   commands from `setup_cmds`? Recommendation: **no** for now. The image
   names in `magnetsetup.json` are stale, and its Workflow commands are
   broken; the magnet-scipy plan documents the commands instead. Updating
   `magnetsetup.json` (Feel++ 0.112 trixie image) belongs to the
   python_magnetsetup fixes.
2. **Currents:** required explicitly (default), or defaulted from the
   housing config / MAGFILE maxima?
3. **Location:** `to_duckdb/` next to `export_inductance_matrix.py`
   (default), as the magnet-scipy plan suggests.
4. **Order:** `export_inductance_matrix.py` is still untracked. Commit it
   first (it waits for the my-magnettools commits) so both scripts land with
   the same conventions? This plan does not depend on it.
5. **Results to the DB** (L3 `electrical_characteristics`, L5 `simulations`)
   stay out of scope until those tables are planned.

## Results

2. (2026-11-25) Baseline, `to_duckdb`: **817 passed, 4 skipped, 2 failed**,
   with `tests/test_check_overview_records.py` and `tests/test_tags.py`
   ignored. Those two modules and the 2 failures
   (`test_schema.py::test_overview_records_check_columns_exist[checks|checked_at]`)
   are the tests-first part of the paused
   [PLAN_overview_record_checks.md](../../plans/PLAN_overview_record_checks.md)
   (code not written yet), not this plan.
3. (2026-11-25) `tests/test_setup_simulation.py`, 27 tests (fake stress_map
   chain, fake YAML order, fake `setup()`): collection failed before the
   module existed.
4. (2026-11-25) `setup_simulation.py` written: 27/27 pass; full suite
   **844 passed, 4 skipped**, the same 2 known failures; `ruff check` clean
   on both files.
5. (2026-11-25, **stopped**) The real `setup()` fails, before any json is
   written:
   - On `magnetdb-2026-11-16-m8hybrid.duckdb` (latest), `M23072801`,
     `thelec`: the geometry loads (14 helices, 13 rings) and the cfg is
     written, then `create_json` fails rendering
     `templates/cfpdes/Axi/thelec/json.mustache`: chevron
     `Unexpected EOF: the tag "T_magnet" was never closed (line 139)`.
   - **Cause:** python_magnetsetup `f8d15d4` (2026-02-23, "remove stats for
     T over whole comput domain") deleted the `Stat_Temperature` block
     together with the closing `{{/T_magnet}}` in 9 json templates
     (`thelec`, `thmag`, `thmag_hcurl`, `thmagel`, `thmagel_hcurl`,
     `thmqs`, …). Every setup with one of these models fails today, through
     python_magnetdb as well. Restoring only `{{/T_magnet}}` is not enough:
     the item before it ends with `}` and no comma, so JSON with more than one
     magnet (assembly setups) would still be invalid.
   - (First attempt, on `test-magnetdb.duckdb`, 2026-09-07: failed earlier,
     `IndexError` in python_magnetgeo `Insert.get_params` (`Zr[i]`), which
     needs Nhelices − 1 rings. Not investigated further: that DB predates the
     rings added in A15 (2026-10-29) [unverified], and tests use the latest
     DB.)
   - Steps 5–7 wait for a python_magnetsetup template fix, a separate plan
     (with E1 and E6 on the same branch, as in the ROADMAP order). The
     integration test is not written yet, so the suite does not fail on it.
   - **Unblocked (2026-11-25)** by
     [python_magnetsetup/PLAN_fix_json_templates.md](../../python_magnetsetup/PLAN_fix_json_templates.md)
     (9 templates and the assembly branch of `setup()`, not committed yet):
     on the latest DB the magnet setup (`thelec`) and the assembly setup
     (`thmag_hcurl`, `gradHZ`) both succeed with this script. Steps 5–7 can
     resume.
   - (2026-11-25, resumed, python_magnetsetup `e78a6c3`, superproject
     `77a9cdf`) Integration test `test_real_insert_setup_on_latest_db` added:
     the real `setup()` on the newest `magnetdb-*.duckdb`
     (`magnetdb-2026-11-16-m8hybrid.duckdb`), `--magnet M23072801`,
     `thelec`; every helix `H1`…`H14` has `Area_H<i>`, `U_H<i>_*` and
     `N_H<i>_*`. **28 passed**, `ruff` clean.
6. (2026-11-25, **stopped**) The three real setups on the latest DB, all
   `thmag_hcurl`, `gradHZ`, exit 0 and write a json that parses, with no
   `Stat_Temperature`:

   | Setup | `U_` / `N_` / `Area_` | `Stat_T_` |
   |---|---|---|
   | `--magnet M23072801` (31 kA) | 280 / 280 / 14 (`H1`…`H14`, 20 sections each) | `Stat_T_` (empty name, `setup()` line 524) |
   | `--magnet M9Bitters-newBi08` (33 kA) | 3 / 3 / 0, **`M9Be` only** | `Stat_T_` |
   | assembly, both | 283 / 283 / 14 | `Stat_T_M23072801`, `Stat_T_M9Bitters-newBi08` |

   - **The inner Bitter part `M9_newBi08` is missing** from both setups that
     contain the Bitters: Parameters (only `U_M9Be_B1..3`, `N_M9Be_*`,
     `M9Be` slits) and Materials (only `Conductor_M9Be`, `Insulator_M9Be`),
     although the log shows `Bitter_setup` processing `M9_newBi08`.
   - **Cause (python_magnetsetup `setup.py` `magnet_setup()`, Bitters and
     Supras branches):** the loop over the parts assigns
     `(mdict, mmat, mmodels, mpost) = _setup(...)` on each part, and `_setup()`
     starts from empty dicts and returns only that part. Each part replaces
     the previous one; only the last survives. Every Bitters magnet with
     more than one part is set up incomplete, through python_magnetdb too.
     Inductance (L_B, M_HB) and Bitters resistance from these setups would be
     wrong.
   - The insert setup is complete. Step 7 (README) waits; the fix is a
     python_magnetsetup plan.
   - **Fixed (2026-11-25)** by
     [python_magnetsetup/PLAN_fix_multipart_magnets.md](../../python_magnetsetup/PLAN_fix_multipart_magnets.md)
     (python_magnetsetup `f1cf3d7`, superproject pin `bc5f947`). Rerun on the
     latest DB, `thmag_hcurl`, `gradHZ`, all exit 0, json parses, no
     `Stat_Temperature`:

     | Setup | `U_` / `N_` / `Area_` | Conductors | `Stat_T_` |
     |---|---|---|---|
     | `--magnet M23072801` (31 kA) | 280 / 280 / 14 | `H1`…`H14` | `Stat_T_` (empty name, `setup()` line 524) |
     | `--magnet M9Bitters-newBi08` (33 kA) | 6 / 6 / 0 | `M9_newBi08`, `M9Be` | `Stat_T_` |
     | assembly, both | 286 / 286 / 14 | 14 insert + both Bitters | `Stat_T_M23072801`, `Stat_T_M9Bitters-newBi08` |

   - Integration test `test_real_bitters_setup_keeps_every_part` added:
     `--magnet M9Bitters-newBi08` on the latest DB; every Bitter part of the
     DB config has `Conductor_<part>`, `U_<part>_*` and `N_<part>_*`.
     `tests/test_setup_simulation.py` **29 passed**; full `to_duckdb` suite
     **846 passed, 4 skipped**, the same 2 known failures (paused overview
     checks); `ruff` clean.
7. (2026-11-25) README section "Feel++ setup from DuckDB —
   `setup_simulation.py`" (and one line in the directory layout). Both
   documented commands run as written on the latest DB (exit 0, files as
   listed); the documented options match `--help`.

**Status: ✅ done, not committed.** The setups are the inputs of the
magnet-scipy numerical commissioning (its "Order of work" steps 2–4: CAD,
mesh, L_H, L_B, M_HB), which needs the CAD / mesh toolchain.
