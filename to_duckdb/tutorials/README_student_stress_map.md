# Hoop-stress analysis (`magnetdb.py hoop-stress` / `stress_map.py`)

Standalone hoop-stress analysis for a magnet site, using only the student
DuckDB database and local YAML geometry files — **no Django, PostgreSQL, or
MagnetDB service required**.

The implementation lives in `stress_map.py` and is exposed through the unified
CLI via `magnetdb.py hoop-stress {barchart,history,stats,fatigue}`.
It replicates the full production chain from
`python_magnetdb/actions/compute_stress_map_chart.py` (and its helpers),
replacing only the Django/ORM data-access layer with DuckDB queries.

---

## Requirements

```
pip install duckdb pandas matplotlib rainflow   # rainflow only needed for fatigue subcommand
```

System packages (must be installed separately):

| Package | Provides |
|---------|----------|
| `python3-magnettools` | `magnettools.magnettools`, `magnettools.Bmap` |
| `python_magnetsetup` | `python_magnetsetup.ana`, `python_magnetsetup.config` |
| `python_magnetrun` | `python_magnetrun.magnetdata`, `python_magnetrun.runetl` |
| `python_magnetgeo` | `python_magnetgeo.MSite`, `python_magnetgeo.deserialize` (needed for `geometry` subcommands) |

---

## Expected data layout

```
student_data/
├── student_magnetdb.duckdb          # populated by seeds_to_duckdb.py / magnetdb.py
├── geometries/                      # YAML files from python_magnetsetup/data/geometries/
│   ├── HL-31.yaml
│   ├── HL-31_H1.yaml
│   ├── Ring-H1H2.yaml
│   └── ...
└── records/
    └── *.txt                        # pupitre time-series files
```

The DuckDB file must contain at least:
- `sites`, `magnets`, `magnet_parts`, `parts`, `materials` (including `MAT_ISOLANT`)
- `site_magnets` with `commissioned_at` / `decommissioned_at` fields
- `experiments` with `file` paths (for auto-discovery by `history` / `stats` / `fatigue`)

---

## Subcommands

```
python magnetdb.py hoop-stress {barchart,history,stats,fatigue} <site> [options]
# or equivalently:
python stress_map.py           {barchart,history,stats,fatigue} <site> [options]
```

> **Note:** `geometry` and `magnet-geometry` remain available directly via
> `stress_map.py` but are not yet wired into `magnetdb.py`.

### barchart

Bar chart of hoop stress per coil at a given current operating point, overlaid
with the `Rpe` yield-stress reference from the DB.

```bash
python magnetdb.py hoop-stress barchart M9 \
    --db student_data/student_magnetdb.duckdb \
    --geometries student_data/geometries \
    --i-h 20000 \
    [--i-b 0] [--i-s 0] \
    [--debug]
```

Outputs:
- A console table with `coil_index`, part name, `nuance`, `hoop_MPa`,
  `hoop_max_MPa` (at 31 kA), `rpe`, `ratio_rpe_max`
- A PNG bar chart saved as `stress_map_<magnet_name>.png`

---

### history

Vectorised hoop-stress time series from one or more pupitre files.
All values are normalised `[0, 1]` in the output plot.

```bash
python magnetdb.py hoop-stress history M9 \
    --db student_data/student_magnetdb.duckdb \
    --geometries student_data/geometries \
    [--pupitre FILE [FILE ...]] \
    [--use-mrun] \
    [--check]
```

- Omit `--pupitre` to process **all** experiment files registered for the site.
- `--use-mrun` loads files via `python_magnetrun.MagnetRun.load_mrun()`
  (supports `.tdms` and path auto-resolution).
- `--check` validates the fast vectorised result against `bmap.getHoop` row by
  row and prints the maximum absolute error per tube.

Outputs: `stress_history_<magnet_name>.png`

---

### stats

Descriptive statistics (min, max, mean, std, p50, p95, p99) of the hoop-stress
time series, per coil.

```bash
python magnetdb.py hoop-stress stats M9 \
    --db student_data/student_magnetdb.duckdb \
    --geometries student_data/geometries \
    [--pupitre FILE [FILE ...]] \
    [--output stats.csv]
```

Prints the table to stdout; saves to CSV with `--output`.

---

### fatigue

Rainflow cycle counting on the hoop-stress time series, one plot per coil.

```bash
python magnetdb.py hoop-stress fatigue M9 \
    --db student_data/student_magnetdb.duckdb \
    --geometries student_data/geometries \
    [--pupitre FILE [FILE ...]] \
    [--bins 15]
```

Requires `pip install rainflow`.
Outputs one PNG per coil: `fatigue_H<N>_fast_<magnet_name>.png`

---

## Common flags (all subcommands except geometry/magnet-geometry)

| Flag | Default | Description |
|------|---------|-------------|
| `--db PATH` | `student_magnetdb.duckdb` | Path to the DuckDB file |
| `--geometries DIR` | `geometries` | YAML geometry fallback directory |
| `--magnet-type {H,B,S}` | `H` | Part type for hoop stress (Helix/Bitter/Supra) |
| `--debug` | off | Enable verbose output from `magnet_setup()` |

---

## Note on Rpe units

In the DuckDB database `Rpe` is stored as-is from the seed files.
Some seed files store it in Pa (e.g. `481e6`), others in MPa (e.g. `481`).
Verify the unit for your specific dataset before interpreting `ratio_rpe` values.
The `barchart` subcommand prints the raw `rpe` column so you can check it.

---

## Architecture — how it replaces MagnetDB

```
MagnetDB (production)          stress_map.py
─────────────────────          ─────────────
Django ORM (Magnet model)  →   load_site_config_from_duckdb()
generate_magnet_directory()→   prepare_geometry_directory(site_name, config, ...)
                               (magnet_name derived from config["geom"])
appenv(...)                →   appenv(...)                (identical)
magnet_setup(env, cfg)     →   magnet_setup(env, cfg)     (identical)
compute_stress_map_chart() →   compute_hoop_at_currents() (identical logic)
                           →   validate_fast_from_pupitre() (vectorised)
```

The only difference is how magnet/part/material data are fetched:
from a live Django/PostgreSQL instance in production, and from a `.duckdb` file here.
