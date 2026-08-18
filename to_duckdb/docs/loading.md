# Loading data — magnets, assemblies, materials

This page covers the complete workflow for building a student DuckDB from the JSON exports in `../../hifimagnet-projects/magnetdb.json/`.

---

## JSON file naming conventions

```
magnetdb.json/
├── <MagnetName>.json            magnet assembly  e.g. M19061901.json, M10Bitters.json
├── <HxxxxNNNNNN>.json           helix part       e.g. H17030101.json
├── <RxxxxNNNNNN>.json           ring/lead part   e.g. R20061901.json
└── <Housing>_<Magnet>_<N>.json  assembly config  e.g. M9_M19061901_0.json
```

The suffix `_N` in assembly files is a **version counter**: each time the magnet configuration at a housing changes (magnet swap, recommissioning), a new file `_N+1` is created. Each file is an independent assembly entry with its own commissioning dates and list of pupitre records.

Available housings: **M7**, **M8**, **M9**, **M10**.

---

## Loading order

Dependencies flow upward — always load in this order:

```
db create  →  material JSONs (MA*)  →  part JSONs (H*, R*)  →  magnet JSONs  →  assembly JSONs
```

`magnetdb.py assembly add` handles the last three automatically: it resolves magnet JSONs from the same directory (or `--magnet-dir`) and the magnet JSONs embed part definitions. A single `assembly add` call is usually sufficient.

---

## Step 0 — Create the database

```bash
cd to_duckdb/
python magnetdb.py db create --db student.duckdb
```

Creates the file and initialises all tables in one step. Fails if the file already exists, preventing accidental overwrites.

```bash
# Delete an existing database (with confirmation prompt)
python magnetdb.py db delete --db student.duckdb

# Delete without prompt (useful in scripts)
python magnetdb.py db delete --db student.duckdb --yes
```

---

## Step 1 — Add materials (optional)

Materials can be imported independently of magnets, which is useful when you want to inspect or correct physical properties without re-importing a full magnet hierarchy.

```bash
JSON=../../hifimagnet-projects/magnetdb.json

python magnetdb.py material add $JSON/MA20072304.json --dry-run
python magnetdb.py material add $JSON/MA20072304.json --db student.duckdb

python magnetdb.py material view --db student.duckdb
python magnetdb.py material view MA20072304 --db student.duckdb
python magnetdb.py material delete MA20072304 --db student.duckdb
```

The operation is **idempotent**: adding the same material twice is safe.

See [schema.md — Material JSON format](schema.md#material-json-format) for the expected JSON structure.

---

## Step 2 — Add magnets

Load a magnet from a MagnetDB JSON export. The JSON embeds all part and material definitions.

```bash
JSON=../../hifimagnet-projects/magnetdb.json

# Preview without writing
python magnetdb.py magnet add $JSON/M25032101.json --dry-run

# Write to DB (creates DB file if it does not exist)
python magnetdb.py magnet add $JSON/M25032101.json --db student.duckdb

# If part JSONs live elsewhere
python magnetdb.py magnet add M25032101.json --input-dir $JSON \
    --part-dir /path/to/parts --db student.duckdb
```

The magnet type (`insert`, `bitters`, `hybrid`) is inferred automatically from the part types. The operation is **idempotent**.

### Inspect and manage magnets

```bash
python magnetdb.py magnet view --db student.duckdb
python magnetdb.py magnet view M25032101 --db student.duckdb
python magnetdb.py magnet delete M25032101 --db student.duckdb
```

---

## Step 3 — Add assemblies

Assemblies reference magnets by name. `assembly add` auto-resolves missing magnets from JSON files in the same directory (or `--magnet-dir`), inserts magnet links, and inserts the `records` list into the `experiments` table.

```bash
JSON=../../hifimagnet-projects/magnetdb.json

python magnetdb.py assembly add $JSON/M10_M19071101_13.json --dry-run
python magnetdb.py assembly add $JSON/M10_M19071101_13.json --db student.duckdb

# Using --input-dir
python magnetdb.py assembly add M10_M19071101_13.json \
    --input-dir $JSON --db student.duckdb
```

The operation is **idempotent**: running it twice with the same JSON is safe.

### Loading multiple assembly versions

Each `<Housing>_<Magnet>_<N>.json` file is an independent operational campaign. Load each version you want:

```bash
# All campaigns for M9 housing with M19061901 insert
for f in $JSON/M9_M19061901_*.json; do
    python magnetdb.py assembly add "$f" --db student.duckdb
done

# All known assemblies across all housings
for f in $JSON/M{7,8,9,10}_*_*.json; do
    python magnetdb.py assembly add "$f" --db student.duckdb
done
```

### Inspect and manage assemblies

```bash
python magnetdb.py assembly view --db student.duckdb
python magnetdb.py assembly view M10_M19071101_13 --db student.duckdb
python magnetdb.py assembly delete M10_M19071101_13 --db student.duckdb
```

### Update AssemblyMagnet fields

Patch positional or temporal fields on a specific magnet within an assembly without re-importing the full JSON:

```bash
python magnetdb.py assembly update-magnet M10_M19071101_13 M19071101 \
    --z-offset 12.5 --r-offset 0.0 --parallax 0.0

python magnetdb.py assembly update-magnet M10_M19071101_13 M19071101 \
    --commissioned-at "2025-11-12 00:00:00"

python magnetdb.py assembly update-magnet M10_M19071101_13 M19071101 \
    --metadata '{"current_max_A": 26000}'
```

Only the fields explicitly passed are updated; all others are left unchanged.

---

## Housing configs

Housing configs describe the physical magnet housing at each experimental station (M7, M8, M9, M10). They map coil-type names (`Insert`, `Bitter`) to current-group labels (`GR1`, `GR2`) and record the set of file formats available for each housing.

Housing configs are **created automatically** when you call `assembly add` — the config for the housing named in the assembly JSON is loaded from the `python_magnetrun` package if it is not already present in the DB.  You do not need to pre-load them manually.

### Inspect housing configs

```bash
# List all housings in the DB
python magnetdb.py housing view --db student.duckdb

# Show full detail for one housing
python magnetdb.py housing view M9 --db student.duckdb
```

**Example output — list all:**

```
Name         Formats
--------------------------------------------------
M9           pupitre, tdms
M10          pupitre, tdms
```

**Example output — single housing:**

```
Housing: M9
  formats        : pupitre, tdms
  coil_assignment:
    Insert → GR1
    Bitter → GR2
```

### Filter assemblies by housing

`assembly view` accepts `--housing` to show only assemblies in a given housing:

```bash
python magnetdb.py assembly view --housing M9 --db student.duckdb
```

---

## Viewing all objects at once

```bash
python magnetdb.py list --db student.duckdb
```

Lists all materials, magnets, assemblies, and housings in one call.

---

See [schema.md](schema.md) for the Assembly JSON format and full schema reference.
