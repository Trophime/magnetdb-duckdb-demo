# Plan — `demos/archive_magnet_data.py`: per-magnet data archive

Status: **proposed** (2026-10-18) — not yet approved/implemented.

## Goal

For one magnet, archive every experiment and overview-record data file
recorded while that magnet was part of an assembly, into a single `.tar.xz`
whose internal paths mirror the records tree (so it can be extracted
straight into a records root), plus a manifest with md5 checksums.

## Findings (read-only investigation)

- **History**: `assembly_magnets(assembly_name, magnet_name, commissioned_at,
  decommissioned_at, …)` → `assemblies(housing, commissioned_at,
  decommissioned_at)`.
- In `magnetdb.duckdb`, `assembly_magnets.commissioned_at` is NULL on all
  101 rows; `decommissioned_at`, where set, always equals the assembly's.
  The per-magnet window must therefore fall back to the assembly's dates.
- **Timezones**: DB commission dates are UTC (`--db-tz` defaults to `UTC`
  across `magnetdb.py`); `overview_records.t0` is UTC; pupitre filenames
  (`"YYYY.MM.DD - HH:MM:SS.txt"`) embed Europe/Paris local time
  (`populate.parse_pupitre_file_ts` returns a tz-aware Paris datetime).
- **Experiments**: `experiments.file` is a bare filename; on-disk path is
  `records_base / srv-data-install / <housing> / <file>` (same rule as
  `compute_exp_stats.ingest_assembly`).
- **Overview records**: `sources_*` columns are bare filenames.
  - pupitre `.txt` → `srv-data-install/<housing>/<file>`
  - TDMS → `pbsurv/<housing-from-filename>/<mode dir>/<file>`, mode dir from
    `python_magnetrun.utils.files`: `Overview`, `Fichiers_Archive`,
    `Fichiers_Default`, `Fichiers_Spike`, `Fichiers_Manuel_Trig`,
    `Fichiers_stats` (lower-case `s`).
  - `hybrid_*` and `*_runlog` sources: empty in both DBs, and no on-disk
    layout is defined in code → out of scope (see follow-up below).
- `records_base` defaults to `populate._RECORDS_BASE` (resolved via
  `data_dirs.json` / env vars).
- 37 `overview_records` rows in the test DB have `assembly_name IS NULL` —
  not attributable to any magnet, ignored.

## Compression choice — xz, not zstd

TDMS is NI's segment format (metadata + raw uncompressed little-endian
samples), not HDF5 — there is no internal compression, so archiving
compression is worthwhile. Benchmark on local sample files
(ratio / wall time, all cores):

| File | Size | gzip -6 | zstd -3 | zstd -9 | zstd -19 | xz -6 | xz -9e |
|---|---|---|---|---|---|---|---|
| M9_Overview | 30 KiB | 3.47 | 2.88 | 2.93 | 3.69 | **4.57** | 4.62 |
| M9_Archive | 27 MiB | 1.44 / 1.8s | 1.41 / 0.1s | 1.48 / 0.5s | 1.57 / 10.6s | **2.00 / 10.9s** | 2.00 / 12.4s |
| M9_Default (50 Hz) | 250 MiB | 6.52 / 7s | 7.02 / 0.3s | 7.32 / 1s | 9.10 / 23s | **11.01 / 16s** | 11.12 / 81s |
| M19_Archive | 424 MiB | 1.61 / 13s | 1.59 / 0.6s | 1.80 / 1.9s | 1.94 / 22s | **2.26 / 18s** | 2.27 / 156s |

- xz -6 wins every file (15–30% smaller than zstd -19, similar or less time).
- `zstd --ultra -22` / `xz -9e`: negligible gain, up to ~10x slower.
- xz tuning for 8-byte floats (`lc=0,lp=3,pb=3`): +1%; delta filter: worse.
- Trade-off: xz decompresses ~10x slower than zstd — acceptable for an
  archive written once.
- Python's stdlib `lzma` (`tarfile` `w:xz`) is single-threaded → stream the
  tar into the system `xz -T0` instead.

## Files affected

- `to_duckdb/demos/archive_magnet_data.py` — **create**
- `to_duckdb/demos/README.md` — **edit** (new section: description,
  examples, flag table)
- `to_duckdb/PLAN_archive_magnet_hybrid_runlog.md` — **create** (follow-up
  plan for hybrid/runlog sources)

## Approach

1. **Magnet history → windows** (read-only DuckDB). Per `assembly_magnets`
   row of the magnet:
   - `start = COALESCE(am.commissioned_at, a.commissioned_at)`; NULL → no
     lower bound.
   - `end = COALESCE(am.decommissioned_at, a.decommissioned_at)`; NULL →
     **until now**.
   - Both interpreted in `--db-tz` (default `UTC`) as tz-aware datetimes.
   - No history → error, non-zero exit.
2. **Records in window** (bounds inclusive, as in
   `populate.find_and_register_pupitre`):
   - Experiments of the assembly whose filename timestamp (Europe/Paris)
     falls in `[start, end]`.
   - Live overview records (`merged_into IS NULL`) of the assembly whose
     `t0` (UTC) falls in `[start, end]`.
   - Records with an unparseable timestamp / NULL `t0` are kept with a
     warning (they do belong to the assembly).
3. **Path resolution** as in *Findings*; already-absolute stored paths used
   as-is; hybrid/runlog sources counted and reported as skipped. Each
   unique file archived once (a pupitre file is often both an experiment
   and an overview source).
4. **Archive**: streaming `tarfile` (`mode="w|"`) piped into
   `xz -<level> -T0` writing the output file. If the `xz` binary is missing,
   fall back to stdlib `w:xz` with a warning. Each file's md5 is computed
   while tar reads it (thin hashing reader wrapper) — one read per file.
   Missing files are warned about and skipped; exit non-zero if no file at
   all was found.
5. **Manifests**, appended last at the archive root, named per magnet so
   several magnets' archives can be extracted into the same records root:
   - `MANIFEST_<magnet>.md5` — `md5sum -c` format, one line per archived
     file; after extraction, `md5sum -c MANIFEST_<magnet>.md5` verifies all.
   - `MANIFEST_<magnet>.csv` — provenance: `assembly, record_kind
     (experiment|overview), record_name, source_type, path, size_bytes, md5,
     status (archived|missing)`; one row per (record, file); missing files
     listed with empty md5.
6. **Summary** printed: per-assembly window, record counts, files
   found / missing / skipped, final archive size and overall ratio.
7. **CLI**:

   | Flag | Default | Description |
   |---|---|---|
   | `--magnet` | *(required)* | Magnet name (`magnets.name`) |
   | `--db` | `DEFAULT_DB` | DuckDB file |
   | `--db-tz` | `UTC` | Timezone of `commissioned_at`/`decommissioned_at` |
   | `--records-base` | `populate._RECORDS_BASE` | Root of the records tree |
   | `--output` | `<magnet>.tar.xz` | Output archive |
   | `--level` | `6` | xz preset 0–9 |
   | `--dry-run` | off | Print plan + CSV manifest to stdout, no archive |

   NumPy-style docstrings, PEP 8 names, same structure as the other demos.
8. **Follow-up plan** `PLAN_archive_magnet_hybrid_runlog.md`: the gap
   (empty `sources_hybrid_*` / `*_runlog` columns, no layout rule for
   `HYBRID_DATA_DIR`, and `PIGBROTHER_RUNLOG_DIR` / `PUPITRE_RUNLOG_DIR` /
   `HYBRID_RUNLOG_DIR` with no default), candidate resolution rules (e.g.
   `cirrus/A[1-4]/YYYY-MM-DD_cirrus_out.log` for pupitre runlogs), open
   questions.

## Verification

1. `--dry-run --magnet M10Bitters` against `magnetdb.duckdb` and
   `test-magnetdb.duckdb` → windows match a manual
   `assembly_magnets JOIN assemblies` query; record counts match a SQL
   `COUNT` with the same bounds; an assembly with NULL `decommissioned_at`
   picks up records up to the present.
2. Fake records tree in the scratchpad (local sample TDMS files copied to
   resolved paths + a few empty pupitre files) → `tar -tJf` lists the
   expected relative paths + both manifests; extracting into an empty dir
   then `md5sum -c MANIFEST_<magnet>.md5` → all `OK`; files deliberately
   left out show `status=missing` in the CSV.
3. Window boundary: an experiment timestamped one minute after
   `decommissioned_at` (UTC→Paris converted) is excluded.
4. Unknown magnet → clean error, non-zero exit.
5. `xz`-missing fallback (e.g. `PATH` without `xz`) still produces a valid
   `.tar.xz`, with a warning.

## Decisions (confirmed in conversation)

- Filter records by the magnet's window within each assembly; a NULL
  `decommissioned_at` means "until today".
- Hybrid/runlog sources skipped with a warning for now; follow-up plan to
  be written.
- Manifest with md5 checksums of archived files.

## Assumptions / open questions

- Two manifest files (`.md5` for verification, `.csv` for provenance) —
  could be reduced to one.
- Window bounds are inclusive.
- Records without a usable timestamp are kept (with a warning), not dropped.
