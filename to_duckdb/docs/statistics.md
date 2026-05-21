# Statistics pipeline

Rather than loading all raw record files on every analysis, statistics are computed once per file and stored in pre-aggregated tables. Cumulative results for any scope (site, magnet, part, date range) are then obtained by pure SQL aggregation — no raw files are re-read.

Two parallel pipelines exist:

| Pipeline | Source table | Stats tables | Script |
|----------|-------------|--------------|--------|
| Operational | `operationaldata` | `op_run_scalars`, `op_site_bin_stats`, `op_part_bin_stats`, `op_stats_processed` | `compute_op_stats.py` |
| Experiment | `experiments` | `exp_run_scalars`, `exp_site_bin_stats`, `exp_part_bin_stats`, `exp_stats_processed` | `compute_exp_stats.py` |

Both pipelines produce identical column structures and the same aggregation primitives.

---

## Design

Each `op_site_bin_stats` / `op_part_bin_stats` row stores five aggregation primitives per *(file, field bin, channel)*:

| Column | Use |
|--------|-----|
| `n_samples` | row count |
| `sum_dt` | total time in bin (s) — directly gives operating hours |
| `sum_x_dt` | `Σ(X·dt)` — divide by `sum_dt` for time-weighted mean |
| `sum_x2_dt` | `Σ(X²·dt)` — combined with above gives time-weighted std; also fatigue input (e.g. `Σ(I²·dt)`) |
| `min_x` / `max_x` | extremes — take `MIN`/`MAX` across files |

These are **additive**: summing over any subset of files gives the cumulative result without re-reading raw data.

---

## Ingesting statistics — `compute_op_stats.py`

Run after the `operationaldata` table has been populated (see [populate.md](populate.md)).

```bash
# Process all operationaldata files for a site
python compute_op_stats.py --db magnetdb.duckdb --records-base /path/to/records \
    --site M9_M19061901

# Pupitre TXT files only
python compute_op_stats.py --db magnetdb.duckdb --records-base /path/to/records \
    --site M9_M19061901 --type Pupitre

# Custom field bins as low:high pairs, comma-separated
python compute_op_stats.py --db magnetdb.duckdb --records-base /path/to/records \
    --site M9_M19061901 --bins "0:0.1,0.1:5,5:10,10:15,15:20,25:30,30:35,35:40,40:45"

# Re-compute already-processed files (e.g. after changing bins)
python compute_op_stats.py --db magnetdb.duckdb --records-base /path/to/records \
    --site M9_M19061901 --reprocess
```

| Option | Default | Description |
|--------|---------|-------------|
| `--db` | `magnetdb.duckdb` | DuckDB file |
| `--records-base` | `records/` | Directory containing the raw record files |
| `--site` | — | Site name (FK into `sites`) |
| `--type` | all | Filter `operationaldata` by type (`Pupitre`, `Archive`, …) |
| `--bins` | 10-bin set (0–45 T) | Field bins as `lo:hi,lo:hi,...` pairs in Tesla |
| `--channels` | `Pmagnet,Ptot,tsb,teb,debitbrut` | Site-level channels for `op_site_bin_stats` |
| `--flow-to-m3s` | `1/3600` | Unit conversion for `debitbrut` → m³/s (default assumes m³/h) |
| `--reprocess` | off | Overwrite already-processed files |
| `--quiet` | off | Suppress per-file progress output |

---

## Ingesting experiment statistics — `compute_exp_stats.py`

Run after the `experiments` table has been populated (`magnetdb.py populate experiments`, see [populate.md](populate.md)).

`experiments.file` stores only the filename (e.g. `2025.04.30 - 13:06:03.txt`). The full path is reconstructed as `records-base / srv-subdir / housing / filename`, where `housing` is read from `sites.housing` for the experiment's site.

```bash
# Process all experiment files for a site (defaults match the standard filesystem layout)
python compute_exp_stats.py --db magnetdb.duckdb --site M10_A250429_00

# Override the root if your records are elsewhere
python compute_exp_stats.py --db magnetdb.duckdb --site M10_A250429_00 \
    --records-base /mnt/LNCMIG-Data/records --srv-subdir srv-data-install

# Custom field bins
python compute_exp_stats.py --db magnetdb.duckdb --site M10_A250429_00 \
    --bins "0:0.1,0.1:5,5:10,10:15,15:20,20:25,25:30,30:35,35:40,40:45"

# Re-compute already-processed experiments
python compute_exp_stats.py --db magnetdb.duckdb --site M10_A250429_00 --reprocess
```

| Option | Default | Description |
|--------|---------|-------------|
| `--db` | `magnetdb.duckdb` | DuckDB file |
| `--site` | — | Site name (FK into `sites`) |
| `--records-base` | `/mnt/LNCMIG-Data/records` | Root directory for record files |
| `--srv-subdir` | `srv-data-install` | Subdirectory under `records-base` containing pupitre TXT files |
| `--bins` | 10-bin set (0–45 T) | Field bins as `lo:hi,lo:hi,...` pairs in Tesla |
| `--channels` | `Pmagnet,Ptot,tsb,teb,debitbrut` | Site-level channels for `exp_site_bin_stats` |
| `--flow-to-m3s` | `1/3600` | Unit conversion for `debitbrut` → m³/s (default assumes m³/h) |
| `--reprocess` | off | Overwrite already-processed experiments |
| `--quiet` | off | Suppress per-file progress output |

### Computed quantities (both pipelines)

*Scalars (`op_run_scalars` / `exp_run_scalars`)* — one value per run, no field binning:

| Channel | Formula | Use |
|---------|---------|-----|
| `energy_j` | `Σ(Ptot · dt)` | Electricity billing |
| `heat_extracted_j` | `Σ((tsb−teb) · Q_m³s · ρ·cₚ · dt)` | Heat estimate |
| `duration_s` | `Σ(dt)` | Total run duration |
| `duration_field_on_s` | `Σ(dt)` where `Field > 0.1 T` | Magnet-on time |

*Site-level bins (`op_site_bin_stats` / `exp_site_bin_stats`)* — one row per (file, bin, channel):
`Pmagnet`, `Ptot`, `tsb`, `teb`, `debitbrut` (configurable via `--channels`).

*Per-part bins (`op_part_bin_stats` / `exp_part_bin_stats`)* — one row per (file, part, bin, channel):
`Icoil`, `Ucoil`, `hoop_stress_proxy` (= I², proportional to σ_θ).
Only rows where `|Icoil| > 0.1 A` are included so idle periods do not dilute the distributions.

---

## Querying cumulative statistics — `query_cumstats.py`

All queries are read-only. Operational and experiment subcommands follow the same pattern.

```bash
# ── Operational data ─────────────────────────────────────────────────────────

# Scalar totals for a site (energy, heat, duration)
python query_cumstats.py --db magnetdb.duckdb --site M9_A19061901_00 scalars

# Field-bin distributions at site level (all channels)
python query_cumstats.py --db magnetdb.duckdb --site M9_A19061901_00 site-bins

# Selected channels with bar-chart plots
python query_cumstats.py --db magnetdb.duckdb --site M9_A19061901_00 site-bins \
    --channels Ptot,tsb --plot

# Per-part stats for all parts of a magnet
python query_cumstats.py --db magnetdb.duckdb --magnet M9Bitters magnet-bins --plot

# Stats for a single part across all runs and sites
python query_cumstats.py --db magnetdb.duckdb --part M9Bi part-bins \
    --channels Icoil,hoop_stress_proxy --plot

# ── Experiment data ───────────────────────────────────────────────────────────

# Scalar totals across all experiments for a site
python query_cumstats.py --db magnetdb.duckdb --site M10_A250429_00 exp-scalars

# Site-level field-bin distributions from experiment data
python query_cumstats.py --db magnetdb.duckdb --site M10_A250429_00 exp-site-bins

# Filter to a single experiment by name
python query_cumstats.py --db magnetdb.duckdb --site M10_A250429_00 \
    --experiment "2025.04.30 - 13:06:03" exp-site-bins

# Per-part field-bin distributions for a specific part
python query_cumstats.py --db magnetdb.duckdb --part M10Bi exp-part-bins \
    --channels Icoil,hoop_stress_proxy --plot
```

| Subcommand | Required flag | Source table |
|------------|--------------|--------------|
| `scalars` | `--site` or `--magnet` | `op_run_scalars` |
| `site-bins` | `--site` | `op_site_bin_stats` |
| `magnet-bins` | `--magnet` | `op_part_bin_stats` |
| `part-bins` | `--part` | `op_part_bin_stats` |
| `exp-scalars` | `--site` or `--magnet` | `exp_run_scalars` |
| `exp-site-bins` | `--site` | `exp_site_bin_stats` |
| `exp-part-bins` | `--part` | `exp_part_bin_stats` |

Add `--channels ch1,ch2` to restrict the channel output.  
Add `--plot` to save PNG bar charts alongside the tabular output.  
Add `--experiment <name>` (exp-* subcommands only) to filter to a single experiment.

---

## Aggregation reference

| Derived quantity | SQL expression |
|-----------------|----------------|
| Operating time (h) | `SUM(sum_dt) / 3600` |
| Time-weighted mean | `SUM(sum_x_dt) / SUM(sum_dt)` |
| Time-weighted std | `sqrt(SUM(sum_x2_dt)/SUM(sum_dt) − mean²)` |
| Cumulative integral | `SUM(sum_x_dt)` (energy, heat, …) |
| Peak value ever | `MAX(max_x)` |
| Fatigue proxy | `SUM(sum_x2_dt)` where channel = `hoop_stress_proxy` gives `Σ(I²·dt)` |
