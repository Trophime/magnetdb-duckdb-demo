# MagnetDB DuckDB Tooling

Helper scripts for building and populating a standalone [DuckDB](https://duckdb.org/) database from MagnetDB data.

No Django, PostgreSQL, MinIO, or any other MagnetDB service needs to be running. The result is a single portable `magnetdb.duckdb` file that can be queried directly from Python or Jupyter notebooks.

These scripts are **admin tools** — they are not part of `python_magnetdb`. Only the generated `.duckdb` file (and the TSV record files) need to be distributed to end users.

---

## Directory layout

```
to_duckdb/
├── README.md                    ← this file
├── schema.py                    ← canonical DDL (single source of truth)
├── schema_diagram.py            ← text summary + graphical ER diagram
├── crud.py                      ← low-level CRUD helpers
├── populate.py                  ← filesystem scanning for TDMS / pupitre files
├── magnetdb.py                  ← unified CLI entry point (use this)
├── compute_op_stats.py          ← ingest per-file operational statistics
├── compute_hoop_stats.py        ← ingest per-file hoop-stress statistics
├── query_cumstats.py            ← query cumulative stats by site / magnet / part
├── stress_map.py                ← hoop-stress analysis library (geometry, plots)
├── conftest.py                  ← pytest fixtures
├── docs/
│   ├── loading.md               ← adding magnets, sites, materials
│   ├── populate.md              ← populate subcommands
│   ├── statistics.md            ← operational statistics (compute + query)
│   ├── query_cumstats.md        ← query_cumstats.py full CLI + API reference
│   ├── hoop-stress.md           ← hoop-stress compute and visualisation
│   └── schema.md                ← database schema reference + JSON formats
├── tests/
│   ├── test_schema.py
│   ├── test_crud.py
│   ├── test_add_magnet.py
│   ├── test_add_site.py
│   ├── test_magnetdb.py
│   ├── test_material_db.py
│   └── test_housing_config_db.py
├── tutorials/                   ← standalone demo scripts
│   ├── README.md
│   ├── queries.py               ← ready-to-run DuckDB query examples
│   ├── statheures_demo.py       ← field-time histogram demo
│   ├── stress_map.py            ← shim → magnetdb.py hoop-stress
│   ├── student_statheures_note.md
│   └── README_student_stress_map.md
├── marimo/
│   ├── select_site.py           ← interactive Marimo site browser
│   └── select_site_note.md
└── deprecated/                  ← superseded standalone scripts
    └── DEPRECATED.md
```

---

## Requirements

```bash
cd to_duckdb/
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

---

## Unified CLI — `magnetdb.py`

```
python magnetdb.py <entity> <action> [arguments] [--db PATH]
```

Default DB: `magnetdb.duckdb` in the current directory.

### Quick reference

| Command | Description | Detail |
|---------|-------------|--------|
| `list` | List all objects in the DB | — |
| `db create` | Create DB and initialise schema | [loading.md](docs/loading.md) |
| `db delete [--yes]` | Delete DB file | [loading.md](docs/loading.md) |
| `material add/view/delete` | Manage materials | [loading.md](docs/loading.md) |
| `magnet add/view/delete` | Manage magnets | [loading.md](docs/loading.md) |
| `site add/view/delete` | Manage sites + experiment records | [loading.md](docs/loading.md) |
| `site update-magnet` | Patch positional/temporal SiteMagnet fields | [loading.md](docs/loading.md) |
| `housing view` | List housing configs | [loading.md](docs/loading.md#housing-configs) |
| `experiments view` | List experiment records | [populate.md](docs/populate.md#experiments-view) |
| `operationaldata view` | List operationaldata records | [populate.md](docs/populate.md#operationaldata-view) |
| `overview-records view` | List overview_records | [populate.md](docs/populate.md#overview-records-view) |
| `populate operationaldata` | Register TDMS/pupitre files from filesystem | [populate.md](docs/populate.md) |
| `populate experiments` | Discover additional pupitre TXT files | [populate.md](docs/populate.md) |
| `populate overview-records` | Process Overview TDMS via python_magnetrun | [populate.md](docs/populate.md) |
| `populate overview-records-from-json` | Load overview_records from a summary JSON | [populate.md](docs/populate.md) |
| `hoop-stress compute` | Compute and persist hoop-stress bin stats + fatigue | [hoop-stress.md](docs/hoop-stress.md) |
| `hoop-stress barchart` | Bar chart: stress at given currents vs Rpe | [hoop-stress.md](docs/hoop-stress.md) |
| `hoop-stress history` | Normalised stress vs time from pupitre file | [hoop-stress.md](docs/hoop-stress.md) |
| `hoop-stress stats` | Descriptive statistics of stress time series | [hoop-stress.md](docs/hoop-stress.md) |
| `hoop-stress fatigue` | Rainflow cycle counting | [hoop-stress.md](docs/hoop-stress.md) |

---

## Typical full setup

```bash
cd to_duckdb/
DB=magnetdb.duckdb
JSON=/home/myuser/hifimagnet-projects/magnetdb.json
RECORDS=/mnt/LNCMIG-Data/records
```

> [!NOTE]
> The default variables `$DB`, `$JSON`, and `$RECORDS` need to be adjusted to point to your local JSON and record directories.

```bash
# 0. Create the database
python magnetdb.py db create --db $DB

# 1. Load sites (magnets auto-resolved from the same JSON directory)
for f in $JSON/M9_A19061901_*.json $JSON/M10_A19071101_*.json; do
    python magnetdb.py site add "$f" --db $DB
done

# 2. Verify
python magnetdb.py list --db $DB

# 3. Populate operationaldata from the filesystem
python magnetdb.py populate operationaldata --all --db $DB \
    --records-base $RECORDS --type Archive Overview Pupitre

# 4. Ingest per-file operational statistics (idempotent)
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

# 5. Ingest hoop-stress statistics (idempotent)
python magnetdb.py hoop-stress compute --all --db $DB

# 6. Query
python tutorials/queries.py
python tutorials/query_cumstats.py --db $DB --site M9_A19061901_00 scalars
python tutorials/query_cumstats.py --db $DB --site M9_A19061901_00 site-bins \
    --channels Ptot,tsb --plot
python magnetdb.py hoop-stress barchart M9_A19061901_00 --db $DB
python magnetdb.py hoop-stress fatigue  M9_A19061901_00 --db $DB

# 7. Distribute magnetdb.duckdb + raw record files
```

---

## Detailed documentation

| Topic | File |
|-------|------|
| Adding magnets, sites, materials | [docs/loading.md](docs/loading.md) |
| Populating TDMS / pupitre / overview tables | [docs/populate.md](docs/populate.md) |
| Operational statistics (compute + query) | [docs/statistics.md](docs/statistics.md) |
| Cumulative query CLI + Python API | [docs/query_cumstats.md](docs/query_cumstats.md) |
| Hoop-stress analysis | [docs/hoop-stress.md](docs/hoop-stress.md) |
| Database schema + JSON formats | [docs/schema.md](docs/schema.md) |
| Deprecated scripts migration guide | [deprecated/DEPRECATED.md](deprecated/DEPRECATED.md) |
| Tutorials | [tutorials/README.md](tutorials/README.md) |

---

## Viewing the database structure

`schema_diagram.py` introspects a live `.duckdb` file (or falls back to
`schema.py` if no file is found) and produces either a plain-text schema
summary or a graphical ER diagram (PNG / SVG / PDF).

```bash
# Text summary — all 21 tables with columns, types, and PK/FK markers
python schema_diagram.py --text

# Graphical ER diagram saved to schema_diagram.png (default)
python schema_diagram.py

# Custom DB file and output path
python schema_diagram.py --db /path/to/magnetdb.duckdb --output er.svg
```

The diagram colour-codes tables by role:

| Colour | Group |
|--------|-------|
| Green  | Reference tables (`materials`, `housing_config`) |
| Blue   | Assembly tables (`parts`, `magnets`, `sites`, junction tables) |
| Yellow | Data tables (`experiments`, `operationaldata`, `overview_records`) |
| Red    | Statistics tables (`*_processed`, `*_scalars`, `*_bin_stats`, `*_fatigue`) |

---

## Example queries

`tutorials/queries.py` contains ready-to-run examples covering:

1. Full site hierarchy (site → magnet → parts → materials)
2. `Icoil_N → part` mapping for a specific magnet
3. Experiment records for a site
4. Material comparison across all helices
5. Coil channel count per magnet
6. Parts shared across multiple magnets
7. All sites in which a magnet has been used
8. Sites and magnets in which a given part has been used

```bash
python tutorials/queries.py
```

When copying cells into Jupyter, paste the connection block (`DB_PATH` + `con = …`) first. `DB_PATH` falls back to `"magnetdb.duckdb"` (cwd-relative) when `__file__` is not defined in a notebook context.
