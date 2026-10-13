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
├── impact.py                    ← impact of updates on stored results (stale marking)
├── conftest.py                  ← pytest fixtures
├── docs/
│   ├── loading.md               ← adding magnets, assemblies, materials
│   ├── populate.md              ← populate subcommands
│   ├── statistics.md            ← operational statistics (compute + query)
│   ├── query_cumstats.md        ← query_cumstats.py full CLI + API reference
│   ├── hoop-stress.md           ← hoop-stress compute and visualisation
│   └── schema.md                ← database schema reference + JSON formats
├── tests/
│   ├── test_schema.py
│   ├── test_crud.py
│   ├── test_add_magnet.py
│   ├── test_add_assembly.py
│   ├── test_magnetdb.py
│   ├── test_material_db.py
│   ├── test_impact.py
│   └── test_housing_config_db.py
├── tutorials/                   ← standalone demo scripts
│   ├── README.md
│   ├── queries.py               ← ready-to-run DuckDB query examples
│   ├── statheures_demo.py       ← field-time histogram demo
│   ├── stress_map.py            ← shim → magnetdb.py hoop-stress
│   ├── student_statheures_note.md
│   └── README_student_stress_map.md
├── marimo/
│   ├── select_assembly.py       ← interactive Marimo assembly browser
│   └── select_assembly_note.md
└── deprecated/                  ← superseded standalone scripts
    └── DEPRECATED.md
```

---

## Requirements

```bash
cd to_duckdb/
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install .[test,notebook,cli]
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
| `check [--entity ...] [--name ...] [--fix]` | Validate DB contents (geometry_data coverage, magnet type consistency, file existence) | below |
| `db create` | Create DB and initialise schema | [loading.md](docs/loading.md) |
| `db delete [--yes]` | Delete DB file | [loading.md](docs/loading.md) |
| `db drop-table --table TABLE [TABLE ...] [--yes] [--dry-run]` | Drop one or more tables from the DB | [loading.md](docs/loading.md) |
| `material add/view/update/delete` | Manage materials; `update` corrects properties from JSON | [loading.md](docs/loading.md), [below](#tracking-the-impact-of-updates) |
| `part view/update/update-status` | View a part, refresh descriptive/geometry fields (including the material of a linked part) from JSON, or change lifecycle status | [loading.md](docs/loading.md), [below](#tracking-the-impact-of-updates) |
| `magnet add/view/update/delete` | Manage magnets; `add` refuses an existing magnet whose parts differ | [loading.md](docs/loading.md) |
| `magnet update-status/update-status-from-file` | Change a magnet's lifecycle status, or apply a JSON list of `{magnet, status, dead_parts, description, changed_at, attachments}` changes in file order (stops at the first rejected one) | [schema.md](docs/schema.md) |
| `assembly add/view/update/delete` | Manage assemblies + experiment records | [loading.md](docs/loading.md) |
| `assembly update-magnet` | Patch positional/temporal AssemblyMagnet fields | [loading.md](docs/loading.md) |
| `housing view` | List housing configs | [loading.md](docs/loading.md#housing-configs) |
| `experiments view` | List experiment records | [populate.md](docs/populate.md#experiments-view) |
| `operationaldata view` | List operationaldata records | [populate.md](docs/populate.md#operationaldata-view) |
| `overview-records view` | List overview_records | [populate.md](docs/populate.md#overview-records-view) |
| `populate operationaldata [--assembly ASSEMBLY\|--all]` | Register TDMS/pupitre files from filesystem | [populate.md](docs/populate.md) |
| `populate experiments [--assembly ASSEMBLY\|--all]` | Discover additional pupitre TXT files | [populate.md](docs/populate.md) |
| `populate overview-records [--assembly ASSEMBLY\|--all]` | Process Overview TDMS via python_magnetrun | [populate.md](docs/populate.md) |
| `populate overview-records-from-json` | Load overview_records from a summary JSON | [populate.md](docs/populate.md) |
| `hoop-stress compute` | Compute and persist hoop-stress bin stats + fatigue; recomputes stale experiments; one bin configuration per experiment | [hoop-stress.md](docs/hoop-stress.md), [below](#tracking-the-impact-of-updates) |
| `hoop-stress barchart` | Bar chart: stress at given currents vs Rpe | [hoop-stress.md](docs/hoop-stress.md) |
| `hoop-stress history` | Normalised stress vs time from pupitre file | [hoop-stress.md](docs/hoop-stress.md) |
| `hoop-stress stats` | Descriptive statistics of stress time series | [hoop-stress.md](docs/hoop-stress.md) |
| `hoop-stress fatigue` | Rainflow cycle counting | [hoop-stress.md](docs/hoop-stress.md) |
| `log view [--table ...] [--operation ...] [--record ...]` | Show the `operation_log` audit trail (inserts, updates with old → new values) | [below](#tracking-the-impact-of-updates) |

### View filters

| Command | Filter options |
|---|---|
| `experiments view` | `--assembly`, `--magnet`, `--part`, `--from`/`--to` |
| `operationaldata view` | `--assembly`, `--type`, `--magnet`, `--part`, `--from`/`--to` |
| `overview-records view` | `--assembly`, `--magnet`, `--part`, `--from`/`--to`, `--signatures` (extra output flag, not a filter) |
| `material view [name]` | positional `name`, `--nuance` |
| `magnet view [name]` | positional `name`, `--type`, `--status` |
| `assembly view [name]` | positional `name`, `--housing`, `--status` |
| `housing view [name]` | positional `name` only |

`--from`/`--to` accept `YYYY-MM-DD` or `YYYY-MM-DD HH:MM:SS`, filtering on the timestamp encoded in the record's filename. See [populate.md](docs/populate.md) and [loading.md](docs/loading.md) for details.

---

## Validating the database — `check`

`magnetdb.py check` scans the DB for data that is present but not usable, so
problems surface before they break `hoop-stress compute` or a query further
down the pipeline:

- **parts** — flags rows missing `geometry` and/or `geometry_data`. `--fix`
  can populate a part's `geometry_data` from its recorded `geometry` file
  path.
- **magnets** — flags rows missing `geometry_data`, a `type` that isn't a
  valid `MagnetType` (`insert`/`bitters`/`supras`), or a linked part whose
  `type` doesn't belong to that magnet type.
- **experiments** / **operationaldata** — flags rows whose `file` is unset or
  doesn't exist on disk.

```bash
# Check everything
python magnetdb.py check --db $DB

# Restrict to one entity, or one named object
python magnetdb.py check --db $DB --entity magnet
python magnetdb.py check --db $DB --entity magnet --name M19071101

# Load a part's geometry_data from its geometry file, where missing
python magnetdb.py check --db $DB --entity part --fix

# Reconstruct missing magnets.geometry_data from parts' geometry_data
# (requires every linked part to already have its own geometry_data)
python magnetdb.py check --db $DB --entity magnet --fix

# Fix everything in one pass — parts are fixed before magnets, so a magnet
# whose parts were only just repaired can be reconstructed in the same run
python magnetdb.py check --db $DB --fix
```

`check` exits non-zero if any problem remains unresolved, so it can gate a
setup script. `--fix` can populate `parts.geometry_data` from an
already-recorded `geometry` file path, and `magnets.geometry_data` from
parts that already have theirs; it never invents a missing `geometry` path
itself for parts, experiments, or operationaldata, and it refuses (with a
clear error) to "fix" a magnet whose `type` isn't a valid `MagnetType` —
that's a data-inconsistency bug to fix by hand, not something to paper over.

---

## Tracking the impact of updates

Stored hoop-stress results (`hoop_stress_bin_stats`, `hoop_stress_fatigue`,
`hoop_stress_fatigue_bins`) are computed from materials, part and magnet
geometry, and magnet positions. When an `update` command changes one of these
inputs, the results computed from it are **marked stale** — never deleted —
and `hoop-stress compute` recomputes them.

Every update writes only the fields whose value actually changes, and records
them in `operation_log` as `{"changes": {field: [old, new]}, "stale": {...}}`
(`geometry_data` is recorded as `"changed"`). Re-applying identical values
prints `(no change)` and logs nothing. The write, the log row and the stale
marks happen in one transaction.

| Command | Changes that mark results stale | Scope |
|---|---|---|
| `material update` | any property (not `description`) | every assembly containing a part made of that material |
| `part update` | `material_name`, `geometry_data` (compared on content, not on the `geometry` path) | every assembly containing a magnet that holds the part |
| `magnet update` | `geometry_data` | every assembly containing the magnet |
| `assembly update-magnet` | `z_offset`, `commissioned_at` (orders the magnets, hence the column → part mapping) | that assembly |
| `assembly update`, `*-status` | — (logged only) | — |

The scope is the whole assembly, all parts: the total field B couples every
coil, so a change on one part affects the stresses of the others.

```bash
# Preview: what would change, and what would become stale
python magnetdb.py material update MAT_COPPER.json --db $DB --dry-run

# Apply — prints the stale experiments and the command to recompute them
python magnetdb.py material update MAT_COPPER.json --db $DB
#   ~ material  MAT_COPPER  updated: electrical_conductivity
#   ! hoop-stress results now stale (electrical_conductivity changed): 1 assembly, 2 experiment(s)
#       hoop_stress_bin_stats: 2 row(s)
#       ...
#     recompute with: python magnetdb.py hoop-stress compute --assembly M9_A19061901_00

# Audit trail of updates
python magnetdb.py log view --operation update --db $DB

# Recompute: only stale (and never-processed) experiments are processed
python magnetdb.py hoop-stress compute --assembly M9_A19061901_00 --db $DB
```

Stale experiments can also be listed directly:
`SELECT * FROM hoop_stress_processed WHERE stale_since IS NOT NULL`
(`stale_reason` is the `operation_log.id` of the change).

**One bin configuration per experiment.** The stats tables carry no bin
configuration, so configurations must not mix: `hoop-stress compute` with
other `--bins` skips already-processed experiments with a warning, and
`--reprocess` deletes *all* hoop rows of each experiment before inserting the
new ones. Since this also drops the rows of magnet types not being computed,
reprocess with `--magnet-type all` (the default).

**Related safeguards.**

- `part update` can correct the material of a part already linked to a
  magnet: `parts.material_name` has no foreign key (DuckDB runs an `UPDATE`
  of a foreign-key column as delete + insert, which fails once the part is
  referenced), and the material's existence is checked in Python instead.
  Databases created before this change keep the foreign key until rebuilt.
- `magnet add` on an existing magnet whose parts (names or order) differ from
  the JSON is refused — it would otherwise silently link new parts and shift
  the coil → part mappings. Re-adding identical content is accepted.
- `assembly decommission` lists the experiments, operationaldata and
  overview_records dated after the new end date that are still assigned to
  the assembly (`populate` never reassigns files).

Known gaps and next steps (angles, magnet bores, updating the inputs that
have no `update` command yet, …) are listed in
[PLAN_update_impact_tracking.md](../PLAN_update_impact_tracking.md#follow-ups-not-in-this-plan-each-needs-its-own-plan-and-approval).

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

# 1. Load assemblies (magnets auto-resolved from the same JSON directory)
for f in $JSON/M9_A19061901_*.json $JSON/M10_A19071101_*.json; do
    python magnetdb.py assembly add "$f" --db $DB
done

# 2. Verify
python magnetdb.py list --db $DB
python magnetdb.py check --db $DB   # flags missing geometry_data, bad file paths, etc.

# 3. Populate operationaldata from the filesystem
python magnetdb.py populate operationaldata --all --db $DB \
    --records-base $RECORDS --type Archive Overview Pupitre
# or for a single assembly:
# python magnetdb.py populate operationaldata --assembly M9_A19061901_00 --db $DB \
#     --records-base $RECORDS --type Archive Overview Pupitre

# 4. Ingest per-file operational statistics (idempotent)
python -c "
import duckdb
con = duckdb.connect('$DB', read_only=True)
for (s,) in con.execute('SELECT name FROM assemblies ORDER BY name').fetchall():
    print(s)
" | while read ASSEMBLY; do
    python compute_op_stats.py --db $DB \
        --records $RECORDS/srv-data-install \
        --assembly "$ASSEMBLY" --type Pupitre
done

# 5. Ingest hoop-stress statistics (idempotent; also recomputes experiments
#    marked stale by an update — see "Tracking the impact of updates")
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
| Adding magnets, assemblies, materials | [docs/loading.md](docs/loading.md) |
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
| Blue   | Assembly tables (`parts`, `magnets`, `assemblies`, junction tables) |
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
