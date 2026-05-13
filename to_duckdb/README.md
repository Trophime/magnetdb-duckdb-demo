# Student DuckDB Tooling

Helper scripts for building and populating a standalone [DuckDB](https://duckdb.org/) database from MagnetDB data, intended for M1 student project work.

No Django, PostgreSQL, MinIO, or any other MagnetDB service needs to be running. The result is a single portable `.duckdb` file that students can query directly from Python or Jupyter notebooks.

These scripts are **teacher/admin tools** — they are not part of `python_magnetdb` and do not need to be shipped to students. Only the generated `.duckdb` file (and the TSV record files) are distributed.

---

## Location in the repository

```
magnetdb/                        ← repo root
├── python_magnetdb/             ← Django application (not needed here)
│   └── seeds/
│       ├── seed-M19061901.py
│       ├── seeds-Bitters.py
│       └── ...
└── to_duckdb/                   ← this directory
    ├── README.md
    ├── schema.py
    ├── crud.py
    ├── seeds_to_duckdb.py       ← DEPRECATED (use magnetdb.py instead)
    ├── magnetdb.py              ← unified CLI (use this)
    ├── add_magnet.py            ← DEPRECATED (kept for compatibility)
    ├── add_site.py              ← DEPRECATED (kept for compatibility)
    ├── find_site_tdms.py        ← find TDMS archive files for a site
    ├── find_site_pupitre.py     ← find pupitre TXT files for a site
    ├── compute_op_stats.py      ← ingest per-file statistics into DuckDB
    ├── query_cumstats.py        ← query cumulative stats by site / magnet / part
    ├── student_statheures_demo.py ← standalone field-time histogram demo
    └── student_queries.py
```

---

## Files

| File | Purpose |
|------|---------|
| `schema.py` | Canonical DDL — single source of truth for all table definitions |
| `crud.py` | CRUD helpers for material, part, magnet, and site operations |
| `seeds_to_duckdb.py` | ~~Build the DB from seed files~~ — **deprecated**, use `magnetdb.py magnet add` / `magnetdb.py site add` |
| `magnetdb.py` | **Unified CLI** — single entry point for all add / view / delete / update operations |
| `add_magnet.py` | ~~Add a magnet from a JSON export~~ — **deprecated**, use `magnetdb.py magnet add` |
| `add_site.py` | ~~Manage sites~~ — **deprecated**, use `magnetdb.py site ...` |
| `find_site_tdms.py` | Find TDMS archive files for a site's operational window and register them in `operationaldata` |
| `find_site_pupitre.py` | Find pupitre TXT files for a site's operational window and register them in `operationaldata` |
| `compute_op_stats.py` | Ingest per-file operational statistics into the four `op_*` tables (idempotent) |
| `query_cumstats.py` | Query cumulative statistics by site, magnet, or part — no raw files needed |
| `student_statheures_demo.py` | Standalone field-time histogram demo (field-bin counts, no python_magnetrun required) |
| `student_queries.py` | Example queries to explore the DB — can be used as a notebook starting point |

---

## Requirements

### Virtualenv setup (recommended)

```bash
cd to_duckdb/
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

All scripts must be run from inside the activated virtualenv.

---

## Unified CLI — `magnetdb.py`

`magnetdb.py` is the single entry point for managing the DuckDB. It replaces the old `add_magnet.py` and `add_site.py` scripts.

```
python magnetdb.py <entity> <action> [arguments] [options]
```

### Quick reference

| Command | Description |
|---------|-------------|
| `magnet add <json> [--input-dir <dir>]` | Add a magnet (parts + materials) from a JSON export |
| `magnet view [name]` | List all magnets, or show detail for one |
| `magnet delete <name>` | Delete a magnet and its part links |
| `site add <json> [--input-dir <dir>]` | Add a site (magnet links) from a JSON export |
| `site view [name]` | List all sites, or show detail for one |
| `site delete <name>` | Delete a site, its magnet links, and its experiments |
| `site update-magnet <site> <magnet>` | Patch positional/temporal fields on a site–magnet link |

All subcommands accept `--db <path>` (default: `student_magnetdb.duckdb` in the current directory).

---

## Building a database from the magnetdb.json exports

This section covers the complete workflow for creating a student DuckDB from the JSON exports in `../../hifimagnet-projects/magnetdb.json/`.

### JSON file naming conventions

```
magnetdb.json/
├── <MagnetName>.json          magnet assembly  e.g. M19061901.json, M10Bitters.json
├── <HxxxxNNNNNN>.json         helix part       e.g. H17030101.json
├── <RxxxxNNNNNN>.json         ring/lead part   e.g. R20061901.json
└── <Housing>_<Magnet>_<N>.json  site config    e.g. M9_M19061901_0.json
```

The suffix `_N` in site files is a **version counter**: each time the magnet configuration at a housing changes (magnet swap, recommissioning), a new file `_N+1` is created. Each file is an independent site entry with its own commissioning dates and list of pupitre records.

Available housings: **M7**, **M8**, **M9**, **M10**.

### Loading order

Dependencies flow upward — always load in this order:

```
part JSONs (H*, R*)  →  magnet JSONs  →  site JSONs
```

`magnetdb.py site add` handles this automatically: it resolves magnet JSONs from the same directory (or `--magnet-dir`) and the magnet JSONs embed part definitions. A single `site add` call is usually sufficient.

### Step 1 — Add a magnet from a JSON export

Load a magnet directly from a MagnetDB magnet JSON export (produced by `python_magnetapi`). The JSON embeds all part and material definitions, so no prior data in the DB is needed.

```bash
cd to_duckdb/
JSON=../../hifimagnet-projects/magnetdb.json

# Preview without writing
python magnetdb.py magnet add $JSON/M25032101.json --dry-run

# Write to DB
python magnetdb.py magnet add $JSON/M25032101.json --db student.duckdb

# Parts live in the same directory — nothing extra needed
# If part JSONs were elsewhere, use --part-dir /path/to/parts/
python magnetdb.py magnet add M25032101.json --input-dir $JSON --db student.duckdb
```

The magnet type (`insert`, `bitters`, `hybrid`) is inferred automatically from the part types. The operation is **idempotent**: running it twice with the same JSON is safe — existing materials, parts, and magnets are skipped.

### Step 1c — Inspect and manage magnets

```bash
# List all magnets
python magnetdb.py magnet view

# Show detail for one magnet (parts, coil indices)
python magnetdb.py magnet view M25032101

# Delete a magnet and its part links
python magnetdb.py magnet delete M25032101
```

---

### Step 2 — Add sites

Sites reference magnets by name, so Step 1 (or Step 1b) must be completed first. Use `magnetdb.py site add` with a MagnetDB site JSON export to add a site with its magnet links and experiment records.

```bash
cd to_duckdb/
JSON=../../hifimagnet-projects/magnetdb.json

# Preview without writing
python magnetdb.py site add $JSON/M10_M19071101_13.json --dry-run

# Write to DB — magnets are auto-resolved from the same JSON directory
python magnetdb.py site add $JSON/M10_M19071101_13.json --db student.duckdb

# Equivalent using --input-dir (json_file becomes a bare name looked up inside it)
python magnetdb.py site add M10_M19071101_13.json --input-dir $JSON --db student.duckdb
```

Magnets referenced in the JSON that are not yet in the DB are loaded automatically from a same-named JSON file (e.g. `M19071101.json`) found in the same directory as the site JSON (or the directory given by `--magnet-dir`). The script fails with a clear message if any magnet file cannot be found.

The operation is **idempotent**: running it twice with the same JSON is safe — existing sites, magnet links, and experiment records are skipped.

#### Loading multiple site versions

Each `<Housing>_<Magnet>_<N>.json` file is an independent operational campaign at that housing. Load each version that you want to include:

```bash
JSON=../../hifimagnet-projects/magnetdb.json

# All campaigns for M9 housing with M19061901 insert
for f in $JSON/M9_M19061901_*.json; do
    python magnetdb.py site add "$f" --db student.duckdb
done

# All known sites across all housings
for f in $JSON/M{7,8,9,10}_*_*.json; do
    python magnetdb.py site add "$f" --db student.duckdb
done
```

Each `_N` site gets a distinct name (e.g. `M9_M19061901_0`) and its own commissioning window, magnet links, and experiment records. The `records` list in each site JSON is loaded into the `experiments` table — these are the pupitre TXT files listed in the MagnetDB export.

### Step 2b — Inspect and manage sites

```bash
# List all sites
python magnetdb.py site view

# Show detail for one site (magnets, experiment count)
python magnetdb.py site view M10_M19071101_13

# Delete a site (removes magnet links and experiments too)
python magnetdb.py site delete M10_M19071101_13
```

### Step 2c — Update SiteMagnet fields

After a site has been added, positional and temporal fields for a specific magnet within that site can be patched without re-importing the full JSON:

```bash
# Update positional offsets
python magnetdb.py site update-magnet M10_M19071101_13 M19071101 \
    --z-offset 12.5 --r-offset 0.0 --parallax 0.0

# Set commissioning / decommissioning dates
python magnetdb.py site update-magnet M10_M19071101_13 M19071101 \
    --commissioned-at "2025-11-12 00:00:00"

# Attach arbitrary metadata (JSON string)
python magnetdb.py site update-magnet M10_M19071101_13 M19071101 \
    --metadata '{"current_max_A": 26000}'

# Target a specific DB file
python magnetdb.py site update-magnet M10_M19071101_13 M19071101 \
    --z-offset 5.0 --db /path/to/student.duckdb
```

Only the fields explicitly passed are updated; all others are left unchanged.

---

## Database schema

```
materials            physical properties of conductor alloys (rpe in Pa)
parts                individual physical components (helix, ring, bitter, lead)
magnets              magnet assemblies (insert, bitters, hybrid, …)
magnet_parts         ordered parts within a magnet, with coil_index
housing_config       wiring layout for a magnet housing (GR1/GR2 coil assignment)
sites                operational configurations (housing, commissioning dates)
site_magnets         magnets active in a site — positional & temporal metadata
experiments          operational records (TSV files) attached to a site
operationaldata      discovered archive files (TDMS/TXT) linked to a site, with type tag
overview_records     processed overview file metadata (OverviewRecord, no raw data)

── Operational statistics ───────────────────────────────────────────────────
op_stats_processed   idempotency guard — which files have been ingested and with which bins
op_run_scalars       per-run scalar totals: energy (billing), heat extracted, duration
op_site_bin_stats    site-level field-bin distributions: Pmagnet, Ptot, tsb, teb, debitbrut
op_part_bin_stats    per-part field-bin distributions: Icoil, Ucoil, hoop_stress_proxy
```

### site_magnets columns

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| `site_name` | VARCHAR | — | FK → sites |
| `magnet_name` | VARCHAR | — | FK → magnets |
| `z_offset` | DOUBLE | 0.0 | Axial offset of the magnet in the site (m) |
| `r_offset` | DOUBLE | 0.0 | Radial offset of the magnet in the site (m) |
| `parallax` | DOUBLE | 0.0 | Parallax angle |
| `commissioned_at` | TIMESTAMP | NULL | When this magnet was commissioned in this site |
| `decommissioned_at` | TIMESTAMP | NULL | When removed (NULL = still active) |
| `metadata` | JSON | `{}` | Free-form key/value store |

### coil_index

The `magnet_parts.coil_index` column maps each helix or bitter part to its `Icoil_N` column in the operational TSV records:

- Assigned 1-based, in the order parts appear in the magnet definition
- Only `helix` and `bitter` parts receive a coil_index
- `ring` and `lead` parts get `NULL`

Example query to retrieve the mapping:

```python
import duckdb
con = duckdb.connect("student_magnetdb.duckdb", read_only=True)

con.execute("""
    SELECT 'Icoil' || mp.coil_index AS column,
           p.name AS part,
           p.type,
           mat.nuance,
           mat.rpe / 1e6 AS rpe_MPa
    FROM magnet_parts mp
    JOIN parts     p   ON p.name   = mp.part_name
    JOIN magnets   m   ON m.name   = mp.magnet_name
    LEFT JOIN materials mat ON mat.name = p.material_name
    WHERE m.name = 'M19061901'
      AND mp.coil_index IS NOT NULL
    ORDER BY mp.coil_index
""").df()
```

---

## Site JSON format

The JSON expected by `magnetdb.py site add` matches the format produced by `python_magnetapi`. The minimal required fields are:

```json
{
    "name":              "M10_M19071101_13",
    "status":            "in_operation",
    "housing":           "M10",
    "commissioned_at":   "2025-11-12 00:00:00",
    "decommissioned_at": "None",
    "magnets": [
        "M19071101",
        "M10Bitters"
    ],
    "records": [
        {
            "name":        "M10_2025.11.13---09:14:21.txt",
            "description": "",
            "file":        "M10_2025.11.13---09:14:21.txt"
        }
    ]
}
```

Each entry in `magnets` is either a **plain string** (name only — positional fields default to `0.0`, metadata to `{}`) or a **dict** with the full `SiteMagnet` fields:

```json
"magnets": [
    "M19071101",
    {
        "name":               "M10Bitters",
        "z_offset":           0.0,
        "r_offset":           0.0,
        "parallax":           0.0,
        "commissioned_at":    "2025-11-12 00:00:00",
        "decommissioned_at":  null,
        "metadata":           {"current_max_A": 26000}
    }
]
```

Notes:
- `magnets` contains magnet **names** — magnets must already be in the DB (or resolvable from a JSON file).
- `decommissioned_at` can be `"None"` or omitted for active sites.
- `records` can be an empty list `[]` if no experiment files are available yet.

---

## Finding archived files — `operationaldata` table

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

### `find_site_tdms.py`

Scans four TDMS subdirectories for a housing and registers matching files in `operationaldata`.

```bash
# Scan all types (dry run — no DB writes)
python find_site_tdms.py M10_M19071101_13 --dry-run

# Scan and register
python find_site_tdms.py M10_M19071101_13

# Restrict to specific types
python find_site_tdms.py M10_M19071101_13 --type Overview Archive

# DB timestamps stored as French local time instead of UTC
python find_site_tdms.py M10_M19071101_13 --db-tz Europe/Paris

# Override storage paths
python find_site_tdms.py M10_M19071101_13 \
    --records-base /data/records \
    --pbsurv pbsurv
```

| Option | Default | Description |
|--------|---------|-------------|
| `--db` | `student_magnetdb.duckdb` | DuckDB file |
| `--db-tz` | `UTC` | Timezone of `commissioned_at` / `decommissioned_at` in the DB |
| `--type` | all | Restrict scan to one or more of `Overview Archive Spike Default` |
| `--records-base` | `/mnt/LNCMIG-Data/records` | Root of the records tree |
| `--pbsurv` | `pbsurv` | Subdirectory of `records-base` that contains housing directories |
| `--dry-run` | — | Match files without writing to the DB |

### `find_site_pupitre.py`

Scans a single flat directory for pupitre TXT files and registers matching files in `operationaldata` with `type = 'Pupitre'`.

```bash
# Scan and register
python find_site_pupitre.py M10_M19071101_13

# Dry run
python find_site_pupitre.py M10_M19071101_13 --dry-run

# DB timestamps stored as French local time instead of UTC
python find_site_pupitre.py M10_M19071101_13 --db-tz Europe/Paris

# Override storage paths
python find_site_pupitre.py M10_M19071101_13 \
    --records-base /data/records \
    --srv-subdir srv-data-install
```

| Option | Default | Description |
|--------|---------|-------------|
| `--db` | `student_magnetdb.duckdb` | DuckDB file |
| `--db-tz` | `UTC` | Timezone of `commissioned_at` / `decommissioned_at` in the DB |
| `--records-base` | `/mnt/LNCMIG-Data/records` | Root of the records tree |
| `--srv-subdir` | `srv-data-install` | Subdirectory of `records-base` that contains housing directories |
| `--dry-run` | — | Match files without writing to the DB |

### Timezone note

The scripts compare file timestamps (always `Europe/Paris`) against the site's `commissioned_at` / `decommissioned_at` from the DB. If those DB timestamps were stored as UTC (the default assumption), use `--db-tz UTC`. If they were stored as French local time, pass `--db-tz Europe/Paris`. The scripts convert both sides to the same timezone before comparing, so DST transitions are handled correctly.

### Populating `operationaldata` — complete workflow

**`experiments` vs `operationaldata`** — two parallel tables, two sources:

| Table | Populated by | Contents |
|-------|-------------|----------|
| `experiments` | `magnetdb.py site add` | Pupitre TXT files listed in the site JSON `records` field |
| `operationaldata` | `find_site_pupitre.py` / `find_site_tdms.py` | All files found on disk within the site's operational window |

`experiments` is limited to what was exported by MagnetDB at a given point in time. `operationaldata` reflects the actual filesystem state and is the feed for `compute_op_stats.py`.

**Standard storage layout** (LNCMI servers, both scripts use these defaults):

```
/mnt/LNCMIG-Data/records/
├── srv-data-install/          ← pupitre TXT files (find_site_pupitre.py)
│   ├── M9/
│   │   ├── 2025.12.02 - 14:30:46.txt
│   │   └── ...
│   └── M10/
│       └── ...
└── pbsurv/                    ← TDMS files (find_site_tdms.py)
    ├── M9/
    │   ├── Overview/          → type = Overview
    │   ├── Fichiers_Archive/  → type = Archive
    │   ├── Fichiers_Spike/    → type = Spike
    │   └── Fichiers_Default/  → type = Default
    └── M10/
        └── ...
```

**Typical run for one site** (adjust `--db-tz` if commissioning dates were stored as local time):

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

**Batch run across all sites in the DB:**

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

**Off-server / custom paths:**

```bash
# Data is on a different mount or local copy
python find_site_pupitre.py M9_M19061901_0 --db student.duckdb \
    --records-base /data/lncmi --srv-subdir srv-data-install

python find_site_tdms.py M9_M19061901_0 --db student.duckdb \
    --records-base /data/lncmi --pbsurv pbsurv
```

---

## Operational statistics

Rather than loading all raw record files on every analysis, statistics are computed once per file and stored in four `op_*` tables. Cumulative results for any scope (site, magnet, part, date range) are then obtained by pure SQL aggregation — no raw files are re-read.

### Design

Each `op_site_bin_stats` / `op_part_bin_stats` row stores five aggregation primitives per *(file, field bin, channel)*:

| Column | Use |
|--------|-----|
| `n_samples` | row count |
| `sum_dt` | total time in bin (s) — directly gives operating hours |
| `sum_x_dt` | `Σ(X·dt)` — divide by `sum_dt` for time-weighted mean |
| `sum_x2_dt` | `Σ(X²·dt)` — combined with above gives time-weighted std; also fatigue input (e.g. `Σ(I²·dt)`) |
| `min_x` / `max_x` | extremes — take `MIN`/`MAX` across files |

These are **additive**: summing over any subset of files gives the cumulative result without re-reading raw data.

### Step 3 — Ingest statistics (`compute_op_stats.py`)

Run after the `operationaldata` table has been populated by `find_site_tdms.py` or `find_site_pupitre.py`.

```bash
# Process all operationaldata files for a site
python compute_op_stats.py --db student.duckdb --records /path/to/records \
    --site M9_M19061901

# Restrict to a specific type (e.g. pupitre TXT files only)
python compute_op_stats.py --db student.duckdb --records /path/to/records \
    --site M9_M19061901 --type Pupitre

# Custom field bins (low:high pairs, comma-separated, in Tesla)
python compute_op_stats.py --db student.duckdb --records /path/to/records \
    --site M9_M19061901 --bins "0:0.1,0.1:5,5:10,10:20,20:30,30:50,50:100"

# Re-compute already-processed files (e.g. after changing bins)
python compute_op_stats.py --db student.duckdb --records /path/to/records \
    --site M9_M19061901 --reprocess
```

| Option | Default | Description |
|--------|---------|-------------|
| `--db` | `student.duckdb` | DuckDB file |
| `--records` | `records/` | Directory containing the raw record files |
| `--site` | — | Site name (FK into `sites`) |
| `--type` | all | Filter `operationaldata` by type (`Pupitre`, `Archive`, …) |
| `--bins` | 7-bin set (0–100 T) | Field bins as `low1:high1,low2:high2,...` |
| `--channels` | `Pmagnet,Ptot,tsb,teb,debitbrut` | Site-level channels for `op_site_bin_stats` |
| `--flow-to-m3s` | `1/3600` | Unit conversion for `debitbrut` → m³/s (default assumes m³/h) |
| `--reprocess` | off | Overwrite already-processed files |
| `--quiet` | off | Suppress per-file progress output |

**Computed quantities**

*Scalars (`op_run_scalars`)* — one value per run, no field binning:

| Channel | Formula | Use |
|---------|---------|-----|
| `energy_j` | `Σ(Ptot · dt)` | Electricity billing |
| `heat_extracted_j` | `Σ((tsb−teb) · Q_m³s · ρ·cₚ · dt)` | Fatal heat estimate |
| `duration_s` | `Σ(dt)` | Total run duration |
| `duration_field_on_s` | `Σ(dt)` where `Field > 0.1 T` | Magnet-on time |

*Site-level bins (`op_site_bin_stats`)* — one row per (file, bin, channel):
`Pmagnet`, `Ptot`, `tsb`, `teb`, `debitbrut` (configurable via `--channels`).

*Per-part bins (`op_part_bin_stats`)* — one row per (file, part, bin, channel):
`Icoil`, `Ucoil`, `hoop_stress_proxy` (= I², proportional to σ_θ).
Only rows where `|Icoil| > 0.1 A` are included so idle periods do not dilute the distributions.

### Step 4 — Query cumulative statistics (`query_cumstats.py`)

All queries are read-only and require only the pre-computed `op_*` tables.

```bash
# Scalar totals for a site (energy, heat, duration)
python query_cumstats.py --db student.duckdb --site M9_M19061901 scalars

# Field-bin distributions at site level (all channels)
python query_cumstats.py --db student.duckdb --site M9_M19061901 site-bins

# Field-bin distributions at site level (selected channels, with plots)
python query_cumstats.py --db student.duckdb --site M9_M19061901 site-bins \
    --channels Ptot,tsb --plot

# Per-part stats for all parts of a magnet
python query_cumstats.py --db student.duckdb --magnet M9Bitters magnet-bins --plot

# Stats for a single part across all runs and sites
python query_cumstats.py --db student.duckdb --part M9Bi part-bins \
    --channels Icoil,hoop_stress_proxy --plot
```

| Subcommand | Required flag | Description |
|------------|--------------|-------------|
| `scalars` | `--site` or `--magnet` | Totals from `op_run_scalars` |
| `site-bins` | `--site` | Field-bin table from `op_site_bin_stats` |
| `magnet-bins` | `--magnet` | Per-part field-bin table from `op_part_bin_stats` |
| `part-bins` | `--part` | Field-bin table for one part from `op_part_bin_stats` |

Add `--channels ch1,ch2` to any subcommand to restrict the channel output.
Add `--plot` to save PNG bar charts alongside the tabular output.

### Aggregation reference

| Derived quantity | SQL expression |
|-----------------|----------------|
| Operating time (h) | `SUM(sum_dt) / 3600` |
| Time-weighted mean | `SUM(sum_x_dt) / SUM(sum_dt)` |
| Time-weighted std | `sqrt(SUM(sum_x2_dt)/SUM(sum_dt) − mean²)` |
| Cumulative integral | `SUM(sum_x_dt)` (energy, heat, …) |
| Peak value ever | `MAX(max_x)` |
| Fatigue proxy | `SUM(sum_x2_dt)` where channel = `hoop_stress_proxy` gives `Σ(I²·dt)` |

---

## Example queries

`student_queries.py` contains ready-to-run examples covering:

1. Full site hierarchy (site → magnet → parts → materials)
2. `Icoil_N → part` mapping for a specific magnet
3. Experiment records for a site
4. Material comparison across all helices
5. Coil channel count per magnet
6. Parts shared across multiple magnets (reused helices/rings)

Run it directly or copy cells into a Jupyter notebook:

```bash
python student_queries.py
```

---

## Typical full setup from magnetdb.json exports

```bash
cd to_duckdb/
DB=student.duckdb
JSON=../../hifimagnet-projects/magnetdb.json
RECORDS=/mnt/LNCMIG-Data/records

# ── 1. Load sites (magnets auto-resolved from the same JSON directory) ───────
# Preview first, then load. Each _N suffix is an independent campaign.

for f in $JSON/M9_M19061901_*.json $JSON/M10_M19071101_*.json; do
    python magnetdb.py site add "$f" --db $DB --dry-run
done

for f in $JSON/M9_M19061901_*.json $JSON/M10_M19071101_*.json; do
    python magnetdb.py site add "$f" --db $DB
done

# ── 2. Verify magnets and sites ──────────────────────────────────────────────
python magnetdb.py magnet view --db $DB
python magnetdb.py site view   --db $DB

# ── 3. Populate operationaldata from the filesystem ──────────────────────────
# Run for every site name now in the DB.

python -c "
import duckdb
con = duckdb.connect('$DB', read_only=True)
for (s,) in con.execute('SELECT name FROM sites ORDER BY name').fetchall():
    print(s)
" | while read SITE; do
    # Pupitre TXT (primary source for compute_op_stats.py)
    python find_site_pupitre.py "$SITE" --db $DB \
        --records-base $RECORDS --srv-subdir srv-data-install

    # TDMS Archive + Overview
    python find_site_tdms.py "$SITE" --db $DB \
        --records-base $RECORDS --type Archive Overview
done

# ── 4. Ingest per-file statistics (idempotent — safe to re-run) ──────────────
python -c "
import duckdb
con = duckdb.connect('$DB', read_only=True)
for (s,) in con.execute('SELECT name FROM sites ORDER BY name').fetchall():
    print(s)
" | while read SITE; do
    python compute_op_stats.py --db $DB \
        --records $RECORDS/srv-data-install \
        --site "$SITE" --type Pupitre
done

# ── 5. Query ──────────────────────────────────────────────────────────────────
python student_queries.py
python query_cumstats.py --db $DB --site M9_M19061901_0 scalars
python query_cumstats.py --db $DB --site M9_M19061901_0 site-bins --channels Ptot,tsb --plot

# ── 6. Ship student.duckdb + raw record files to students ────────────────────
```

---

## Deprecated scripts

`add_magnet.py`, `add_site.py`, and `seeds_to_duckdb.py` are kept for reference only and will be removed in a future version. Migrate to the equivalent `magnetdb.py` commands:

| Old command | New command |
|-------------|-------------|
| `python seeds_to_duckdb.py --repo .. --seeds ...` | `python magnetdb.py magnet add <json>` + `python magnetdb.py site add <json>` |
| `python add_magnet.py <json>` | `python magnetdb.py magnet add <json>` |
| `python add_site.py add <json>` | `python magnetdb.py site add <json>` |
| `python add_site.py update-magnet <s> <m> ...` | `python magnetdb.py site update-magnet <s> <m> ...` |
