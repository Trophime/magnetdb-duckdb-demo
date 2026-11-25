# magnetdb-duckdb-demo — Workspace Roadmap

*Snapshot: 2026-11-25 · branch `housing-config-versions` · previous snapshot 2026-11-16*

Umbrella roadmap over every plan file in this repository and its four
submodules (`python_magnetrun`, `python_magnetsetup`, `python_magnetgeo`,
`python_magnetcooling`). It **links to** the detailed plans and the two
component roadmaps rather than repeating them:

- [to_duckdb/plans/ROADMAP.md](to_duckdb/plans/ROADMAP.md) — detailed `to_duckdb` history, last updated 2026-08-21
- [python_magnetrun/prompts/ROADMAP.md](python_magnetrun/prompts/ROADMAP.md) — detailed `python_magnetrun` history, last updated 2026-06-11
- [PLAN_digital_twin_schema.md — Cross-plan order](plans/PLAN_digital_twin_schema.md#cross-plan-order-blockers-and-approvals) — authoritative order for track B
- [PLAN_m1_project_sort.md](plans/PLAN_m1_project_sort.md) — themed sort of the 50-item M1 note
- [REVIEW_readability_maintainability.md](REVIEW_readability_maintainability.md) — readability and maintainability review of `to_duckdb` and the dashboard (2026-11-15), source of A28–A31 and C11–C13
- magnet-scipy `ROADMAP.md` (`~/github/magnet-scipy`, snapshot 2026-11-12) — the replay and comparison engine; links both ways in [Cross-repository: magnet-scipy](#cross-repository-magnet-scipy)

Statuses below were checked against code and git history on 2026-11-25
(open-item counts: rows of each Open table whose status does not start with ✅ or ❌),
not only against each plan's own status line (see
[Status drift to fix](#status-drift-to-fix)). Files marked *uncommitted*
exist in the working tree but not in git yet.

**Legend.**
Status: ✅ done · 🔄 in progress · 📝 drafted, awaiting approval ·
💡 idea / sketch, no approvable plan · ⛔ blocked on external input ·
⏸ tabled / deferred · ❌ superseded / dropped.
Effort (relative, no calendar): S · M · L · XL · ? (not sizeable yet).

---

## Tracks at a glance

| Track | Scope | Open items | Next step |
|---|---|---|---|
| [A](#a--data-pipeline-to_duckdb) | `to_duckdb` schema, CLI, compute pipelines | 27 | finish-and-deploy done (rebuild A21, checks A22, deployed 2026-11-23); `setup_simulation.py` done (A33); commit `export_inductance_matrix.py` (A34) after the my-magnettools commits; decide the M8 `TotalField` stats (A35) and A27 tolerances before or during testing; A32 and A26 now unblocked; code health: A31 first, A28 before A1, A29 before A3–A5 |
| [B](#b--digital-twin--etl) | installations, run config, characteristics, Pupitre ETL, signatures, sessions | 17 steps | **decide the lag method** to resume the overview-record checks (paused since 2026-11-18); approve the flow-params phases; approve the D1 = a code and step R; field factors via magnettools after E1 |
| [C](#c--dashboards-appsdashboardsmagnetdb) | Dash app | 13 | approve the live M8 viewer (C14), then the cryogenic group (C15); tester issues from F7; shared viewer code (C11) before C9 and C10 |
| [D](#d--python_magnetrun) | data-access library | 19 | commit or drop the `cli.py` fix (D18); bump the pin to `d882a6d` (D19); approve D17; D2 parquet ready to execute |
| [E](#e--python_magnetsetup--python_magnetgeo--python_magnetcooling) | setup / geometry / cooling libraries | 8 | three python_magnetsetup bugs fixed (E7); approve E1 (Supra) — unblocks A2, the M8 assemblies and their field factors; E6 lint and E8 on the same branch; check python_magnetdb's copy (E9) |
| [F](#f--infrastructure-ci-packaging-deployment) | runner, apt depot, magnettools packaging, DB architecture, deployment | 10 | F7: testers (step 11); CAD / mesh toolchain for the numerical commissioning (F10); decide F5 (option F; simulation storage already decided, Q10); approve F1 → F2 → F3; write the F9 plan |
| [G](#g--external-integrations--research) | external DBs/APIs, research items | 10 | mostly blocked on external input |

---

## A — Data pipeline (`to_duckdb`)

### Done since the 2026-11-16 snapshot

| Item | Evidence |
|---|---|
| A21 — final full rebuild `magnetdb-2026-11-16.duckdb` on calcul22 (done 2026-11-17, exit 0, after one resume at `exp-stats`); M8 hybrid patch from the regenerated `Data/M8_summary-2026.json` (55 records): `magnetdb-2026-11-16-m8hybrid.duckdb`, the deployed DB | [PLAN_finish_and_deploy.md](plans/PLAN_finish_and_deploy.md) steps 6–9 |
| A22 — post-build checks of the 11-16 DB, all pass (dates, M8 assemblies and versions, #17 modes, #18 duplicates gone, file and ETL checks on 6 543 files, A17 links, Tech Staff); hoop stress still open | 2026-11-18, results in [PLAN_finish_and_deploy.md](plans/PLAN_finish_and_deploy.md) |
| Overview records: energy from the pupitre sources only (was double-counted with the Overview TDMS), plus an energy check line | `4b07761` |
| Build step `materials` loads `MAT_ISOLANT` (needed by every geometry rebuild) | `e72ad6e` |
| A33 — `setup_simulation.py`: Feel++ setup of an assembly or magnet from DuckDB (no server, no Postgres); `setup.json` with UUID, descriptors, provenance, geometry fingerprint; 29 tests incl. 2 on the latest DB | `8ba3500`; [PLAN_setup_simulation.md](to_duckdb/plans/PLAN_setup_simulation.md) |
| Simulation storage decided across the plans (Postgres job state, DuckDB `simulation_results`, rustfs, admin import) | `2f7aa0c`; [Q10](#open-questions) |

### Done since the 2026-11-15 snapshot

| Item | Evidence |
|---|---|
| A17 — `assembly add` refuses retired/dead magnets and writes nothing; `magnet add` refuses a part ID that exists with another `design_office_reference` (parts A and B of the [plan](to_duckdb/plans/PLAN_retired_magnet_guard.md)) | `ecc8cb7` |
| Plan and notes files moved into `plans/` folders (repo root, `to_duckdb/`, the dashboard) | `ed87429` |
| A31, mechanical part — `ruff check --fix` on `to_duckdb`, the dashboard, notebooks and `stage/` (60 files; imports sorted, whitespace) | `8b2018f`; submodules: see D and E6 (pins bumped in `4494b15`) |

### Done since the 2026-11-07 snapshot

| Item | Evidence |
|---|---|
| Full rebuild `magnetdb-2026-11-10.duckdb` on calcul22 (A21; export resumed after the `--no-utc` failure); candidate to deploy: the copy with the #17 modes, `~/magnetdb-checks/magnetdb-2026-11-10.mode17.duckdb` | built 2026-11-12; checks in [PLAN_finish_and_deploy.md](plans/PLAN_finish_and_deploy.md) |
| A24 phase E — SQL builder `populate overview-records-from-operationaldata`, stored Overview `mode` | `d5ad7f9`, `12b0960` |
| A24 phase G — validation on the 11-10 DB (≈ 1 450 new overview rows, accepted; builder 61 s vs ≈ 12.6 min for `overview-json` + `overview-infer`); decision 2: Default/Trigger files named < 90 s before an overview are read for their real end; build step `overview-ops` after `overview-json` (`--reprocess`) | `5712db7`, `023b81a`; results in [PLAN_overview_records_from_operationaldata.md](plans/PLAN_overview_records_from_operationaldata.md#phase-g-results-2026-11-13) |
| M8 overview records built from `operationaldata` too (128 instead of 37), replaced rows keep their hybrid lists ([PLAN_m8_overview_records.md](plans/PLAN_m8_overview_records.md) part B) | `023b81a` |
| Data issue #14 — M8 assemblies and wiring (`M8_A211225_00`, `M8_A230913_00`), rename from `M8_A230919_00` | `53b55e6`, `06e1b9f`; [PLAN_m8_assembly_rename.md](plans/PLAN_m8_assembly_rename.md) |
| Data issue #17 — Overview operating mode from the right IH / IB channels (pigbrother → pupitre current map for the M10 supply swap) | `88108f3`, `0fcb682`; python_magnetrun `e4c1654` |
| Data issue #18 — skip list for the 24 pupitre files stored under two housings (`pupitre_skip.json`, `--skip-file`) | `7b29a5c`; hifimagnet-projects `8d51e89` |
| Build steps `file-check` and `etl-check` (file quality and ETL tags in every build); export runs the submodule's `mysql_connect.py` | `02b7ee2` |
| A23 — `LNCMI Tech Staff` includes MAINTENANCE codes; build step `tech-staff` (last) and warnings when `users` is rebuilt without it ([plan](to_duckdb/plans/PLAN_tech_staff_research_area.md)) | `e40fefd` |
| `EXPERIENCES_LOG` field table in `Data/README.md` | `0343253` |

### Done since the 2026-11-02 snapshot

| Item | Evidence |
|---|---|
| A16 — empty date cells highlighted in dashboard tables + report-only `check --entity dates` (scope option 2, no `--fix`) ([plan](plans/PLAN_missing_dates.md)) | `5e66207`; dashboard look confirmed by the user 2026-11-03 |
| `housing sync [--dry-run]` adds missing housings/versions from the bundled JSON; `housing view <H> [--at]` lists versions (track B step H) | `888f009` |
| Users demo: corrections and `--from` cutoff use `HStart`, not the unreliable log timestamp | `095449b` |
| Source JSON fixes and A15 rings committed in `hifimagnet-projects` (A15 step 7, G5 part) | hifimagnet-projects `4a926d8`, `612cafb`, `9338e22` |

### Done since the 2026-10-30 snapshot

| Item | Evidence |
|---|---|
| A15 — rings given to the insert magnets that had none (option C fit, sharing rule, `M25032101` rings excluded), written back to `hifimagnet-projects`, checked on a scratch rebuild ([plan](plans/PLAN_insert_rings.md)) | `0ebb564` (`suggest_rings.py`, `rings_report.txt`); step 7 (commit in `hifimagnet-projects`, then one full rebuild) left — see G5, A21 |
| `magnet add` / `assembly add` are all or nothing; failures logged in `operation_log`, `Error: …` + exit 1 instead of a traceback ([plan](plans/PLAN_atomic_load.md)) | 2026-10-29, plan committed in `ba24ca4` |
| "Commissioned into assembly" events dated with the link's `commissioned_at` instead of the import time ([plan addendum](plans/PLAN_import_json_dates.md)) | `84d0079` |
| Rebuildable magnet geometry: magnet/assembly geometry never stored, rebuild checked and stored in `magnets.geometry_problem`, warning on `magnet add`, breaking part updates refused, colour on Magnet stats ([plan](plans/PLAN_magnet_geometry_check.md)) — resolves [Q2](#open-questions) | `ba24ca4`, `5a4456d` (`magnet_geometry.py`), `9d0e486`; dashboard look awaits the user's check (step 5) |
| A18 — every state-changing `magnetdb.py` subcommand writes `operation_log` (gaps G1–G8, incl. `hoop-stress compute`) ([plan](plans/PLAN_operation_log_coverage.md)) | `ef60cec` |

### Done since the 2026-10-16 snapshot

| Item | Evidence |
|---|---|
| Importer reads `manufactured_at` / `assembled_at` from the JSON, name date as fallback with a warning, implausible dates are errors ([plan](plans/PLAN_import_json_dates.md)) | `195732c` (`crud.py` `_parse_json_date`, `_resolve_date`) — plan status line still says "proposed" |
| EXPERIENCES_LOG ↔ experiments linking report, acronym corrections, `users_table_demo.py` rework | `59197ad` (`demos/report_experiments_linking.py`) |
| Per-magnet data archive (`.tar.xz` + md5 manifest) ([plan](to_duckdb/plans/PLAN_archive_magnet_data.md)) | `0ade81d` (`demos/archive_magnet_data.py`) |
| Pupitre experiment-file checker | `fb203f9` (`check_experiment_files.py`) |
| Corrupted files skipped in `compute_op_stats`; pupitre time changes (DST) handled in `compute_exp_stats` | `5b7a506`, `feb2df7` |
| magnettools optional in `to_duckdb` (only hoop-stress commands need it) — see F4 | `1e58ba9` (`stress_map.py`) |

### Done since the 2026-08-21 snapshot

| Item | Evidence |
|---|---|
| `operation_log` audit table + `magnetdb.py log` ([plan](to_duckdb/plans/PLAN_operation_log.md)) | `e2389aa`; `schema.py`, `magnetdb.py` |
| Update-impact tracking: stale marking, `material update`, FK drop ([plan](plans/PLAN_update_impact_tracking.md)) | approved + implemented 2026-10-08, `d7ede6a` (`to_duckdb/impact.py`) |
| Hoop-stress rainflow fatigue-bins matrix (`hoop_stress_fatigue_bins`) | in `schema.py`, committed — **no plan file was ever written** |
| Per-experiment hoop-stress processing record (`hoop_stress_processed`, `bin_config`, `stale_since`/`stale_reason`) | `schema.py` — covers the *stress* stage of the processing-status flag |
| `populate overview-records-from-json` | subcommand present in `magnetdb.py` |
| Lifecycle: auto-close at CRUD, enum-driven statuses | `5c938bd`, `753c056` |
| DB consistency check helper | `566e3f7`, `dd87797` |
| Fill missing `Magnet Sites` in proposals ([plan](plans/PLAN_fill_magnet_sites.md)) | `Data/proposals_2026-07-22_with_sites.csv` |

Earlier work (dedup, hoop-stress Phases 1–5, lifecycle, site→assembly
rename Track A) is recorded in [to_duckdb/plans/ROADMAP.md](to_duckdb/plans/ROADMAP.md).

### Open

| ID | Item | Plan | Status | Effort | Depends on / blocker |
|---|---|---|---|---|---|
| A1 | `compute_exp_stats.py` ~3× faster, atomic per-file writes | [PLAN_exp_stats_performance.md](to_duckdb/plans/PLAN_exp_stats_performance.md) | 📝 since 2026-10-09 | M | best after **A28** (same code in `compute_op_stats.py`); full reprocess ≈ 1.6 h today |
| A2 | Hoop-stress columns named by part; Parquet sub-dir per assembly | [PLAN_hoop_stress_part_names.md](to_duckdb/plans/PLAN_hoop_stress_part_names.md) | 📝 2026-10-15 | S–M | best after **E1** (M8 assemblies fail `load_magnettools` until then) |
| A3 | `incidents` entity linked to assembly/magnet/part + `status_history` | [PLAN_incident_tracking.md](to_duckdb/plans/PLAN_incident_tracking.md) | 📝 since 2026-08-28 | M | — (M1 note item 31) |
| A4 | `part delete` command | [PLAN_part_delete.md](to_duckdb/plans/PLAN_part_delete.md) | 📝 since 2026-08-28 | S | — (split from A3, independent) |
| A5 | `jc` table + supra-part `jc_name` link | [PLAN_jc_table.md](plans/PLAN_jc_table.md) | 📝 since 2026-09-02 | S–M | relates to **E2** (detailed Supras) |
| A6 | Days-based date tolerance for fuzzy matching | [PLAN_fuzzy_date_tolerance.md](to_duckdb/plans/PLAN_fuzzy_date_tolerance.md) | 📝 — partly covered by `d0fb3ce` and the `59197ad` linking rework | S | check what is left first |
| A7 | `populate all` composite subcommand | [PLAN_populate_all.md](to_duckdb/plans/PLAN_populate_all.md) | 💡 | S | opens: hard-fail policy, `--reprocess` scope |
| A8 | Scheduled populate (systemd timer + `--settle-seconds`) | [PLAN_scheduled_populate.md](to_duckdb/plans/PLAN_scheduled_populate.md) | 💡 | S–M | A7; runs in the writer container (F8) |
| A9 | Pluggable user sources (CSV / SUPERVISION MySQL / userdb API) | [PLAN_users_multi_source.md](to_duckdb/plans/PLAN_users_multi_source.md) | 📝 Phase 1; ⛔ Phases 2–3 | M | SUPERVISION schema, userdb API shape — see [Q9](#open-questions) |
| A10 | EcoNRJ parameter inference (Tr, R, ImaxH, ImaxB) | [PLAN_econrj_parameter_inference.md](to_duckdb/plans/PLAN_econrj_parameter_inference.md) | 💡 | M | meaning of `Tr`; fit granularity |
| A11 | Update-impact follow-ups 1–4, 6–7 (stale display, drift detection, insert angles, bores, portable geometry paths, update coverage); #5 dropped ([Q2](#open-questions)) | [PLAN_update_impact_tracking.md §Follow-ups](plans/PLAN_update_impact_tracking.md) | 💡 each needs its own plan | S each | #1 feeds **C4** |
| A12 | Processing-status flag for the remaining stages (fatigue, signatures, plateaux, …) | — none | 💡 partly done (stress stage via `hoop_stress_processed`) | S–M | B S2 (defines the signature/plateaux stages) |
| A13 | Schema cleanup: drop `sum_x2_dt`, `exp_part_bin_stats`, maybe `magnets.geometry_data` (unset by design since [Q2](#open-questions); still written by `magnet add --geometry`); `operationaldata` stays (file index of A24, 2026-11-07) | [to_duckdb/TODOs.md](to_duckdb/TODOs.md) | 💡 | ? | C4 (retire `part_stats.py` consumers first) |
| A14 | Hoop-stress `--check` mode against `magnettools.Bmap.getHoop()` | [to_duckdb/TODOs.md](to_duckdb/TODOs.md) (POSTPONED) | ⛔ | S | fix in `~/github/my-magnettools`, then a reinstall — **F4** makes this routine |
| A19 | `demos/plot_magnet_incidents.py`: defaults & spikes over a magnet's lifetime | [PLAN_magnet_incidents_plot.md](to_duckdb/plans/PLAN_magnet_incidents_plot.md) | 📝 awaiting approval | S | — |
| A20 | Hybrid and run-log files in `archive_magnet_data.py` | [PLAN_archive_magnet_hybrid_runlog.md](to_duckdb/plans/PLAN_archive_magnet_hybrid_runlog.md) | 📝 2026-10-22 | S | on-disk layout of hybrid/run-log files to confirm; columns empty today (fed by B step R) |
| A21 | Full rebuild from scratch with the fixed source JSON and the housing-config versions | `scripts/build_from_scratch.sh` | ✅ 2026-11-17: `magnetdb-2026-11-16.duckdb` (calcul22, ≈ 37 h incl. one resume at `exp-stats`), then the M8 hybrid patch `magnetdb-2026-11-16-m8hybrid.duckdb` (2026-11-22), deployed on calcul18 (F7). calcul22's superproject is ahead of `origin` by `0075e4e` (`demos/magnet-assembly-history.py`) and merges: push or reset. Its 11-16 DB is not patched (the patched copy is next to it) | M | A1 would shorten the next one |
| A22 | After A21: hoop-stress compute (not in `build_from_scratch.sh`; needs magnettools, absent from `.venv`) and the post-build checks | — | 🔄 checks ✅ on the 11-16 DB (2026-11-18, all pass); left: **hoop stress** | S–M | M8 hoop stress waits for **E1**; doing A2 first avoids a second full stress run |
| A25 | Keep tags, check rules and magnet wirings across rebuilds: `hifimagnet-projects/magnetdb.json/pupitre_checks.json`, `etl import` / `etl dump`, build step `etl-config` | [PLAN_pupitre_checks_file.md](plans/PLAN_pupitre_checks_file.md) | ✅ 2026-11-07: `etl import` / `etl dump`, build step `etl-config`; [revision 2](plans/PLAN_pupitre_checks_file.md#revision-2-2026-11-07-simplified-model): insert wiring derived from the helix count (stored wirings = overrides, none needed so far), global rules; `pupitre_checks.json` = 2 tags, 11 rules (`IH_vs_Icoil7`, `A1_vs_A2`, `A3_vs_A4`, housing values M7/M8/M10, `M7-140317` pairs); M7/M10 housing versions for swapped supplies (python_magnetrun `69f6c49`, `4774ec2`) | S–M | data issues #13–#15 of the [schema plan](plans/PLAN_digital_twin_schema.md) open: `M8_A211225_00`, `M10_A220223_00` boundary; M7 2014 current offset kept tagged |

| A26 | Hybrid files (kHz, RMS, vprocess, trigger) in `operationaldata`, from their names and folders (incl. the 2019–2024 year folders); `HybridData` searches year folders; builder matches them by overlap and stores paths, not basenames | [PLAN_m8_overview_records.md](plans/PLAN_m8_overview_records.md) part C | 💡 outline; unblocked (F7 deployed). The M8 summary JSON regenerated by hand on 2026-11-22 is the stopgap it replaces; HYBRIDE `DCCT` (`I_BOB`, C14) may be an alternative source | M | answers A20's layout question; row granularity (≈ 48 000 rows per system-hour vs ≈ 310 000 per file) to decide |
| A27 | Tag review before the testers see the tags: `check:channel_not_empty` on every file of 12 assemblies (derived wiring suspected, e.g. `M10_A260326_00`, `M10_A241209_00`, `M8_A211225_00`); `check:dcct_mismatch` on 1 117 of 6 548 files (tolerance per period / housing?) | — (to write) | 💡 found 2026-11-13 on a copy with both checks on all files | S–M | user's decision on tolerances; fixes go into `pupitre_checks.json`, then `check_experiment_files.py --etl --recheck` (≈ 15 min, no rebuild) |
| A28 | Shared module for the code common to `compute_exp_stats.py` and `compute_op_stats.py` (72 % shared lines); settle the `field.abs() > FIELD_THRESHOLD` (exp) vs signed (op) difference in `compute_scalars` | [review §1](REVIEW_readability_maintainability.md) (plan to write) | 💡 | S–M | A31; before **A1**; the 2026-11-16 rebuild runs with the signed op version (only the op stats to recompute if it is a bug) |
| A29 | Split `crud.py` (4619 lines) and `build_parser` (869 lines) by entity, `crud` kept as a re-exporting facade; until then new entities go in new modules | [review §2](REVIEW_readability_maintainability.md) (plan to write) | 💡 | M–L | A31; before A3, A4, A5 |
| A30 | `print` → `logging` in `to_duckdb` and the dashboard (147 `print` in `crud.py`); narrow the 40 broad `except Exception` handlers | [review §5–6](REVIEW_readability_maintainability.md) (plan to write) | 💡 | M | before A8 and F8 (unattended runs); pairs with D12 |
| A31 | Lint clean-up in `to_duckdb` and the dashboard: `ruff check --fix` applied 2026-11-16 (219 → 114 findings, `8b2018f`; on these changes before the commit: `to_duckdb` 874 passed / 3 skipped, dashboard 202 passed without `mrun_test.py`; not re-run on the commit); left: the 114 findings that need a decision (broad `except` under A30, `zip` without `strict`, …) and public names or `config.py` for the ≈ 56 cross-module uses of private names | [review §4, smaller items](REVIEW_readability_maintainability.md) (plan to write) | 🔄 mechanical part applied | S | — ; first, so the A28, A29 and C11 diffs stay readable |
| A32 | `overview_records.teb` = 0 on 259 of 3 341 records of `magnetdb-2026-11-16.duckdb`: all Overview-sourced (254 NORMAL, 4 ECO, 1 also with a pupitre source), spread over 2019–2026; 126 were already rows in the 2026-11-10 DB (where every record had `teb` = 0). To find out: `teb` missing from the source files, or records the SQL builder (`overview-ops`) does not match | — (to write) | 💡 found 2026-11-18 in the post-build checks | S | unblocked (F7 deployed); start from a few source files; a builder fix probably needs only `overview-ops --reprocess`, no full rebuild (to confirm) |
| A33 | `setup_simulation.py`: Feel++ setup from DuckDB | [PLAN_setup_simulation.md](to_duckdb/plans/PLAN_setup_simulation.md) | ✅ 2026-11-25 (`8ba3500`) | S | python_magnetsetup E7; M8 waits for E1; its setups feed magnet-scipy's numerical commissioning (needs F10) |
| A34 | `export_inductance_matrix.py`: magnettools inductance matrix of an assembly as CSV (magnet-scipy F1); on M9_A230801_00 L_B = 1.858e-2 H, confirmed by the Archive identification in magnet-scipy (1.7–1.95e-2 H) | — (magnet-scipy `prompts/inductance_csv_from_duckdb.md`) | 🔄 written and tested, **untracked** | S | commit `create_Bstack` / `pair_tube_inductances` in `my-magnettools` first; the devcontainer image `magnettools-db:trixie-1.2.6` lacks them (F4) |
| A35 | M8 field stats and history from `TotalField` instead of `Field` when the assembly holds a supra magnet (both M8 assemblies), in `compute_exp_stats.py` and `compute_op_stats.py`; reprocess M8 only (189 files) | — (to write) | 💡 user request 2026-11-23; `TotalField` exists only from 2025-05-16 (116 files; 73 before, 52 with field); 4 older files have `Field` > 34 T | S–M | decisions: files before 2025-05-16, where to record the column used, scope (overview records, labels), sign (A28) |
| A36 | Read SUPERVISION / MAGNETS / LOGS from MySQL directly in the build (`EXPERIENCES_LOG`, `site_parameters`, cirrus) instead of the CSV exports | — (to write; overlaps A9 Phase 2 and the sessions plan) | 💡 user request 2026-11-23 | M | Q14 (live vs build-time); same connection code as C14 |

**Order for the data-quality chain:** JSON dates ✅ → A15 ✅ → A16 ✅ → A21 rebuilds ✅ (11-05, 11-10, 11-16) → A22 checks ✅ → deployed to calcul18 ✅ (F7, 2026-11-23). Next: A27 and A35 (before or during testing), A32, A26.

---

## B — Digital twin & ETL

Order, blockers and approvals come from
[PLAN_digital_twin_schema.md](plans/PLAN_digital_twin_schema.md#cross-plan-order-blockers-and-approvals).
**Approved so far: steps 0, E, H, R (header) (done), step 1 parts A and B (done), the file-check rules (steps 1–7 done) and the S1 methodology.**
Steps 1, S1, 2b and 2c can run in parallel. This track takes over
`to_duckdb/ROADMAP.md`'s former Open Questions 1 (lag) and 2 (plateaux), and
its Later item "Commissioning data structure".

"Step R" below is the sessions follow-up of [PLAN_session_records.md](plans/PLAN_session_records.md);
the schema plan's own step R (header resolution order) is listed as **R (header)**.

### Done since the 2026-11-16 snapshot

| Item | Plan | Evidence |
|---|---|---|
| Flow-params history: phase 0 items 1–2 (python_magnetcooling: pump model clamped at `Imax`, piecewise pump fit fixed; swapped hand-filled files); the rest awaits approval | [PLAN_flow_params_history.md](plans/PLAN_flow_params_history.md) | python_magnetcooling `9254d59` (pin `acdff56`), `ba54c06` |
| Overview-record checks: plan approved, steps 1–2 done, step 3 written but **stopped for re-plan** (both cross-correlation lag methods biased toward 0; least squares over ±300 s exact) | [PLAN_overview_record_checks.md](plans/PLAN_overview_record_checks.md) *(uncommitted)* | 2026-11-18; code and tests uncommitted in python_magnetrun and `to_duckdb/tests` |
| L5 revised: `simulation_results` (kept results only, admin import, UUID) instead of DuckDB `simulations` / `simulation_currents`; L3 `simulation_uid` | [PLAN_digital_twin_schema.md](plans/PLAN_digital_twin_schema.md) | `2f7aa0c` |

### Done since the 2026-11-07 snapshot

| Item | Plan | Evidence |
|---|---|---|
| File-check rules steps 6–7: experiment tables show `File integrity` / `ETL checks`, colour by precedence (unreadable or load error `#f1aeb5`, truncated `#ffe5d0`, then the most severe tag), tooltips and legend; File viewer colours the file selector and adds a note; `etl_spec` refuses the two colours; docs (`to_duckdb/docs/schema.md` "File checks and tags", python_magnetrun README) | [PLAN_file_check_rules.md](plans/PLAN_file_check_rules.md) | `0c9a924`, `28c0601`, `6234061`; python_magnetrun `0b231c6` (pushed) — the maintainer's look in the running app is still to report |

### Done since the 2026-11-05 snapshot

| Item | Plan | Evidence |
|---|---|---|
| File-check rules steps 1–4: `tags` (seeded `check:channel_not_empty`), `check_rules` (housing / assembly / magnet, optional housing version), `record_tags`; `magnetdb.py tag …` / `rule …`; `check_experiment_files.py --etl` stores the tags of failed checks; spec format 2 (rules replace the `Icoil` current check, `max_abs` / `p99_abs` / `mean_abs`); magnet parts renamed **wiring** (`set_magnet_wiring`) | [PLAN_file_check_rules.md](plans/PLAN_file_check_rules.md) | `57a95bf`; python_magnetrun `9db713b` |
| Documents only: ETL D1 revised b → a (magnet parts with `valid_from` / `valid_to`, one spec per period, `spec_period` check; code not done); header versions with a status (`stale` / `commissioning` / `valid`), data issue #12 (`M25032101` H1–H4 on `Ucoil2` since 2025-05-09), probes as FEM inputs (`v_probe_coherence`), open questions #31–#33 | [PLAN_pupitre_etl_spec.md](plans/PLAN_pupitre_etl_spec.md), [PLAN_digital_twin_schema.md](plans/PLAN_digital_twin_schema.md) | `bd47b13` |

### Done since the 2026-11-02 snapshot

| Item | Plan | Evidence |
|---|---|---|
| Step H — time-versioned housing config: `HousingConfig.versions` / `.at(t0)` in the bundled JSON, resolved at data start by every caller; `cleanupData` keeps `keys_to_add` columns; DuckDB `housing_config_versions`; first version `M8-260305` (M8 Bitters on `Ucoil14` since 2026-03-05) | [PLAN_digital_twin_schema.md](plans/PLAN_digital_twin_schema.md) (cross-plan row H) | `dfe5610`; python_magnetrun `311c284` |
| R (header) — header resolution order (assembly → housing version → header), documents only | [PLAN_digital_twin_schema.md](plans/PLAN_digital_twin_schema.md) (cross-plan row R, L2 "Pupitre header reader") | `2eb5099` |
| Step 1 parts A and B — Pupitre ETL spec per (assembly, housing version): `PupitreEtlSpec`, `prepare_pupitre`, `txt2csv` options; DuckDB `pupitre_etl_magnet`, `file_context.py`, `magnetdb.py etl set-magnet\|show\|export`, `check_experiment_files.py --etl`; `load_mrun` / `fromtxt` ETL arguments. Opt-in: no caller switched yet (step 2a) | [PLAN_pupitre_etl_spec.md](plans/PLAN_pupitre_etl_spec.md) | `055491f`, `0cc94e3`, `dd5e75f`, `9f7c72e`; python_magnetrun `eaf8ca2`, `b439c4a`, `d2e79e7`, `b565da6`, `09935ff` |

### Done since the 2026-10-16 snapshot

| Item | Plan | Evidence |
|---|---|---|
| Step E — file quality on `experiments` (`header_class`, `file_integrity` ok / truncated / unreadable, `file_checks`), filled in `magnetdb-2026-10-08.duckdb` | L2 in [PLAN_digital_twin_schema.md](plans/PLAN_digital_twin_schema.md) | `2ce7a09`; python_magnetrun `4caf41c` |
| Pupitre files with a binary crash tail load their valid rows (`truncated`, not `unreadable`); single-row files; DST rules for filenames | [PLAN_pupitre_binary_tail.md](plans/PLAN_pupitre_binary_tail.md) | `feb2df7`, `5b7a506`; python_magnetrun `17c16f9`, `b3344bd` |
| `magnetrun sessions`: one record per EXPERIENCES_LOG session (2018 → now) listing overview, archive, pupitre, incident, stats, hybrid and runlog files; unlogged files grouped | [PLAN_session_records.md](plans/PLAN_session_records.md), checks in [NOTES_session_records_checks.md](plans/NOTES_session_records_checks.md) | python_magnetrun `b75b6a9` (on `origin/spike/tdms-polars-benchmark`), pinned by the superproject in `0987dae`, dropped by `ffdb347`, restored by merge `a77f37c` (superproject `74cdd28`) |
| Cirrus A1 run-log analysis: reference current rebuilt from the log; 180/202 sessions matched to experiments; client IP → housing; 2014 clock dates | [NOTES_cirrus_A1_runlogs.md](plans/NOTES_cirrus_A1_runlogs.md), [NOTES_cirrus_A1_experiment_matching.md](plans/NOTES_cirrus_A1_experiment_matching.md) *(uncommitted)* | analysis 2026-10-16; python_magnetrun `909b2c6` (cirrus logs) — input for #27 and step R |

### Open

| Step | Work | Plan | Status | Depends on | Blocker |
|---|---|---|---|---|---|
| 0 | Reconcile plan documents | — | ✅ 2026-10-07 | — | — |
| E | File quality on `experiments` | L2 in the [schema plan](plans/PLAN_digital_twin_schema.md) | ✅ 2026-10-22 | — | — |
| H | Time-versioned housing config | cross-plan row H in the [schema plan](plans/PLAN_digital_twin_schema.md) | ✅ 2026-11-03 | — | — |
| R (header) | Header resolution order (documents only) | cross-plan row R in the [schema plan](plans/PLAN_digital_twin_schema.md) | ✅ 2026-11-03 | H | — |
| R | Sessions follow-up: find the pigbrother run log (`pigbrother_runlog` in `summary.json` / `sessions.json`); other follow-ups (archive size threshold, `power_end`, range cache, overview continuation rule) | [PLAN_session_records.md §Follow-up step R](plans/PLAN_session_records.md#follow-up-step-r-pigbrother-runlog-path-proposed-2026-10-23) | 📝 step R awaiting approval; other follow-ups need decisions | sessions ✅ | — |
| S1 | Signature regime robustness study (incl. lag Side A vs Side B, robust `Field` signature) | [PLAN_signature_regime_robustness.md](apps/dashboards/magnetdb/plans/PLAN_signature_regime_robustness.md) | 📝 methodology approved, not run | — | tooling location; RDP vs PELT; test-file set |
| S2 | Fill `overview_records.signatures`/`plateaux`/`sync_info` with real output | to write | 💡 | S1 | — |
| S3 | `teb` as a time series, shifted by stored lag | to write | 💡 | S2 | one-offset-per-file assumption |
| 1 | Pupitre ETL spec v1 | [PLAN_pupitre_etl_spec.md](plans/PLAN_pupitre_etl_spec.md) | 🔄 parts A and B committed with D1 = b (opt-in path). D1 = a (revised 2026-11-05) documented, its text aligned with the wiring and rules naming on 2026-11-07 (check rules keep the housing-version axis); its code awaits approval. The current-check tolerance during transients is covered by the file-check rules (`p99_abs`). Follow-ups, each needing its own plan: re-export specs when a housing version is added, raw pupitre view in `file_viewer` (`etl_checks` in the dashboards: done by the file-check rules step 6) | H, R (header) | none |
| 1 (rules) | File-check rules steps 5–7: M9 rules on a copy of the new DB (tolerances measured first), dashboard tag colours and tooltips, docs (`to_duckdb/docs/schema.md`, python_magnetrun README) | [PLAN_file_check_rules.md](plans/PLAN_file_check_rules.md) | ✅ 2026-11-13: step 5 (2026-11-07; rules superseded by A25 revision 2), step 6 as revised 2026-11-12 (`28c0601`), step 7 (`6234061`); the tags themselves are reviewed in A27 | 1 | — |
| 1b | Supra current `IS` for M8; hybrid loading moved into python_magnetrun | outline in [PLAN_pupitre_etl_spec.md](plans/PLAN_pupitre_etl_spec.md) | 💡 outline agreed | 1 | #27 Hybrid ↔ pupitre clock lag (M8 work started, `00e6467`; cirrus notes give a measured offset method) |
| 2a | Switch Pupitre callers (`load_mrun`, dashboards, `stress_map.py`) to the spec path | to write | 💡 | 1 | — |
| 2b | Phase 2: probes + L2 run configuration + `v_config_sections` | to write | 💡 | — | #2, #17, #20 (MAGFILE support landed in python_magnetrun `fc3dc54`) |
| 2c | Phase 1: L1 installation (PID, Ivar) | to write | ⛔ | — | **CIRRUS XML history access** |
| 3 | Pupitre ETL spec v2, driven by the assembly | to write | 💡 | 1, 2b | — |
| 4 | M5 rewiring | [NOTES_M5_bitters_wiring.md](plans/NOTES_M5_bitters_wiring.md) | ⏸ notes on hold | 2a, (3) | formal confirmation of M5 wiring |
| 5 | Phase 3: L3 characteristics + raw commissioning tables | to write | 💡 | 2a, 2b, 1b, S2, E ✅ | #22–#25 |
| 6 | Phase 4: ODE config builder (magnet_scipy inputs) | to write | 💡 | 2c, 5, S2 | `materials.alpha`; empty signatures until S2 |
| 7 | Phases 5–7: storage, L4 digital variants, L5 simulations | to write | 💡 | 5, 6 | #10 rustfs instance (shared with **D3**); online sim ↔ live comparison is also the "robot" role of F5 option F |
| — | Commissioning measurements + numerical companion | [PLAN_commissioning_numerical_companion.md](plans/PLAN_commissioning_numerical_companion.md) | ❌ superseded — §1 merged into step 5 | — | — |
| 1 (overview checks) | Rule checks on the Overview channels of each overview record, Field ↔ `Champ_magn` cross-check, one clock lag per pupitre file in `sync_info`; tags colour the overview-record tables | [PLAN_overview_record_checks.md](plans/PLAN_overview_record_checks.md) *(uncommitted)* | 🔄 paused at step 3 since 2026-11-18 | 1 (rules) ✅ | **lag method** ([Q15](#open-questions)); the same choice serves S1, #27 and magnet-scipy D1 / D4 |
| L3 flow params | Water-flow parameters per magnet: reference from the commissioning runs, check per experiment, refit, history (pump law vs hydraulics) | [PLAN_flow_params_history.md](plans/PLAN_flow_params_history.md) | 📝 phase 0 items 1–2 done; phases 1–5 await approval | — | supersedes the L3 "Flow parameters" section; magnet-scipy `flow_params_check.md`, `flow_probe_faults.md` |
| L3 FF magnettools | Field factor per magnet (field per unit current [T/A]) from the magnettools bindings, as intrinsic / in-situ L3 rows (`source = magnettools`), compared with the factors in use (MAGFILE, fits of pupitre `Field`) | — (to write; findings in [PLAN_header_field_factor_study.md](plans/PLAN_header_field_factor_study.md)) | 💡 user request 2026-11-23 | **E1** (M8 supra), magnettools in the environment (F4) | which magnettools call; report first or DB rows; feeds magnet-scipy M4 and M8-B; reuses A34's chain |

---

## C — Dashboards (`apps/dashboards/magnetdb`)

### Done since the 2026-11-16 snapshot

| Item | Plan | Evidence |
|---|---|---|
| Database selector lists the newest DB first | — | `9e5b64e` |
| Signal Stats files linked from the overview-record tables; the "Pigbrother Stats viewer" page renamed "Signal Stats viewer", its banner shows the duration and links to the overview record | — | `edaa485`, `ea7365c`, `cfd4f49` |
| Overview-records and File-viewer banners: one item per line, Hybrid sources, `SupraField` / `TotalField` | — | `ae3197d`, `ec18a12` |
| Overview records: energy from the pupitre sources only, with an energy check line | — | `4b07761` |
| File viewer: I_BOB [Hybrid] curve shown again (timestamp resolution, `align_hybrid_to_pupitre`) | — | `496b00d` |
| Deployed on calcul18 (image `2026.11.23`) with a maintenance page when the dashboard is down | [PLAN_dashboard_podman_operations.md](plans/PLAN_dashboard_podman_operations.md) | `bd9d474`, `8f9a4fb`; see F7 |

### Done since the 2026-11-07 snapshot

| Item | Plan | Evidence |
|---|---|---|
| File-quality and ETL check columns, tag colours, tooltips and legend in every experiment table; coloured file selector and note in the File viewer (track B file-check rules step 6) | [PLAN_file_check_rules.md](plans/PLAN_file_check_rules.md) | `28c0601` |
| I_BOB [Hybrid] overlay in the File viewer works on the real DB: the kHz day comes from the pupitre start time (stored kHz names have no date) | [PLAN_m8_overview_records.md](plans/PLAN_m8_overview_records.md) part D | `a5ab9ca` |
| C8 — About operation log 10 per page (latest first) | [PLAN_dashboard_tables_newest_first.md](plans/PLAN_dashboard_tables_newest_first.md) (done) | `a15eb7c` |

### Done since the 2026-11-02 snapshot

| Item | Plan | Evidence |
|---|---|---|
| Overview/Archive viewer page for `operationaldata` | [PLAN_operational_viewer.md](apps/dashboards/magnetdb/plans/PLAN_operational_viewer.md) | `ee1433f` (`pages/operational_viewer.py`) |
| Assembly and magnet history in Magnet/Part stats sorted newest first | — | `a88051c` |
| Empty date cells highlighted (A16) | [PLAN_missing_dates.md](plans/PLAN_missing_dates.md) | `5e66207` |
| Housing-config versions shown in the dashboard (track B step H) | [PLAN_digital_twin_schema.md](plans/PLAN_digital_twin_schema.md) | `dfe5610` |

### Done since the 2026-10-30 snapshot

| Item | Plan | Evidence |
|---|---|---|
| About page: operation log in a collapsible `html.Details` block | [PLAN_dashboard_tables_newest_first.md](plans/PLAN_dashboard_tables_newest_first.md) | `0987dae` — 10 per page done since (C8, `a15eb7c`) |
| Magnet stats coloured by `magnets.geometry_problem` (track A geometry check) | [PLAN_magnet_geometry_check.md](plans/PLAN_magnet_geometry_check.md) | `ba24ca4` (`magnet_stats.py`, `dash_selectors.py`); look awaits the user's check |

### Done since the 2026-10-16 snapshot

| Item | Plan | Evidence |
|---|---|---|
| Per-user plot style in browser `localStorage`, export/import, "Reset all"; nothing written under `$HOME/.config` | [PLAN_per_user_plot_style.md](apps/dashboards/magnetdb/plans/PLAN_per_user_plot_style.md) | `998158d` |
| Selected database kept in a cookie | — | `99065fe`, `3b81559` |
| Dated tables open newest first (groups keep their order; charts stay oldest first) | [PLAN_dashboard_tables_newest_first.md](plans/PLAN_dashboard_tables_newest_first.md) | `8614a4a`, `1c8d571` — the About-log part done since (C8, `a15eb7c`) |
| `sync_zoom` handling in the File viewer | — | `75d6a8a`, `b3343bc` |
| More information on experiments on the About page (en/fr/de/nl) | — | `257812f` |
| GitHub issue template for dashboard feedback | — | `6f124c8` (`.github/ISSUE_TEMPLATE/dashboard.yml`) |
| Dashboard image without magnettools; local Docker + Traefik deployment | see F4, F6 | `33099cc`, `949a260` |

### Done since the 2026-08-21 snapshot

| Item | Plan | Evidence |
|---|---|---|
| i18n (en/fr/de/nl) + 🌐 selector | [PLAN_dashboard_i18n.md](plans/PLAN_dashboard_i18n.md) | `d1cecff`, `b0b1bd3` (`src/i18n.py`) |
| Database summary banner | [PLAN_database_summary_banner.md](plans/PLAN_database_summary_banner.md) | `df0ca56`, `df3b273` |
| Graph CSV download | [PLAN_graph_csv_download.md](plans/PLAN_graph_csv_download.md) | `19e67c5` |
| Click-to-pin cursor sync | [PLAN_cross_graph_cursor_sync.md](apps/dashboards/magnetdb/plans/PLAN_cross_graph_cursor_sync.md) | `d3a2c89` |
| Per-field style overrides + gear icon | [PLAN_field_style_overrides.md](apps/dashboards/magnetdb/plans/PLAN_field_style_overrides.md) | `style_editor.py`, used on 3 pages |
| Sensor group order | [PLAN_group_order.md](apps/dashboards/magnetdb/plans/PLAN_group_order.md) | `53aa756` |
| Date filters on Experiments/Overview tables | [PLAN_experiment_overview_date_filters.md](apps/dashboards/magnetdb/plans/PLAN_experiment_overview_date_filters.md) | committed |
| Per-region loading spinner | [PLAN_loading_spinner_scope.md](apps/dashboards/magnetdb/plans/PLAN_loading_spinner_scope.md) | `bf52c5a` |
| SUPERVISION `bdd` data in viewers | [PLAN_supervision_bdd_file_viewer.md](plans/PLAN_supervision_bdd_file_viewer.md) | `8089706` |
| Incident-file curves on Defaults & Spikes | [PLAN_defaults_spikes_incident_data.md](apps/dashboards/magnetdb/plans/PLAN_defaults_spikes_incident_data.md) | 2026-10-15, `0afaeb9` |
| Hoop-stress history in Part stats | [PLAN_part_stats_hoop_stress.md](apps/dashboards/magnetdb/plans/PLAN_part_stats_hoop_stress.md) | committed |
| Research-area, TDMS stats viewer, About pages; magnet-time coloured by field range; DB-change callback | — | `048cb57`, `5d66fab`, `d24a82d`, `7155c22`, `f7ebd36` |

### Open

| ID | Item | Plan | Status | Effort | Depends on / blocker |
|---|---|---|---|---|---|
| C1 | Waterflow comparison page (+ root fix of cwd-dependent `importlib.resources`) | [PLAN_waterflow_dashboard.md](plans/PLAN_waterflow_dashboard.md) | 📝 no status line, not implemented | M | **E3** (waterflow_factory rework); the resources part may be partly done (`597b56f`) |
| C2 | Click an event marker to lazily load that event file | [PLAN_overview_records_event_click.md](apps/dashboards/magnetdb/plans/PLAN_overview_records_event_click.md) | 📝 draft, diverged | S | possibly superseded by the eager toggle + Defaults & Spikes curves — [Q3](#open-questions) |
| C3 | Magnet stats Housing/Year filter | [PLAN_magnet_stats_year_filter.md](apps/dashboards/magnetdb/plans/PLAN_magnet_stats_year_filter.md) | ⏸ tabled 2026-08-20 | S | — |
| C4 | Stress/fatigue linking in assembly/magnet stats; show stale results | [to_duckdb/plans/ROADMAP.md](to_duckdb/plans/ROADMAP.md) Later; A11 #1 | 💡 | S–M | A11 #1 |
| C5 | Table technology for trend columns (great_tables nanoplot vs DataTable+base64 vs ag-grid Enterprise) | [PLAN_m1_project_sort.md §3b](plans/PLAN_m1_project_sort.md) | 💡 decision open | ? | [Q6](#open-questions) |
| C6 | M1-note dashboards: pigbrother `Champ_magn` in overview (13), fault annotations (26/30), commissioning (45), magnet_scipy comparison (46), energy balance (47) | [PLAN_m1_project_sort.md](plans/PLAN_m1_project_sort.md) | 💡 | M each | 45 → B step 5; 46 → B step 6 |
| C7 | Comparison-page performance (`PERFORMANCE_PLAN.md`) | — | ❌ plan file removed; page in `pages_disabled/` | — | — |
| C9 | Wide-format CSV download | [PLAN_csv_download.md](apps/dashboards/magnetdb/plans/PLAN_csv_download.md) | 📝 proposed 2026-11-03 | ? | best after **C11** (`download_group_csv` is copied in five pages) |
| C10 | Hybrid viewer page | [PLAN_hybrid_viewer.md](apps/dashboards/magnetdb/plans/PLAN_hybrid_viewer.md) | 📝 drafted 2026-11-03 | ? | best after **C11** (else a fourth copy of the viewer page); relates to B step 1b (hybrid loading moved into python_magnetrun) and A26 (hybrid files in `operationaldata`, 2019–2024 year folders) |
| C11 | Shared viewer code (zoom, CSV download, sensor menus) for the File / Operational / Stats viewers (66–86 % shared lines), then Overview / Defaults & Spikes, then the Magnet / Part / Assembly stats pages | [review §1](REVIEW_readability_maintainability.md) (plan to write) | 💡 | M | A31; before C9, C10 and the F7 tester issues; not in the first calcul18 image |
| C12 | One connection helper; page-level SQL (4 pages) moved into `magnetdb_analysis.py`; status lists shared with `to_duckdb/enums.py` | [review §3](REVIEW_readability_maintainability.md) (plan to write) | 💡 | M | **F5** decision (where shared queries live) |
| C13 | Small fixes: declare `pint` / `scipy` / `natsort` in `pyproject.toml`, stale paths in UI hints and the default `DB_PATH`, dead code (`magnetdb_metrics.py`, `pages_disabled/`), French comments, docstrings of the viewer callbacks | [review, smaller items](REVIEW_readability_maintainability.md) (plan to write) | 💡 | S | — |
| C14 | Live M8 viewer: while an M8 session is open (EXPERIENCES_LOG `M8i` / `M8e`), poll SUPERVISION and HYBRIDE and plot sensors by category like the File viewer; local first | [PLAN_live_m8_viewer.md](plans/PLAN_live_m8_viewer.md) *(uncommitted)* | 📝 awaiting approval (7 questions, defaults given) | M | calcul18 in its own plan (Podman secret, read-only account, `mysql_scanner` in the image); first slice of C11 (`sensor_group_block`) |
| C15 | "Cryogenic" group for M8 files in the File viewer, from the HYBRIDE MySQL DB over the file's time span | — (follow-up of C14) | 💡 user request 2026-11-23 | S | C14 (`live_sources.py`, `hybride-db-defs.json`); HYBRIDE timestamps are Paris local time; lag vs pupitre to measure; channel list ([Q16](#open-questions)) |

Tester
feedback from the calcul18 evaluation (F7) will arrive as GitHub issues
through the `6f124c8` template.

---

## D — `python_magnetrun`

Only open and recent streams are listed here. Completed history lives in
[python_magnetrun/prompts/ROADMAP.md](python_magnetrun/prompts/ROADMAP.md).

### Done since the 2026-11-16 snapshot

| Item | Plan | Evidence |
|---|---|---|
| SUPERVISION `bdd` defs: `ted` / `tsd` and the nitrogen channels described; `Nitrogen_Level` renamed `Loop_Pressurisation`; field definitions fixed | — | `ad929c4`, `fb3208e`; superproject `19a14cd`, `49fcccd` |
| `utils.files`: pigbrother Stats TDMS files resolved to `Fichiers_stats` (the Stats viewer showed no sensors) | — | `19bed52` |
| python_magnetcooling pin bumped to `9254d59` | — | `9bc23e8` (pinned in `1e5a657`) |
| `flow_params.compute`: `Vpmax` is the speed rise above `Vp0`; sort by current | [PLAN_flow_params_history.md](plans/PLAN_flow_params_history.md) | `d882a6d` (pushed, **not pinned**: D19) |

### Done since the 2026-11-15 snapshot

| Item | Plan | Evidence |
|---|---|---|
| `ruff check --fix` (13 files; mechanical fixes) — test suite not run on this commit yet | — | `8ff434c` (pushed; superproject `8b2018f`); rest in D17 |

### Done since the 2026-11-07 snapshot

| Item | Plan | Evidence |
|---|---|---|
| `analysis`: pigbrother "Stats" files renamed `signal_stats` (A24 phase A) | [PLAN_overview_records_from_operationaldata.md](plans/PLAN_overview_records_from_operationaldata.md) | `3354e50` |
| Housing config: M7 and M10 versions for swapped insert supplies (A25); M8-211225 12-slot wiring and new `M8-230913` (data issue #14); `pigbrother_current_map`, GR1 → IH during `M10-210325` (data issue #17) | [PLAN_pigbrother_pupitre_current_channels.md](plans/PLAN_pigbrother_pupitre_current_channels.md) | `69f6c49`, `33cb732`, `e4c1654` |
| Hybrid: EXPERIENCES_LOG session mask for kHz currents; pupitre ↔ Hybrid lag example | — | `5d2a58a` |
| README: the pupitre ETL spec checks are rules (file-check rules step 7) | [PLAN_file_check_rules.md](plans/PLAN_file_check_rules.md) | `0b231c6` (pushed) |

### Done since the 2026-11-05 snapshot

| Item | Plan | Evidence |
|---|---|---|
| `runetl` check rules (spec format 2): `rules` in `PupitreEtlSpec`, evaluated with `DataFrame.eval`; `current` and `ICOIL_CHECK_ATOL` removed; `etl show` prints the rules — B file-check rules | [PLAN_file_check_rules.md](plans/PLAN_file_check_rules.md) | `9db713b` |
| `magnetrun cirrus-mirror`: raw cirrus logs and CIRRUS XMLs from srv-data-install into `<root>/cirrus/<feed>/` (stage D; full 2026 back-fill ≈ 1.8 GB done locally) | `PLAN_cirrus_mirror.md` *(local, git-ignored)* | `37dda4d` |
| Examples: compare / plot a SUPERVISION `bdd.csv` export against a pupitre aggregate csv (clock offset, default 7196 s) | — | `321cecd` |

### Done since the 2026-11-02 snapshot

| Item | Plan | Evidence |
|---|---|---|
| Time-versioned housing config (`HousingConfig.versions` / `.at(t0)`) — B step H | [PLAN_digital_twin_schema.md](plans/PLAN_digital_twin_schema.md) | `311c284` |
| Pupitre ETL spec part A (`PupitreEtlSpec`, `prepare_pupitre`, etl CLI); `fromtxt` forwards ETL arguments; `txt2csv` opt-in spec options, working imports and logging (its plot options remain broken); `load_mrun` explicit ETL arguments — B step 1 | [PLAN_pupitre_etl_spec.md](plans/PLAN_pupitre_etl_spec.md) | `eaf8ca2`, `b439c4a`, `d2e79e7`, `b565da6`, `09935ff` |
| `correlations` accepts narwhals frames; `get-record` narwhals-backed with `--housing ALL`; `mysql_connect --utc/--no-utc` (naive UTC export by default) | — | `78db2c9`, `d23d7b8`, `73eb198` |
| Spike `b75b6a9` (sessions, end times) merged back after `ffdb347` had dropped its pin; 1409 tests pass (the 10 failures / 24 errors that remain come from Git LFS pointer files in `data/`) | [PLAN_session_records.md](plans/PLAN_session_records.md) | `a77f37c`; superproject `74cdd28` |

### Done since the 2026-10-16 snapshot

| Item | Plan | Evidence |
|---|---|---|
| File quality on experiments: truncation reported to `to_duckdb` (B step E) | [PLAN_digital_twin_schema.md](plans/PLAN_digital_twin_schema.md) L2 | `4caf41c` |
| Time changes (DST) within a pupitre file; polars UTF-8 errors on binary tails | [PLAN_pupitre_binary_tail.md](plans/PLAN_pupitre_binary_tail.md) | `17c16f9`, `b3344bd` |
| Cirrus run-log download (`requests.cirrus_logs`), sorted by time | [NOTES_cirrus_A1_runlogs.md](plans/NOTES_cirrus_A1_runlogs.md) | `909b2c6`; superproject `e0b4a10` |
| `magnetrun sessions` (`analysis/sessions.py`), `FileDiscovery.discover_window`, archive/pupitre end times in `extract_data`; 1350 tests pass | [PLAN_session_records.md](plans/PLAN_session_records.md) | `b75b6a9` — pinned by the superproject in `0987dae`, dropped by `ffdb347`, restored by `a77f37c` |

### Done since that roadmap's 2026-06-11 update (not yet reflected there)

| Item | Plan | Evidence |
|---|---|---|
| Polars MagnetData for pupitre | [polars-magnetdata-pupitre.plan.md](python_magnetrun/prompts/polars-magnetdata-pupitre.plan.md) | ✅ in plan; `magnetdata_polars.py` |
| Narwhals downstream consumers | [narwhals-downstream-consumers.plan.md](python_magnetrun/prompts/narwhals-downstream-consumers.plan.md) | `6fec823` |
| TdmsMagnetData → polars by default; custom `nptdms` live (part of Stream 4.3) | [mrun-cache-implementation.plan.md](python_magnetrun/prompts/mrun-cache-implementation.plan.md) | `1892c37`; plan says ✅ Live |
| Trigger & VProcess plotting (Stream 4.6) | [4.6-trigger-vprocess-plotting.plan.md](python_magnetrun/prompts/4.6-trigger-vprocess-plotting.plan.md) | `plot_vprocess_variable` in `hybrid_data.py` |
| TDMS stats files, archive-TDMS file discovery, MAGFILE data, SUPERVISION `bdd` defs, MySQL export sort, thread-safe pint registry, bandit hook | — | `eea0dbe`, `3e57785`, `fc3dc54`, `5c827c5`, `077800f`, `6e22643`, `5362867` |

### Open

| ID | Item | Plan | Status | Effort | Depends on / blocker |
|---|---|---|---|---|---|
| D1 | TDMS polars export benchmark spike | [tdms-polars-benchmark.plan.md](python_magnetrun/prompts/tdms-polars-benchmark.plan.md) | 🔄 — the superproject pins branch `housing-config-versions`, which contains `spike/tdms-polars-benchmark` (merge `a77f37c`; see Q1) | S | — |
| D2 | Parquet save/load with rich metadata (Stream 4.7, Phases 1–7) | [parquet-save-load.plan.md](python_magnetrun/prompts/parquet-save-load.plan.md) | 📝 fully designed (D1–D8), all ⏳ | M (~3 d) | — |
| D3 | Curated Parquet input + S3-backed file access | [curated-parquet-s3.plan.md](python_magnetrun/prompts/curated-parquet-s3.plan.md) | 💡 discussion notes | M | D2; rustfs instance (shared with B step 7) |
| D4 | Phase 2D side-by-side comparison (`plot_comparison(list[DataLoader])`) | [ROADMAP §2D](python_magnetrun/prompts/ROADMAP.md) | 💡 unblocked | M | — |
| D5 | Cross-domain comparison Phases D–G + 3.7 pattern entries in `*-defs.json` | `cross-domain-comparison.prompt.md`, [ROADMAP §4.2](python_magnetrun/prompts/ROADMAP.md) | 💡 (`ComparisonSession` not started) | L | D6 |
| D6 | `HybridData` timestamp support (Stream 4.1) | [hybriddata-timestamp-plan.md](python_magnetrun/prompts/hybriddata-timestamp-plan.md) | ❓ `addTime` present in `hybrid_data.py` — verify | S | — |
| D7 | snake_case migration with deprecation shims (required by CLAUDE.md) | [snake-case-migration.plan.md](python_magnetrun/prompts/snake-case-migration.plan.md) | 📝 Pass 1 not started; open questions in plan | L | — |
| D8 | Test coverage → 80 % | [coverage-80pct.plan.md](python_magnetrun/prompts/coverage-80pct.plan.md) | ❓ status unknown | M | — |
| D9 | Label/legend uniformization | [label-legend-uniformization.plan.md](python_magnetrun/prompts/label-legend-uniformization.plan.md) | ❓ plan shows 12 open steps; superproject `6577295`/`f3f9334` changed labels | S | verify |
| D10 | TDMS export (Stream 4.5) | [ROADMAP §4.5](python_magnetrun/prompts/ROADMAP.md) | 💡 | M ×3 | — |
| D11 | Multiple-file `vs_time` regression (Stream 1) | [ROADMAP §1](python_magnetrun/prompts/ROADMAP.md) | 💡 open since May | S | — |
| D12 | mypy, logging migration, quick wins | [ROADMAP](python_magnetrun/prompts/ROADMAP.md) | 💡 background | S | — |
| D13 | marimo tutorial notebooks | [marimo-tutorial.plan.md](python_magnetrun/prompts/marimo-tutorial.plan.md) | 💡 not started (only `.ipynb` notebooks exist) | M | — |
| D14 | Dash / pywry / Textual GUIs | [dash-plan](python_magnetrun/docs/dash-plan.md), [gui-plan](python_magnetrun/docs/gui-plan.md), [tui-plan](python_magnetrun/docs/tui-plan.md) | 💡 not started | L | overlaps track C — [Q4](#open-questions) |
| D15 | HoloViews plotting migration | [holoviews-migration.plan.md](python_magnetrun/prompts/holoviews-migration.plan.md) | ⏸ optional | M | — |
| D16 | Legacy TODO list (spike removal, smoothing, mrecord rework, …) | [python_magnetrun/TODO.md](python_magnetrun/python_magnetrun/TODO.md) | 💡 unsorted | ? | partly superseded by B |
| D17 | Last lint findings: one B007 false positive in `readers/csv_readers.py` (`# noqa` with a reason); exclude the nested `python_magnetcooling` submodule from ruff (its 22 findings belong to E6); test suite before and after | — (plan given in session 2026-11-16, no plan file) | 📝 awaiting approval | S | — ; `.pre-commit-config.yaml` still pins ruff `v0.4.0` (`.venv` has 0.17.4) |
| D18 | `analysis/cli.py`: combined analysis crashed on `d[5].empty` (hybrid incidents are a dict), seen on 2026-11-22 after `summary.json` was written; fix and test in the working tree | — | 🔄 **uncommitted** | S | commit with a test run, or drop |
| D19 | Bump the superproject pin from `9bc23e8` to `d882a6d` (flow-params compute fix); the checkout is already there | — | 💡 | S | with the next python_magnetrun commit (D18 or the overview checks) |

Archive TDMS files log formula warnings (`Référence_GR2 = Référence_A3 +
Référence_A4`, variables missing in `M9_Archive_*`); seen during F7, a
`*-defs.json` configuration issue, the files still load.

---

## E — `python_magnetsetup` / `python_magnetgeo` / `python_magnetcooling`

### Done since the 2026-11-16 snapshot

| Item | Evidence |
|---|---|
| python_magnetsetup: E7 (json templates, assembly YAML load, multi-part magnets) | `e78a6c3`, `f1cf3d7`, `ed970e6` |
| python_magnetcooling: the two import errors on `main` fixed, imports tested in fresh interpreters, CI runs ruff and pytest on Python 3.11 / 3.12, pump model clamped at `Imax` | `97bcf69`, `c7aba45`, `bed072d`, `9254d59` (pinned) |
| python_magnetgeo: Bitter geometry (YAML, `.d`) from identification sheets, outputs moved to `hifimagnet-projects` | `4aaac9e`, `c066758` (not pinned) |

### Open

| ID | Item | Plan | Status | Effort | Depends on / blocker |
|---|---|---|---|---|---|
| E1 | Fix the Supra branch of `magnet_setup` (`DetailLevel.NONE`), deb runtime deps, tests run at .deb build | [python_magnetsetup/PLAN_supra_umagnet.md](python_magnetsetup/PLAN_supra_umagnet.md) | 📝 2026-10-15 (plans committed in `cf9718a`) | M | — ; **unblocks A2 and the M8 assemblies** |
| E2 | Supra detail levels DBLPANCAKE / PANCAKE / TAPE | [python_magnetsetup/PLAN_supra_detail_levels.md](python_magnetsetup/PLAN_supra_detail_levels.md) | 📝 2026-10-16 | M–L | E1; relates to A5 (`jc`) |
| E3 | Cooling TODOs: thermohydraulics check (gradHZH), z-dependent dh/sh, waterflow_factory via magnetrun, mrun input for waterflow pipeline, secondary-flow hysteresis | [python_magnetcooling/TODOs.md](python_magnetcooling/TODOs.md) | 💡 no plans | ? | feeds C1 |
| E4 | Cooling models from the M1 student (primary heat exchanger) | [to_duckdb/plans/ROADMAP.md](to_duckdb/plans/ROADMAP.md) Later | ⛔ | M | student's models |
| E5 | `python_magnetgeo` | — | no open plans | — | Track B of the rename is under G3 |
| E6 | Lint findings left after `ruff check --fix`: `python_magnetsetup` 85 (25 unused variables, 13 star-import uses, …), `python_magnetgeo` 53 (incl. a syntax error in `data/template-gmsh-suprastruct.py`), `python_magnetcooling` 22 (not started; 4 undefined names in quoted annotations) | — (to write) | 🔄 mechanical part: python_magnetsetup `42a0c56`, python_magnetgeo `c4ba865` (pins bumped in `4494b15`); python_magnetsetup suite now 373 tests (E7) | S–M | on the python_magnetsetup branch with E1 / E8 |
| E7 | python_magnetsetup fixes found by A33: the 9 Axi cfpdes json templates (unclosed `{{/T_magnet}}` since `f8d15d4`); the assembly YAML load in `setup()` (`f.name` on a path string); multi-part Bitters / Supras kept whole in `magnet_setup()` (regression since `b7a8359`) | [PLAN_fix_json_templates.md](python_magnetsetup/PLAN_fix_json_templates.md), [PLAN_fix_multipart_magnets.md](python_magnetsetup/PLAN_fix_multipart_magnets.md) | ✅ 2026-11-25: `e78a6c3`, `f1cf3d7`, `ed970e6` (pushed; pins `77a9cdf`, `bc5f947`) | S | Supras checked by unit test only until E1 |
| E8 | Single-magnet setups name the magnet `""` (`setup()` line 524), giving `Stat_T_` / `PowerM_` with an empty name | — | 💡 found 2026-11-25 | S | on the python_magnetsetup branch with E1 / E6 |
| E9 | python_magnetdb carries its own copy of python_magnetsetup (`~/github/python_magnetdb/python_magnetsetup/`): check it for the three E7 bugs, which would break FE setups through the magnetdb server | — | 💡 not checked | S | — |

Reference: [Cooling Boundary Conditions for Electromagnets.md](Cooling_Boundary_Conditions_for_Electromagnets.md)
*(uncommitted, 2026-10-09)*: per-magnet Robin condition (h, T_w) driven by
each magnet's own current and pump; background for E3 and B step 6.

---

## F — Infrastructure, CI, packaging, deployment

| ID | Item | Plan | Status | Effort | Depends on / blocker |
|---|---|---|---|---|---|
| F1 | Self-hosted GitHub runner (`ghrunner`, `MagnetDB/apt-depot` only) | [PLAN_github_runner_setup.md](plans/PLAN_github_runner_setup.md) | 📝 | S | host to confirm (the plan says calcul22, now the dev workstation only) |
| F2 | `apt-ci` upload path to euler + generic build workflow | [PLAN_apt_ci_upload.md](plans/PLAN_apt_ci_upload.md) | 📝 | M | F1 |
| F3 | freesteam Debian package on release | [PLAN_freesteam_deb_ci.md](plans/PLAN_freesteam_deb_ci.md) | 📝 | S | F1, F2 |
| F4 | magnettools release pipeline (deb + wheel + public image) | [PLAN_magnettools_release_pipeline.md](plans/PLAN_magnettools_release_pipeline.md), [NOTES_auditwheel_spike.md](plans/NOTES_auditwheel_spike.md) | 📝 Phase 1; 🔄 Phase 2 — first slice [PLAN_magnettools_optional.md](plans/PLAN_magnettools_optional.md) steps 0–5 ✅ (`1e58ba9`, `33099cc`: magnettools optional, `debian:trixie` devcontainer fed by `magnettools-db:trixie-1.2.6`), step 6 (devcontainer rebuild in VS Code) left to the user | L | F1 (its step 9 revises "no runner"); GPL `libgsl`/`libfreesteam` licensing for public binaries; unblocks A14, hoop-stress tests |
| F5 | DuckDB ↔ PostgreSQL (`python_magnetdb`) architecture | [PLAN_duckdb_postgres_merge.md](plans/PLAN_duckdb_postgres_merge.md) (follow-up discussion 2026-10-28), [PLAN_duckdb_master_control_plane.md](plans/PLAN_duckdb_master_control_plane.md), [NOTES_python_magnetdb_deployment.md](plans/NOTES_python_magnetdb_deployment.md) | 📝 **option F** proposed 2026-10-28: DuckDB master for all magnet data, Postgres for shared control data only, python_magnetdb as a thin API over `to_duckdb`, `simulator`/`robot` roles; supersedes "Solution 1". 2026-11-25: simulation storage decided within it (section "Simulation runs and meshes"; rustfs replaces MinIO; the DuckDB file is confidential; sizing). python_magnetdb deployment delayed (notes only) | XL | [Q10](#open-questions); each phase gets its own plan |
| F6 | Plan 1 — dashboard on the dev machine (Docker, read-only snapshot, Traefik `:8443`) | [PLAN_dashboard_local_deployment.md](plans/PLAN_dashboard_local_deployment.md) | 🔄 steps 0–5, 7, 10, 11 passed; 6, 8, 9 left; plan 1b (calcul22) not needed | S | — |
| F7 | Plan 2 — dashboard on **calcul18** (rootless Podman + Quadlet as user `magnetdb`, uid 1004; Traefik `:8443`, mkcert CA + basicAuth; read-only records via rclone 1.75.2 and a restricted sftp key) | [PLAN_dashboard_server_deployment.md §Target: calcul18](plans/PLAN_dashboard_server_deployment.md#target-calcul18-2026-10-30), units in `scripts/quadlet/`, [tester note](apps/dashboards/magnetdb/docs/evaluation_tester_note.md) *(French)* | 🔄 evaluation with advanced users approved 2026-10-30; **deployed 2026-11-23**: image `magnetdb-dashboard:2026.11.23` and `magnetdb-2026-11-16-m8hybrid.duckdb` (10-08 DB kept), calcul22's `bdd.csv` (naive UTC, to 2026-11-17); maintainer's browser check passed; maintenance page live (`8f9a4fb`); rollback image `localhost/magnetdb-dashboard:previous`. Step 11 (testers): **start not confirmed** ([Q19](#open-questions)) | M | wired LNCMI network only (VPN does not pass `:8443`); open findings: no client IP in the access log, records key reads all of `/mnt/pve/DATA` |
| F8 | Plan 3 — `to_duckdb` writer container (private image from `magnettools-db`, read-write on demand) | [PLAN_dashboard_server_deployment.md §Plan 3](plans/PLAN_dashboard_server_deployment.md#plan-3-to_duckdb-writer-container) | 💡 draft notes | M | F7; once it runs, the server holds the master DB; relates to F5 (API process as sole DuckDB writer) |
| F9 | Cirrus raw-log mirror on calcul18 (stage B: scheduled `magnetrun cirrus-mirror` into the server's runlog root) | `PLAN_cirrus_mirror.md` *(local, git-ignored)*, draft at its end | 💡 draft; stage D (code, local back-fill) ✅ `37dda4d` | S | F7 host; feeds B step R, A20 and the L1 "CIRRUS XML history" blocker of B step 2c |
| F10 | CAD / mesh / solve toolchain for FE runs from A33 setups (magnet-scipy numerical commissioning: L_H, L_B, M_HB, R tables): Salome + HIFIMAGNET image with python_magnetgeo 1.0.1 (the 9.14.0 image has 0.3.1), gmsh with python_magnetgmsh (no image here: local venv), Feel++ `feelpp-v0.112.0-trixie.sif` (✅ smoke test 2026-11-24); `magnetsetup.json` still names old images | magnet-scipy `prompts/numerical_commissioning_M23072801.md` | 💡 | M | bind-mount the local repos or rebuild the images (open decision there); R tables also need the materials clean-up (data issue #7) |

Known infra issue: the File viewer hang on the records mount was a
**rclone 1.60 VFS-cache deadlock**, not a dashboard bug
([PLAN_dashboard_local_deployment.md §File viewer hang](plans/PLAN_dashboard_local_deployment.md#file-viewer-hang-rclone-160)).
Fixed on calcul24 and calcul18 with rclone 1.75.2; calcul22 still runs 1.60.

---

## G — External integrations & research

| ID | Item | Source | Status | Blocker |
|---|---|---|---|---|
| G1 | B-profile → currents inversion; experiment-planning optimizer | [M1 sort §E](plans/PLAN_m1_project_sort.md) | ⛔ | formula from Cedric/Romain |
| G2 | `python_magnetrun/requests` read **and write** to Cedric's DB; M7/M8 assembly configs | M1 sort §F (29/50) | ⛔ | authorization — [Q7](#open-questions) |
| G3 | Site→Assembly rename Track B (`python_magnetdb`, `python_magnetapi`) + magnetapi bulk-import test | [PLAN_site_to_assembly_rename.md](plans/PLAN_site_to_assembly_rename.md) | ⏸ deferred | separate repos; may be reshaped by F5 option F |
| G4 | Engie API linked to experiments | M1 sort §F (42) | 💡 | — |
| G5 | `hifimagnet-projects`: M7/M8 assembly setup, bitter status cleanup, bitter naming convention (the 2026-10-28 JSON fixes and the 2026-10-29 rings, A15 step 7, are committed: `4a926d8`, `612cafb`, `9338e22`) | [to_duckdb/TODOs.md](to_duckdb/TODOs.md), M1 sort §F/G | 💡 | cahier E. Verney |
| G6 | Field validation M8–M10 (`Field + Supra_Field == Total_Field`) | [to_duckdb/TODOs.md](to_duckdb/TODOs.md) | 💡 | — |
| G7 | Pre-2022 pigbrother data (NAS 2018–2021) | [to_duckdb/TODOs.md](to_duckdb/TODOs.md) | ⛔ | availability unknown |
| G8 | Special experiments (M19, negative IH/IB) | [to_duckdb/TODOs.md](to_duckdb/TODOs.md) | 💡 | schema design |
| G9 | Fix `python_magnetrun/examples/bilan.py`; update numerical commissioning | [to_duckdb/TODOs.md](to_duckdb/TODOs.md) | 💡 | the latter folds into B step 5 |
| G10 | Exploratory: ggsql spike, querychat over a local LLM | M1 sort §H | 💡 | — |

Reference: [package-assessment-prompt.md](package-assessment-prompt.md)
*(uncommitted)* — checklist prompt to assess a package's readiness for the
MagnetDB ecosystem.

---

## Cross-track dependencies

```mermaid
graph LR
  subgraph F[F · infra]
    F1[F1 runner] --> F2[F2 apt-ci] --> F3[F3 freesteam]
    F1 --> F4[F4 magnettools release]
    F6[F6 local deploy] --> F7[F7 calcul18 deploy] --> F8[F8 writer container]
    F5[F5 option F]
  end
  subgraph E[E · setup/cooling]
    E1[E1 Supra fix] --> E2[E2 Supra detail levels]
    E3[E3 cooling TODOs]
  end
  subgraph A[A · to_duckdb]
    A1[A1 exp-stats perf]
    A2[A2 part-named hoop columns]
    A5[A5 jc table]
    A7[A7 populate all] --> A8[A8 scheduler]
    A11[A11 update-impact follow-ups]
    A12[A12 processing-status flag]
    A13[A13 schema cleanup]
    A14[A14 hoop --check]
    A15[A15 insert rings ✅] --> A21[A21 full rebuild 🔄]
    A16[A16 missing dates ✅] --> A21
    A21 --> A22[A22 hoop stress + checks]
    A17[A17 retired guard ✅]
    A20[A20 archive hybrid/runlog]
    A3[A3 incidents]
    A31[A31 lint clean-up] --> A28[A28 stats common code] --> A1
    A31 --> A29[A29 crud split]
    A29 -.-> A3
    A29 -.-> A5
    A30[A30 logging] -.-> A8
  end
  subgraph B[B · digital twin]
    BR[R sessions runlog]
    BH[H housing versions ✅] --> BRH[R header ✅] --> B1
    B1[1 ETL spec v1 🔄] --> B1b[1b Supra IS M8]
    B1 --> B1r[rules steps 5–7 🔄]
    B1 --> B2a[2a switch callers]
    B2b[2b run config]
    B1 --> B3[3 ETL spec v2]
    B2b --> B3
    BS1[S1 signature study] --> BS2[S2 fill signatures] --> BS3[S3 teb series]
    B2c[2c installation]
    B2a --> B5[5 characteristics]
    B2b --> B5
    B1b --> B5
    BS2 --> B5
    B2c --> B6[6 ODE builder]
    B5 --> B6
    BS2 --> B6
    B5 --> B7[7 storage/variants/sims]
    B6 --> B7
    B2a --> B4[4 M5 rewiring]
  end
  subgraph C[C · dashboards]
    C1[C1 waterflow]
    C4[C4 stress links + stale]
    C6[C6 commissioning / scipy dashboards]
    C11[C11 shared viewer code] --> C9[C9 wide CSV]
    C11 --> C10[C10 hybrid viewer]
    C12[C12 DB access layer]
  end
  subgraph D[D · python_magnetrun]
    D2[D2 parquet save/load] --> D3[D3 curated parquet + S3]
    D6[D6 HybridData timestamps] --> D5[D5 cross-domain]
  end
  E1 --> A2
  E2 -.-> A5
  F4 --> A14
  F4 --> F8
  A1 -.-> A21
  E1 -.-> A22
  A22 --> F7
  A8 -.-> F8
  E3 --> C1
  A11 --> C4
  C4 --> A13
  BS2 --> A12
  BR -.-> A20
  B5 --> C6
  B6 --> C6
  D3 -. rustfs .- B7
  F5 -.-> F8
  F5 -. robot .- B7
  A31 --> C11
  A30 -.-> F8
  F5 --> C12
  E7[E7 magnetsetup fixes ✅] --> A33[A33 setup_simulation ✅]
  A33 --> F10[F10 CAD / mesh toolchain]
  F10 --> MSC[magnet-scipy numerical commissioning]
  A34[A34 inductance export] --> MSC
  E1 --> BFF[B: field factors via magnettools]
  LAG[lag method Q15] --> BOC[B: overview-record checks]
  LAG -.-> MSC
  C14[C14 live M8 viewer] --> C15[C15 cryogenic group]
  C14 -.-> A36[A36 MySQL in the build]
```

---

## Cross-repository: magnet-scipy

magnet-scipy (`~/github/magnet-scipy`, branch `claude_cleanup`, its own
`ROADMAP.md` with snapshot 2026-11-12) is the replay and comparison engine.
It reads files produced here and does not depend on DuckDB. The items that
meet:

| magnet-scipy | Here | Link |
|---|---|---|
| F1 — inductance CSV from DuckDB (`prompts/inductance_csv_from_duckdb.md`) | A34 `export_inductance_matrix.py` | the script is F1's implementation; L_B confirmed by the Archive identification (`85048af`) |
| `prompts/numerical_commissioning_M23072801.md` (FE R and L of M9_A230801_00) | A33 `setup_simulation.py` (option A there), E7, F10 | setups done; CAD / mesh toolchain next; R tables after the materials clean-up |
| D1 `ode-config` / D4 clock lag ("D1 estimates the lag by cross-correlation") | B overview-record checks, S1, #27 | the cross-correlation bias found here (Q15) applies there too |
| D3 — results in DuckDB | L5 `simulation_results` | revised 2026-11-25 (`2f7aa0c`, `e440aa7`) |
| M4 (field demand → reference currents), M8 stage B (screens ρ(T, \|B\|)) | B "L3 FF magnettools" | same magnettools chain as A34 |
| M3 — temperature coefficient | data issue #7, `materials.alpha`; Postgres materials extraction (12 materials missing in the live python_magnetdb DB, mixed `t_ref`) | blocks trustworthy FE R tables |
| M8 stage C — screen thermal state | C14 / C15, HYBRIDE `TTEcran4K/50K/100K` [to confirm] | the live viewer shows that data first |
| `flow_params_check.md`, `flow_probe_faults.md` (detector done), `debitbrut_staging_model.md` | [PLAN_flow_params_history.md](plans/PLAN_flow_params_history.md) | source study; the flow-probe detector could become a file-check tag |
| `operating_mode` (per-shot ECO / NORMAL, `2cbbcbe`) | `infer_operating_mode` (#17), `overview_records.mode` | possibly the same heuristic twice: to compare [unchecked] |

---

## Awaiting your approval

Drafted plans that can start as soon as they are approved. **Bold**
marks the ones that unblock other work.

0. **Lag method** for the overview-record checks ([PLAN_overview_record_checks.md](plans/PLAN_overview_record_checks.md), re-plan at step 3) — unpauses work uncommitted since 2026-11-18; the same choice serves S1 and magnet-scipy D1 / D4
1. **E1** [PLAN_supra_umagnet.md](python_magnetsetup/PLAN_supra_umagnet.md) — unblocks A2, E2, the M8 assemblies, their hoop stress (A22) and their field factors
2. **F5** [PLAN_duckdb_master_control_plane.md](plans/PLAN_duckdb_master_control_plane.md) — approves the direction and phase order; shapes F8 and G3
3. **F1** [PLAN_github_runner_setup.md](plans/PLAN_github_runner_setup.md) — unblocks F2, F3, F4
4. B step R ([PLAN_session_records.md](plans/PLAN_session_records.md#follow-up-step-r-pigbrother-runlog-path-proposed-2026-10-23))
5. B step 1, D1 = a code ([PLAN_pupitre_etl_spec.md](plans/PLAN_pupitre_etl_spec.md) step 9 and "D1 revision" files; text aligned with the wiring and rules naming 2026-11-07)
6. A2 [PLAN_hoop_stress_part_names.md](to_duckdb/plans/PLAN_hoop_stress_part_names.md) (after E1; before the full hoop-stress run of A22 avoids running it twice)
7. A1 [PLAN_exp_stats_performance.md](to_duckdb/plans/PLAN_exp_stats_performance.md) — makes the next full rebuild faster (best after A28)
8. C9 [PLAN_csv_download.md](apps/dashboards/magnetdb/plans/PLAN_csv_download.md), C10 [PLAN_hybrid_viewer.md](apps/dashboards/magnetdb/plans/PLAN_hybrid_viewer.md) (after F7, best after C11)
9. A19 [PLAN_magnet_incidents_plot.md](to_duckdb/plans/PLAN_magnet_incidents_plot.md), A20 [PLAN_archive_magnet_hybrid_runlog.md](to_duckdb/plans/PLAN_archive_magnet_hybrid_runlog.md)
10. A3 [PLAN_incident_tracking.md](to_duckdb/plans/PLAN_incident_tracking.md) and A4 [PLAN_part_delete.md](to_duckdb/plans/PLAN_part_delete.md)
11. A5 [PLAN_jc_table.md](plans/PLAN_jc_table.md)
12. A6 [PLAN_fuzzy_date_tolerance.md](to_duckdb/plans/PLAN_fuzzy_date_tolerance.md) (check what `d0fb3ce` and `59197ad` already cover first)
13. E2 [PLAN_supra_detail_levels.md](python_magnetsetup/PLAN_supra_detail_levels.md) (after E1)
14. F2, F3, F4 Phase 1 (after F1)
15. C1 [PLAN_waterflow_dashboard.md](plans/PLAN_waterflow_dashboard.md)
16. D2 [parquet-save-load.plan.md](python_magnetrun/prompts/parquet-save-load.plan.md) — design is complete
17. A26 — [PLAN_m8_overview_records.md](plans/PLAN_m8_overview_records.md) part C, to revise (F7 is deployed)
18. D17 — last lint findings in python_magnetrun (two one-line changes; no plan file)
19. C14 [PLAN_live_m8_viewer.md](plans/PLAN_live_m8_viewer.md) — live M8 viewer; also builds the MySQL access that C15 and A36 reuse
20. Flow-params history phases 1–5 ([PLAN_flow_params_history.md](plans/PLAN_flow_params_history.md))

Plans still **to be written** before work can start: A35 (M8 `TotalField`
stats, decisions in [Q17](#open-questions)); A36 and C15 (after C14);
B "L3 FF magnettools"; E8 / E9; F10 (or in magnet-scipy); A27 (tag review);
A28–A31 and C11–C13 (from the [review](REVIEW_readability_maintainability.md));
E6 (lint findings left in the setup / geometry / cooling libraries);
B steps S2, 2a, 2b, 2c;
the B step 1 follow-ups (spec re-export, raw pupitre
view; the transient tolerance is covered by the file-check rules);
A12; F8 (from the draft notes); F9 (from the draft in `PLAN_cirrus_mirror.md`);
a short retro-plan for the already-committed
`hoop_stress_fatigue_bins` table.

---

## Status drift to fix

These plan files or roadmaps say something that git or the code contradicts.
They are listed here and **were not edited**.

| File | Says | Reality |
|---|---|---|
| [PLAN_session_records.md](plans/PLAN_session_records.md), [NOTES_session_records_checks.md](plans/NOTES_session_records_checks.md) | "the parent repo does not record that submodule commit yet" | no longer true: python_magnetrun `b75b6a9` is in the pinned branch (merge `a77f37c`, superproject `74cdd28`) |
| [PLAN_digital_twin_schema.md](plans/PLAN_digital_twin_schema.md) cross-plan table | row H "versions not yet loaded into `magnetdb.duckdb`" | loaded in `magnetdb-2026-11-05.duckdb` (A21 rebuild, 6 versions incl. `M8-260305`), or by `housing sync` on older DBs |
| [to_duckdb/plans/ROADMAP.md](to_duckdb/plans/ROADMAP.md) | snapshot 2026-08-21; fatigue-bins matrix and `overview-records-from-json` under "Next"; `PERFORMANCE_PLAN.md` under "Next"; header points to this file "status as of 2026-10-16" | both items landed; `PERFORMANCE_PLAN.md` no longer exists; this file is now 2026-11-02 |
| [python_magnetrun/prompts/ROADMAP.md](python_magnetrun/prompts/ROADMAP.md) | updated 2026-06-11; 4.3 polars "deferred"; 4.6 "planned" | polars/narwhals/custom nptdms landed in September; 4.6 done; sessions, file quality, cirrus logs added in October |
| [to_duckdb/TODOs.md](to_duckdb/TODOs.md) | dashboard rework "(awaiting approval)"; "concat entries that share one pupitre file" unchecked | both done |
| [PLAN_hoop_stress_parquet_columns.md](to_duckdb/plans/PLAN_hoop_stress_parquet_columns.md), [PLAN_hoop_stress_part_history.md](to_duckdb/plans/PLAN_hoop_stress_part_history.md) | "pending approval, not started" | landed 2026-08-13 |
| [PLAN_hoop_stress_per_part_tests.md](to_duckdb/plans/PLAN_hoop_stress_per_part_tests.md) | "done, uncommitted" | committed in `558d505` (2026-08-18) |
| [PLAN_part_stats_hoop_stress.md](apps/dashboards/magnetdb/plans/PLAN_part_stats_hoop_stress.md), [PLAN_experiment_overview_date_filters.md](apps/dashboards/magnetdb/plans/PLAN_experiment_overview_date_filters.md), [PLAN_loading_spinner_scope.md](apps/dashboards/magnetdb/plans/PLAN_loading_spinner_scope.md) | "implemented, uncommitted" | committed |
| [PLAN_field_style_overrides.md](apps/dashboards/magnetdb/plans/PLAN_field_style_overrides.md) | "Proposed, not yet implemented" | implemented (`style_editor.py`) |
| [PLAN_operation_log.md](to_duckdb/plans/PLAN_operation_log.md), [PLAN_dashboard_i18n.md](plans/PLAN_dashboard_i18n.md), [PLAN_database_summary_banner.md](plans/PLAN_database_summary_banner.md), [PLAN_graph_csv_download.md](plans/PLAN_graph_csv_download.md), [PLAN_cross_graph_cursor_sync.md](apps/dashboards/magnetdb/plans/PLAN_cross_graph_cursor_sync.md), [PLAN_fill_magnet_sites.md](plans/PLAN_fill_magnet_sites.md) | no status line | implemented (see track tables) |
| [PLAN_waterflow_dashboard.md](plans/PLAN_waterflow_dashboard.md), [PLAN_overview_records_event_click.md](apps/dashboards/magnetdb/plans/PLAN_overview_records_event_click.md) | no status line | not implemented |
| [PLAN_fuzzy_date_tolerance.md](to_duckdb/plans/PLAN_fuzzy_date_tolerance.md) | "pending" | partly covered by `d0fb3ce` (and possibly `59197ad`) |
| [PLAN_github_runner_setup.md](plans/PLAN_github_runner_setup.md) | runner host calcul22 | calcul22 is now kept as the dev workstation (servers moved to calcul18) — host to re-decide |
| `python_magnetrun/python_magnetcooling/TODOs.md` | — | a stray copy of [python_magnetcooling/TODOs.md](python_magnetcooling/TODOs.md) inside the magnetrun submodule |
| magnet-scipy `ROADMAP.md` | snapshot 2026-11-12 | misses the 11-16 → 11-25 work (flow-probe detector, `operating_mode`, energy balance, Archive inductance identification, paired matrix and tap validation, per-tap benchmarks) and the new prompts (`numerical_commissioning_M23072801`, `inductance_matrix_fem`, `phase3_inverse_problem`, `debitbrut_staging_model`, …); to refresh in its own plan |
| [python_magnetrun/prompts/ROADMAP.md](python_magnetrun/prompts/ROADMAP.md) | — | the overview-record checks and the flow-params compute fix (`d882a6d`) are not in it either |
| `python_magnetrun/wrongdata.txt` | — | an empty stray file (2026-11-18) in the submodule's working tree |

---

## Open questions

1. ~~**D1** — stay pinned on `spike/tdms-polars-benchmark`?~~ **Resolved:**
   python_magnetrun stays on that branch
   ([PLAN_dashboard_server_deployment.md](plans/PLAN_dashboard_server_deployment.md), decisions of 2026-10-22).
   Follow-up done: the superproject pinned `b75b6a9` (sessions) in `0987dae`;
   `ffdb347` dropped it by mistake and merge `a77f37c` (superproject
   `74cdd28`) restored it. python_magnetrun now runs on `housing-config-versions`,
   which contains the spike branch.
2. ~~**A11 #5 vs A13** — update-impact follow-up 5 wants to *use*
   `magnets.geometry_data` in the hoop-stress computation, while schema
   cleanup lists it as vestigial. Which way?~~ **Resolved 2026-11-02:** A13.
   Magnet and assembly geometry stay unset and are always rebuilt from the
   parts; A11 #5 is dropped. Whether the rebuild works is checked and stored
   in `magnets.geometry_problem`
   ([PLAN_magnet_geometry_check.md](plans/PLAN_magnet_geometry_check.md)).
3. **C2** — now that Defaults & Spikes plots incident curves, is the
   click-to-load event view still wanted, or can it be marked superseded?
4. **D14** — are the Dash/pywry/Textual GUI plans in `python_magnetrun/docs/`
   still wanted alongside `apps/dashboards/magnetdb`?
5. **B S1** — lag Side A (`synchronization.py`) vs Side B (Wolali's
   `get_lag()`): the comparison is still to run (see
   [to_duckdb/ROADMAP.md Open Question 1](to_duckdb/plans/ROADMAP.md)).
6. **C5** — table technology for trend columns (great_tables selectively vs
   DataTable+base64 vs ag-grid Enterprise).
7. **G2** — is write access to Cedric's database something to pursue?
8. **B** — the 27 numbered open questions in
   [PLAN_digital_twin_schema.md](plans/PLAN_digital_twin_schema.md#open-questions).
9. **A9** — does python_magnetrun's MySQL export (`077800f`) and
   `SUPERVISION_DATA_DIR` (`b81a491`) already give enough SUPERVISION schema
   knowledge to unblock Phase 2?
10. **F5** — approve option F
    ([PLAN_duckdb_master_control_plane.md](plans/PLAN_duckdb_master_control_plane.md),
    its own "Open questions" section), which supersedes "Solution 1" of
    [PLAN_duckdb_postgres_merge.md](plans/PLAN_duckdb_postgres_merge.md)?
    **Simulation storage, decided 2026-11-25** (section "Simulation runs and
    meshes" of that plan):
    - Postgres keeps the job state; the Postgres role gates every run,
      compute servers included.
    - DuckDB `simulation_results` (L5 of the
      [schema plan](plans/PLAN_digital_twin_schema.md)) holds kept results
      only, imported by an admin on request, keyed by a UUID.
    - Meshes and CAD stay attachments, with a geometry fingerprint and the
      meshing options.
    - `audit_logs` records create and delete; cleanup by hand.
    - The object store is **rustfs** (replaces MinIO).
    - Exploratory runs are normal and are not saved unless asked;
      setups come from
      [PLAN_setup_simulation.md](to_duckdb/plans/PLAN_setup_simulation.md).
    - Deferred: `keep` flag, review statuses and screen, automatic expiry.
    - Sizing (2018–2026 counts): ≈ 2 new magnets and 6–7 new assemblies
      per year; meshes 4–60 GB per year (≈ 220 GB with assembly meshes);
      ≈ 70–90 runs per year.

    Still open: confidential columns of the DuckDB file and a redacted copy
    for students (the file is confidential); whether assembly meshes are
    kept. Approving option F itself remains open.
11. ~~**A18** — the 7 default choices at the end of
    [PLAN_operation_log_coverage.md](plans/PLAN_operation_log_coverage.md)
    (e.g. `db drop-table operation_log`, stale marks from `check --fix`,
    log granularity of G7/G8).~~ **Resolved 2026-11-02** by the
    implementation (`ef60cec`): dropping `operation_log` needs `--force`,
    G7 logs one summary row per run, G8 one row per assembly run.
12. **B R** — the pending decisions in
    [NOTES_session_records_checks.md](plans/NOTES_session_records_checks.md#decisions-pending)
    (archive size threshold, `power_end`, range cache, overview continuation rule).
13. **F7** — narrow the records key to `srv-data-install/` and `pbsurv/`
    (rclone filters or server-side chroot), and whether client IPs are needed
    in the Traefik log (Quadlet pod on pasta).
14. **A36 / C14 / C15** — MySQL sources read live (dashboard) or at build
    time (DuckDB tables), or mixed (build-side `EXPERIENCES_LOG`,
    `site_parameters`, cirrus; live `bdd` and HYBRIDE, recommended); a
    read-only MySQL account and a Podman secret for calcul18; keep a CSV
    fallback for offline work?
15. **B overview checks** — lag method: least squares over ±300 s
    (recommended; exact on the synthetic case) instead of the two
    cross-correlation methods of `synchronization.py` (biased toward 0 on
    finite plateau windows)? The answer also applies to S1 (Q5), #27 and
    magnet-scipy D1 / D4.
16. **C15** — which HYBRIDE channels for the cryogenic group (one category per
    table, or a tag list with units for `PT`, `HL`, `FT`, `VT`,
    `ValvesAnalog`)? Is the pupitre ↔ HYBRIDE clock lag the same as the
    −190 s measured on the FEPC TDMS files (#27)?
17. **A35** — M8 files before 2025-05-16 have no `TotalField`: use `Field`
    and mark it (recommended), rebuild `Field + ffS·I_BOB` from Hybrid, or
    first check the 4 files whose `Field` exceeds 34 T? Where to record the
    column used (`bin_config` JSON or a column)? Also overview records and
    dashboard labels? Same sign rule as A28?
18. **B L3 FF magnettools** — which magnettools binding gives the field
    factor; first output a report or DB rows (`electrical_characteristics`
    is designed, not created)?
19. **F7** — have the testers started (step 11)? It decides whether A27, A35
    and Q13 come before or during testing.
20. **F5 / students** — which columns of the DuckDB file are confidential
    (`parts.geometry_data`, `parts.cad`, `parts.design_office_reference`,
    material properties, `users.local_contact`), and do students need a
    redacted copy? Keep assembly meshes, or only magnet meshes?

---

## Suggested order

Ordered by dependency, not by date. Finish-and-deploy is done (2026-11-23);
the work now runs in two lanes that barely touch each other.

| # | Operations lane | Numerics lane |
|---|---|---|
| 1 | **Secure the uncommitted work:** the lag method ([Q15](#open-questions)) to resume the overview-record checks; D18 (`cli.py`); D19 (pin `d882a6d`); `python_magnetrun/wrongdata.txt` | **A34:** commit `create_Bstack` / `pair_tube_inductances` in `my-magnettools`, then `export_inductance_matrix.py` |
| 2 | **Before or during testing** ([Q19](#open-questions)): A27 (tag tolerances), A35 (M8 `TotalField`), Q13 (records key, client IPs) | **F10:** CAD / mesh toolchain, then magnet-scipy's numerical commissioning on the A33 setups (L_H, L_B, M_HB). Any time, no toolchain: the Archive identification on ECO runs in magnet-scipy (L_H, M_HB) |
| 3 | **MySQL sources:** C14 (live viewer) → C15 (cryogenic group) → A36 (build-side reads, A9, sessions) | **python_magnetsetup branch:** E1 (Supra), E6 (lint), E8; check python_magnetdb's copy (E9) |
| 4 | **While the testers work:** A32 (`teb` = 0), A26 (hybrid files in `operationaldata`), tester issues; the flow-params phases | **After E1:** field factors via magnettools; A2 → hoop stress (A22); FE R tables after the materials clean-up (data issue #7) |

Then, as before:

4. **Unblockers:** E1 → A2; F1 → F2/F4. E1 makes the M8 assemblies
   usable; F4 makes magnettools installable everywhere (tests, A14).
5. **Architecture decision:** F5 option F, before writing the F8 plan and
   before C12 (dashboard database access).
6. **Cheap drafted work:** A19, A4, A3, A5 (A5 before E2), A6. A29 (crud
   split) before A3–A5, or at least its rule: new entities in new modules.
   A28 before A1.
7. **Track B in parallel:** the D1 = a code; step R, S1 execution choices;
   2b and 2c as access allows (file-check rules done, kept across rebuilds by A25).
   A26 (hybrid files in `operationaldata`), then C10 (after C11).
8. **Library storage:** D2 → D3, coordinated with B step 7's rustfs need.
9. **Dashboards that follow the data:** C4 after A11 #1; C1 after E3;
   C6 after B steps 5–6; tester issues from F7.
10. **Housekeeping between larger items:** the [Status drift](#status-drift-to-fix)
    corrections, D11, D12 with A30 (logging, before F8 and A8), C13,
    A13 once C4 has retired `exp_part_bin_stats`.
11. **External and research items (G)** as their blockers clear.

---

## Plan index

Every plan and notes file in the workspace, mapped to its track.

| File | Track / status |
|---|---|
| **Repo root** | |
| [PLAN_apt_ci_upload.md](plans/PLAN_apt_ci_upload.md) | F2 📝 |
| [PLAN_atomic_load.md](plans/PLAN_atomic_load.md) | A ✅ (2026-10-29) |
| [PLAN_commissioning_numerical_companion.md](plans/PLAN_commissioning_numerical_companion.md) | B ❌ superseded |
| [PLAN_dashboard_i18n.md](plans/PLAN_dashboard_i18n.md) | C ✅ |
| [PLAN_dashboard_local_deployment.md](plans/PLAN_dashboard_local_deployment.md) | F6 🔄 |
| [PLAN_dashboard_podman_operations.md](plans/PLAN_dashboard_podman_operations.md) | F7 ✅ maintenance page and operations note (2026-11-23; the note itself is git-ignored) |
| [PLAN_dashboard_server_deployment.md](plans/PLAN_dashboard_server_deployment.md) | F7 🔄, F8 💡 |
| [PLAN_dashboard_tables_newest_first.md](plans/PLAN_dashboard_tables_newest_first.md) | C ✅ (C8 About log ✅ 2026-11-13) |
| [PLAN_database_summary_banner.md](plans/PLAN_database_summary_banner.md) | C ✅ |
| [PLAN_digital_twin_schema.md](plans/PLAN_digital_twin_schema.md) | B (master) |
| [PLAN_duckdb_master_control_plane.md](plans/PLAN_duckdb_master_control_plane.md) | F5 📝 option F |
| [PLAN_duckdb_postgres_merge.md](plans/PLAN_duckdb_postgres_merge.md) | F5 💡 discussion |
| [PLAN_file_check_rules.md](plans/PLAN_file_check_rules.md) | B 1 (rules) ✅ (steps 1–7, 2026-11-13) |
| [PLAN_fill_magnet_sites.md](plans/PLAN_fill_magnet_sites.md) | A ✅ |
| [PLAN_finish_and_deploy.md](plans/PLAN_finish_and_deploy.md) | A21 / F7 ✅ steps 1–9 (deployed 2026-11-23); the testers are F7 step 11 |
| [PLAN_flow_params_history.md](plans/PLAN_flow_params_history.md) | B "L3 flow params" 📝 (phase 0 items 1–2 ✅) |
| [PLAN_freesteam_deb_ci.md](plans/PLAN_freesteam_deb_ci.md) | F3 📝 |
| [PLAN_github_runner_setup.md](plans/PLAN_github_runner_setup.md) | F1 📝 |
| [PLAN_graph_csv_download.md](plans/PLAN_graph_csv_download.md) | C ✅ |
| [PLAN_header_field_factor_study.md](plans/PLAN_header_field_factor_study.md) | B 💡 discussion record (study plan to write) |
| [PLAN_import_json_dates.md](plans/PLAN_import_json_dates.md) | A ✅ |
| [PLAN_insert_rings.md](plans/PLAN_insert_rings.md) | A15 ✅ (step 7: rings committed in `hifimagnet-projects`, rebuild A21 ✅) |
| [PLAN_jc_table.md](plans/PLAN_jc_table.md) | A5 📝 |
| [PLAN_live_m8_viewer.md](plans/PLAN_live_m8_viewer.md) | C14 📝 *(uncommitted)* |
| [PLAN_m1_project_sort.md](plans/PLAN_m1_project_sort.md) | reference (C6, G) |
| [PLAN_m19_combined_run.md](plans/PLAN_m19_combined_run.md) | G8 💡 note |
| [PLAN_m19_joint_operation.md](plans/PLAN_m19_joint_operation.md) | G8 📝 drafted 2026-11-12 |
| [PLAN_m8_assembly_rename.md](plans/PLAN_m8_assembly_rename.md) | A ✅ data issue #14 (2026-11-13) |
| [PLAN_m8_overview_records.md](plans/PLAN_m8_overview_records.md) | A ✅ parts B, D (2026-11-13); A26 💡 part C after F7 |
| [PLAN_magnet_geometry_check.md](plans/PLAN_magnet_geometry_check.md) | A ✅ (Q2); dashboard look awaits the user's check |
| [PLAN_magnetdb_duckdb_demo_extraction.md](plans/PLAN_magnetdb_duckdb_demo_extraction.md) | ✅ executed 2026-08-26 |
| [PLAN_magnettools_optional.md](plans/PLAN_magnettools_optional.md) | F4 Phase 2 slice ✅ (step 6 left to the user) |
| [PLAN_magnettools_release_pipeline.md](plans/PLAN_magnettools_release_pipeline.md) | F4 📝 |
| [PLAN_missing_dates.md](plans/PLAN_missing_dates.md) | A16 ✅ (2026-11-02) |
| [PLAN_operation_log_coverage.md](plans/PLAN_operation_log_coverage.md) | A18 ✅ |
| [PLAN_overview_mode_gr_mapping.md](plans/PLAN_overview_mode_gr_mapping.md) | A ✅ data issue #17 (2026-11-12) |
| [PLAN_overview_record_checks.md](plans/PLAN_overview_record_checks.md) | B "1 (overview checks)" 🔄 paused at step 3 *(uncommitted)* |
| [PLAN_overview_records_from_operationaldata.md](plans/PLAN_overview_records_from_operationaldata.md) | A24 ✅ (phase G 2026-11-13) |
| [PLAN_pigbrother_pupitre_current_channels.md](plans/PLAN_pigbrother_pupitre_current_channels.md) | D ✅ (data issue #17) |
| [PLAN_pupitre_checks_file.md](plans/PLAN_pupitre_checks_file.md) | A25 ✅ |
| [PLAN_pupitre_binary_tail.md](plans/PLAN_pupitre_binary_tail.md) | B ✅ (step E follow-up) |
| [PLAN_pupitre_etl_spec.md](plans/PLAN_pupitre_etl_spec.md) | B1 🔄 (parts A and B ✅ with D1 = b; D1 = a 📝; follow-ups to plan) |
| `PLAN_cirrus_mirror.md` *(local, git-ignored)* | D ✅ stage D; F9 💡 stage B |
| [PLAN_run_selection.md](plans/PLAN_run_selection.md) | 💡 design discussion (2026-11-10), not approved |
| [PLAN_session_records.md](plans/PLAN_session_records.md) | B ✅ sessions; R 📝 |
| [PLAN_site_to_assembly_rename.md](plans/PLAN_site_to_assembly_rename.md) | ✅ Track A; G3 ⏸ Track B |
| [PLAN_supervision_bdd_file_viewer.md](plans/PLAN_supervision_bdd_file_viewer.md) | C ✅ |
| [PLAN_update_impact_tracking.md](plans/PLAN_update_impact_tracking.md) | A ✅; A11 follow-ups |
| [PLAN_waterflow_dashboard.md](plans/PLAN_waterflow_dashboard.md) | C1 📝 |
| [PROJECT_STRUCTURE_PLAN.md](plans/PROJECT_STRUCTURE_PLAN.md) | reference (copy from `2026-m1-hifimagnet`) |
| [JNLG_USE_CASE_COVERAGE.md](plans/JNLG_USE_CASE_COVERAGE.md) | reference (JNL-G use cases: DuckDB demo vs python_magnetdb; input for F5) |
| [NOTES_M5_bitters_wiring.md](plans/NOTES_M5_bitters_wiring.md) | B4 ⏸ |
| [NOTES_auditwheel_spike.md](plans/NOTES_auditwheel_spike.md) | F4 |
| [NOTES_cirrus_A1_runlogs.md](plans/NOTES_cirrus_A1_runlogs.md), [NOTES_cirrus_A1_experiment_matching.md](plans/NOTES_cirrus_A1_experiment_matching.md) | B reference (#27, step R) *(uncommitted)* |
| [NOTES_python_magnetdb_deployment.md](plans/NOTES_python_magnetdb_deployment.md) | F5 (deployment delayed) |
| [NOTES_session_records_checks.md](plans/NOTES_session_records_checks.md) | B R, Q12 |
| [Cooling Boundary Conditions for Electromagnets.md](Cooling_Boundary_Conditions_for_Electromagnets.md) | E3 / B6 reference *(uncommitted)* |
| [package-assessment-prompt.md](package-assessment-prompt.md) | reference *(uncommitted)* |
| [REVIEW_readability_maintainability.md](REVIEW_readability_maintainability.md) | A28–A31, C11–C13 💡 — code review of 2026-11-15 *(uncommitted)* |
| **to_duckdb/** | |
| [PLAN_archive_magnet_data.md](to_duckdb/plans/PLAN_archive_magnet_data.md) | A ✅ |
| [PLAN_archive_magnet_hybrid_runlog.md](to_duckdb/plans/PLAN_archive_magnet_hybrid_runlog.md) | A20 📝 |
| [PLAN_econrj_parameter_inference.md](to_duckdb/plans/PLAN_econrj_parameter_inference.md) | A10 💡 |
| [PLAN_exp_stats_performance.md](to_duckdb/plans/PLAN_exp_stats_performance.md) | A1 📝 |
| [PLAN_fuzzy_date_tolerance.md](to_duckdb/plans/PLAN_fuzzy_date_tolerance.md) | A6 📝 |
| [PLAN_hoop_stress_history.md](to_duckdb/plans/PLAN_hoop_stress_history.md) (index) + [PLAN_hoop_stress_parquet_columns.md](to_duckdb/plans/PLAN_hoop_stress_parquet_columns.md), [PLAN_hoop_stress_part_history.md](to_duckdb/plans/PLAN_hoop_stress_part_history.md), [PLAN_hoop_stress_per_part_tests.md](to_duckdb/plans/PLAN_hoop_stress_per_part_tests.md), [PLAN_hoop_stress_fatigue_additivity.md](to_duckdb/plans/PLAN_hoop_stress_fatigue_additivity.md) | A ✅ Phases 1–5 |
| [NOTES_hoop_stress_implementation.md](to_duckdb/plans/NOTES_hoop_stress_implementation.md) | A14 (known limitations of `--check`) |
| [PLAN_hoop_stress_part_names.md](to_duckdb/plans/PLAN_hoop_stress_part_names.md) | A2 📝 |
| [PLAN_incident_tracking.md](to_duckdb/plans/PLAN_incident_tracking.md) | A3 📝 |
| [PLAN_lifecycle_status.md](to_duckdb/plans/PLAN_lifecycle_status.md) | A ✅ |
| [PLAN_magnet_incidents_plot.md](to_duckdb/plans/PLAN_magnet_incidents_plot.md) | A19 📝 |
| [PLAN_operation_log.md](to_duckdb/plans/PLAN_operation_log.md) | A ✅ |
| [PLAN_overview_records_pupitre_dedup.md](to_duckdb/plans/PLAN_overview_records_pupitre_dedup.md) | A ✅ |
| [PLAN_part_delete.md](to_duckdb/plans/PLAN_part_delete.md) | A4 📝 |
| [PLAN_populate_all.md](to_duckdb/plans/PLAN_populate_all.md) | A7 💡 |
| [PLAN_retired_magnet_guard.md](to_duckdb/plans/PLAN_retired_magnet_guard.md) | A17 ✅ (2026-11-16) |
| [PLAN_scheduled_populate.md](to_duckdb/plans/PLAN_scheduled_populate.md) | A8 💡 |
| [PLAN_setup_simulation.md](to_duckdb/plans/PLAN_setup_simulation.md) | A33 ✅ (2026-11-25) |
| [PLAN_tech_staff_research_area.md](to_duckdb/plans/PLAN_tech_staff_research_area.md) | A23 ✅ |
| [PLAN_users_multi_source.md](to_duckdb/plans/PLAN_users_multi_source.md) | A9 📝 / ⛔ |
| [ROADMAP.md](to_duckdb/plans/ROADMAP.md), [TODOs.md](to_duckdb/TODOs.md) | component roadmap / backlog |
| **apps/dashboards/magnetdb/** | |
| [PLAN_cross_graph_cursor_sync.md](apps/dashboards/magnetdb/plans/PLAN_cross_graph_cursor_sync.md) | C ✅ |
| [PLAN_csv_download.md](apps/dashboards/magnetdb/plans/PLAN_csv_download.md) | C9 📝 |
| [PLAN_dashboard_hierarchy_rework.md](apps/dashboards/magnetdb/plans/PLAN_dashboard_hierarchy_rework.md) | C ✅ (2026-08-19) |
| [PLAN_defaults_spikes_incident_data.md](apps/dashboards/magnetdb/plans/PLAN_defaults_spikes_incident_data.md) | C ✅ |
| [PLAN_experiment_overview_date_filters.md](apps/dashboards/magnetdb/plans/PLAN_experiment_overview_date_filters.md) | C ✅ |
| [PLAN_field_style_overrides.md](apps/dashboards/magnetdb/plans/PLAN_field_style_overrides.md) | C ✅ |
| [PLAN_group_order.md](apps/dashboards/magnetdb/plans/PLAN_group_order.md) | C ✅ |
| [PLAN_hybrid_viewer.md](apps/dashboards/magnetdb/plans/PLAN_hybrid_viewer.md) | C10 📝 |
| [PLAN_loading_spinner_scope.md](apps/dashboards/magnetdb/plans/PLAN_loading_spinner_scope.md) | C ✅ |
| [PLAN_magnet_stats_year_filter.md](apps/dashboards/magnetdb/plans/PLAN_magnet_stats_year_filter.md) | C3 ⏸ |
| [PLAN_operational_viewer.md](apps/dashboards/magnetdb/plans/PLAN_operational_viewer.md) | C ✅ (2026-11-04) |
| [PLAN_overview_records_event_click.md](apps/dashboards/magnetdb/plans/PLAN_overview_records_event_click.md) | C2 📝 |
| [PLAN_part_stats_hoop_stress.md](apps/dashboards/magnetdb/plans/PLAN_part_stats_hoop_stress.md) | C ✅ |
| [PLAN_per_user_plot_style.md](apps/dashboards/magnetdb/plans/PLAN_per_user_plot_style.md) | C ✅ (2026-10-22) |
| [PLAN_plot_style_config.md](apps/dashboards/magnetdb/plans/PLAN_plot_style_config.md) | C ✅ (2026-08-19) |
| [PLAN_signature_regime_robustness.md](apps/dashboards/magnetdb/plans/PLAN_signature_regime_robustness.md) | B S1 📝 |
| [docs/evaluation_tester_note.md](apps/dashboards/magnetdb/docs/evaluation_tester_note.md) | F7 tester note |
| **python_magnetsetup/** | |
| [PLAN_supra_umagnet.md](python_magnetsetup/PLAN_supra_umagnet.md) | E1 📝 |
| [PLAN_supra_detail_levels.md](python_magnetsetup/PLAN_supra_detail_levels.md) | E2 📝 |
| [PLAN_fix_json_templates.md](python_magnetsetup/PLAN_fix_json_templates.md) | E7 ✅ (json templates, assembly YAML load) |
| [PLAN_fix_multipart_magnets.md](python_magnetsetup/PLAN_fix_multipart_magnets.md) | E7 ✅ (multi-part Bitters / Supras) |
| **python_magnetcooling/** | |
| [TODOs.md](python_magnetcooling/TODOs.md) | E3 💡 |
| **python_magnetrun/** — open | |
| [prompts/tdms-polars-benchmark.plan.md](python_magnetrun/prompts/tdms-polars-benchmark.plan.md) | D1 🔄 |
| [prompts/parquet-save-load.plan.md](python_magnetrun/prompts/parquet-save-load.plan.md) | D2 📝 |
| [prompts/curated-parquet-s3.plan.md](python_magnetrun/prompts/curated-parquet-s3.plan.md) | D3 💡 |
| [prompts/hybriddata-timestamp-plan.md](python_magnetrun/prompts/hybriddata-timestamp-plan.md) | D6 ❓ |
| [prompts/snake-case-migration.plan.md](python_magnetrun/prompts/snake-case-migration.plan.md) | D7 📝 |
| [prompts/coverage-80pct.plan.md](python_magnetrun/prompts/coverage-80pct.plan.md) | D8 ❓ |
| [prompts/label-legend-uniformization.plan.md](python_magnetrun/prompts/label-legend-uniformization.plan.md) | D9 ❓ |
| [prompts/marimo-tutorial.plan.md](python_magnetrun/prompts/marimo-tutorial.plan.md) | D13 💡 |
| [docs/dash-plan.md](python_magnetrun/docs/dash-plan.md), [docs/gui-plan.md](python_magnetrun/docs/gui-plan.md), [docs/tui-plan.md](python_magnetrun/docs/tui-plan.md) | D14 💡 |
| [prompts/holoviews-migration.plan.md](python_magnetrun/prompts/holoviews-migration.plan.md) | D15 ⏸ |
| [python_magnetrun/TODO.md](python_magnetrun/python_magnetrun/TODO.md) | D16 💡 |
| [prompts/ROADMAP.md](python_magnetrun/prompts/ROADMAP.md) | component roadmap |
| **python_magnetrun/** — done (see its ROADMAP) | |
| `3.9-hybrid-code-quality`, `4.6-trigger-vprocess-plotting`, `analysis-plotting-to-plotting-subpackage`, `analysis-subpackage-refactoring`, `bprofile-implementation`, `cli-consolidation`, `data-property-abc`, `downsampling-metrics`, `downsampling-refactoring`, `fix-remaining-issues`, `hts-magnetdata`, `hybrid-formula-key-resolution`, `hybrid-subpackage-refactoring`, `l2-binary-reader-base`, `m4-downsampling`, `mrun-cache-implementation`, `narwhals-downstream-consumers`, `outlier-consolidation`, `phase2b-time-alignment`, `plotting-refactoring`, `polars-magnetdata-pupitre`, `rdp-downsampling`, `reader-container-refactoring`, `timestamp-utc-refactoring`, `truncated-pupitre-files` (all `.plan.md` in [prompts/](python_magnetrun/prompts/)) | D ✅ |
