# Deprecated scripts

All scripts listed here are superseded by the unified CLI `magnetdb.py` and are
kept only for backward compatibility or as importable modules.  They may be
removed in a future version.

---

## `add_magnet.py`

> **Superseded by:** `python magnetdb.py magnet add <json_file> [options]`

Add a magnet (with its parts and materials) to a student DuckDB database from a
MagnetDB magnet JSON export.

Parts may be embedded inline as dicts or referenced by name (plain string).
When a part entry is a plain string, the script looks for a file named
`<part_name>.json` in the same directory as the magnet JSON (or the directory
given by `--part-dir`) and loads the full part definition from there.

### JSON format (as exported from MagnetDB)

```json
{
    "name":                    "M25032101",
    "status":                  "in_operation",
    "design_office_reference": "",
    "description":             "14 Helices, Phi = 34 mm",
    "parts": [
        "H24110501",
        {
            "name":                    "H24110502",
            "description":             "H2",
            "status":                  "in_operation",
            "type":                    "helix",
            "design_office_reference": "HL-37-021-B",
            "geometry":                "/path/to/HL-37_H2.yaml",
            "material": { "...": "..." }
        }
    ]
}
```

`"H24110501"` is a name-only reference resolved from `<part_dir>/H24110501.json`.

### Usage

```
python add_magnet.py M25032101.json
python add_magnet.py M25032101.json --db path/to/student.duckdb
python add_magnet.py M25032101.json --dry-run
python add_magnet.py M25032101.json --part-dir /path/to/part/jsons
```

---

## `add_site.py`

> **Superseded by:** `python magnetdb.py site <subcommand> [options]`

Add a site to a student DuckDB database from a MagnetDB site JSON export.

Magnets referenced in the JSON that are not yet in the database are loaded
automatically from a same-named JSON file (e.g. `M19071101.json`) found in
the same directory as the site JSON (or the directory given by `--magnet-dir`).

### JSON format (as exported from MagnetDB)

```json
{
    "name":               "M10_M19071101_13",
    "description":        "",
    "status":             "in_operation",
    "housing":            "M10",
    "commissioned_at":    "2025-11-12 00:00:00",
    "decommissioned_at":  "None",
    "magnets": [
        "M19071101",
        {
            "name":               "M10Bitters",
            "z_offset":           0.0,
            "r_offset":           0.0,
            "parallax":           0.0,
            "commissioned_at":    "2025-11-12 00:00:00",
            "decommissioned_at":  null,
            "metadata":           {}
        }
    ],
    "records": [
        {"name": "M10_2025.11.13---09:14:21.txt", "description": "", "file": "..."}
    ]
}
```

### Usage

```
python add_site.py add M10_M19071101_13.json
python add_site.py add M10_M19071101_13.json --db path/to/student.duckdb --dry-run
python add_site.py add M10_M19071101_13.json --magnet-dir /path/to/magnet/jsons
python add_site.py update-magnet M10_M19071101_13 M19071101 --z-offset 12.5
```

---

## `find_site_tdms.py`

> **Superseded by:** `python magnetdb.py populate operationaldata`

Load a site by name, then find TDMS files in all known subdirectories whose
filename timestamp falls within the site's commissioned / decommissioned window.

Matched files are inserted into the `operationaldata` table in the DuckDB
database, and printed to stdout.

### Scanned directories and type labels

| Directory | Type |
|---|---|
| `/mnt/LNCMIG-Data/records/pbsurv/<housing>/Overview/` | `Overview` |
| `/mnt/LNCMIG-Data/records/pbsurv/<housing>/Fichiers_Archive/` | `Archive` |
| `/mnt/LNCMIG-Data/records/pbsurv/<housing>/Fichiers_Spike/` | `Spike` |
| `/mnt/LNCMIG-Data/records/pbsurv/<housing>/Fichiers_Default/` | `Default` |

### Timestamp formats (French local time, Europe/Paris)

- **Overview / Archive** — `YYDDMM-HHMM` (6+4 digits, French day-first, minute precision)
- **Spike** — `YYMMDD-HHMMSS` (6+6 digits, ISO date order, second precision), e.g. `M10_Spikes_250615-021640.tdms`
- **Default** — `YYMMDD-HHMMSS`, optional suffix after timestamp, e.g. `M10_Default_240718-124401_Courants50Hz.tdms`

The timezone of `commissioned_at` / `decommissioned_at` stored in DuckDB is
uncertain.  Default assumption is UTC; override with `--db-tz` if needed.

### Usage

```
python find_site_tdms.py M10_M19071101_13
python find_site_tdms.py M10_M19071101_13 --db-tz Europe/Paris
python find_site_tdms.py M10_M19071101_13 --dry-run
python find_site_tdms.py M10_M19071101_13 --type Archive Spike
python find_site_tdms.py M10_M19071101_13 --records-base /data/records
```

---

## `find_site_pupitre.py`

> **Superseded by:** `python magnetdb.py populate operationaldata --type Pupitre`
> or `python magnetdb.py populate experiments`

Load a site by name, then find pupitre TXT files whose filename timestamp
falls within the site's commissioned / decommissioned window.

Matched files are inserted into the `operationaldata` table (type = `Pupitre`)
in the DuckDB database, and printed to stdout.

### Scanned directory

```
/mnt/LNCMIG-Data/records/srv-data-install/<housing>/
```

### Filename format

`YYYY.MM.DD - HH:MM:SS.txt` (French local time, Europe/Paris)

The timezone of `commissioned_at` / `decommissioned_at` stored in DuckDB is
uncertain.  Default assumption is UTC; override with `--db-tz` if needed.

### Usage

```
python find_site_pupitre.py M10_M19071101_13
python find_site_pupitre.py M10_M19071101_13 --db-tz Europe/Paris
python find_site_pupitre.py M10_M19071101_13 --dry-run
python find_site_pupitre.py M10_M19071101_13 --records-base /data/records --srv-subdir srv-data-install
```

---

## `find_site_overview_records.py`

> **Superseded by:** `python magnetdb.py populate overview-records` (to process files)
> or `python magnetdb.py overview-records view` (to query)

Query all `overview_records` attached to a site given by its name.

Each row corresponds to one processed `OverviewRecord` (one overview TDMS file)
and carries the experiment metadata: start time, duration, housing, mode,
pupitre parameters (`teb`, `bp`), source-file counts, signature keys, and
synchronisation info.

### Usage

```
python find_site_overview_records.py M10_M19071101_13
python find_site_overview_records.py M10_M19071101_13 --db my.duckdb
python find_site_overview_records.py M10_M19071101_13 --json
python find_site_overview_records.py M10_M19071101_13 --signatures
```

---

## `seeds_to_duckdb.py`

> **Superseded by:**
> ```
> python magnetdb.py magnet add <magnet>.json
> python magnetdb.py site   add <site>.json
> ```

Build a student DuckDB database from MagnetDB seed files, **without** requiring
a running Django stack or PostgreSQL.

### How it works

The seed files (`seeds-Bitters.py`, `seed-M19061901.py`, …) call functions from
`python_magnetdb.seeds.crud` which normally write to Django ORM / PostgreSQL.

This script replaces that entire layer with lightweight stubs that capture
every `create_*` / `query_*` call and store the data in memory.  Once all seeds
are loaded the collected data is flushed to DuckDB via the shared crud helpers.

### `coil_index` assignment

Parts are ordered in the `parts` list passed to `create_magnet()`.  Only parts
of type `helix` or `bitter` receive a `coil_index` (1-based).  Parts of type
`ring` or `lead` get `NULL`.

### Usage

```
pip install duckdb
python seeds_to_duckdb.py [--output student_magnetdb.duckdb] [--seeds all|bitters|M19061901|...]
```

---

## Finding archived files — standalone script workflow

> **Superseded by:** `python magnetdb.py populate operationaldata` and `python magnetdb.py populate experiments`

Two helper scripts scan the storage server for raw data files that belong to a given site's operational window (between `commissioned_at` and `decommissioned_at`). Matched files are inserted into the `operationaldata` table, which mirrors `experiments` and adds a `type` column.

### `operationaldata` type values

| Type | Script | File format | Source directory |
|------|--------|-------------|-----------------|
| `Overview` | `find_site_tdms.py` | `.tdms`, `YYDDMM-HHMM` | `<records_base>/<pbsurv>/<housing>/Overview/` |
| `Archive` | `find_site_tdms.py` | `.tdms`, `YYDDMM-HHMM` | `<records_base>/<pbsurv>/<housing>/Fichiers_Archive/` |
| `Spike` | `find_site_tdms.py` | `.tdms`, `YYMMDD-HHMMSS` | `<records_base>/<pbsurv>/<housing>/Fichiers_Spike/` |
| `Default` | `find_site_tdms.py` | `.tdms`, `YYMMDD-HHMMSS` | `<records_base>/<pbsurv>/<housing>/Fichiers_Default/` |
| `Pupitre` | `find_site_pupitre.py` | `.txt`, `YYYY.MM.DD - HH:MM:SS` | `<records_base>/<srv_subdir>/<housing>/` |

All file timestamps are interpreted as French local time (`Europe/Paris`).

### Typical run for one site

```bash
SITE=M9_M19061901_0
DB=student.duckdb

# 1. Pupitre TXT files (primary source for compute_op_stats.py)
python find_site_pupitre.py $SITE --db $DB --dry-run   # preview counts
python find_site_pupitre.py $SITE --db $DB

# 2. TDMS files (Archive + Overview are most useful; add Spike/Default if needed)
python find_site_tdms.py $SITE --db $DB --type Archive Overview --dry-run
python find_site_tdms.py $SITE --db $DB --type Archive Overview

# 3. Verify
python -c "
import duckdb
con = duckdb.connect('$DB', read_only=True)
print(con.execute(\"SELECT type, COUNT(*) FROM operationaldata WHERE site_name='$SITE' GROUP BY type\").df())
"
```

### Batch run across all sites in the DB

```bash
DB=student.duckdb

python -c "
import duckdb
con = duckdb.connect('$DB', read_only=True)
for (s,) in con.execute('SELECT name FROM sites ORDER BY name').fetchall():
    print(s)
" | while read SITE; do
    python find_site_pupitre.py "$SITE" --db "$DB"
    python find_site_tdms.py    "$SITE" --db "$DB" --type Archive Overview
done
```

### Off-server / custom paths

```bash
python find_site_pupitre.py M9_M19061901_0 --db student.duckdb \
    --records-base /data/lncmi --srv-subdir srv-data-install

python find_site_tdms.py M9_M19061901_0 --db student.duckdb \
    --records-base /data/lncmi --pbsurv pbsurv
```

### Timezone note

The scripts compare file timestamps (always `Europe/Paris`) against the site's `commissioned_at` / `decommissioned_at` from the DB. If those DB timestamps were stored as UTC (the default assumption), use `--db-tz UTC`. If they were stored as French local time, pass `--db-tz Europe/Paris`.
