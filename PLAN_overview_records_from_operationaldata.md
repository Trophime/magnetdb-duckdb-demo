# Plan: build overview_records from operationaldata (+ SignalStats rename)

Status: **draft, revised 2026-11-07, awaiting approval** (first draft 2026-11-06)

Revision 2026-11-07:
- facts taken from the A21 rebuild `magnetdb-2026-11-05.duckdb`;
- M8 left out of the SQL builder (its records have hybrid sources);
- new build-script phase;
- file-name patterns checked against the DB;
- `teb`/`BP` reprocessing cost now that op stats are done;
- conflict with ROADMAP A13;
- `record_tags` keys;
- order after A25.

## Goal

Build `overview_records` rows with SQL over `operationaldata`. Each file's
start/end time and the Overview file's `mode` are computed once per file and
stored, so rebuilding a record no longer re-reads files over the records mount.
In the same change, rename pigbrother "Stats" files to **SignalStats**
everywhere, from `python_magnetrun` through the DB to the dashboard, so they
cannot be confused with the DB statistics tables (`op_*_stats`,
`compute_op_stats`).

## Why

Findings from the code (2026-11-06) and `magnetdb-2026-11-05.duckdb`
(2026-11-07):

- `process_overview_file` loads overview, archive, pupitre and incident data
  in full and computes synchronisation, lag and signatures. `summary.json`
  then keeps only `filename` + source lists. All 1833 live `overview_records`
  rows (M8 36, M9 953, M10 844; plus 119 merged tombstones) have empty
  `signatures`.
- The DB side loads files in full again: the overview for `duration`
  (`overview-records-from-json`) and again for `mode`
  (`_postprocess_overview_record`, on every insert with an assembly), and every
  pupitre file for `teb`/`bp` (`overview-records-infer`). The build runs
  these as the `overview-json` and `overview-infer` steps of
  `scripts/build_from_scratch.sh`.
- File discovery (`select_files`) lists the whole day's files and reads
  metadata for each one over the mount, once per overview, with no cache.
- Dashboard reads only `duration`, `mode`, `teb`, `sources_*`.
  `teb = 0` in all 1833 live rows.
- `operationaldata`: Archive 6635, Default 4378, Overview 3347, Pupitre 6543,
  Spike 33465. No start/end time columns.
  - **ManuelTrig and Stats files are not registered.** Yet 242 rows have
    `sources_trigger` filled and 36 have `sources_stats` filled (all M8).
  - M8 hybrid files are not registered either; 34 M8 rows have
    `sources_hybrid_kHz`.
- `op_stats_processed`: 6536 Pupitre files (build step `op-stats`), so the
  per-file pupitre pass already exists. Its scalars are `duration_s`,
  `duration_field_on_s`, `energy_j`, `heat_extracted_j`; no `teb`/`BP`.

Sessions (`analysis/sessions.py`) were considered: they skip the full data
loads but use the same uncached discovery, and give no
`duration`/`teb`/`mode`. Not used here.

## Naming decisions

| Where | Old | New |
|---|---|---|
| `python_magnetrun` `FileSet` field | `stats` | `signal_stats` (+ deprecated `stats` property) |
| `FileSet.to_dict` / `summary.json` / `sessions.json` key | `"stats"` | `"signal_stats"` (`from_dict` also reads `"stats"`) |
| `FileDiscovery.candidate_files` key | `"stats"` | `"signal_stats"` |
| `utils/files.py` constant | `DIR_STATS` | `DIR_SIGNAL_STATS` (`DIR_STATS` kept as alias) |
| `operationaldata.type` | — | `'SignalStats'` (new), plus `'Trigger'` (new) |
| `overview_records` column | `sources_stats` | `sources_signal_stats` |
| Dashboard label | "Stats" | "Signal stats" |

Unchanged: on-disk folder `Fichiers_stats`, file pattern `<housing>_Stats_*`
(pigbrother's names); the unrelated `stats` meanings (`commands/stats.py`,
`processing.stats`, `magnetrun stats` CLI, `hoop-stress stats`,
`magnetdata_*` statistics methods, `examples/get-record.py`,
`tests/test_get_record.py`).

## Files affected

### python_magnetrun (submodule, own repo)

| File | Action |
|---|---|
| `python_magnetrun/analysis/loaders.py` | edit: `FileSet.signal_stats`, `stats` shim property, `to_dict`/`from_dict`, `candidate_files`/`discover_window` key, `_select_related_files*`, log lines, docstrings |
| `python_magnetrun/utils/files.py` | edit: `DIR_SIGNAL_STATS` (+ alias), `stats_filter` → `signal_stats_filter` in `find_files`/`find_files_from_archive` |
| `python_magnetrun/analysis/cli.py` | edit: `summary.json` row key + `list_cols` |
| `tests/analysis/test_loaders.py` | edit: new key/field; add shim + legacy-key tests |
| `tests/analysis/test_summary_stats.py` | edit: `"signal_stats"` key |

### to_duckdb

| File | Action |
|---|---|
| `to_duckdb/schema.py` | edit: `operationaldata` + `t_start`, `t_end`, `mode`; `overview_records.sources_stats` → `sources_signal_stats` (CREATE + migration) |
| `to_duckdb/populate.py` | edit: `SignalStats` and `Trigger` in `_TDMS_SUBDIR_NAMES` / `_TDMS_TS_PATTERNS`; `parse_tdms_file_ts` accepts minute or second precision; new `fill_operationaldata_metadata()` |
| `to_duckdb/crud.py` | edit: `_fileset_lists`, `_OVERVIEW_RECORD_COLUMNS`, `_overview_record_to_columns`, `insert_overview_record_from_dict` (`signal_stats` + `stats` alias); `_postprocess_overview_record` reads stored `mode`; new `build_overview_records_from_operationaldata()` |
| `to_duckdb/compute_op_stats.py` | edit: `teb_mean`, `teb_count`, `bp_mean`, `bp_count` scalars in `compute_scalars` |
| `to_duckdb/config.py` | edit: units for the new scalars in `SCALAR_CHANNEL_UNITS` |
| `to_duckdb/magnetdb.py` | edit: subcommands `populate operationaldata-metadata`, `populate overview-records-from-operationaldata`; `populate operationaldata --type` accepts the new types |
| `to_duckdb/import_housing_summary.py` | edit: accept `stats` / `signal_stats` column |
| `to_duckdb/demos/archive_magnet_data.py` | edit: `_ARCHIVED_SOURCES` key |
| `to_duckdb/docs/populate.md` | edit: column rename, new types, new subcommands |
| `to_duckdb/tests/test_schema.py` | edit: migration tests |
| `to_duckdb/tests/test_populate.py` | edit: new types, metadata fill |
| `to_duckdb/tests/test_crud.py` | edit: rename; builder; stored-mode tests |
| `to_duckdb/tests/test_compute_stats.py` | edit: new scalars |
| `to_duckdb/tests/test_magnetdb.py` | edit: rename; new subcommands dispatch |

### Dashboard

| File | Action |
|---|---|
| `apps/dashboards/magnetdb/src/magnetdb_analysis.py` | edit: `sources_signal_stats` (2 queries + docstrings) |
| `apps/dashboards/magnetdb/src/pages/assembly_stats.py` | edit: column + label |
| `apps/dashboards/magnetdb/src/pages/magnet_stats.py` | edit: column + label |
| `apps/dashboards/magnetdb/src/pages/part_stats.py` | edit: column + label |
| `apps/dashboards/magnetdb/src/pages/stats_research_area.py` | edit: label/key |
| `apps/dashboards/magnetdb/tests/stats_research_area_test.py` | edit: key |

`pages/operational_viewer.py` needs no change: it lists only the `Overview`
and `Archive` types (`OPERATIONAL_TYPES`).

### Repo root

| File | Action |
|---|---|
| `scripts/build_from_scratch.sh` | edit: new types in the `operationaldata` step; new steps `operationaldata-metadata` and `overview-ops` (phase G) |
| `python_magnetrun` (submodule pointer) | bump after phase A |
| `ROADMAP.md` | edit: A24 status; A13 wording (see open question 1) |

## Approach

Starts after the A25 work in progress (uncommitted `magnetdb.py`,
`test_magnetdb.py`, `build_from_scratch.sh`, `ROADMAP.md`) is committed, so
the two changes don't mix in the same files.

### Phase A — python_magnetrun: `stats` → `signal_stats`

1. Tests first in `tests/analysis/test_loaders.py`:
   - `FileSet.to_dict()` has `"signal_stats"`;
   - `FileSet.from_dict({"stats": [...]})` fills `signal_stats`;
   - `FileSet().stats` emits `DeprecationWarning` and returns `signal_stats`.

   → verify: new tests fail.
2. Rename in `loaders.py`, `utils/files.py`, `analysis/cli.py`, keeping the
   shim and the `DIR_STATS` alias. `sessions.py` follows through `to_dict()`.
   → verify: `grep -nE "\.stats\b|\"stats\"|stats_f\b|DIR_STATS"` over these
   files shows only the shim and alias; `pytest tests/analysis` green.
3. Full test suite → verify: same pass count as before the change.
4. Commit in `python_magnetrun` (on approval), bump the submodule here.

### Phase B — schema and file types (to_duckdb)

5. Tests first in `test_schema.py`:
   - a DB holding `overview_records.sources_stats` data ends up with
     `sources_signal_stats` holding the same data (36 rows in the 11-05 DB);
   - `ensure_schema` run twice is a no-op;
   - `operationaldata` has `t_start`, `t_end`, `mode`.

   → verify: tests fail.
6. `schema.py`:
   - In `SCHEMA_SQL`:
     - rename the column in `CREATE TABLE overview_records`;
     - drop the `ADD COLUMN IF NOT EXISTS sources_stats` line (otherwise it
       would re-add the old column);
     - add `ALTER TABLE operationaldata ADD COLUMN IF NOT EXISTS
       t_start TIMESTAMP / t_end TIMESTAMP / mode VARCHAR`.
   - In `ensure_schema()`, after `SCHEMA_SQL`, same pattern as `experiment_ids`:
     - if `sources_stats` exists, `RENAME COLUMN sources_stats TO
       sources_signal_stats`;
     - then `ADD COLUMN IF NOT EXISTS sources_signal_stats VARCHAR[]`.

   → verify: step-5 tests pass; full to_duckdb suite green.
7. `populate.py`, with file names as seen in the 11-05 DB:
   - `SignalStats` → `Fichiers_stats`, pattern `_Stats_+(\d{6}-\d{4,6})`.
     It accepts `M8_Stats_260226-094838.tdms` and the legacy
     `M9_Stats__190304-1459.tdms`; `parse_tdms_file_ts` picks `%H%M%S` or
     `%H%M` from the length.
   - `Trigger` → `Fichiers_Manuel_Trig`, pattern
     `_ManuelTrig_(\d{6}-\d{6})`, `%y%m%d-%H%M%S`.

   Tests first in `test_populate.py` with these three names.
   → verify: tests pass; `populate operationaldata --type SignalStats Trigger
   --dry-run` on one M8 and one M9 assembly lists files (read-only). This
   also shows whether M9/M10 have Stats files at all.

### Phase C — per-file metadata pass

8. `populate.fill_operationaldata_metadata(con, assembly_name, types,
   reprocess)`:
   - For rows with `t_end IS NULL` (or all rows with `reprocess`), call
     `python_magnetrun.utils.files.extract_data(path, housing, key=None)`.
     This is the existing metadata-only path: TDMS properties, archive mtime,
     last pupitre line.
   - Convert local Europe/Paris → naive `db_tz` (UTC default), the same
     convention as `overview_records.t0`.
   - For `Overview` rows only: load once with `load_magnetdata`, store
     `infer_operating_mode(Data["Courants_Alimentations"])` in `mode`.
   - Commit per file, so the pass can be stopped and resumed.

   CLI: `magnetdb.py populate operationaldata-metadata --assembly X|--all
   [--type ...] [--reprocess] [--dry-run]`.
   Tests first (fixtures with fake `extract_data` / overview frames).
   → verify: tests pass; on a DB copy, one assembly gets `t_start`/`t_end`
   filled for every row, `mode` filled for every Overview row.

### Phase D — teb / BP per pupitre file

9. `compute_scalars`: add `teb_mean` and `bp_mean` (plain sample mean over
   non-NaN rows) when the column exists, plus `teb_count` and `bp_count`
   (non-NaN sample counts). That reproduces `_mean_across_frames`
   (samples-weighted) exactly when combining files. Add their units in
   `config.SCALAR_CHANNEL_UNITS`.
   Tests first in `test_compute_stats.py`.
   → verify: tests pass. A new build gets the scalars from the `op-stats`
   step. The 11-05 DB's 6536 processed files only gain them with
   `compute_op_stats --type Pupitre --reprocess`, one full load per file
   (open question 4).

### Phase E — SQL builder + stored mode

10. `crud._postprocess_overview_record`: use `operationaldata.mode` of the
    row's overview file when not NULL; otherwise keep the current load.
    Test first: with a stored mode, no file is loaded (patched
    `load_magnetdata` must not be called).
    → verify: test passes; existing `_postprocess` tests still green.
11. `crud.build_overview_records_from_operationaldata(con, assembly_name,
    reprocess, verbose)`. For each `Overview` row of a **non-M8** assembly
    with `t_start`/`t_end`, write one row through
    `_write_overview_record_row`.

    | Column | Value |
    |---|---|
    | `filename` | file stem |
    | `assembly_name` | the `operationaldata` row's |
    | `housing` | the assembly's |
    | `t0` | `t_start` |
    | `duration` | `t_end − t_start` [s] |
    | `sources_<kind>` | basenames of rows of the same housing whose `[t_start, t_end]` overlaps the overview's (strict, as `select_files`), excluding files ≤ 30 s for Archive/Pupitre and with no minimum for Default/Spike/Trigger/SignalStats |
    | `teb`, `bp` | `SUM(mean·count)/SUM(count)` over the `sources_pupitre` files from `op_run_scalars`; `0.0` when the scalars are missing (today's value) |
    | `mode` | via step 10 (stored) |
    | JSON columns, runlog lists | empty, as in the DB today |
    | hybrid lists | empty (M9/M10 have none) |

    - `on_conflict` is `skip`, or `replace` with `reprocess`.
    - M8 assemblies are skipped with a note and keep the `summary.json` path,
      since their hybrid files are not in `operationaldata` (open question 5).
    - Then run `merge_duplicate_pupitre_records`, as `overview-records-infer`
      does.

    CLI: `magnetdb.py populate overview-records-from-operationaldata
    --assembly X|--all [--reprocess] [--dry-run]`.
    Tests first on an in-memory DB with synthetic `operationaldata` rows
    (overlap edges, min-duration, midnight crossing, teb weighting, M8
    skipped).
    → verify: tests pass.

### Phase F — dashboard and docs

12. Rename `sources_stats` → `sources_signal_stats` and the "Stats" label →
    "Signal stats" in the files listed above; update `docs/populate.md`.
    → verify: `grep -rn "sources_stats" apps to_duckdb` returns only the
    migration; dashboard tests green (`--ignore=tests/mrun_test.py`).

### Phase G — validation on real data, then the build script

13. On a scratch copy of `magnetdb-2026-11-05.duckdb` (read-only on the
    records mount), for one M9 and one M10 assembly:
    1. register `SignalStats`/`Trigger`;
    2. run phase C;
    3. `compute_op_stats --type Pupitre --reprocess` for these two
       assemblies;
    4. build into a scratch copy of `overview_records`.

    Compare against the existing rows:
    - same set of `filename`s;
    - `sources_*` per kind: list the differences;
    - `duration` within 1 s, or explain the difference;
    - `mode` identical;
    - `teb` now non-zero.

    → verify: a difference report that the user reviews before any change to
    the build or to the DB to deploy.
14. Time phase E for the same assemblies against `overview-json` +
    `overview-infer` → verify: report both wall times.
15. `scripts/build_from_scratch.sh`, after the user accepts the report:
    - the `operationaldata` step adds `--type ... SignalStats Trigger`;
    - new step `operationaldata-metadata` after `operationaldata`;
    - new step `overview-ops` (the SQL builder) after `op-stats`, before
      `overview-json`.

    `overview-json` stays: it inserts with `skip`, so it only adds the rows the
    builder did not write (M8, files missing from `operationaldata`).
    `overview-infer` stays for those rows and the pupitre merge.
    → verify: `--help` lists the steps; `--from operationaldata --to
    overview-infer` on a scratch DB copy runs clean.

## Assumptions & open questions

1. **Conflict with ROADMAP A13 / `to_duckdb/TODOs.md`.** They propose dropping
   `operationaldata`, while this plan makes it the file index. Proposal: drop
   `operationaldata` from A13 (keep `sum_x2_dt` and `exp_part_bin_stats`). OK?
2. **Expected differences in `sources_*`.** Current discovery only lists the
   overview's own calendar day (`find_files`), so it misses an Archive started
   the day before and files after midnight. The SQL overlap will include them.
   Step 13 lists these; I assume they are fixes, not regressions.
3. **Files still being written.** The last file of the current day gets a
   provisional `t_end`. Proposal: `--reprocess` on the latest day, or skip
   files modified in the last 10 min. Which do you prefer?
4. **`teb`/`BP` on the 11-05 DB.** It can get them from a full
   `compute_op_stats --type Pupitre --reprocess` (6536 file loads), or wait
   for the next rebuild, where `op-stats` computes them anyway. I assume we
   wait for the next rebuild; `teb` is 0 today in any case.
5. **M8 stays on the `summary.json` path** until its hybrid files (kHz, RMS,
   trigger, vprocess) are registered in `operationaldata`, which would be a
   separate plan, close to A20. M8 rows are the only ones with
   `sources_hybrid_*` and `sources_stats` today.
6. **Stats coverage on M9/M10 is unknown.** Only M8 rows have
   `sources_stats` in the 11-05 DB; the step 7 dry-run will show whether M9
   and M10 have `Fichiers_stats` files.
7. **`t0` precision.** It stays minute-precision from the Overview file name
   (as `infer_overview_record_fields` already does), not the first sample
   time.
8. **Cost of the first metadata pass.** It reads metadata for about 54k files
   plus the new types over the rclone mount (33k Spike). It runs once; check
   that the mount is on rclone ≥ 1.75 first (see the 1.60 deadlock note).
9. **`record_tags`.** PLAN_file_check_rules.md plans `record_key =
   overview_records.filename`. The builder keeps the file stem as
   `filename`, so tags survive a rebuild of the table. Future tags on
   `operationaldata` should key on `file`, not `id`, which is a sequence that
   changes on every rebuild.
10. **Existing builders.** `populate overview-records`, `-from-json`,
    `-from-archive` and `-infer` stay unchanged apart from the rename and
    step 10; deprecating them would be a later decision. Archive-anchored
    records (`process_archive_file`, no Overview) are out of scope.
11. **`sync_info`/lag correlation** stays an on-demand `python_magnetrun`
    analysis per record (ROADMAP S2).
12. **Postgres merge.** `PLAN_duckdb_postgres_merge.md` folds `operationaldata`
    into a generic `records` table. `t_start`/`t_end`/`mode` should carry over
    as columns of that table.
13. **Branches.** Phase A goes on `python_magnetrun`'s current branch, and the
    rest on `housing-config-versions` after the A25 commit, unless you want a
    dedicated branch.
