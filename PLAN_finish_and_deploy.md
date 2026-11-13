# Plan: finish the database and dashboard work, then deploy on calcul18

**Status (2026-11-13): draft for discussion; nothing approved.** Each item
below gets its own short plan (or uses an existing one) and needs `approve`
before any step.

## Goal

Finish the pending database and dashboard changes first, then deploy **one**
new database and dashboard image on calcul18 (ROADMAP F7), instead of
deploying the current candidate DB and patching it afterwards.

## Where things stand (2026-11-13)

Done this week:

- Full rebuild on calcul22: `to_duckdb/magnetdb-2026-11-10.duckdb` (ROADMAP
  A21), with the A22 checks run on it (`check --entity dates`, M8 wiring
  since 2026-03-05, M8 stats).
- Data issue #14 (M8 assemblies and wiring) and the rename to
  `M8_A230913_00`, in the DB, the code and the tests
  ([PLAN_m8_assembly_rename.md](PLAN_m8_assembly_rename.md)).
- Data issue #17 (operating mode with the right IH / IB channels): code
  committed and pushed; stored modes corrected on the calcul22 copy
  `~/magnetdb-checks/magnetdb-2026-11-10.mode17.duckdb`
  ([PLAN_overview_mode_gr_mapping.md](PLAN_overview_mode_gr_mapping.md),
  [PLAN_pigbrother_pupitre_current_channels.md](PLAN_pigbrother_pupitre_current_channels.md)).
- `EXPERIENCES_LOG` field table in [Data/README.md](Data/README.md).

The candidate DB (the `.mode17` copy) compared with the DB calcul18 serves
today:

| | calcul18 (`magnetdb-2026-10-08.duckdb`) | candidate (2026-11-10 `.mode17`) |
|---|---|---|
| Experiments / overview records / users | 6 483 / 1 915 / 4 323 | 6 548 / 1 952 / 4 595 |
| File quality (`file_integrity`, schema plan step E) | 6 483 filled | **0**: the build does not run it, deploying as is would lose it |
| ETL checks and tags (`etl_checks`, `record_tags`) | (no tables) | **0** (11 rules loaded, never applied): not in the build either |
| `overview_records.teb` > 0 | 0 | **0**: the SQL builder (`overview-ops`) is not in the build yet |
| Hoop stress | 0 | 0: no regression; blocked by E1 and magnettools (F4) |

## Order

### 1. Database code

| # | Item | Plan | Effort | Why before deploying |
|---|---|---|---|---|
| 1 | **A24 phase G**: validate the SQL builder on a copy of the 2026-11-10 DB (steps 13–14), then add the `overview-ops` build step (step 15) | [PLAN_overview_records_from_operationaldata.md](PLAN_overview_records_from_operationaldata.md) | M | fills `teb` / `BP` |
| 2 | **Build script**: add the two file-check steps (`check_experiment_files.py`, plain and `--etl`); call the submodule's `mysql_connect.py` by path in the export step (today it runs the copy in the separate `~/github/python_magnetrun` checkout) | to write; [scripts/build_from_scratch.sh](scripts/build_from_scratch.sh) | S | file quality and tags in every new build |
| 3 | **Data issue #18**: skip rule for the 24 pupitre files stored under two housings | to write; issue #18 in [PLAN_digital_twin_schema.md](PLAN_digital_twin_schema.md) | S–M | today they count twice in M5 / M10 experiments and stats |
| 3b | **M8 in the SQL builder** (part B): all 128 M8 overviews get a row; the 37 existing rows keep their hybrid lists; build order `overview-json` → `overview-ops --reprocess` → `overview-infer` (revises phase G step 15) | [PLAN_m8_overview_records.md](PLAN_m8_overview_records.md) | S | only 37 of 128 M8 overviews have a row today, none with `teb` |

### 2. Dashboards

| # | Item | Plan | Effort |
|---|---|---|---|
| 4 | **File-check rules step 6** (file-quality and check columns, tag colours and tooltips, revised 2026-11-12), then **step 7** (docs). Tested on the `.mode17` copy after running the two file checks on it (calcul22, `screen`) | [PLAN_file_check_rules.md](PLAN_file_check_rules.md) | M |
| 5 | **C8**: About page, operation log 10 per page (optional) | [PLAN_dashboard_tables_newest_first.md](PLAN_dashboard_tables_newest_first.md) | S |
| 5b | **I_BOB overlay fix** (part D): `load_hybrid_supra_current` takes the date from the pupitre start time; today it raises `ValueError` on every real M8 row (stored kHz names have no date) | [PLAN_m8_overview_records.md](PLAN_m8_overview_records.md) | S |

Items 1–3, 5 and 5b are independent; item 4 only needs the checks of item 2
run on a copy; item 3b goes with item 1 (same build step).

### 3. Final database

6. Commit and push; on calcul22 pull (calcul22 cannot reach GitHub from a
   non-interactive session: the pull is done by the user), then **one full
   rebuild** in `screen` (≈ 1.5 days; the 2026-11-10 build took 37 h up to the
   export step). A rebuild keeps the deployed DB equal to what the build
   script produces; #18 changes which experiments are inserted anyway.
7. Post-build checks, read-only: dates; M8 assemblies and housing versions;
   Overview modes equal to the `.mode17` results (#17); `teb` > 0; file
   quality and tags filled; #18 duplicates gone; counts compared with the
   2026-11-10 DB.

### 4. Deployment (F7)

8. Run the dashboard locally against the new DB: pages, tag colours.
9. calcul18 deployment plan: dashboard image, DB copy, Quadlet units, the
   maintainer's browser check, then the testers
   ([PLAN_dashboard_server_deployment.md](PLAN_dashboard_server_deployment.md)).

## After the deployment

- E1 → A2 → hoop stress (A22): [python_magnetsetup/PLAN_supra_umagnet.md](python_magnetsetup/PLAN_supra_umagnet.md),
  [to_duckdb/PLAN_hoop_stress_part_names.md](to_duckdb/PLAN_hoop_stress_part_names.md);
  needs magnettools in the environment (F4).
- Hybrid files in `operationaldata` (part C of
  [PLAN_m8_overview_records.md](PLAN_m8_overview_records.md)): year folders in
  `HybridData`, hybrid kinds matched by overlap, paths instead of basenames;
  answers A20's layout question.
- C9 [CSV download](apps/dashboards/magnetdb/PLAN_csv_download.md), C10
  [Hybrid viewer](apps/dashboards/magnetdb/PLAN_hybrid_viewer.md).
- A1 [exp-stats performance](to_duckdb/PLAN_exp_stats_performance.md), if a
  later rebuild is too slow.
- Tester issues from F7 (GitHub issue template).

Any time: update the [ROADMAP](ROADMAP.md) snapshot (dated 2026-11-07) once
its uncommitted edits are committed.

## Decisions to confirm

Suggested by Claude on 2026-11-13, not yet confirmed by the user:

1. **#18 before the deployment** (implies the full rebuild of stage 3).
2. **C9 / C10 and A1 after the deployment.**
3. **C8 optional** before the deployment.

## Notes

- The 4 M8 mode changes of #17 were checked on 2026-11-13: the supply mapping
  holds on M8; `250604-1120` (slope 0.652) and `261028-0858` (a 79-min
  low-power run, max ≈ 1.3 kA) are limits of the ECO / NORMAL heuristic, not
  of the channel fix.
- `EXPERIENCES_LOG` `Paimant` is an energy (MWh, presumed) with 0.1 MWh
  resolution: 0.0 does not mean "unpowered".
