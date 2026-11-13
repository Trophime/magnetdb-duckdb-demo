# Plan: M8 overview records (SQL builder, I_BOB overlay, hybrid files)

**Status (2026-11-13): parts B and D approved and done** (uncommitted; step 7,
the check in the running dashboard, goes with step 8 of
[PLAN_finish_and_deploy.md](PLAN_finish_and_deploy.md)). Part C, after the
deployment (F7), gets its own revision and approval.

## Goal

- **Before the deployment:** every M8 Overview file gets an `overview_records`
  row from the SQL builder, with `teb`, `bp`, `mode` and its pigbrother/pupitre
  sources, while the 37 existing M8 rows keep their hybrid lists. The
  dashboard's I_BOB overlay works on the real DB.
- **After the deployment:** hybrid files are registered in `operationaldata`
  and matched by time overlap like the other files, so M8 no longer needs
  `summary.json`.

## Findings (2026-11-13, read-only)

Checked on `magnetdb-2026-11-10.mode17.duckdb`, the python_magnetrun code,
the dashboard and `records/CEA`.

- `operationaldata` has 128 M8 Overview files (2022-11-24 → 2026-11-09), all
  with `t_start`, `t_end` and `mode`; 187 M8 pupitre files, all with
  `teb_mean` / `bp_mean`.
- `overview_records` has 37 M8 rows (2026-02-26 → 2026-10-13), all from
  `Data/M8_summary-2026.json`; none has `teb` > 0. The SQL builder skips M8,
  so the other 91 overviews have no row.
- `records/CEA` layout: `kHz/<date>/<system>/HHHOST_n_LIST_k.bin` (8 lists for
  `FEPC-LNCMI`, 5 for `FEPC-AUX-LNCMI`, per hour), `rms/<date>/<system>/…_HHMM--…_HHMM.rms`
  (hourly), `vprocess/<date>/YYYYMMDD_HHMMSS__YYYYMMDD_HHMMSS.vprocess`
  (hourly), `trigger/TRIGGER__<date>__HH-MM/<system>/*.CNV`. Daily folders
  exist at the top level since 2025-01-01; 2019–2024 days are in year folders
  (`kHz/2024/2024-05-19/…`, confirmed by the user), which
  `HybridData._discover_data` does not search. Trigger folder names are UTC
  (they match pigbrother spikes on 2026-03-26 and 2026-04-14). The kHz folder
  of a day holds hours 00–23.
- Year-folder coverage is per campaign, and there is nothing for 2021:

  | Kind | Year folders |
  |---|---|
  | kHz | 2020 (01-30 → 07-31), 2022 (06-13 → 11-30), 2023 (05-10 → 10-30), 2024 (05-19 → 12-31) |
  | RMS | as kHz, plus 2019 (10-07 → 12-06); 2024 from 05-17 |
  | vprocess | 2022, 2023, 2024 (from 06-17, 05-10, 05-22) |
  | trigger | no year folders (54 folders in 2020–2024) |

  Of the 36 M8 overviews of 2022–2024, 6 (2023) fall between campaigns.
- `crud` stores basenames, for example `13HOST_2_LIST_0.bin`. The dashboard's
  `load_hybrid_supra_current` needs a `YYYY-MM-DD` in that string, so it
  raises `ValueError: Cannot extract a date from hybrid source
  '13HOST_2_LIST_0.bin'` on the real DB. The test passes only because its
  fixture stores a full path.
- The `summary.json` hybrid lists come from `loaders._discover_hybrid_data`:
  - it selects by UTC hour, on the overview's start day only, so overviews
    past midnight or longer than 24 h lose hours (`M8_Overview_260323-0919`,
    23.8 h, gets 1 hour);
  - it attaches trigger folders outside the overview
    (`TRIGGER__2026-03-05__13-19` is in the gap between two overviews and
    listed in both);
  - it lists each trigger folder twice, once per FEPC system.

  Part B keeps these lists as they are; part C replaces them.

## Part B — M8 in the SQL builder (before the deployment)

### Files affected

| File | Action |
|---|---|
| `to_duckdb/crud.py` | edit: `build_overview_records_from_operationaldata` builds M8 (M8 branch and `skipped_m8` count removed); when it replaces an existing row, it keeps that row's `sources_hybrid_*` lists; docstring |
| `to_duckdb/magnetdb.py` | edit: CLI count line and the subcommand description (no "M8 skipped") |
| `to_duckdb/docs/populate.md` | edit: the M8 sentence of `overview-records-from-operationaldata` |
| `to_duckdb/tests/test_crud.py` | edit: `test_…_skips_m8` becomes `test_…_builds_m8`; new hybrid-carry-over test; `skipped_m8` removed from the count asserts |
| `scripts/build_from_scratch.sh`, `scripts/README.md` | edit: phase G step 15, in the order of B4 below |
| `PLAN_overview_records_from_operationaldata.md` | edit: open question 5 and step 15 point here |

### Approach

1. Tests first in `test_crud.py`:
   - an M8 assembly with one Overview and one Pupitre row gets a row with its
     sources, `teb` and `mode`, and empty hybrid lists;
   - an existing M8 row with `sources_hybrid_kHz/rms/trigger/vprocess` filled,
     rebuilt with `reprocess=True`, keeps those four lists while its other
     columns come from `operationaldata`;
   - the count dicts no longer have `skipped_m8`.

   → verify: the new tests fail.
2. `crud.py`:
   - remove the M8 early return and the `skipped_m8` key;
   - before writing a row that already exists (`reprocess`), read its four
     `sources_hybrid_*` columns and put them in the new row.

   Update the CLI line and description in `magnetdb.py`, and `docs/populate.md`.
   → verify: step-1 tests pass; full to_duckdb suite green, with the same
   count as before plus the new tests.
3. On a scratch copy of the `.mode17` DB: `populate
   overview-records-from-operationaldata --all --reprocess`.
   → verify, with a comparison like phase G's:
   - 128 M8 rows in total;
   - the 37 existing rows keep their hybrid lists unchanged;
   - `mode` is identical on those 37;
   - `teb` > 0 on the M8 rows that have a pupitre source;
   - M9/M10 results are unchanged from the phase G run.
4. Build order: phase G step 15 is revised (it said `overview-ops` before
   `overview-json`; that order would drop the M8 hybrid lists, since
   `overview-json` skips rows that already exist). The new order:
   - `overview-json` (unchanged: loads the summaries, including the M8 hybrid
     lists);
   - `overview-ops`: `populate overview-records-from-operationaldata --all
     --reprocess` (rebuilds every row that has an Overview in
     `operationaldata`, keeping the hybrid lists);
   - `overview-infer` (unchanged).

   → verify: `--help` lists the steps in this order; `bash -n` passes;
   `--from overview-json --to overview-infer` on a scratch copy runs clean,
   and gives the same table as step 3.

## Part D — I_BOB overlay (before the deployment)

### Files affected

| File | Action |
|---|---|
| `apps/dashboards/magnetdb/src/magnetdb_analysis.py` | edit: `load_hybrid_supra_current` takes the date from `start` (naive UTC), not from `hybrid_source`; `_HYBRID_DATE_RE` removed if unused; docstring (no `Raises`) |
| `apps/dashboards/magnetdb/tests/hybrid_supra_current_test.py` | edit: new test with a basename source |

### Approach

5. Test first: `load_hybrid_supra_current("13HOST_1_LIST_0.bin", "M8", …,
   start=2024-03-15 10:00, …)` with `HybridRun.fromdir` patched → it is called
   with `date_str="2024-03-15"`.
   → verify: fails today with the `ValueError`.
6. `date_str = start.strftime("%Y-%m-%d")`; `hybrid_source` stays a parameter
   (it is the lru-cache key and the availability check in `file_viewer.py`).
   → verify: dashboard tests green (`--ignore=tests/mrun_test.py`).
7. With the dashboard run locally against the part-B scratch DB (part of step
   8 of PLAN_finish_and_deploy.md): File viewer, M8, pupitre file
   `2026.03.05 - 14:42:13.txt`, select "I_BOB [Hybrid]".
   → verify: the I_BOB trace is drawn (reads the records mount).

### Results (2026-11-13)

- Steps 1–2: the M8 skip test became `test_…_builds_m8`; new
  `test_…_keeps_hybrid_lists_on_replace`; to_duckdb 855 passed, 3 skipped.
- Step 3 (scratch copy of the `.mode17` DB with the decision-2 incident ends):
  128 M8 rows (`M8_A211225_00` 8, `M8_A230913_00` 120, 5 more pupitre
  merges), no M8 Overview without a row; the 37 rows from `summary.json`
  keep identical hybrid lists and `mode`; `teb` > 0 on the 114 M8 rows with a
  pupitre source; no M9/M10 row changes; `--all` in 65 s.
- Step 4: build steps `… overview-json overview-ops overview-infer …`;
  `bash -n` and `--help` OK. `--from overview-json --to overview-infer` on a
  scratch copy with `overview_records` emptied: the three steps OK, and the
  table (3 327 rows) is identical to step 3's.
- Steps 5–6: new `test_load_hybrid_supra_current_takes_date_from_start`;
  dashboard tests 167 passed (`--ignore=tests/mrun_test.py`). With the real
  data (pupitre `2026.03.05 - 14:42:13.txt`, scratch DB), the loader returns
  7 201 rows at 1 Hz in 8 s. I_BOB stays within −10.8 … 17.4 A that afternoon:
  to look at on a day with the supra magnet powered.

## Part C — hybrid files in `operationaldata` (after the deployment)

Outline only, to be revised and approved after F7.

1. python_magnetrun `HybridData._discover_data`: also search
   `<kind>/<YYYY>/<date>/` for kHz, RMS and vprocess (trigger folders have no
   year folders). The dashboard's I_BOB loader uses it through
   `HybridRun.fromdir`.
2. `populate operationaldata --type HybridKHz HybridRMS HybridVProcess
   HybridTrigger` for M8:
   - register files from their names and folders only (no file read);
   - `file` relative to the records root, so the date and FEPC system are
     kept;
   - `t_start` / `t_end` in UTC: kHz = the hour, RMS and vprocess = the range
     in the name, trigger = the folder time (a point in time);
   - `assembly_name` from the M8 assembly dates.
3. Builder: hybrid kinds in the overlap match. The hybrid columns store the
   path relative to `CEA/` instead of the basename. Trigger folders follow the
   rule chosen for Default/Trigger (phase G decision 2).
4. Remove the part-B carry-over and the M8 dependency on `summary.json`; the
   dashboard can use the stored path.
5. A20 ([to_duckdb/PLAN_archive_magnet_hybrid_runlog.md](to_duckdb/PLAN_archive_magnet_hybrid_runlog.md)):
   open question 1 (CEA layout) is answered by the findings above.

## Assumptions & open questions

1. **Hybrid lists kept as they are (part B).** The 37 rows keep the
   hour-based lists, with their known defects, until part C.
2. **Build order change (B4).** This revises phase G step 15. The phase G
   report and its three decisions (≈ 1 450 new rows, Default/Trigger files in
   gaps, step-14 timing) are still open; B4 is done with step 15, after you
   accept that report.
3. **kHz folder date = UTC date (D6).** The folder holds hours 00–23 and the
   hours are UTC, so `start`'s UTC date picks the right folder. A pupitre file
   that crosses midnight UTC still gets an empty hour range
   (`range(start.hour, end.hour + 1)`); this is unchanged and not fixed here,
   since M8 runs are in daytime.
4. **No I_BOB option before 2026.** After part B, M8 rows before 2026 have no
   hybrid lists, so `get_hybrid_khz_source` returns `None` and the option is
   not offered. That is correct until part C.
5. **Part C size.** One row per kHz file would be about 310 000 rows (13 per
   hour); one row per system and hour, about 48 000. To be decided in part C,
   with the hybrid ↔ pupitre clock lag (data issue #27) and hybrid days before
   the first M8 assembly (kHz data starts 2020-01-30; `M8_A211225_00` is
   commissioned 2021-12-25).
