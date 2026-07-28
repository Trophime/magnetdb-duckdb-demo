"""
statheures_demo.py
==================
Demonstrates the statheures field-time statistics workflow using the
MagnetDB DuckDB database and TSV record files, without python_magnetrun.

This script adapts the plan from statheures_stats_implementation.md:
- PandasMagnetData.getData()  →  pd.read_csv(filepath, sep='\\t')
- run.getMagnetRef()          →  experiments.site_name from DuckDB
- run.getRunRef()             →  experiments.name from DuckDB

Usage (run from to_duckdb/)
--------------------------
    python tutorials/statheures_demo.py
    python tutorials/statheures_demo.py --site M10_M19071101_13 --step 1.0
    python tutorials/statheures_demo.py --site M10_M19071101_13 --year 2025
    python tutorials/statheures_demo.py --site M10_M19071101_13 \\
        --compare 2025 2026

Requirements
------------
    pip install duckdb pandas numpy matplotlib
"""

import argparse
from pathlib import Path

import duckdb
import matplotlib.pyplot as plt
import pandas as pd

# ---------------------------------------------------------------------------
# Configuration — adjust to match your local paths
# ---------------------------------------------------------------------------
_HERE           = Path(__file__).resolve().parent.parent
DEFAULT_DB      = str(_HERE / "magnetdb.duckdb")
DEFAULT_RECORDS = str(_HERE / "records")  # directory containing TSV files
DEFAULT_SITE    = "M10_M19071101_13"
FIELD_COL       = "Field"            # column name for central field in T
TIME_COL        = "t"                # elapsed time column in seconds
DEFAULT_STEP    = 1.0                # bin width in Tesla
DEFAULT_DT      = 10.0               # fallback sampling interval in seconds


# ---------------------------------------------------------------------------
# 1. Retrieve experiment file list from DuckDB
# ---------------------------------------------------------------------------

def get_experiments(site_name: str, db_path: str) -> pd.DataFrame:
    """
    Return a DataFrame of experiments for a site with columns:
        name, file, year, month
    Sorted by name (which encodes the run date in the filename).
    """
    con = duckdb.connect(db_path, read_only=True)
    df = con.execute("""
        SELECT
            name,
            file,
            -- Extract year and month from filename pattern
            -- e.g. 'M10_2025.11.13---09:14:21.txt' → year=2025, month=11
            TRY_CAST(REGEXP_EXTRACT(file, '_(\\d{4})\\.', 1) AS INTEGER) AS year,
            TRY_CAST(REGEXP_EXTRACT(file, '_\\d{4}\\.(\\d{2})\\.', 1) AS INTEGER) AS month
        FROM experiments
        WHERE site_name = ?
        ORDER BY name
    """, [site_name]).df()
    con.close()
    return df


def get_site_context(site_name: str, db_path: str) -> dict:
    """Return site metadata and list of active magnets from DuckDB."""
    con = duckdb.connect(db_path, read_only=True)
    site = con.execute(
        "SELECT housing, status, commissioned_at FROM sites WHERE name = ?",
        [site_name]
    ).fetchone()
    magnets = con.execute("""
        SELECT m.name, m.type
        FROM site_magnets sm
        JOIN magnets m ON m.name = sm.magnet_name
        WHERE sm.site_name = ?
    """, [site_name]).fetchall()
    con.close()
    return {
        "site":    site_name,
        "housing": site[0] if site else "?",
        "status":  site[1] if site else "?",
        "magnets": [{"name": n, "type": t} for n, t in magnets],
    }


# ---------------------------------------------------------------------------
# 2. Load a single record file
#    Replaces PandasMagnetData.getData()
# ---------------------------------------------------------------------------

def load_record(filepath: str | Path) -> pd.DataFrame | None:
    """
    Load a TSV operational record file into a pandas DataFrame.
    Returns None if the file is missing or cannot be parsed.

    This is the student equivalent of:
        run = PandasMagnetData(filepath)
        df  = run.getData()
    """
    filepath = Path(filepath)
    if not filepath.exists():
        print(f"  [SKIP] not found: {filepath.name}")
        return None
    try:
        df = pd.read_csv(filepath, sep='\t', low_memory=False)
        if FIELD_COL not in df.columns:
            print(f"  [SKIP] no '{FIELD_COL}' column in {filepath.name}")
            return None
        return df
    except Exception as exc:
        print(f"  [ERROR] {filepath.name}: {exc}")
        return None


def infer_dt(df: pd.DataFrame) -> float:
    """
    Infer the sampling interval in seconds from the elapsed time column.
    Falls back to DEFAULT_DT if the column is missing or median is invalid.
    """
    if TIME_COL in df.columns:
        dt = df[TIME_COL].diff().median()
        if pd.notna(dt) and dt > 0:
            return float(dt)
    return DEFAULT_DT


# ---------------------------------------------------------------------------
# 3. Core statistics — mirrors Section 3 of the plan
# ---------------------------------------------------------------------------

def bin_counts(df: pd.DataFrame, step=1.0,
               champmin=0.0, champmax=36.0) -> pd.Series:
    """
    Compute sample counts per field bin for one DataFrame.
    Returns Series indexed by lower bin edge (T), values are integer counts.

    Store counts — not hours. Hours are computed at query time:
        hours = counts * dt / 3600

    This is the key pattern from Section 4: counts are additive across files
    so you never need all files in memory simultaneously.
    """
    mask = df[FIELD_COL].between(champmin, champmax)
    bins = (df.loc[mask, FIELD_COL] // step) * step
    return bins.value_counts().sort_index()


def compute_hours(df: pd.DataFrame, step=1.0,
                  champmin=0.0, champmax=36.0,
                  date_start=None, date_end=None) -> pd.Series:
    """
    Compute hours per field bin for a single DataFrame.
    Mirrors compute_hours() from Section 3 of the plan.

    date_start / date_end filtering applies only when the DataFrame has a
    datetime index (not typical for TSV records — filter at the DuckDB level
    by selecting the right experiment files instead).
    """
    dt = infer_dt(df)
    counts = bin_counts(df, step, champmin, champmax)
    return (counts * dt / 3600.0).rename('heures')


# ---------------------------------------------------------------------------
# 4. Multi-file accumulation — mirrors Section 4 of the plan
# ---------------------------------------------------------------------------

def accumulate_hours(
    site_name:   str,
    db_path:     str,
    records_dir: str,
    step:        float = DEFAULT_STEP,
    champmin:    float = 0.0,
    champmax:    float = 36.0,
    year:        int   = None,
) -> pd.Series:
    """
    Accumulate hours per field bin across all record files for a site.

    Uses the incremental strategy from Section 4:
        - Load one file at a time (never all in memory)
        - Accumulate bin counts, convert to hours at the end
        - Skip missing files gracefully

    Parameters
    ----------
    year : optional int — if given, process only files from that year
    """
    experiments = get_experiments(site_name, db_path)
    if year is not None:
        experiments = experiments[experiments["year"] == year]

    accumulated_counts = pd.Series(dtype=float)
    accumulated_dt_sum = 0.0
    n_files   = 0
    n_skipped = 0

    for _, row in experiments.iterrows():
        path = Path(records_dir) / row["file"]
        df = load_record(path)
        if df is None:
            n_skipped += 1
            continue

        dt     = infer_dt(df)
        counts = bin_counts(df, step, champmin, champmax)

        # Additive accumulation — core property from Section 4
        accumulated_counts = accumulated_counts.add(counts, fill_value=0)
        accumulated_dt_sum += dt
        n_files += 1

    if n_files == 0:
        print("  No files processed.")
        return pd.Series(dtype=float, name='heures')

    # Use median dt across all files for final conversion
    dt_median = accumulated_dt_sum / n_files
    hours = (accumulated_counts * dt_median / 3600.0).rename('heures').sort_index()

    print(f"  Processed {n_files} files, skipped {n_skipped}")
    print(f"  Median sampling interval: {dt_median:.1f} s")
    print(f"  Total hours in field [{champmin}–{champmax}] T: {hours.sum():.1f} h")
    return hours


# ---------------------------------------------------------------------------
# 5. Optional: persist bin counts to DuckDB — mirrors Section 6 of the plan
# ---------------------------------------------------------------------------

STATS_SCHEMA = """
CREATE TABLE IF NOT EXISTS processed_experiments (
    file         VARCHAR PRIMARY KEY,
    site_name    VARCHAR,
    n_samples    INTEGER,
    dt_seconds   DOUBLE,
    processed_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS field_bin_counts (
    site_name    VARCHAR,
    file         VARCHAR,
    year         INTEGER,
    month        INTEGER,
    field_bin    DOUBLE,
    sample_count BIGINT,
    PRIMARY KEY (site_name, file, year, month, field_bin)
);
"""


def init_stats_tables(db_path: str) -> None:
    """Add stats tables to the existing student DuckDB (idempotent)."""
    con = duckdb.connect(db_path)
    con.execute(STATS_SCHEMA)
    con.close()
    print(f"Stats tables initialised in {db_path}")


def process_and_store(
    site_name:   str,
    db_path:     str,
    records_dir: str,
    step:        float = DEFAULT_STEP,
    champmin:    float = 0.0,
    champmax:    float = 36.0,
) -> dict:
    """
    Process each record file for a site and store bin counts in DuckDB.
    Idempotent: already-processed files are skipped.

    Mirrors process_run() + ingest_all() from Section 6 of the plan,
    using direct pd.read_csv instead of PandasMagnetData.
    """
    init_stats_tables(db_path)
    experiments = get_experiments(site_name, db_path)
    con = duckdb.connect(db_path)
    results = {"new": 0, "skipped": 0, "errors": []}

    for _, row in experiments.iterrows():
        file = row["file"]
        year = row["year"]
        month = row["month"]
        path = Path(records_dir) / file

        # Idempotency check — skip if already in processed_experiments
        already = con.execute(
            "SELECT COUNT(*) FROM processed_experiments WHERE file = ?", [file]
        ).fetchone()[0]
        if already:
            results["skipped"] += 1
            continue

        df = load_record(path)
        if df is None:
            results["errors"].append(file)
            continue

        try:
            dt     = infer_dt(df)
            counts = bin_counts(df, step, champmin, champmax).reset_index()
            counts.columns = ["field_bin", "sample_count"]

            # Register DataFrame in DuckDB (zero copy) and INSERT
            con.register("current_counts", counts)
            con.execute(f"""
                INSERT OR REPLACE INTO field_bin_counts
                    (site_name, file, year, month, field_bin, sample_count)
                SELECT '{site_name}', '{file}', {year or 'NULL'},
                       {month or 'NULL'}, field_bin, sample_count
                FROM current_counts
            """)
            con.unregister("current_counts")

            con.execute("""
                INSERT INTO processed_experiments (file, site_name, n_samples, dt_seconds)
                VALUES (?, ?, ?, ?)
            """, [file, site_name, len(df), dt])

            results["new"] += 1

        except Exception as exc:
            results["errors"].append((file, str(exc)))

    con.close()
    print(f"  Stored: {results['new']} new, {results['skipped']} skipped, "
          f"{len(results['errors'])} errors")
    return results


# ---------------------------------------------------------------------------
# 6. Query layer — mirrors Section 6 query functions
# ---------------------------------------------------------------------------

def query_yearly_hours(
    db_path:   str,
    site_name: str,
    champmin:  float = 0.0,
    champmax:  float = 36.0,
) -> pd.DataFrame:
    """
    Return hours per (year, field_bin) from the pre-computed table.
    No raw TSV files needed.
    """
    con = duckdb.connect(db_path, read_only=True)
    df = con.execute(f"""
        SELECT field_bin, year,
               SUM(sample_count) * 10.0 / 3600.0 AS heures
        FROM field_bin_counts
        WHERE site_name   = ?
          AND field_bin BETWEEN {champmin} AND {champmax}
        GROUP BY field_bin, year
        ORDER BY year, field_bin
    """, [site_name]).df()
    con.close()
    return df


def query_compare_intervals(
    db_path:    str,
    site_name:  str,
    year1:      int,
    year2:      int,
    champmin:   float = 0.0,
    champmax:   float = 36.0,
) -> pd.DataFrame:
    """
    Two-year comparison from pre-computed table.
    Mirrors compare_intervals() from Section 6 of the plan.
    """
    con = duckdb.connect(db_path, read_only=True)
    df = con.execute(f"""
        WITH
        y1 AS (
            SELECT field_bin, SUM(sample_count)*10.0/3600 AS heures_{year1}
            FROM field_bin_counts
            WHERE site_name = ? AND year = {year1}
              AND field_bin BETWEEN {champmin} AND {champmax}
            GROUP BY field_bin
        ),
        y2 AS (
            SELECT field_bin, SUM(sample_count)*10.0/3600 AS heures_{year2}
            FROM field_bin_counts
            WHERE site_name = ? AND year = {year2}
              AND field_bin BETWEEN {champmin} AND {champmax}
            GROUP BY field_bin
        )
        SELECT COALESCE(y1.field_bin, y2.field_bin) AS field_bin,
               COALESCE(heures_{year1}, 0)           AS heures_{year1},
               COALESCE(heures_{year2}, 0)           AS heures_{year2}
        FROM y1 FULL OUTER JOIN y2 USING (field_bin)
        ORDER BY field_bin
    """, [site_name, site_name]).df()
    con.close()
    return df


# ---------------------------------------------------------------------------
# 7. Plotting
# ---------------------------------------------------------------------------

def plot_hours_histogram(hours: pd.Series, title: str, step: float) -> None:
    """Bar chart of hours per field bin."""
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    # Linear scale
    axes[0].bar(hours.index, hours.values, width=step * 0.8,
                align='edge', color='steelblue', edgecolor='white')
    axes[0].set_xlabel("Magnetic field (T)")
    axes[0].set_ylabel("Hours")
    axes[0].set_title(title)
    axes[0].grid(axis='y', alpha=0.4)

    # Log scale — reveals time spent in low-field ranges
    positive = hours[hours > 0]
    axes[1].bar(positive.index, positive.values, width=step * 0.8,
                align='edge', color='steelblue', edgecolor='white')
    axes[1].set_yscale('log')
    axes[1].set_xlabel("Magnetic field (T)")
    axes[1].set_ylabel("Hours (log scale)")
    axes[1].set_title(f"{title} — log scale")
    axes[1].grid(axis='y', alpha=0.4)

    plt.tight_layout()
    safe_title = title.replace(" ", "_").replace("/", "-")
    plt.savefig(f"statheures_{safe_title}.png", dpi=150)
    print(f"Saved statheures_{safe_title}.png")
    plt.show()


def plot_comparison(df: pd.DataFrame, year1: int, year2: int,
                    step: float, site_name: str) -> None:
    """Side-by-side bar chart comparing two years."""
    fig, ax = plt.subplots(figsize=(12, 5))
    x = df["field_bin"].values
    w = step * 0.4
    ax.bar(x,       df[f"heures_{year1}"], width=w, align='edge',
           label=str(year1), color='steelblue')
    ax.bar(x + w,   df[f"heures_{year2}"], width=w, align='edge',
           label=str(year2), color='tomato', alpha=0.8)
    ax.set_xlabel("Magnetic field (T)")
    ax.set_ylabel("Hours")
    ax.set_title(f"Field-time histogram — {site_name} — {year1} vs {year2}")
    ax.legend()
    ax.grid(axis='y', alpha=0.4)
    plt.tight_layout()
    plt.savefig(f"statheures_compare_{year1}_{year2}.png", dpi=150)
    print(f"Saved statheures_compare_{year1}_{year2}.png")
    plt.show()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Field-time statistics (statheures) using DuckDB + TSV records.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--db",      default=DEFAULT_DB)
    parser.add_argument("--records", default=DEFAULT_RECORDS)
    parser.add_argument("--site",    default=DEFAULT_SITE)
    parser.add_argument("--step",    type=float, default=DEFAULT_STEP,
                        help="Bin width in Tesla (default: 1.0)")
    parser.add_argument("--champmin", type=float, default=0.0)
    parser.add_argument("--champmax", type=float, default=36.0)
    parser.add_argument("--year",    type=int, default=None,
                        help="Filter to a single year")
    parser.add_argument("--compare", type=int, nargs=2, metavar=("YEAR1", "YEAR2"),
                        help="Compare two years (requires --persist first)")
    parser.add_argument("--persist", action="store_true",
                        help="Store bin counts in DuckDB for fast re-queries")
    args = parser.parse_args()

    db_path     = args.db
    records_dir = args.records
    site_name   = args.site

    # Show site context
    ctx = get_site_context(site_name, db_path)
    print(f"\nSite: {ctx['site']}  [{ctx['housing']}]  {ctx['status']}")
    print(f"Magnets: {[m['name'] for m in ctx['magnets']]}")

    if args.persist:
        # Store pre-computed bin counts back to DuckDB
        print("\n── Ingesting records into DuckDB …")
        process_and_store(site_name, db_path, records_dir,
                          args.step, args.champmin, args.champmax)

    if args.compare:
        year1, year2 = args.compare
        print(f"\n── Comparing {year1} vs {year2} (from stored counts) …")
        df = query_compare_intervals(db_path, site_name, year1, year2,
                                     args.champmin, args.champmax)
        print(df.to_string(index=False))
        plot_comparison(df, year1, year2, args.step, site_name)

    else:
        # Direct file-by-file computation (no persistence needed)
        year_label = str(args.year) if args.year else "all years"
        print(f"\n── Computing field-time statistics for {site_name} ({year_label}) …")
        hours = accumulate_hours(site_name, db_path, records_dir,
                                 args.step, args.champmin, args.champmax,
                                 args.year)
        if not hours.empty:
            print(f"\n{hours.to_string()}")
            plot_hours_histogram(
                hours,
                title=f"{site_name} — {year_label}",
                step=args.step,
            )


if __name__ == "__main__":
    main()
