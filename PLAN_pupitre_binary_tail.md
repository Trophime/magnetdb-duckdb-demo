# Plan: Pupitre files whose crash tail is binary (invalid UTF-8)

**Status (2026-10-22).** Written as a follow-up of step E
([PLAN_digital_twin_schema.md](PLAN_digital_twin_schema.md), "File quality
on `experiments`"). The binary-tail fix is **not approved for
implementation**. Two related items are **done** (approved and implemented
2026-10-22): see "Done: single-row files and DST rules for filenames" at
the end.

## Goal

M10 `2020.10.13 - 11:38:15.txt` and files like it load their valid rows
(here 209 rows, `11:38:16` → `11:41:44`), get
`file_integrity = 'truncated'` instead of `unreadable`, and have their
stats computed.

## Background

- Step E drops a crash tail (NUL padding, then stale rows from an older
  run) at the first `Date`/`Time` that does not parse or steps back more
  than 1 h (`count_valid_pupitre_rows`). That cutoff runs **after**
  parsing.
- In M10 `2020.10.13 - 11:38:15.txt` (experiment 844, `M10_A200525_00`),
  lines 1–211 are clean: parameter line, header, 209 rows with all 88
  fields. From line 212: 2539 NUL bytes, then ~12 lines of binary data
  (old disk blocks that were not a text file), no final newline. All 12
  invalid-UTF-8 lines are in that tail.
- Both backends fail before the cutoff can run:
  - polars: `ComputeError: invalid utf-8 sequence` (`pl.read_csv` decodes
    the whole file as UTF-8);
  - pandas: `UnicodeDecodeError … position 90113`.
    `_open_text_with_fallback` (`utils/files.py`) chooses the encoding
    after reading only the **first character**, so a file valid at its
    start opens as UTF-8 and the Latin-1 fallback never applies to a
    corrupt tail.
- Impact on stats is small: the run never had field on (`Field` max
  0.0 T) and lasts 3.5 min. It is missing from duration and energy totals.

## Files affected

| Repo | File | Action |
|---|---|---|
| python_magnetrun | `python_magnetrun/readers/csv_readers.py` | edit: `PupitreReader` helper returning the file's bytes up to the first line holding a NUL byte or invalid UTF-8, plus the number of lines cut |
| python_magnetrun | `python_magnetrun/magnetdata_polars.py`, `python_magnetrun/magnetdata_pandas.py` | edit: on a decode error in the full read, re-read through that helper; the timestamp cutoff still runs afterwards, and the lines cut are added to `rows_dropped` |
| python_magnetrun | `tests/test_truncated_pupitre.py` | edit: fixture with valid rows, then NUL bytes, then random non-UTF-8 bytes; both backends |
| demo | `PLAN_digital_twin_schema.md` | edit: step E counts (one `unreadable` file becomes `truncated`) |

## Steps

1. Write the test first, modelled on this file → verify: it fails with
   `ComputeError` (polars) and `UnicodeDecodeError` (pandas).
2. Add the helper; use it only when the normal full read fails to decode
   → verify: the new test passes; the python_magnetrun suite still passes
   (1318 passed, 19 skipped on 2026-10-22).
3. Real file → verify: both backends load 209 rows ending at
   `11:41:44`, `truncated = True`.
4. Back up `to_duckdb/magnetdb-2026-10-08.duckdb`, then run
   `check_experiment_files.py --assembly M10_A200525_00 --recheck` and
   `compute_exp_stats.py --assembly M10_A200525_00` → verify:
   experiment 844 is `truncated` and `STATS DONE`; compared with the
   backup, no other experiment's values change.
5. Update the step E counts in `PLAN_digital_twin_schema.md`.

## Assumptions and open questions

- **Only on failure.** The fallback runs only when decoding fails, so
  normal files are read exactly as today. Making the encoding probe read
  the whole file would also work, but adds a pass over every file.
- **Cut the bytes, do not decode the junk as Latin-1.** Decoding the
  binary tail as text could change the inferred column types or exceed
  the column count; cutting the bytes before parsing avoids both.
- **Not included:** the `compute_op_stats.py` fallback reader has no
  corrupt-tail cutoff. No effect today: its main path goes through
  `load_magnetdata` (cutoff applies), the fallback only runs when
  python_magnetrun fails, and `op_run_scalars` only holds 68 pupitre runs
  of `M10_A180220_00`, none with a corrupt tail. Copy the 3-line cutoff of
  `compute_exp_stats.py` if op stats are extended to more assemblies.

## Done: single-row files and DST rules for filenames

Approved and implemented 2026-10-22.

### Single-row files left out of experiment stats

- **Problem.** 23 experiments stayed `pending` (8 M10, 1 M5, 4 M7, 10 M9;
  e.g. M10 `2023.05.10 - 14:04:01/14:04:15/14:04:52/14:07:17`). Each file
  has a single data row, so `sum(dt)` is 0 and `compute_scalars` raises
  `ZeroDivisionError` on the time-weighted mean; every run retried them.
  Together with the 11 `unreadable` files this accounts for all 34
  `pending` experiments in `magnetdb-2026-10-08.duckdb`.
- **Fix.** `get_experiments` in `to_duckdb/compute_exp_stats.py` leaves out
  experiments whose `file_checks.rows_read` is below 2, as it does for
  `unreadable` files. They stay `pending`; `file_checks` says why.
  Experiments not checked yet (no `rows_read`) are still processed.
- **Verified.** `test_get_experiments_skips_unreadable_and_single_row`;
  `to_duckdb` suite 565 passed; on `magnetdb-2026-10-08.duckdb`,
  `get_experiments` over all assemblies leaves out exactly the 34
  `pending` experiments (23 with `rows_read` = 1, 11 `unreadable`).

### `local_to_utc_naive`: same DST rules as `series_local_to_utc_naive`

- **Problem.** The filename → UTC conversion (`utils/timezone.py`) had no
  rule for the hour repeated at the end of summer time
  (`AmbiguousTimeError`) or the hour skipped at its start
  (`NonExistentTimeError`), unlike the conversion of the data columns. No
  pupitre file on disk (14 626 scanned) has a name in either hour.
- **Fix.** Ambiguous time → first (DST) occurrence, with a warning (a
  single timestamp cannot be inferred); non-existent time → shifted
  forward.
- **Verified.** Two new cases in `TestLocalToUtcNaive`
  (`tests/test-timestamp.py`); python_magnetrun suite 1320 passed,
  19 skipped.
- **Remaining inconsistency (not changed).** `hybrid/hybrid_data.py`
  resolves ambiguous times as the second occurrence (`ambiguous=False`).
