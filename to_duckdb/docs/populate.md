# Populating data tables — `magnetdb.py populate`

`magnetdb.py populate` fills the file-level tables from the filesystem or from pre-computed JSON summaries. Each subcommand accepts one or more assembly names **or** `--all` to process every assembly in the DB.

---

## `populate operationaldata`

Scans the storage server for TDMS and pupitre TXT files within each assembly's operational window and registers them in the `operationaldata` table. File IDs are assigned automatically via a database sequence.

```bash
# Dry run — preview file counts without writing
python magnetdb.py populate operationaldata --assembly M10_M19071101_13 --dry-run

# Scan all types for one assembly
python magnetdb.py populate operationaldata --assembly M10_M19071101_13 --db student.duckdb

# Restrict to specific types
python magnetdb.py populate operationaldata --assembly M10_M19071101_13 --type Archive Overview

# Process all assemblies in the DB
python magnetdb.py populate operationaldata --all --db student.duckdb

# DB timestamps stored as French local time instead of UTC
python magnetdb.py populate operationaldata --all --db-tz Europe/Paris
```

| Option | Default | Description |
|--------|---------|-------------|
| `--assembly ASSEMBLY` | — | Assembly name to process (repeat for multiple); use `--all` instead to process every assembly |
| `--type` | all | Restrict to one or more of `Overview Archive Spike Default Pupitre` |
| `--records-base` | `/mnt/LNCMIG-Data/records` | Root of the records tree |
| `--srv-subdir` | `srv-data-install` | Subdirectory of `records-base` for pupitre TXT files |
| `--pbsurv` | `pbsurv` | Subdirectory of `records-base` for TDMS files |
| `--db-tz` | `UTC` | Timezone of `commissioned_at` / `decommissioned_at` in the DB |
| `--dry-run` | — | Match files without writing to the DB |

---

## `populate experiments`

Scans the pupitre TXT directory and registers matching files in the `experiments` table. The operation is idempotent — rows already present are skipped.

> **Note:** `assembly add` already inserts the `records` field from the assembly JSON into `experiments`. Use `populate experiments` to discover additional pupitre files that were not listed in the original JSON export.

```bash
python magnetdb.py populate experiments --assembly M10_M19071101_13 --dry-run
python magnetdb.py populate experiments --assembly M10_M19071101_13 --db student.duckdb
python magnetdb.py populate experiments --all --db student.duckdb
python magnetdb.py populate experiments --all --db-tz Europe/Paris
```

| Option | Default | Description |
|--------|---------|-------------|
| `--assembly ASSEMBLY` | — | Assembly name to process (repeat for multiple); use `--all` instead to process every assembly |
| `--records-base` | `/mnt/LNCMIG-Data/records` | Root of the records tree |
| `--srv-subdir` | `srv-data-install` | Subdirectory of `records-base` for pupitre TXT files |
| `--db-tz` | `UTC` | Timezone of `commissioned_at` / `decommissioned_at` in the DB |
| `--dry-run` | — | Match files without writing to the DB |

---

## `populate overview-records`

Processes Overview TDMS files registered in `operationaldata` (type = `Overview`) using the `python_magnetrun` analysis pipeline and inserts the results into `overview_records`. Requires `python_magnetrun` to be installed.

Run `populate operationaldata --type Overview` first if `operationaldata` is empty.

```bash
python magnetdb.py populate overview-records --assembly M10_M19071101_13 --db student.duckdb
python magnetdb.py populate overview-records --all --db student.duckdb
python magnetdb.py populate overview-records --all --reprocess
python magnetdb.py populate overview-records --assembly M10_M19071101_13 --dry-run
```

| Option | Default | Description |
|--------|---------|-------------|
| `--assembly ASSEMBLY` | — | Assembly name to process (repeat for multiple); use `--all` instead to process every assembly |
| `--reprocess` | — | Overwrite existing `overview_records` rows (upsert instead of skip) |
| `--dry-run` | — | List files without processing or writing to the DB |

Data directories used by `python_magnetrun` are resolved from environment variables:

```bash
export MAGNETRUN_PUPITRE_DATA_DIR=/data/records/srv-data-install
python magnetdb.py populate overview-records --all --db student.duckdb
```

---

## `populate overview-records-from-json`

Loads `overview_records` from a pre-computed summary JSON file, without requiring `python_magnetrun` or the raw TDMS files. Use this when a summary has already been produced (e.g. by `python -m python_magnetrun.analysis.cli`) or when TDMS files are not locally accessible.

```bash
python magnetdb.py populate overview-records-from-json summary-2026.json \
    --assembly M10_M19071101_13 --db student.duckdb

python magnetdb.py populate overview-records-from-json summary-2026.json \
    --assembly M10_M19071101_13 --dry-run

python magnetdb.py populate overview-records-from-json summary-2026.json \
    --assembly M10_M19071101_13 --reprocess --db student.duckdb

# Records already carry assembly_name — no --assembly needed
python magnetdb.py populate overview-records-from-json summary-2026.json \
    --db student.duckdb
```

| Option | Default | Description |
|--------|---------|-------------|
| `--assembly ASSEMBLY` | — | Assembly name to assign to all loaded records; overrides any `assembly_name` in the JSON |
| `--reprocess` | — | Overwrite existing rows (upsert instead of skip) |
| `--dry-run` | — | Preview records without writing to the DB |
| `--db` | `student_magnetdb.duckdb` | Target DuckDB file |

### Accepted JSON format

The file must contain a top-level JSON array. Each element is a dict with the following fields (all optional except `filename`):

| Field | Type | Description |
|-------|------|-------------|
| `filename` | string | **Required.** Base filename without extension (primary key) |
| `housing` | string | Housing identifier (`M8`, `M9`, `M10`, …) |
| `mode` | string | Measurement mode |
| `t0` | string \| null | Start timestamp (`"YYYY-MM-DD HH:MM:SS"` or ISO 8601) |
| `duration` | float | Run duration in seconds |
| `teb` | float | Pupitre inlet water temperature (°C) |
| `bp` | float | Pupitre pressure (bar) |
| `sources_overview` | list\[str\] \| csv | Overview TDMS file path(s) |
| `sources_archive` | list\[str\] \| csv | Archive TDMS file path(s) |
| `sources_pupitre` | list\[str\] \| csv | Pupitre TXT file path(s) |
| `sources_default` | list\[str\] \| csv | Default incident file path(s) |
| `sources_trigger` | list\[str\] \| csv | Trigger incident file path(s) |
| `sources_spike` | list\[str\] \| csv | Spike incident file path(s) |
| `sources_hybrid_kHz` | list\[str\] \| csv | Hybrid kHz file path(s) |
| `sources_hybrid_rms` | list\[str\] \| csv | Hybrid RMS file path(s) |
| `sources_hybrid_trigger` | list\[str\] \| csv | Hybrid trigger file path(s) |
| `sources_hybrid_vprocess` | list\[str\] \| csv | Hybrid vprocess file path(s) |
| `sources_pigbrother_runlog` | list\[str\] \| csv | Pigbrother run-log file path(s) |
| `sources_pupitre_runlog` | list\[str\] \| csv | Pupitre Cirrus run-log file path(s) |
| `signatures` | dict | Per-channel signature statistics |
| `sync_info` | dict | Synchronisation metadata |
| `flow_params` | dict | Computed flow parameters |
| `metrics` | dict | Distance / correlation metrics |
| `debitbrut` | dict | Raw flow-rate data |
| `assembly_name` | string | Assembly FK (overridden by `--assembly` when supplied) |

Each `sources_*` field accepts either a Python list of paths or a comma-separated string. The short alias without the `sources_` prefix (e.g. `overview` instead of `sources_overview`) is also accepted.

**Minimal example:**

```json
[
  {
    "filename": "M10_261105-1530",
    "housing":  "M10",
    "t0":       "2026-11-05 15:30:00",
    "duration": 182.4,
    "teb":      14.2,
    "bp":       9.8,
    "sources_overview": ["/data/records/pbsurv/M10/Overview/M10_261105-1530.tdms"],
    "signatures": {"Courant_GR1": {"min": 0.0, "max": 26100.0, "mean": 25980.3}}
  }
]
```

---

## `populate overview-records-infer`

Fills in `housing`, `t0`, `assembly_name`, `duration`, `teb`, and `bp` for `overview_records` rows that were loaded bare from a manifest (typically via `populate overview-records-from-json`) and still have `assembly_name IS NULL`. Requires `python_magnetrun` to be installed.

`housing` and `t0` are parsed directly from the row's `filename`, which must follow python_magnetrun's `<housing>_Overview_<YYMMDD-HHMM>` convention (e.g. `M9_Overview_220127-1756`). `assembly_name` is the unique `assemblies` row of that `housing` whose `commissioned_at`/`decommissioned_at` window contains `t0`; if zero or more than one assembly matches, the row is skipped (left for manual resolution, e.g. via `overview-records-from-json --assembly` or `attach_assembly_to_overview_record`).

`duration` is read from the first entry in `sources_overview` via `python_magnetrun`'s `getDuration()`. `teb` and `bp` are the samples-weighted mean of the `teb`/`BP` columns across **every** existing file in `sources_pupitre` (files are concatenated before averaging, so longer runs contribute more samples — not averaged per-file).

The remaining fields (`mode`, `signatures`, `sync_info`, `flow_params`, `metrics`, `debitbrut`) are left untouched — they require the full `populate overview-records` processing pipeline.

```bash
# Preview which rows would be processed
python magnetdb.py populate overview-records-infer --dry-run --db student.duckdb

# Infer fields for all rows still missing an assembly_name
python magnetdb.py populate overview-records-infer --db student.duckdb

# Re-infer rows that already have an assembly_name too
python magnetdb.py populate overview-records-infer --reprocess --db student.duckdb

# DB timestamps stored as French local time instead of UTC
python magnetdb.py populate overview-records-infer --db-tz Europe/Paris --db student.duckdb
```

| Option | Default | Description |
|--------|---------|-------------|
| `--db-tz` | `UTC` | Timezone of `commissioned_at` / `decommissioned_at` in the DB |
| `--reprocess` | — | Re-infer rows that already have an `assembly_name` (default: only `NULL` ones) |
| `--dry-run` | — | List rows that would be processed without writing to the DB |

---

## Inspecting the data tables

### `experiments view`

Lists rows in the `experiments` table — pupitre files (and any other records) associated with each assembly. The table is populated by `assembly add` (from the `records` field of the assembly JSON) and by `populate experiments`.

```bash
# List all experiments across all assemblies
python magnetdb.py experiments view --db student.duckdb

# Filter by assembly
python magnetdb.py experiments view --assembly M10_M19071101_13 --db student.duckdb

# Filter by magnet (all assemblies/campaigns where that magnet was installed)
python magnetdb.py experiments view --magnet M19071101 --db student.duckdb

# Filter by part (all assemblies/campaigns where that part was installed)
python magnetdb.py experiments view --part H17030101 --db student.duckdb

# Filter by time range (timestamp extracted from pupitre filename)
python magnetdb.py experiments view --from 2026-03-01 --to 2026-03-31 --db student.duckdb
python magnetdb.py experiments view --from "2026-03-01 08:00:00" --db student.duckdb

# Combine filters freely
python magnetdb.py experiments view \
    --magnet M19071101 --from 2026-01-01 --to 2026-12-31 --db student.duckdb
```

| Option | Description |
|--------|-------------|
| `--assembly ASSEMBLY` | Filter by assembly name |
| `--magnet MAGNET` | Filter by magnet name (joins via `assembly_magnets`) |
| `--part PART` | Filter by part name (joins via `assembly_magnets → magnet_parts`) |
| `--from DATETIME` | Include records at or after this date/time (`YYYY-MM-DD` or `YYYY-MM-DD HH:MM:SS`) |
| `--to DATETIME` | Include records at or before this date/time (inclusive) |

> **Note:** For `experiments`, the timestamp is extracted from the pupitre filename (`YYYY.MM.DD - HH:MM:SS.txt`). Records with non-matching filenames are excluded when `--from` or `--to` is used.

**Example output:**

```
experiments  assembly=M10_M19071101_13  (3 row(s))

ID     Assembly                File                                    Status
-----------------------------------------------------------------------------------------------
1      M10_M19071101_13        /data/records/srv-data-install/...      
2      M10_M19071101_13        /data/records/srv-data-install/...      
3      M10_M19071101_13        /data/records/srv-data-install/...      
```

---

### `operationaldata view`

Lists rows in the `operationaldata` table — every TDMS and pupitre file registered for an assembly, with its type and status. Populated by `populate operationaldata`.

```bash
# List all records
python magnetdb.py operationaldata view --db student.duckdb

# Filter by assembly
python magnetdb.py operationaldata view --assembly M10_M19071101_13 --db student.duckdb

# Filter by file type (Overview, Archive, Spike, Default, Pupitre)
python magnetdb.py operationaldata view --type Pupitre --db student.duckdb

# Filter by magnet or part
python magnetdb.py operationaldata view --magnet M19071101 --db student.duckdb
python magnetdb.py operationaldata view --part H17030101 --db student.duckdb

# Filter by time range
python magnetdb.py operationaldata view --from 2026-03-01 --to 2026-03-31 --db student.duckdb

# Combine filters
python magnetdb.py operationaldata view \
    --assembly M10_M19071101_13 --type Overview --from 2026-01-01 --db student.duckdb
```

| Option | Description |
|--------|-------------|
| `--assembly ASSEMBLY` | Filter by assembly name |
| `--type TYPE` | Filter by file type: `Overview`, `Archive`, `Spike`, `Default`, `Pupitre` |
| `--magnet MAGNET` | Filter by magnet name (joins via `assembly_magnets`) |
| `--part PART` | Filter by part name (joins via `assembly_magnets → magnet_parts`) |
| `--from DATETIME` | Include records at or after this date/time |
| `--to DATETIME` | Include records at or before this date/time (inclusive) |

> **Note:** For `operationaldata`, the timestamp is extracted from the filename. Pupitre TXT files use `YYYY.MM.DD - HH:MM:SS`; TDMS Overview/Archive files use `YYMMDD-HHMM`; TDMS Spike/Default files use `YYMMDD-HHMMSS`. Records whose filenames don't match any known pattern are excluded when `--from`/`--to` is used.

**Example output (assembly + type filter):**

```
operationaldata  assembly=M10_M19071101_13  type=Overview  (2 row(s))

ID     Assembly                Type      File                                          Status
---------------------------------------------------------------------------------------------------------
42     M10_M19071101_13        Overview  /data/records/pbsurv/M10/Overview/...         
43     M10_M19071101_13        Overview  /data/records/pbsurv/M10/Overview/...         
```

---

### `overview-records view`

Lists rows in the `overview_records` table — processed summaries derived from Overview TDMS files. Populated by `populate overview-records` or `populate overview-records-from-json`.

```bash
# List all overview records
python magnetdb.py overview-records view --db student.duckdb

# Filter by assembly, magnet, or part
python magnetdb.py overview-records view --assembly M10_M19071101_13 --db student.duckdb
python magnetdb.py overview-records view --magnet M19071101 --db student.duckdb
python magnetdb.py overview-records view --part H17030101 --db student.duckdb

# Filter by time range (uses the t0 column directly)
python magnetdb.py overview-records view --from 2026-03-01 --to 2026-03-31 --db student.duckdb
python magnetdb.py overview-records view --from "2026-03-01 08:00:00" --db student.duckdb

# Combine filters
python magnetdb.py overview-records view \
    --magnet M19071101 --from 2026-01-01 --to 2026-12-31 --db student.duckdb

# Include per-record channel signatures and sync details
python magnetdb.py overview-records view \
    --assembly M10_M19071101_13 --signatures --db student.duckdb
```

| Option | Description |
|--------|-------------|
| `--assembly ASSEMBLY` | Filter by assembly name |
| `--magnet MAGNET` | Filter by magnet name (joins via `assembly_magnets`) |
| `--part PART` | Filter by part name (joins via `assembly_magnets → magnet_parts`) |
| `--from DATETIME` | Include records where `t0 >=` this date/time (`YYYY-MM-DD` or `YYYY-MM-DD HH:MM:SS`) |
| `--to DATETIME` | Include records where `t0 <=` this date/time (inclusive) |
| `--signatures` | Include per-channel min/max/mean and sync timeshift for each record |

**Example output:**

```
overview_records  assembly=M10_M19071101_13  (2 row(s))

Filename              t0                   Duration  Mode  teb    bp   n_src
----------------------------------------------------------------------------------------------
M10_261105-1530       2026-11-05 15:30:00  03:02     HP    14.2   9.8  3
M10_261106-0910       2026-11-06 09:10:00  01:24     HP    13.8   9.6  3
```

With `--signatures`, each row is followed by per-channel min/max/mean statistics and sync timeshift (if available):

```
M10_261105-1530       2026-11-05 15:30:00  03:02     HP    14.2   9.8  3
    Courant_GR1: min=0.00  max=26100.00  mean=25980.30
    sync timeshift: 0.012 s
```

**Columns:**

| Column | Description |
|--------|-------------|
| `Filename` | Base filename without extension (primary key) |
| `t0` | Run start timestamp |
| `Duration` | Run duration `HH:MM` or `MM:SS` |
| `Mode` | Measurement mode (e.g. `HP`, `HP+Bitter`) |
| `teb` | Inlet water temperature (°C) |
| `bp` | Water pressure (bar) |
| `n_src` | Total number of source files across all `sources_*` columns |
