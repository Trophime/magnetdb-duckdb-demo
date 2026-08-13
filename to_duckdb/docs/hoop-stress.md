# Hoop-stress analysis — `magnetdb.py hoop-stress`

Per-part hoop-stress statistics are computed from pupitre time-series files and stored in three `hoop_stress_*` tables. The `hoop-stress` group of subcommands covers both the computation pipeline and the visualisation tools.

---

## Stress bins

Bins are specified as **edge values in MPa** — a comma-separated list of N values defining N-1 consecutive intervals:

```
--bins 0,100,200,300,400,500,600   →  [(0,100), (100,200), ..., (500,600)]
```

The default is `0,100,200,300,400,500,600` (6 bins spanning 0–600 MPa in 100 MPa steps).

The legacy pair format `0:100,100:200,...` is still accepted for backward compatibility.

### Bin config tracking

The bin configuration is stored in `hoop_stress_processed` as a canonical edges string (e.g. `"0.0,100.0,200.0,300.0,400.0,500.0,600.0"`). The primary key is `(experiment_id, bin_config)`, so re-running with different bins coexists safely with existing results — no data loss occurs. A warning is printed when an experiment has already been processed with a different bin configuration:

```
[WARN] [42] M10_261105-1530: previously processed with different bin(s):
       {'0.0,100.0,200.0,300.0,400.0,500.0,600.0'}. Use --reprocess to overwrite.
```

### Experiment status

After processing, `experiments.status` gets `"HOOP STRESS DONE"` appended — comma-joined with whatever's already there (e.g. `"STATS DONE"` from `exp-stats compute`) so both pipelines' completion stays visible. A `status` of `"pending"` or empty is replaced outright rather than appended to, since it carries no information. This is idempotent: reprocessing an experiment that already carries the token leaves it unchanged.

---

## Evaluation point (z0)

Both Helix and Bitter parts are internally divided into axial sections (turn-groups/plates) with their own current density, but hoop stress is reported **once per DB part**, not once per section. For each part, the section whose z-extent actually contains an observation point `z0` is selected — Bz and current density are both sampled there — instead of an arbitrary "middle" section by array index.

`z0` defaults to `0.0` per part (assumes magnets are centered on z=0) but is resolved **per magnet** from `site_magnets.z_offset` via `resolve_z0_by_type()`, so a magnet installed off-center within a site is evaluated at its own true axial position, not the site's. This is automatic — there is no `--z0` flag; update `site_magnets.z_offset` in the DB if a magnet is misaligned.

Bitter parts are additionally grouped from their physical plates (`BMagnets`) into one representative value per part via `mt.create_Bstack()`, so `B1_fast`, `B2_fast`, … correspond to DB parts, matching `H1_fast`, `H2_fast`, ….

---

## `hoop-stress compute`

Processes all experiment files for one or more sites and persists results in `hoop_stress_bin_stats` and `hoop_stress_fatigue`.

```bash
# One site (default bins)
python magnetdb.py hoop-stress compute M10_M19071101_13 --db student.duckdb

# All sites
python magnetdb.py hoop-stress compute --all --db student.duckdb

# Custom bin edges
python magnetdb.py hoop-stress compute M10_M19071101_13 \
    --bins 0,150,300,450,600 --db student.duckdb

# Re-process already-computed experiments
python magnetdb.py hoop-stress compute M10_M19071101_13 --reprocess

# Dry run — discover files without writing
python magnetdb.py hoop-stress compute M10_M19071101_13 --dry-run
```

| Option | Default | Description |
|--------|---------|-------------|
| `--bins` | `0,100,200,300,400,500,600` | Bin edges in MPa |
| `--magnet-type` | `all` | Restrict to `H` (helix), `B` (bitter), `S` (supra), or `all` |
| `--parquet-dir` | `<db dir>/hoop_parquet` | Directory for Parquet output files |
| `--geometries` | — | Override geometry YAML directory |
| `--reprocess` | — | Overwrite already-processed experiments |
| `--dry-run` | — | Discover files without writing |
| `--use-mrun` | — | Load files via `python_magnetrun.MagnetRun.load_mrun()` |
| `--quiet` | — | Suppress per-file output |

---

## `hoop-stress part-history`

Aggregates a part's hoop-stress bin-stats and fatigue proxy across every experiment (and site) it has contributed to, and persists a chronologically-sorted concatenation of its raw stress time series.

```bash
python magnetdb.py hoop-stress part-history H12082401 --db student.duckdb
```

Reads `hoop_stress_bin_stats`/`hoop_stress_fatigue` for the part (joined to `experiments` for the site/experiment list), and each contributing experiment's Parquet file — resolved via `hoop_stress_processed.parquet_path` — for the raw series; `t0`/`site_name` come from that file's own metadata (see `hoop-stress compute` above). Experiments whose Parquet predates the part-name column rename (no column named after the part) are skipped with a `[WARN]`.

Writes `<parquet_dir>/parts/<part_name>.parquet` (`timestamp`, `hoop_stress_MPa`, `experiment_id`, `site_name`), sorted by `timestamp`.

| Option | Default | Description |
|--------|---------|-------------|
| `--parquet-dir` | `<db dir>/hoop_parquet` | Directory Parquet files live in; output goes to `<parquet_dir>/parts/` |

---

## `hoop-stress barchart`

Bar chart of per-part hoop stress at specific nominal currents, compared against the material Rpe limit.

```bash
python magnetdb.py hoop-stress barchart M10_M19071101_13 --db student.duckdb

# Specify operating currents
python magnetdb.py hoop-stress barchart M10_M19071101_13 --i-h 26000 --i-b 0
```

| Option | Default | Description |
|--------|---------|-------------|
| `--i-h` | `20000` | Helix current [A] |
| `--i-b` | `0` | Bitter current [A] |
| `--i-s` | `0` | Supra current [A] |

---

## `hoop-stress history`

Normalised hoop-stress vs time plot from a pupitre measurement file.

```bash
python magnetdb.py hoop-stress history M10_M19071101_13 --db student.duckdb

# Explicit pupitre file
python magnetdb.py hoop-stress history M10_M19071101_13 \
    --pupitre /path/to/file.txt

# Use python_magnetrun loader (supports .tdms and path auto-resolution)
python magnetdb.py hoop-stress history M10_M19071101_13 --use-mrun
```

---

## `hoop-stress stats`

Descriptive statistics (mean, std, peak) of the hoop-stress time series.

```bash
python magnetdb.py hoop-stress stats M10_M19071101_13 --db student.duckdb

# Save to CSV
python magnetdb.py hoop-stress stats M10_M19071101_13 --output stats.csv
```

---

## `hoop-stress fatigue`

Rainflow cycle counting on the hoop-stress time series (fatigue assessment).

```bash
python magnetdb.py hoop-stress fatigue M10_M19071101_13 --db student.duckdb

# Change number of histogram bins
python magnetdb.py hoop-stress fatigue M10_M19071101_13 --bins 20
```

---

## Shared options (history / stats / fatigue)

| Option | Default | Description |
|--------|---------|-------------|
| `--db` | `student_magnetdb.duckdb` | DuckDB file |
| `--geometries` | `geometries/` | Directory of YAML geometry files |
| `--debug` | — | Enable debug output from `magnet_setup()` |
| `--pupitre FILE ...` | — | Explicit pupitre file(s); omit to use all experiments for the site |
| `--pupitre-datadir DIR` | from `python_magnetrun` | Root directory for pupitre TXT resolution |
| `--use-mrun` | — | Load via `python_magnetrun.MagnetRun.load_mrun()` |
| `--check` | — | Validate fast results row by row against `bmap.getHoop` |
| `--magnet-type` | `all` | Coil type(s): `H`, `B`, `S`, or `all` |

---

## Standalone pipeline (`compute_hoop_stats.py`)

The `hoop-stress compute` subcommand delegates to `compute_hoop_stats.py`, which can also be run directly:

```bash
python compute_hoop_stats.py --site M9_M19061901 --db student.duckdb
python compute_hoop_stats.py --site M9_M19061901 --bins 0,150,300,450,600 \
    --db student.duckdb --reprocess
```

---

## `hoop_stress_processed` — idempotency table

| Column | Type | Description |
|--------|------|-------------|
| `experiment_id` | INTEGER | FK → experiments(id) |
| `bin_config` | VARCHAR | Canonical edges string, e.g. `"0.0,100.0,..."` — part of composite PK |
| `processed_at` | TIMESTAMP | When this row was written |
| `magnet_type` | VARCHAR | `H`, `B`, `S`, or `all` |
| `parquet_path` | VARCHAR | Path to the Parquet time-series file (if saved) |

Primary key: `(experiment_id, bin_config)`.
