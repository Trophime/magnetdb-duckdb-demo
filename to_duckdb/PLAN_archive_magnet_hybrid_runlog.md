# Plan — hybrid and run-log files in `demos/archive_magnet_data.py`

Status: **proposed** (2026-10-22) — follow-up to
[`PLAN_archive_magnet_data.md`](PLAN_archive_magnet_data.md); not yet
approved/implemented.

## Goal

Let `archive_magnet_data.py` archive the files listed in the
`overview_records` columns it currently skips, with their correct on-disk
path inside the tarball:

- `sources_hybrid_kHz`, `sources_hybrid_rms`, `sources_hybrid_trigger`,
  `sources_hybrid_vprocess`
- `sources_pigbrother_runlog`, `sources_pupitre_runlog`

## Current gap

- These columns are **empty in both databases** (`magnetdb.duckdb`,
  `test-magnetdb.duckdb`), so the skip affects no real data today. They will
  be populated as soon as the overview pipeline records hybrid / run-log
  files.
- No code defines where these files live relative to a records root:
  - `HYBRID_DATA_DIR` (default `/mnt/LNCMIG-Data/records/CEA`) — a root,
    but no rule for the sub-layout below it (per housing? per kind?).
  - `PIGBROTHER_RUNLOG_DIR`, `PUPITRE_RUNLOG_DIR`, `HYBRID_RUNLOG_DIR` — no
    hard-coded default at all (env var / `data_dirs.json` only).
- It is also unknown whether the stored values will be bare filenames (like
  the other `sources_*` columns) or paths relative to their root.

## Candidate resolution rules (to confirm)

| Source | Candidate on-disk path | Archive member |
|---|---|---|
| `pupitre_runlog` | `PUPITRE_RUNLOG_DIR / cirrus / A[1-4] / YYYY-MM-DD_cirrus_out.log` (per `FileSet` docstring; feed `A1`–`A4` must come from the stored value) | relative to the records root, or under a `runlog/pupitre/` prefix if the dir is outside it |
| `pigbrother_runlog` | `LOG_ACQ_ENET.txt` "co-located with .tdms files" (`data_dirs.py`) → `pbsurv/<housing>/…`? — the stored value must disambiguate, since every session has the same filename | idem |
| `hybrid_*` | `HYBRID_DATA_DIR / …` — layout unknown | relative to the records root (`CEA/…`) |

Once confirmed, the change is local to `resolve_path()` (and moving the
types from `_SKIPPED_SOURCES` to `_ARCHIVED_SOURCES`).

## Open questions

1. What is the actual directory layout under `CEA/` for hybrid kHz / RMS /
   trigger / vprocess files?
2. Where do run-log files live on the production records mount, and are
   `*_RUNLOG_DIR` inside the records root (so their archive path can stay
   relative to it)?
3. Will `sources_pigbrother_runlog` store a path (needed: `LOG_ACQ_ENET.txt`
   is not unique) and `sources_pupitre_runlog` include the `A[1-4]` feed?
4. Run-logs are per day / per acquisition, shared by many sessions — archive
   whole files (current dedup handles repetition) or slice them to the
   magnet's windows?

## Verification (when implemented)

- Fake records tree with one file per new source type at the confirmed
  path → `tar -tJf` lists them at the expected members; `md5sum -c` OK.
- Dry run on a DB where the columns are populated → no
  `skipped files (no known on-disk layout)` warning.
