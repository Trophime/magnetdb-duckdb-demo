# Cumulative statistics queries — `query_cumstats.py`

`query_cumstats.py` is a **read-only** tool that aggregates pre-computed statistics stored in the `op_*` and `exp_*` tables. No raw record files are ever re-read.

Two parallel families of subcommands are provided:

| Family | Source tables | Description |
|--------|--------------|-------------|
| `scalars`, `site-bins`, `magnet-bins`, `part-bins` | `op_run_scalars`, `op_site_bin_stats`, `op_part_bin_stats` | Cumulative stats from operational data files |
| `exp-scalars`, `exp-site-bins`, `exp-magnet-bins`, `exp-part-bins` | `exp_run_scalars`, `exp_site_bin_stats`, `exp_part_bin_stats` | Cumulative stats from experiment records |

Both families share identical aggregation logic, CLI flags, and output helpers.

---

## Prerequisites

The relevant compute step must have been run before querying:

- **Operational data** — `compute_op_stats.py` (see [statistics.md](statistics.md))
- **Experiment data** — `compute_exp_stats.py` (same approach, `exp_*` tables)
- **Hoop stress** — `magnetdb.py hoop-stress compute` (see [hoop-stress.md](hoop-stress.md))

---

## CLI reference

```
python query_cumstats.py <subcommand> [options]
```

### Global options

| Flag | Default | Description |
|------|---------|-------------|
| `--db` | `student.duckdb` | Path to DuckDB file |
| `--site` | — | Site name (FK into `sites`) |
| `--magnet` | — | Magnet name |
| `--part` | — | Part name |
| `--channels` | all | Comma-separated channel filter, e.g. `Ptot,tsb` |
| `--experiment` | all | Filter `exp-*` commands to a single experiment by name |
| `--plot` | off | Save PNG bar charts alongside tabular output |

### Subcommands — operational data

| Subcommand | Required flag | Source table | Description |
|------------|--------------|-------------|-------------|
| `scalars` | `--site` or `--magnet` | `op_run_scalars` | Total scalar quantities (energy, heat, duration) |
| `site-bins` | `--site` | `op_site_bin_stats` | Field-bin distributions at site level |
| `magnet-bins` | `--magnet` | `op_part_bin_stats` | Per-part field-bin distributions for a magnet |
| `part-bins` | `--part` | `op_part_bin_stats` | Field-bin distributions for a single part |

### Subcommands — experiment data

| Subcommand | Required flag | Source table | Description |
|------------|--------------|-------------|-------------|
| `exp-scalars` | `--site` or `--magnet` | `exp_run_scalars` | Total scalar quantities across experiments |
| `exp-site-bins` | `--site` | `exp_site_bin_stats` | Field-bin distributions at site level |
| `exp-magnet-bins` | `--magnet` | `exp_part_bin_stats` | Per-part field-bin distributions for a magnet |
| `exp-part-bins` | `--part` | `exp_part_bin_stats` | Field-bin distributions for a single part |

---

## Examples

### Operational data

```bash
DB=magnetdb.duckdb

# Scalar totals for a site (energy, heat, duration)
python query_cumstats.py --db $DB --site M9_M19061901 scalars

# Scalar totals aggregated over all runs of a magnet
python query_cumstats.py --db $DB --magnet M9Bitters scalars

# Field-bin distribution at site level — all channels, tabular
python query_cumstats.py --db $DB --site M9_M19061901 site-bins

# Selected channels with bar-chart PNG
python query_cumstats.py --db $DB --site M9_M19061901 site-bins \
    --channels Ptot,tsb --plot

# Per-part stats for all parts of a magnet
python query_cumstats.py --db $DB --magnet M9Bitters magnet-bins --plot

# Stats for a single part across all runs and sites
python query_cumstats.py --db $DB --part M9Bi part-bins \
    --channels Icoil,hoop_stress_proxy --plot
```

### Experiment data

```bash
# Scalar totals for a site from experiment records
python query_cumstats.py --db $DB --site M9_M19061901 exp-scalars

# Field-bin distribution at site level
python query_cumstats.py --db $DB --site M9_M19061901 exp-site-bins

# Restrict to a single named experiment
python query_cumstats.py --db $DB --site M9_M19061901 \
    --experiment myrun_2024 exp-site-bins

# Per-part field-bin stats for a magnet (with plot)
python query_cumstats.py --db $DB --magnet M9Bitters exp-magnet-bins --plot

# Stats for a single part across all experiments
python query_cumstats.py --db $DB --part M9Bi exp-part-bins \
    --channels Icoil,hoop_stress_proxy --plot

# Same part, restricted to one experiment
python query_cumstats.py --db $DB --part M9Bi \
    --experiment myrun_2024 exp-part-bins
```

---

## Output formats

### Scalar output (`scalars` / `exp-scalars`)

```
───────────────────────────────────────────────────────
  Scalar statistics — M9_M19061901
───────────────────────────────────────────────────────
  Total duration                    1234.567  h  (42 files)
  Field-on duration                  987.123  h  (42 files)
  Electrical energy                   12.345  MWh  (42 files)
  Heat extracted                       9.876  MWh  (42 files)
```

### Bin output (`site-bins`, `magnet-bins`, `part-bins` and `exp-*` variants)

```
──────────────────────────────────────────────────────────────────────────
  Ptot — site M9_M19061901
  Bin (T)          Hours         Mean        Std        Min        Max
──────────────────────────────────────────────────────────────────────────
  0.0–5.0          12.340      123.456     10.234     98.000    145.000
  5.0–10.0        234.560      456.789     23.456    300.000    600.000
  ...
```

### Plot output (`--plot`)

A `cumstats_<scope>_<channel>.png` file is written in the current directory for each channel. Site-level commands produce one figure per channel; part/magnet commands produce one figure per channel with one bar group per part.

---

## Python API

The query functions can be imported and called directly:

```python
import duckdb
from query_cumstats import (
    # Operational
    query_scalars,
    query_site_bins,
    query_magnet_bins,
    query_part_bins,
    # Experiment
    query_exp_scalars,
    query_exp_site_bins,
    query_exp_magnet_bins,
    query_exp_part_bins,
)

con = duckdb.connect("magnetdb.duckdb", read_only=True)

# All functions return a pandas DataFrame.
df_scalars   = query_scalars(con, site_name="M9_M19061901")
df_site      = query_site_bins(con, "M9_M19061901", channels=["Ptot", "tsb"])
df_magnet    = query_magnet_bins(con, "M9Bitters")
df_part      = query_part_bins(con, "M9Bi", channels=["Icoil"])

# Experiment variants — identical signatures, extra experiment_name kwarg
df_exp_site  = query_exp_site_bins(con, "M9_M19061901", channels=["Ptot"])
df_exp_part  = query_exp_part_bins(con, "M9Bi", experiment_name="myrun_2024")

con.close()
```

All functions accept `channels: list[str] | None` to restrict output. The `exp_*` variants additionally accept `experiment_name: str | None`.

---

## Aggregation reference

These expressions are applied in every bin query:

| Derived quantity | SQL expression |
|-----------------|----------------|
| Operating time (h) | `SUM(sum_dt) / 3600` |
| Time-weighted mean | `SUM(sum_x_dt) / SUM(sum_dt)` |
| Time-weighted std | `sqrt(SUM(sum_x2_dt)/SUM(sum_dt) − mean²)` |
| Cumulative integral | `SUM(sum_x_dt)` (energy, heat, …) |
| Peak value | `MAX(max_x)` |

The five primitive columns (`sum_dt`, `sum_x_dt`, `sum_x2_dt`, `min_x`, `max_x`) are **additive**: summing over any subset of files or experiments produces a valid cumulative result without re-reading raw data.

---

## Related documentation

| Topic | File |
|-------|------|
| Ingesting operational statistics | [statistics.md](statistics.md) |
| Hoop-stress compute and visualisation | [hoop-stress.md](hoop-stress.md) |
| Database schema reference | [schema.md](schema.md) |
| Populating TDMS / pupitre tables | [populate.md](populate.md) |
