# Student Note — Field-Time Statistics with DuckDB

> This note explains how to apply the `statheures` statistics plan
> (`statheures_stats_implementation.md`) using the student DuckDB database
> and the TSV record files shipped alongside it.
>
> You do **not** need `python_magnetrun` or `PandasMagnetData` for this work.
> Load record files directly with `pandas.read_csv`.

---

## What you already have

```
student_data/
├── student_magnetdb.duckdb      ← structural metadata + experiment index
└── records/
    ├── M10_2025.11.13---09:14:21.txt
    ├── M10_2025.11.13---13:08:27.txt
    └── ...                      ← one TSV file per operational run
```

The DuckDB database gives you:

- `sites` — hall, status, commissioning dates
- `magnets`, `parts`, `materials` — magnet configuration hierarchy
- `site_magnets` — which magnets operated in each site
- `experiments` — one row per record file, with the filename that locates the TSV

---

## What `PandasMagnetData` does (and how to replace it)

In the full MagnetDB codebase, `PandasMagnetData` is a class from
`python_magnetrun` that wraps loading a record file into a pandas DataFrame.
Its three key methods are:

| `PandasMagnetData` method | What it returns | Student equivalent |
|---|---|---|
| `run.getData()` | pandas DataFrame of the record | `pd.read_csv(filepath, sep='\t')` |
| `run.getRunRef()` | Run identifier string | `experiments.name` from DuckDB |
| `run.getMagnetRef()` | Magnet/site reference string | `experiments.site_name` from DuckDB |

### Loading a record file

```python
import pandas as pd

df = pd.read_csv("student_data/records/M10_2025.11.13---09:14:21.txt", sep='\t')
print(df.columns.tolist())
# Typical columns: t, Field, Icoil1, Icoil2, ..., Tin1, Tout, ...
```

Key columns for the statheures statistics:

| Column | Description | Unit |
|--------|-------------|------|
| `t` | Elapsed time since start of run | s |
| `Field` | Central magnetic field (Hall probe) | T |
| `Icoil1`…`IcoilN` | Currents per power supply | A |
| `timestamp` | Wall-clock datetime (if present) | — |

> **Sampling interval**: each row is one sample. The sampling interval is
> typically 10 seconds, but verify with `df['t'].diff().median()` on your
> actual files. The conversion factor `COUNT(*) × dt / 3600` gives hours,
> where `dt` is the interval in seconds.

---

## Mapping the plan to your DuckDB workflow

The plan in `statheures_stats_implementation.md` assumes all data is already
in a single DataFrame indexed by datetime. With individual TSV files and DuckDB,
the workflow has one extra step: **look up which files belong to which site
before loading them**.

### Full adapted workflow

```
DuckDB (experiments table)
    │  query: SELECT file FROM experiments WHERE site_name = '...'
    │
    ▼
Record file list
    │  for each file: pd.read_csv(records_dir / file, sep='\t')
    │
    ▼
pandas DataFrame (one per file)
    │  bin Field column → field_bin
    │  count rows × dt / 3600 → hours
    │
    ▼  incremental accumulation (additive — see Section 4 of the plan)
Accumulated bin counts
    │
    ▼  (optional) write back to DuckDB
field_bin_counts table  →  yearly_hours(), compare_intervals(), ...
```

The key insight from Section 4 of the plan is that **bin counts are additive**:
you never need all files in memory at once. Accumulate counts file by file,
convert to hours only at the end.

---

## Concrete implementation

See `student_statheures_demo.py` for a full working script. The main functions are:

### 1. Get experiments for a site from DuckDB

```python
import duckdb

def get_experiments(site_name: str, db_path: str, records_dir: str) -> list[dict]:
    """Return list of {name, file, path} for all experiments at a site."""
    con = duckdb.connect(db_path, read_only=True)
    rows = con.execute("""
        SELECT name, file FROM experiments
        WHERE site_name = ? ORDER BY name
    """, [site_name]).fetchall()
    con.close()
    return [
        {"name": name, "file": file,
         "path": str(Path(records_dir) / file)}
        for name, file in rows
    ]
```

### 2. Compute bin counts for one file (Section 3 of the plan)

```python
def bin_counts(df: pd.DataFrame, step=1.0, champmin=0.0, champmax=36.0,
               field_col='Field') -> pd.Series:
    """
    Return Series: field_bin (lower edge, T) → sample COUNT.
    Store counts, not hours — hours are computed at query time.
    Mirrors bin_counts() from Section 4 of the plan.
    """
    mask = df[field_col].between(champmin, champmax)
    bins = (df.loc[mask, field_col] // step) * step
    return bins.value_counts().sort_index().rename('count')
```

### 3. Accumulate across all files for a site

```python
from pathlib import Path
import pandas as pd
import numpy as np

def compute_site_hours(site_name, db_path, records_dir,
                       step=1.0, champmin=0.0, champmax=36.0):
    experiments = get_experiments(site_name, db_path, records_dir)
    accumulated = pd.Series(dtype=float)

    for exp in experiments:
        if not Path(exp["path"]).exists():
            print(f"  [SKIP] {exp['file']} not found")
            continue
        df = pd.read_csv(exp["path"], sep='\t')
        if 'Field' not in df.columns:
            print(f"  [SKIP] {exp['file']} has no Field column")
            continue

        dt = df['t'].diff().median() if 't' in df.columns else 10.0
        counts = bin_counts(df, step, champmin, champmax)
        hours  = counts * dt / 3600.0

        accumulated = accumulated.add(hours, fill_value=0)

    return accumulated.rename('heures').sort_index()
```

### 4. Two-interval comparison (Section 3 of the plan)

With individual TSV files you filter by the experiment name (which encodes
the run date) rather than a datetime index:

```python
def compute_site_hours_for_year(site_name, year, db_path, records_dir, step=1.0):
    """Hours per field bin for a specific year, using filename date."""
    con = duckdb.connect(db_path, read_only=True)
    rows = con.execute("""
        SELECT name, file FROM experiments
        WHERE site_name = ?
          AND CAST(SUBSTRING(file, 4, 4) AS INTEGER) = ?
        ORDER BY name
    """, [site_name, year]).fetchall()
    con.close()

    accumulated = pd.Series(dtype=float)
    for name, file in rows:
        path = Path(records_dir) / file
        if not path.exists():
            continue
        df  = pd.read_csv(path, sep='\t')
        dt  = df['t'].diff().median() if 't' in df.columns else 10.0
        accumulated = accumulated.add(
            bin_counts(df) * dt / 3600.0, fill_value=0
        )
    return accumulated.rename('heures').sort_index()

# Two-year comparison — same pattern as Section 3 of the plan
h2024 = compute_site_hours_for_year('M10_M19071101_13', 2025, ...)
h2025 = compute_site_hours_for_year('M10_M19071101_13', 2026, ...)
comparison = pd.concat([h2024.rename('2025'), h2025.rename('2026')], axis=1).fillna(0)
```

---

## Optional: persist bin counts back to DuckDB

If you want to follow the full Section 6 schema from the plan (storing pre-computed
counts to avoid re-reading TSV files), you can add two tables to the existing
student DuckDB. This lets you query hours instantly without reading any TSV files.

```python
STATS_SCHEMA = """
CREATE TABLE IF NOT EXISTS processed_experiments (
    file         VARCHAR PRIMARY KEY,
    site_name    VARCHAR,
    n_samples    INTEGER,
    dt_seconds   DOUBLE,
    processed_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS field_bin_counts (
    site_name   VARCHAR,
    file        VARCHAR,
    year        INTEGER,
    month       INTEGER,
    field_bin   DOUBLE,
    sample_count BIGINT,
    PRIMARY KEY (site_name, file, year, month, field_bin)
);
"""
```

See the demo script for `process_and_store()` which populates these tables,
and `query_yearly_hours()` / `query_compare_intervals()` which read from them.

---

## Differences from the original plan

| Plan assumption | Student reality | Adaptation |
|---|---|---|
| `PandasMagnetData(filepath).getData()` | `pd.read_csv(path, sep='\t')` | Direct load — no wrapper needed |
| `run.getMagnetRef()` | `experiments.site_name` in DuckDB | Query DuckDB for site context |
| `run.getRunRef()` | `experiments.name` in DuckDB | Already in the index |
| Files in a single folder, glob `*.csv` | Files listed in `experiments` table | Query DuckDB to get file list |
| `timestamp` column as index | `t` column (elapsed seconds) | Use filename to extract run date; use `t` for duration |
| Sampling always 10 s | Verify with `df['t'].diff().median()` | Use actual `dt` per file |

---

## Exercises

1. **Basic histogram**: compute and plot hours per field bin (1 T steps) for one site
   across all available records. Use `matplotlib` bar chart.

2. **Year comparison**: compare 2025 vs 2026 operations for site `M10_M19071101_13`
   using the two-interval pattern from Section 3.

3. **Per-magnet breakdown**: the site has two magnets (`M19071101` insert and
   `M10Bitters`). The `Field` column reflects the combined field. Explore whether
   the `Icoil1`…`IcoilN` channel currents correlate with the field bins — do
   higher field bins correspond to higher currents on all helices proportionally?

4. **Persistence**: implement `process_and_store()` to populate `field_bin_counts`,
   then verify that querying the table gives the same result as the direct
   file-by-file computation.

5. **Bin width sensitivity**: repeat the histogram with `step = 0.5 T` and `step = 2 T`.
   How does the choice of bin width affect the interpretation?
