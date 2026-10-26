# Plan: session records from EXPERIENCES_LOG (`magnetrun sessions`)

Status: proposed 2026-10-22, revised the same day after exploring the limits
(see [Limits explored](#limits-explored-2026-10-22)), then after the
file-quality commits of 2026-10-22 afternoon (`4caf41c`, `17c16f9`, `b3344bd`
in `python_magnetrun`; [PLAN_pupitre_binary_tail.md](PLAN_pupitre_binary_tail.md)).
**Approved and implemented 2026-10-22 (not committed)**; verification results
and open issues in [NOTES_session_records_checks.md](NOTES_session_records_checks.md).
Follow-up step R (runlog path fix, [below](#follow-up-step-r-pigbrother-runlog-path-proposed-2026-10-23))
is **proposed, awaiting approval**.

**Goal.** A `magnetrun sessions` command that turns `Data/EXPERIENCES_LOG.csv`
into one record per session, for any housing, from **2018-01-01 to now**. Each
record lists the overview, archive, pupitre, incident, stats, hybrid and runlog
files found in the session window `[HStart, HStop]`, written to
`sessions.json`. Files that no session claims are grouped into **unlogged**
records, so powered runs missing from the log are not lost.

The aim of overview records is to link pupitre, pigbrother and hybrid data.
Today that link only exists for sessions that have an Overview TDMS file. A
session-window anchor covers every case, including years and housings with no
Overview capture.

## Background (investigation of 2026-10-22)

Read-only queries on `Data/EXPERIENCES_LOG.csv`,
`to_duckdb/magnetdb-2026-10-08.duckdb` and the raw files under
`~/LNCMIG-Data/records`.

### How discovery works today

[`FileDiscovery.discover`](python_magnetrun/python_magnetrun/analysis/loaders.py)
starts from one Overview TDMS file:

1. Parse the start time from the filename and open the file to get the end time.
2. Glob the whole day for archive, pupitre and incident files.
3. [`select_files`](python_magnetrun/python_magnetrun/utils/files.py) opens each
   candidate to get its time range and keeps those that overlap.
4. For M8, pick the hybrid (CEA) files by UTC hour, from the overview's duration.

So anything without an Overview file is invisible, and nothing groups several
overviews into one experiment. `discover_from_archive` / `process_archive_file`
already handle archive-anchored sessions, but they have not been run for
2018–2021.

### Session ↔ file agreement

- M9/M10, 2022–2025: about **96 %** of overview records fall inside a logged
  session, and about **90 %** of user sessions longer than 5 min have at least
  one overview record (2026 is not processed yet in the snapshot).
- M5/M7 are well covered too: M7 2021 has 16 of 20 overviews inside a session,
  M5 2023 has 24 of 26. Several overviews often fall in one session.
- 5–15 % of sessions contain several overview records. A session is the natural
  "experiment" unit above `overview_records`.
- Overview and pupitre files start a median 2–4 min after `HStart` (all
  housings 2018–2026), except for the known M5 pupitre drift in 2023–2025 (see
  `m5_pupitre_clock_drift`). A plain overlap test works.

### Clocks and data pitfalls

- **Never use the `timestamp` column.** Up to 2019 it equals `HStart`. From 2020
  it drifts, reaching about 7.5 h (≈448 min) in 2025–26. One 2017 row is off by
  295 200 min. Use `HStart`/`HStop` only.
- `HStart`/`HStop` are Paris local time with a trailing AM/PM marker that has no
  effect (`"8/31/06  14:50:56.078 PM"`). `overview_records.t0` is UTC;
  filename timestamps (used by `select_files`) are Paris local time. Compare in
  local time, and watch the ambiguous hour when clocks go back in autumn.
- `EXPLOIT.` (8090 rows) and `EXPLOIT` (10 rows, 2007–2013) are the same
  operator account.
- `ElecGroup` always matches the GR1/GR2 mapping in the housing configs, and
  `e` is always the Bitter (B) coil, `i` the Helix (H) coil. Group 1 is the B
  side for M10/M8 and the H side for M9. Rows with an unusual pairing (e.g. 6
  rows in 2008 with `M10i` on group 1) point to swapped runs.
- `MinuteCount` is consistently slightly shorter than `HStop − HStart`
  (median 0.3 h on long sessions); it probably excludes some idle time.

### What exists on disk, 2018 → now

| Housing | 2018 | 2019 | 2020 | 2021 | 2022 → now |
|---|---|---|---|---|---|
| **M9** (≈400–460 user sessions/yr) | archive + pupitre | archive until 2019-10-07; overview from 2019-05-31 | overview | overview | overview (summaries exist) |
| **M10** (≈215–360/yr) | archive (until 2018-12-11) + pupitre | **pupitre only** | overview from 2020-02-06 | overview | overview (summaries exist) |
| **M5** | archive + pupitre | overview from 2019-09-02 | overview | overview | overview (summaries partial) |
| **M3** | – | – | – | overview (from 2021) | overview |
| **M7** | 3 sessions | 3 sessions | – | 6 sessions | few |
| **M8** | no sessions logged | – | – | – | overview + hybrid |

## Limits explored (2026-10-22)

### 1. Files outside any session

- Only 165 of 6047 pupitre runs since 2018 (2.7 %) fall outside every session,
  carrying 0.3 % of the energy (249 of 87 042 MWh). Most are short (median
  1–10 min) and unpowered.
- But **49 of them reached more than 1 T** (`exp_run_scalars.field_max`, i.e.
  `max(Field)` of the pupitre file; checked against 4 raw files, the values are
  held plateaus, not spikes). They form unlogged campaigns: M10 18–23 May 2018,
  M5 Dec 2019 – Feb 2020, M9 8–26 Apr 2024 (≈15 runs at 5.4 T, several hours
  each), plus a few in Nov 2024 and Jan 2025.
- 41 of these 49 are **not linked to any overview record** either (17 in years
  without a summary, 24 not linked although a summary exists). A few have a
  same-day Overview that does not claim them (M9 Apr 2024, M10 2022-10-24,
  M5 2024-07-03 and 2026-06-02): not investigated.
- Overview records outside sessions: 2–6 % for M9/M10. One cluster is M9
  9–20 Jan 2026, with overviews lasting up to 3 days and no session within
  2 days: recordings left running while idle.

**Consequence:** add an unlogged pass (step 4).

### 2. Sessions with no `HStop`

- 503 rows since 2018. About **70 % are followed by a new session on the same
  coil within 10 min**: false starts, to drop.
- Of the 147 left, half contain pupitre runs. These runs end a median 151 min
  after `HStart` (at most 11 h) for user sessions, so the cap "next `HStart` on
  the same coil, or `HStart` + 12 h" holds.
- They come in bursts (e.g. M9 in Nov 2024, mostly powered user runs at 35 T).

### 3. Duplicates, short sessions, merging coils

- Exact duplicate rows exist only in 2006–2015; none after 2018.
- 544 sessions are shorter than 5 min: 9 contain a powered run, all have zero
  `Paimant`. Keep and flag.
- Merging the `i`/`e` rows of a housing whose windows overlap works: only 12
  merged groups mix two non-operator user codes, mostly typos (`GSC01-118` /
  `GCS01-118`, `TEST` / `Test`, `GMS12-119` / `GMS12-129`).

### 4. Long sessions (> 12 h)

- 251 closed M9/M10 rows (≈130 sessions once coils are merged, 89 proposals)
  last more than 12 h, up to 29.1 h. They are **real**: all are user sessions
  with non-zero `Paimant` (1.3–5.6 MW average), and in 239 of 251 the pupitre
  recording covers the window up to `HStop`.
- Typical shape: start 08:00–11:00 (or evening), close during the night;
  161 cross midnight.
- Only 2–3 look closed late: M10 2022-05-17 (10.9 h without pupitre data before
  `HStop`), M9 2020-06-20 M9e (11.5 h), M9 2021-05-08 (1.6 h).

**Consequence:** never cut long sessions; record where the data actually ends.

### 5. Discovery cost: archive end times

- Reading an Archive TDMS file's time range costs **6.8 s, and up to 42 s**, for
  a 450–500 MB M9 file, against ≈0.1 s for Overview and pupitre files. About
  7000 M9/M10 archives exist since 2018, and today's discovery re-reads the
  ranges of all same-day archives for every overview.
- The cost is in `TdmsFile.open`, which parses every segment header when no
  `.tdms_index` file exists (most years have none). With an index file it takes
  1–2.6 s. Counting the samples of one channel adds only ≈0.4 s, and
  `len(channel)` from the metadata matched the counted samples in 9 of 9 files.
- **The file modification time gives the end time for free.** On 14 archives
  (2018–2025) it matched the computed end within ±35 s. Over all 6753
  Archive files since 2018 (M3/M5/M8/M9/M10), none has a modification time
  before its start, after the next file's start, or more than a day after its
  start.
- This does **not** hold for Overview files: 74 have a modification time after
  the next overview's start and 96 more than a day after their start (e.g. M9
  June 2019 files modified on 2019-09-04). Overview files are cheap to open
  anyway.

### 6. Truncated and unreadable pupitre files

Step E of [PLAN_digital_twin_schema.md](PLAN_digital_twin_schema.md) now
records `experiments.file_integrity` (`ok` / `truncated` / `unreadable`), and
the pupitre readers cut a corrupt tail (NUL padding, binary blocks, stale rows
from an older run) before parsing.

- Since 2018: 12 `truncated` files (11 `corrupt_tail`, 1
  `incomplete_last_line`) and 7 `unreadable` (header-only or missing header).
- Discovery does **not** use those readers. `extract_data` takes a pupitre
  file's end time from its **last line** (`_pupitre_end_from_last_line`),
  which lies in the corrupt tail. Result: `select_files` silently drops
  **all 11 `corrupt_tail` files**, which still hold valid rows (e.g. M9
  `2020.09.30 - 21:05:02`, 343 min). For two of them the last line comes from
  an older run, giving an end time years before the start. Only the
  `incomplete_last_line` file (M8 `2026.03.20 - 11:09:00`) is kept.
- This also affects today's overview-anchored `summary.json` runs.
- The 7 `unreadable` files have no usable rows; dropping them is right.

**Consequence:** step 0 also fixes the pupitre end time.

### 7. Daylight-saving changes

- Discovery compares naive Paris wall-clock times on both sides (`HStart`,
  filename timestamps, pupitre `Date`/`Time`), so no conversion is needed for
  matching. A pupitre file that spans a clock change has an end time off by
  1 h in wall-clock terms; the overlap test tolerates that.
- The only UTC conversion is the M8 hybrid hour selection. `zoneinfo`'s
  default (`fold=0`) resolves the repeated autumn hour as the first (DST)
  occurrence, the same rule as `local_to_utc_naive` since `17c16f9`.
  (`hybrid/hybrid_data.py` still uses the second occurrence; noted in
  [PLAN_pupitre_binary_tail.md](PLAN_pupitre_binary_tail.md), not changed
  here.)

### 8. M5 pupitre drift and the future SUPERVISION source

- 8 M5 pupitre files from 2024–25 fall outside sessions because of the drift.
- `to_duckdb/TODOs.md` and ROADMAP A9 plan to read sessions from the SUPERVISION
  database instead of the CSV: `load_sessions` must be the only code that reads
  the CSV.

## Files affected

All in the `python_magnetrun` submodule except the last one.

- **Edit** `python_magnetrun/utils/files.py`: cheap end time for Archive TDMS
  files, and a correct end time for pupitre files with a corrupt tail
  (step 0).
- **Create** `python_magnetrun/analysis/sessions.py`: loads, cleans and merges
  sessions; drives discovery and the unlogged pass; registers the CLI command.
- **Edit** `python_magnetrun/analysis/loaders.py`:
  - add `FileDiscovery.discover_window(housing, start, end)`;
  - move the hybrid hour selection into a helper that takes a time window, so
    both `_discover_hybrid_data` and `discover_window` can use it. Existing
    behaviour stays the same.
- **Edit** `python_magnetrun/main.py`: register the `sessions` command.
- **Create** `tests/analysis/test_sessions.py`; **edit** the existing tests of
  `utils/files.py` for step 0.
- **Edit** `python_magnetrun/analysis/README.md`: document the command.
- **Edit** `Data/README.md` (parent repo): fix the EXPERIENCES_LOG column list
  (18 columns: `timestamp, UserCode, UserName, OperatorName, Magnet, ElecGroup,
  HStart, HStop, MinuteCount, Paimant, Pmax, Phydraulique, Ptotale,
  dDepassement, nDepassement, Cout, Qtotale, QCout`) and add how to produce
  `sessions.json`.

## Approach

0. **End times in `extract_data`** (`utils/files.py`):
   - **Archive files:** for a `.tdms` file in an Archive directory, use the
     file modification time as the end time when it is plausible: after the
     filename start and less than 24 h after it. Otherwise fall back to the
     current `_tdms_end_from_properties`. Overview and incident files keep the
     current method.
   - **Pupitre files:** keep the last-line read, but when it gives no end time
     or one before the start, load the file through `MagnetRun.fromtxt` (whose
     readers cut the corrupt tail since `4caf41c`/`b3344bd`) and use start +
     duration of the valid rows. This only happens for a handful of files.

   → verify: tests first (plausible / implausible modification time; pupitre
   fixture with valid rows then a stale tail from an older run, modelled on
   `tests/test_truncated_pupitre.py`). Then on real data:
   - compare both Archive methods on ≥ 5 archives per housing and year
     (2018 → 2026, M5/M9/M10); report the largest difference (expected
     < 60 s) and the time per file;
   - the 11 `corrupt_tail` pupitre files since 2018 are kept by
     `select_files`, with an end time within a few seconds of start +
     `exp_run_scalars.duration_s`; the 7 `unreadable` files are still
     skipped;
   - `magnetrun analysis` is unchanged apart from these fixes: run it with
     `--dry-run` off on one month of M9 Overview files (e.g. July 2025, which
     contains the `corrupt_tail` file `2025.07.01 - 09:58:01`) before and
     after step 0, and diff the two `summary.json` files. Expected: identical
     file lists, except that `2025.07.01 - 09:58:01.txt` now appears; report
     the run times of both.

1. **Tests first** (`tests/analysis/test_sessions.py`), covering:
   - `HStart`/`HStop` parsing, including the AM/PM marker;
   - `EXPLOIT.` and `EXPLOIT` treated as one operator account;
   - removing exact duplicate rows;
   - dropping an unclosed session followed by a new one on the same coil within
     10 min;
   - capping an unclosed session at the next `HStart` on the same coil or
     `HStart` + 12 h;
   - merging the `i`/`e` rows of the same housing whose windows overlap into
     one session;
   - grouping unclaimed files into unlogged records;
   - `discover_window` on a window that crosses midnight, using fake files under
     `tmp_path` and mocking end-time extraction as `test_loaders.py` does.

   → verify: they fail before the code exists.

2. **`load_sessions(csv, housing, start, end)`** in `sessions.py`. Works in
   Paris local time and never uses the `timestamp` column. Each session record
   holds:
   - start and stop times, with a flag when the stop time was capped;
   - the list of users (UserCode) and an operator-session flag;
   - per coil (`i`/`e`): `ElecGroup`, `MinuteCount`, `Paimant`;
   - `logged = true`.

   Long sessions (> 12 h) are kept as they are.

   → verify: the step 1 tests pass.

3. **`FileDiscovery.discover_window`**:
   - glob pigbrother Overview, Archive, Default, ManuelTrig, Spikes and Stats
     files for every day the window touches, plus the day before (archive files
     rotate every ~5 h and can start before midnight);
   - glob pupitre files for the days in the window;
   - filter with the existing `select_files`;
   - reuse `_discover_runlogs` and the hybrid helper (hybrid only for M8);
   - set `anchor` to `overview`, `archive`, `pupitre` or `none`;
   - record `data_end`, the end of the last file found, next to the session
     stop time.

   → verify: tests pass; the existing `tests/analysis` suite passes before and
   after.

4. **Unlogged pass.** After all sessions of the period are discovered, list the
   Overview, Archive and pupitre files of the period that no session claimed.
   Chain those whose gap is under 30 min into one record with `logged = false`,
   no users, and the same file-list fields.

   → verify: tests pass.

5. **CLI** `magnetrun sessions --log CSV --housing M9 --from 2018-01-01
   [--to …] [--output-dir DIR]`. Discovery only, no data loading. Writes
   `sessions.json`; the existing `summary.json` workflow is unchanged.

   → verify: `magnetrun sessions --help`.

6. **Real-data checks**:
   - (a) M10, 2019: sessions get pupitre files, with `anchor=pupitre`;
   - (b) M9, 2018: archive and pupitre files are found;
   - (c) M9, 2025: compare against `Data/M9_summary-2025.json`. At least 312 of
     the 330 overview files should appear in a logged session;
   - (d) M9, April 2024 and M10, May 2018: the unlogged campaigns appear as
     `logged = false` records;
   - (e) M10 2022-05-17 and M9 2020-06-20: `data_end` is about 11 h before the
     session stop time.

   → verify: print the counts and report them as-is.

7. **Lint and tests**: `ruff check` and `pytest tests/analysis`.

   → verify: no new warnings, all pass.

## Assumptions and open questions

1. **Scope:** this plan stops at `sessions.json` in `python_magnetrun`. Loading
   it into a `sessions` table in `to_duckdb` (and linking it to
   `overview_records` / `experiments`) would be a separate plan.
2. **Submodule branch:** `python_magnetrun` is on `spike/tdms-polars-benchmark`.
   Work there or on a new branch?
3. **Where should step 0 go?** Step 0 has two parts: the Archive end time
   from the modification time, and the pupitre end time for files with a
   corrupt tail. `extract_data` (where both would go) is also used by the
   existing `magnetrun analysis` command, which produces `summary.json`.
   Three options:
   - **(a) Both parts in `extract_data`.** `magnetrun analysis` also becomes
     faster and stops dropping the 11 `corrupt_tail` pupitre files. Its
     archive end times then come from the modification time instead of the
     file content.
   - **(b) Only the pupitre part in `extract_data`; the Archive part only in
     `magnetrun sessions`.** `magnetrun analysis` gets the bug fix but keeps
     reading archive end times from the file content, and stays slow.
   - **(c) Both parts only in `magnetrun sessions`.** `magnetrun analysis`
     is unchanged and keeps dropping `corrupt_tail` pupitre files.

   **Decided 2026-10-22: (a).** Both parts go into `extract_data`. The
   modification-time shortcut only works while copies of the archive files
   keep their modification times (true today); otherwise the fallback to
   reading the file applies.
4. **A persistent file-range index** (path, type, housing, start, end, size,
   modification time, method), built once and updated incrementally, is left
   out. With step 0, reading the ranges of all files since 2018 takes minutes
   rather than hours, so an index is no longer needed for this plan. It can be a
   later plan if repeated runs are still too slow.
5. **Unlogged chaining gap:** 30 min, to confirm on the real-data checks.
6. **Operator sessions and sessions under 5 min:** kept and flagged, not
   dropped, so whoever reads the file decides what to filter.
7. **File quality in `sessions.json`:** not recorded. `experiments.file_integrity`
   in `to_duckdb` already holds it; a later `sessions` table can join it.
8. **M5 pupitre drift in 2023–25:** not corrected. The 8 affected files will end
   up in unlogged records.
9. **Future source:** `load_sessions` is the only place that knows about the
   CSV, so the source can be swapped for the SUPERVISION database later.

## Follow-up step R: pigbrother runlog path (proposed 2026-10-23)

**Status: proposed, awaiting approval.** The other follow-ups (archive size
threshold, `power_end`, range cache, overview continuation rule) are listed in
[NOTES_session_records_checks.md](NOTES_session_records_checks.md) and still
need decisions.

**Goal.** The pigbrother run log is found, so the `pigbrother_runlog` field of
`summary.json` and `sessions.json` records is filled.

**Problem.** `FileDiscovery._discover_runlogs` looks for
`<pigbrother_runlog_dir>/LOG_ACQ_ENET.txt` (`PIGBROTHER_LOG_FILENAME` in
`runlogs/pigbrother.py`). The real file is
`~/LNCMIG-Data/records/pbsurv/log/Log_ACQ_ENET.txt`: another directory, and
another case (`Log_` instead of `LOG_`). Callers pass the Overview directory
(`analysis/processing.py`, twice; `analysis/sessions.py`) or nothing (default:
`pigbrother_datadir`), and `data_dirs.PIGBROTHER_RUNLOG_DIR` has no default
and is not set. So the log is never found: `pigbrother_runlog` is empty in
every summary and session record.

**Files affected** (`python_magnetrun` submodule):

- **Edit** `python_magnetrun/analysis/loaders.py`: `_discover_runlogs`
  searches, in order, the explicit `pigbrother_runlog_dir`,
  `data_dirs.PIGBROTHER_RUNLOG_DIR` when set, then `<pigbrother_datadir>/log`;
  in each, it matches `LOG_ACQ_ENET.txt` case-insensitively.
- **Edit** `tests/analysis/test_loaders.py`: tests for the search order and the
  case-insensitive match.
- **Edit** `python_magnetrun/runlogs/README.md`: real location and name of the
  file.

No caller needs to change: they keep passing the Overview directory, and the
`<pigbrother_datadir>/log` fallback finds the file.

**Approach and checks:**

1. Tests first (fake trees under `tmp_path`): file at
   `<pigbrother_datadir>/log/Log_ACQ_ENET.txt` found; explicit directory wins
   over the fallback; no file → empty list, as today. → verify: they fail
   before the change, pass after; `tests/analysis` still passes.
2. Implement in `_discover_runlogs`. → verify: `ruff check` clean.
3. Real data: `magnetrun sessions` on one month (e.g. M9, July 2025) and
   `magnetrun analysis` on one overview. → verify: `pigbrother_runlog` lists
   `…/pbsurv/log/Log_ACQ_ENET.txt`.
4. Update `runlogs/README.md`.

**Assumptions and open questions:**

1. **One file for all records.** The log is a single file (19.5 MB, September
   2019 → now), so every record will list the same path. Whoever reads it must
   filter its events by housing and time.
2. **Magnet names in the log.** Since August 2025, M9 and M10 appear as
   `M9Mod1` / `M10Mod1`; `_parse_acquisition` keeps those names as they are.
   Normalizing them is left to whoever uses the events (e.g. the
   crash-flag follow-up in the notes), not part of this step.
3. **Share access.** The file sits on the network share; a first read failed
   once with "Input/output error" on 2026-10-22, then worked. No retry is
   added.

## Related

- `to_duckdb/demos/users_table_demo.py`: `update_overview_records_ids` already
  links sessions to overview records (with the UTC → Paris conversion).
- `to_duckdb/demos/find_research_area_candidates.py:67` matches only
  `'EXPLOIT.'` exactly; harmless while the `users` table keeps the 2018 cutoff.
- The 182.4 T `field_max` seen earlier (M10, 2024-12-05) is gone after the
  file-quality reprocessing of 2026-10-22: the highest `field_max` is now
  42.03 T (M8, valid, see `m8_42T_field_valid`). M10 `2024.12.05 - 11:16:02`
  is now `truncated` (`corrupt_tail`), consistent with a stale tail having
  caused the bad value.
- [PLAN_pupitre_binary_tail.md](PLAN_pupitre_binary_tail.md) and step E of
  [PLAN_digital_twin_schema.md](PLAN_digital_twin_schema.md): the pupitre
  file-quality work that step 0 reuses.
- [NOTES_cirrus_A1_experiment_matching.md](NOTES_cirrus_A1_experiment_matching.md):
  a similar session ↔ experiment matching, from Cirrus run logs.
