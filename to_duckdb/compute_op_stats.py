"""
compute_op_stats.py
===================
Ingest per-file operational statistics into DuckDB.

For each operationaldata file not yet processed this script:
  1. Loads the record file (via python_magnetrun or pandas fallback).
  2. Computes per-run scalar stats   → op_run_scalars
       'energy_j'            = sum(Ptot * dt)
       'heat_extracted_j'    = sum((tsb - teb) * Q_m3s * rho_cp * dt)
       'duration_s'          = sum(dt)
       'duration_field_on_s' = sum(dt) where Field > field_threshold
  3. Computes site-level field-bin stats → op_site_bin_stats
       channels: Pmagnet, Ptot, tsb, teb, debitbrut  (configurable)
  4. Computes per-part field-bin stats  → op_part_bin_stats
       channels: Icoil, Ucoil, hoop_stress_proxy (= I^2)
       only rows where |Icoil| > current_threshold are counted
  5. Marks the file as processed in op_stats_processed (idempotent).

Usage
-----
    python compute_op_stats.py --db magnetdb.duckdb --records-base ../data/M9 \\
        --site M9_M19061901
    python compute_op_stats.py --db magnetdb.duckdb --records-base ../data/M9 \\
        --site M9_M19061901 --type pupitre --reprocess

Physical constants
------------------
    debitbrut is assumed to be in m³/h.
    Override with --flow-to-m3s if your data uses different units.
    Water: rho = 1000 kg/m³, cp = 4186 J/(kg·K)  →  rho_cp = 4 186 000 J/(m³·K)
"""

import argparse
import json
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from config import DEFAULT_DB
from schema import ensure_schema

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_RECORDS_BASE = "records"

FIELD_COL = "Field"
FIELD_THRESHOLD = 0.1  # T  — minimum field to count as "field on"
CURRENT_THRESHOLD = 0.1  # A  — minimum |Icoil| to count as "coil on"
FLOW_TO_M3S = 1.0 / 3600.0  # m³/h → m³/s
RHO_CP = 1_000.0 * 4_186.0  # J / (m³·K)  water

DEFAULT_BINS: list[tuple[float, float]] = [
    (0.0, 0.1),
    (0.1, 5.0),
    (5.0, 10.0),
    (10.0, 15.0),
    (15.0, 20.0),
    (20.0, 25.0),
    (25.0, 30.0),
    (30.0, 35.0),
    (35.0, 40.0),
    (40.0, 45.0),
]

SITE_CHANNELS = ["Pmagnet", "Ptot", "tsb", "teb", "debitbrut"]

# ---------------------------------------------------------------------------
# File loading
# ---------------------------------------------------------------------------


def _compute_dt(df: pd.DataFrame) -> pd.Series:
    """Return a dt Series (seconds) using Date+Time columns or a 't' column."""
    if "Date" in df.columns and "Time" in df.columns:
        try:
            ts = pd.to_datetime(
                df["Date"].astype(str) + " " + df["Time"].astype(str),
                format="%Y.%m.%d %H:%M:%S",
            )
            dt = ts.diff().dt.total_seconds().fillna(0.0)
            dt = dt.clip(lower=0.0)
            return dt
        except Exception:
            pass
    if "t" in df.columns:
        dt = df["t"].diff().fillna(0.0).clip(lower=0.0)
        return dt
    # fallback: constant interval from median of non-zero gaps
    if "t" in df.columns:
        median_dt = df["t"].diff().dropna()
        median_dt = median_dt[median_dt > 0].median()
        return pd.Series(
            float(median_dt) if pd.notna(median_dt) else 1.0, index=df.index
        )
    return pd.Series(1.0, index=df.index)


def load_file(path: Path) -> pd.DataFrame | None:
    """Load a record file into a DataFrame with a 'dt' column added.

    Tries python_magnetrun.magnetdata.load_magnetdata first; falls back to
    pd.read_csv for plain TSV files.
    """
    if not path.exists():
        print(f"  [SKIP] not found: {path.name}")
        return None
    try:
        from python_magnetrun.magnetdata import load_magnetdata

        md = load_magnetdata(str(path))
        df = md.Data.copy()
    except Exception:
        try:
            df = pd.read_csv(path, sep="\t", low_memory=False)
        except Exception as exc:
            print(f"  [ERROR] cannot read {path.name}: {exc}")
            return None

    if FIELD_COL not in df.columns:
        print(f"  [SKIP] no '{FIELD_COL}' column in {path.name}")
        return None

    df["dt"] = _compute_dt(df)
    return df


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------


def get_operationaldata(con, site_name: str, od_type: str | None) -> pd.DataFrame:
    """Return operationaldata rows for a site, optionally filtered by type."""
    q = "SELECT id, name, file FROM operationaldata WHERE site_name = ?"
    params = [site_name]
    if od_type:
        q += " AND type = ?"
        params.append(od_type)
    q += " ORDER BY name"
    return con.execute(q, params).df()


def get_site_parts(con, site_name: str) -> pd.DataFrame:
    """Return parts with their coil_index for all magnets at a site."""
    return con.execute(
        """
        SELECT p.name AS part_name, mp.coil_index, mp.magnet_name
        FROM site_magnets sm
        JOIN magnet_parts mp ON mp.magnet_name = sm.magnet_name
        JOIN parts p         ON p.name = mp.part_name
        WHERE sm.site_name = ?
          AND mp.coil_index IS NOT NULL
        ORDER BY mp.coil_index
    """,
        [site_name],
    ).df()


def is_processed(con, od_id: int) -> bool:
    return (
        con.execute(
            "SELECT 1 FROM op_stats_processed WHERE operationaldata_id = ?", [od_id]
        ).fetchone()
        is not None
    )


def mark_processed(con, od_id: int, df: pd.DataFrame, bins: list[tuple]) -> None:
    dt_median = float(df["dt"][df["dt"] > 0].median()) if (df["dt"] > 0).any() else 0.0
    con.execute(
        """
        INSERT OR REPLACE INTO op_stats_processed
            (operationaldata_id, n_rows, dt_median, bin_config)
        VALUES (?, ?, ?, ?)
        """,
        [od_id, len(df), dt_median, json.dumps(bins)],
    )


# ---------------------------------------------------------------------------
# Stat computation
# ---------------------------------------------------------------------------


def _assign_bins(field: pd.Series, bins: list[tuple]) -> pd.Series:
    """Return the bin_low for each row, or NaN if outside every bin."""
    out = pd.Series(np.nan, index=field.index)
    for low, high in bins:
        mask = (field >= low) & (field < high)
        out[mask] = low
    return out


def _bin_agg(x: pd.Series, dt: pd.Series) -> dict:
    """Aggregate one channel over the rows already filtered to a single bin."""
    x = x.astype(float)
    dt = dt.astype(float)
    return {
        "n_samples": len(x),
        "sum_dt": float(dt.sum()),
        "sum_x_dt": float((x * dt).sum()),
        "sum_x2_dt": float((x**2 * dt).sum()),
        "min_x": float(x.min()),
        "max_x": float(x.max()),
    }


# ── Scalars ─────────────────────────────────────────────────────────────────


def compute_scalars(
    df: pd.DataFrame,
    flow_to_m3s: float = FLOW_TO_M3S,
    rho_cp: float = RHO_CP,
) -> dict[str, float]:
    """Return per-run scalar statistics."""
    dt = df["dt"].astype(float)
    scalars: dict[str, float] = {}

    scalars["duration_s"] = float(dt.sum())

    field_on = df[FIELD_COL].astype(float) > FIELD_THRESHOLD
    scalars["duration_field_on_s"] = float(dt[field_on].sum())

    if "Ptot" in df.columns:
        ptot = df["Ptot"].astype(float)
        scalars["energy_j"] = float((ptot * dt).sum())

    if all(c in df.columns for c in ("tsb", "teb", "debitbrut")):
        delta_t = df["tsb"].astype(float) - df["teb"].astype(float)
        flow_m3s = df["debitbrut"].astype(float) * flow_to_m3s
        heat_w = delta_t * flow_m3s * rho_cp
        scalars["heat_extracted_j"] = float((heat_w * dt).sum())

    return scalars


def insert_scalars(con, od_id: int, scalars: dict[str, float]) -> None:
    for channel, value in scalars.items():
        con.execute(
            "INSERT OR REPLACE INTO op_run_scalars VALUES (?, ?, ?)",
            [od_id, channel, value],
        )


# ── Site-level bin stats ─────────────────────────────────────────────────────


def compute_site_bin_stats(
    df: pd.DataFrame,
    bins: list[tuple],
    channels: list[str],
) -> list[dict]:
    """Return rows for op_site_bin_stats (missing channels are silently skipped)."""
    field = df[FIELD_COL].astype(float)
    bin_low = _assign_bins(field, bins)
    rows = []
    for low, high in bins:
        mask = bin_low == low
        sub = df[mask]
        if sub.empty:
            continue
        for ch in channels:
            if ch not in sub.columns:
                continue
            agg = _bin_agg(sub[ch], sub["dt"])
            rows.append(
                {"field_bin_low": low, "field_bin_high": high, "channel": ch, **agg}
            )
    return rows


def insert_site_bin_stats(con, od_id: int, rows: list[dict]) -> None:
    for r in rows:
        con.execute(
            """
            INSERT OR REPLACE INTO op_site_bin_stats
                (operationaldata_id, field_bin_low, field_bin_high, channel,
                 n_samples, sum_dt, sum_x_dt, sum_x2_dt, min_x, max_x)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            [
                od_id,
                r["field_bin_low"],
                r["field_bin_high"],
                r["channel"],
                r["n_samples"],
                r["sum_dt"],
                r["sum_x_dt"],
                r["sum_x2_dt"],
                r["min_x"],
                r["max_x"],
            ],
        )


# ── Per-part bin stats ────────────────────────────────────────────────────────


def compute_part_bin_stats(
    df: pd.DataFrame,
    bins: list[tuple],
    part_name: str,
    coil_index: int,
) -> list[dict]:
    """Return rows for op_part_bin_stats for one part/coil.

    Channels computed:
      Icoil             — coil current
      Ucoil             — coil voltage
      hoop_stress_proxy — I^2, proportional to hoop stress (sigma_theta ∝ I^2)

    Only rows where |Icoil| > CURRENT_THRESHOLD are included so that idle
    periods (field off, I ≈ 0) do not dilute the distributions.
    """
    i_col = f"Icoil{coil_index}"
    u_col = f"Ucoil{coil_index}"
    if i_col not in df.columns:
        return []

    field = df[FIELD_COL].astype(float)
    icoil = df[i_col].astype(float)
    active = icoil.abs() > CURRENT_THRESHOLD
    bin_low = _assign_bins(field, bins)

    rows = []
    for low, high in bins:
        mask = (bin_low == low) & active
        sub = df[mask]
        if sub.empty:
            continue

        i_sub = sub[i_col].astype(float)
        dt_sub = sub["dt"]

        # Icoil
        rows.append(
            {
                "part_name": part_name,
                "field_bin_low": low,
                "field_bin_high": high,
                "channel": "Icoil",
                **_bin_agg(i_sub, dt_sub),
            }
        )

        # Ucoil
        if u_col in sub.columns:
            rows.append(
                {
                    "part_name": part_name,
                    "field_bin_low": low,
                    "field_bin_high": high,
                    "channel": "Ucoil",
                    **_bin_agg(sub[u_col].astype(float), dt_sub),
                }
            )

        # Hoop stress proxy (I^2)
        rows.append(
            {
                "part_name": part_name,
                "field_bin_low": low,
                "field_bin_high": high,
                "channel": "hoop_stress_proxy",
                **_bin_agg(i_sub**2, dt_sub),
            }
        )

    return rows


def insert_part_bin_stats(con, od_id: int, rows: list[dict]) -> None:
    for r in rows:
        con.execute(
            """
            INSERT OR REPLACE INTO op_part_bin_stats
                (operationaldata_id, part_name, field_bin_low, field_bin_high, channel,
                 n_samples, sum_dt, sum_x_dt, sum_x2_dt, min_x, max_x)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            [
                od_id,
                r["part_name"],
                r["field_bin_low"],
                r["field_bin_high"],
                r["channel"],
                r["n_samples"],
                r["sum_dt"],
                r["sum_x_dt"],
                r["sum_x2_dt"],
                r["min_x"],
                r["max_x"],
            ],
        )


# ---------------------------------------------------------------------------
# Top-level ingestion
# ---------------------------------------------------------------------------


def ingest_site(
    site_name: str,
    db_path: str,
    records_dir: str,
    od_type: str | None = None,
    bins: list[tuple] = DEFAULT_BINS,
    site_channels: list[str] = SITE_CHANNELS,
    flow_to_m3s: float = FLOW_TO_M3S,
    rho_cp: float = RHO_CP,
    reprocess: bool = False,
    verbose: bool = True,
) -> dict:
    """Process all operationaldata files for *site_name* and persist stats.

    Parameters
    ----------
    site_name:    site FK (must exist in the sites table)
    db_path:      path to the DuckDB file
    records_dir:  directory containing the raw record files
    od_type:      filter operationaldata by type (e.g. 'pupitre'), or None for all
    bins:         list of (low, high) field bins in Tesla
    site_channels: columns to track in op_site_bin_stats
    flow_to_m3s:  unit conversion for debitbrut → m³/s (default: 1/3600 for m³/h)
    rho_cp:       water rho*cp in J/(m³·K) (default: 4 186 000)
    reprocess:    if True, overwrite already-processed files
    verbose:      print progress lines
    """
    con = duckdb.connect(db_path)
    ensure_schema(con)

    od_df = get_operationaldata(con, site_name, od_type)
    parts = get_site_parts(con, site_name)
    records_path = Path(records_dir)

    results = {"new": 0, "skipped": 0, "errors": []}

    for _, row in od_df.iterrows():
        od_id = int(row["id"])
        filename = row["file"]

        if not reprocess and is_processed(con, od_id):
            results["skipped"] += 1
            continue

        path = records_path / filename
        df = load_file(path)
        if df is None:
            results["errors"].append(filename)
            continue

        if verbose:
            print(f"  processing {filename}  ({len(df)} rows)")

        try:
            # 1. Scalar stats
            scalars = compute_scalars(df, flow_to_m3s, rho_cp)
            insert_scalars(con, od_id, scalars)

            # 2. Site-level bin stats
            site_rows = compute_site_bin_stats(df, bins, site_channels)
            insert_site_bin_stats(con, od_id, site_rows)

            # 3. Per-part bin stats
            for _, part in parts.iterrows():
                part_rows = compute_part_bin_stats(
                    df, bins, part["part_name"], int(part["coil_index"])
                )
                insert_part_bin_stats(con, od_id, part_rows)

            mark_processed(con, od_id, df, bins)
            results["new"] += 1

        except Exception as exc:
            results["errors"].append((filename, str(exc)))
            if verbose:
                print(f"  [ERROR] {filename}: {exc}")

    con.close()

    if verbose:
        print(
            f"\nDone — {results['new']} processed, "
            f"{results['skipped']} skipped, "
            f"{len(results['errors'])} errors"
        )
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_bins(s: str) -> list[tuple[float, float]]:
    """Parse '0:0.1,0.1:5,5:10' into [(0.0, 0.1), (0.1, 5.0), (5.0, 10.0)]."""
    bins = []
    for pair in s.split(","):
        lo, hi = pair.strip().split(":")
        bins.append((float(lo), float(hi)))
    return bins


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest operational statistics into DuckDB.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--db", default=DEFAULT_DB, help="DuckDB file path")
    parser.add_argument(
        "--records-base",
        default=DEFAULT_RECORDS_BASE,
        dest="records_base",
        help="Directory of record files",
    )
    parser.add_argument("--site", required=True, help="Site name (FK)")
    parser.add_argument(
        "--type", default=None, help="Filter operationaldata by type, e.g. 'pupitre'"
    )
    parser.add_argument(
        "--bins",
        default=None,
        help="Field bins as 'low1:high1,low2:high2,...' (default: built-in 7-bin set)",
    )
    parser.add_argument(
        "--channels",
        default=",".join(SITE_CHANNELS),
        help="Comma-separated site-level channels (default: Pmagnet,Ptot,tsb,teb,debitbrut)",
    )
    parser.add_argument(
        "--flow-to-m3s",
        type=float,
        default=FLOW_TO_M3S,
        help="Unit conversion: debitbrut → m³/s (default 1/3600 for m³/h input)",
    )
    parser.add_argument(
        "--reprocess", action="store_true", help="Re-compute already-processed files"
    )
    parser.add_argument("--quiet", action="store_true", help="Suppress per-file output")
    args = parser.parse_args()

    bins = _parse_bins(args.bins) if args.bins else DEFAULT_BINS
    channels = [c.strip() for c in args.channels.split(",") if c.strip()]

    ingest_site(
        site_name=args.site,
        db_path=args.db,
        records_dir=args.records_base,
        od_type=args.type,
        bins=bins,
        site_channels=channels,
        flow_to_m3s=args.flow_to_m3s,
        reprocess=args.reprocess,
        verbose=not args.quiet,
    )


if __name__ == "__main__":
    main()
