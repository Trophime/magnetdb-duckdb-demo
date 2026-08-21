"""
compute_exp_stats.py
====================
Ingest per-file experiment statistics into DuckDB.

For each experiments file not yet processed this script:
  1. Loads the record file (via python_magnetrun or pandas fallback).
  2. Computes per-run scalar stats   → exp_run_scalars
       'energy_j'            = sum(Ptot[W] * dt)  (Ptot stored in MW, ×1e6)
       'heat_extracted_j'    = sum((tsb - teb) * Q_m3s * rho_cp * dt)
       'duration_s'          = sum(dt)
       'duration_field_on_s' = sum(dt) where Field > field_threshold
  3. Computes assembly-level field-bin stats → exp_assembly_bin_stats
       channels: Pmagnet, Ptot, tsb, teb, debitbrut  (configurable)
  4. Computes per-part field-bin stats  → exp_part_bin_stats
       channels: Icoil, Ucoil, hoop_stress_proxy (= I^2)
       only rows where |Icoil| > current_threshold are counted
  5. Marks the file as processed in exp_stats_processed (idempotent).

Usage
-----
    python compute_exp_stats.py --db magnetdb.duckdb --assembly M10_A250429_00
    python compute_exp_stats.py --db magnetdb.duckdb --assembly M10_A250429_00 --reprocess

Physical constants
------------------
    debitbrut is assumed to be in m³/h.
    Override with --flow-to-m3s if your data uses different units.
    Water: rho = 1000 kg/m³, cp = 4186 J/(kg·K)  →  rho_cp = 4 186 000 J/(m³·K)
"""

import argparse
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from config import DEFAULT_DB, MW_TO_W, SCALAR_CHANNEL_UNITS
from populate import (
    _RECORDS_BASE as _DEFAULT_RECORDS_BASE,
    _SRV_SUBDIR as _DEFAULT_SRV_SUBDIR,
)
from schema import ensure_schema

DEFAULT_RECORDS_BASE = str(_DEFAULT_RECORDS_BASE)
DEFAULT_SRV_SUBDIR = _DEFAULT_SRV_SUBDIR

# ---------------------------------------------------------------------------
# Defaults  (same as compute_op_stats)
# ---------------------------------------------------------------------------

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

ASSEMBLY_CHANNELS = ["Field", "Pmagnet", "Ptot", "tsb", "teb", "debitbrut"]

# ---------------------------------------------------------------------------
# File loading  (identical logic to compute_op_stats)
# ---------------------------------------------------------------------------


def _compute_dt(df: pd.DataFrame) -> pd.Series:
    if "Date" in df.columns and "Time" in df.columns:
        try:
            ts = pd.to_datetime(
                df["Date"].astype(str) + " " + df["Time"].astype(str),
                format="%Y.%m.%d %H:%M:%S",
            )
            dt = ts.diff().dt.total_seconds().fillna(0.0)
            return dt.clip(lower=0.0)
        except Exception:
            pass
    if "t" in df.columns:
        return df["t"].diff().fillna(0.0).clip(lower=0.0)
    return pd.Series(1.0, index=df.index)


def load_file(path: Path) -> tuple[pd.DataFrame, dict] | None:
    if not path.exists():
        print(f"  [SKIP] not found: {path}")
        return None
    try:
        from python_magnetrun.magnetdata import load_magnetdata

        md = load_magnetdata(str(path))
        md.Units()
        df = md.Data.copy()
        units = md.units
    except Exception:
        try:
            df = pd.read_csv(path, sep="\t", low_memory=False)
            units = {}
        except Exception as exc:
            print(f"  [ERROR] cannot read {path.name}: {exc}")
            return None

    if FIELD_COL not in df.columns:
        print(f"  [SKIP] no '{FIELD_COL}' column in {path.name}")
        return None

    df["dt"] = _compute_dt(df)
    return df, units


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------


def get_experiments(con, assembly_name: str) -> pd.DataFrame:
    return con.execute(
        """
        SELECT e.id, e.name, e.file, s.housing
        FROM experiments e
        JOIN assemblies s ON s.name = e.assembly_name
        WHERE e.assembly_name = ?
        ORDER BY e.name
        """,
        [assembly_name],
    ).df()


def get_assembly_parts(con, assembly_name: str) -> pd.DataFrame:
    return con.execute(
        """
        SELECT p.name AS part_name, mp.coil_index, mp.magnet_name
        FROM assembly_magnets sm
        JOIN magnet_parts mp ON mp.magnet_name = sm.magnet_name
        JOIN parts p         ON p.name = mp.part_name
        WHERE sm.assembly_name = ?
          AND mp.coil_index IS NOT NULL
        ORDER BY mp.coil_index
        """,
        [assembly_name],
    ).df()


def is_processed(con, exp_id: int) -> bool:
    return (
        con.execute(
            "SELECT 1 FROM exp_stats_processed WHERE experiment_id = ?", [exp_id]
        ).fetchone()
        is not None
    )


def mark_processed(con, exp_id: int, df: pd.DataFrame, bins: list[tuple]) -> None:
    dt_median = float(df["dt"][df["dt"] > 0].median()) if (df["dt"] > 0).any() else 0.0
    con.execute(
        """
        INSERT OR REPLACE INTO exp_stats_processed
            (experiment_id, processed_at, n_rows, dt_median, bin_config)
        VALUES (?, now(), ?, ?, ?)
        """,
        [exp_id, len(df), dt_median, json.dumps(bins)],
    )


# ---------------------------------------------------------------------------
# Stat computation  (same helpers as compute_op_stats)
# ---------------------------------------------------------------------------


def _assign_bins(field: pd.Series, bins: list[tuple]) -> pd.Series:
    out = pd.Series(np.nan, index=field.index)
    for low, high in bins:
        mask = (field >= low) & (field < high)
        out[mask] = low
    return out


def _bin_agg(x: pd.Series, dt: pd.Series) -> dict:
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


def _conversion_factor(units: dict, key: str, target_unit, ureg) -> float | None:
    """Scalar multiplier from ``key``'s declared field unit to ``target_unit``.

    Returns ``None`` when ``key``'s unit is unknown (e.g. CSV fallback load
    path), so the caller can fall back to its historical default. Raises
    ``pint.DimensionalityError`` if the declared unit is incompatible with
    ``target_unit``.
    """
    entry = units.get(key)
    declared_unit = entry[1] if entry else None
    if declared_unit is None:
        return None
    return (1.0 * declared_unit).to(target_unit).magnitude


def compute_scalars(
    df: pd.DataFrame,
    flow_to_m3s: float = FLOW_TO_M3S,
    rho_cp: float = RHO_CP,
    units: dict | None = None,
) -> dict[str, float]:
    from python_magnetrun.magnetdata_base import _make_ureg

    ureg = _make_ureg()
    units = units or {}

    dt = df["dt"].astype(float)
    scalars: dict[str, float] = {}

    scalars["duration_s"] = float(dt.sum())

    field_on = df[FIELD_COL].astype(float) > FIELD_THRESHOLD
    scalars["duration_field_on_s"] = float(dt[field_on].sum())

    if "Ptot" in df.columns:
        ptot_to_w = _conversion_factor(units, "Ptot", ureg.watt, ureg)
        if ptot_to_w is None:
            ptot_to_w = MW_TO_W
        scalars["energy_j"] = float((df["Ptot"].astype(float) * ptot_to_w * dt).sum())

    if all(c in df.columns for c in ("tsb", "teb", "debitbrut")):
        for key in ("tsb", "teb"):
            entry = units.get(key)
            if entry and entry[1] is not None:
                if entry[1].dimensionality != ureg.degC.dimensionality:
                    raise ValueError(
                        f"compute_scalars: expected a temperature unit for {key!r}, got {entry[1]}"
                    )
        delta_t = df["tsb"].astype(float) - df["teb"].astype(float)

        debit_to_m3s = _conversion_factor(
            units, "debitbrut", ureg.meter**3 / ureg.second, ureg
        )
        if debit_to_m3s is None:
            debit_to_m3s = flow_to_m3s
        flow_m3s = df["debitbrut"].astype(float) * debit_to_m3s
        scalars["heat_extracted_j"] = float((delta_t * flow_m3s * rho_cp * dt).sum())

    return scalars


def insert_scalars(con, exp_id: int, scalars: dict[str, float]) -> None:
    for channel, value in scalars.items():
        con.execute(
            "INSERT OR REPLACE INTO exp_run_scalars VALUES (?, ?, ?, ?)",
            [exp_id, channel, value, SCALAR_CHANNEL_UNITS.get(channel)],
        )


def compute_assembly_bin_stats(
    df: pd.DataFrame, bins: list[tuple], channels: list[str]
) -> list[dict]:
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


def insert_assembly_bin_stats(con, exp_id: int, rows: list[dict]) -> None:
    for r in rows:
        con.execute(
            """
            INSERT OR REPLACE INTO exp_assembly_bin_stats
                (experiment_id, field_bin_low, field_bin_high, channel,
                 n_samples, sum_dt, sum_x_dt, sum_x2_dt, min_x, max_x)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            [
                exp_id,
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


def compute_part_bin_stats(
    df: pd.DataFrame, bins: list[tuple], part_name: str, coil_index: int
) -> list[dict]:
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

        rows.append(
            {
                "part_name": part_name,
                "field_bin_low": low,
                "field_bin_high": high,
                "channel": "Icoil",
                **_bin_agg(i_sub, dt_sub),
            }
        )

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


def insert_part_bin_stats(con, exp_id: int, rows: list[dict]) -> None:
    for r in rows:
        con.execute(
            """
            INSERT OR REPLACE INTO exp_part_bin_stats
                (experiment_id, part_name, field_bin_low, field_bin_high, channel,
                 n_samples, sum_dt, sum_x_dt, sum_x2_dt, min_x, max_x)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            [
                exp_id,
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


def ingest_assembly(
    assembly_name: str,
    db_path: str,
    records_base: str = DEFAULT_RECORDS_BASE,
    srv_subdir: str = DEFAULT_SRV_SUBDIR,
    bins: list[tuple] = DEFAULT_BINS,
    assembly_channels: list[str] = ASSEMBLY_CHANNELS,
    flow_to_m3s: float = FLOW_TO_M3S,
    rho_cp: float = RHO_CP,
    reprocess: bool = False,
    verbose: bool = True,
) -> dict:
    """Process all experiment files for *assembly_name* and persist stats.

    experiments.file stores only the filename; the full path is reconstructed
    as records_base / srv_subdir / housing / filename.
    If experiments.file is already an absolute path it is used as-is (migration
    backward-compatibility).
    """
    con = duckdb.connect(db_path)
    ensure_schema(con)

    exp_df = get_experiments(con, assembly_name)
    parts = get_assembly_parts(con, assembly_name)

    results = {"new": 0, "skipped": 0, "errors": []}

    for _, row in exp_df.iterrows():
        exp_id = int(row["id"])
        filename = row["file"]
        housing = row["housing"]

        if not reprocess and is_processed(con, exp_id):
            results["skipped"] += 1
            continue

        f = Path(filename)
        path = (
            f
            if f.is_absolute()
            else Path(records_base) / srv_subdir / housing / filename
        )
        result = load_file(path)
        if result is None:
            results["errors"].append(filename)
            continue
        df, units = result

        if verbose:
            print(f"  processing {path.name}  ({len(df)} rows)")

        try:
            scalars = compute_scalars(df, flow_to_m3s, rho_cp, units)
            insert_scalars(con, exp_id, scalars)

            assembly_rows = compute_assembly_bin_stats(df, bins, assembly_channels)
            insert_assembly_bin_stats(con, exp_id, assembly_rows)

            for _, part in parts.iterrows():
                part_rows = compute_part_bin_stats(
                    df, bins, part["part_name"], int(part["coil_index"])
                )
                insert_part_bin_stats(con, exp_id, part_rows)

            mark_processed(con, exp_id, df, bins)
            con.execute(
                """
                    UPDATE experiments
                    SET status = 'STATS DONE'
                    WHERE id = ?
                """,
                [exp_id],
            )

            results["new"] += 1

        except Exception as exc:
            results["errors"].append((filename, str(exc)))
            if verbose:
                print(f"  [ERROR] {path.name}: {exc}")

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
    bins = []
    for pair in s.split(","):
        lo, hi = pair.strip().split(":")
        bins.append((float(lo), float(hi)))
    return bins


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest experiment statistics into DuckDB.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--db", default=DEFAULT_DB, help="DuckDB file path")
    parser.add_argument("--assembly", default=None, help="Assembly name (FK)")
    parser.add_argument(
        "--site", dest="assembly", help=argparse.SUPPRESS
    )  # deprecated alias — keep for one release cycle, then remove
    parser.add_argument(
        "--records-base",
        default=DEFAULT_RECORDS_BASE,
        dest="records_base",
        help=f"Root directory for record files (default: {DEFAULT_RECORDS_BASE})",
    )
    parser.add_argument(
        "--srv-subdir",
        default=DEFAULT_SRV_SUBDIR,
        dest="srv_subdir",
        help=f"Subdirectory under records-base for pupitre TXT files (default: {DEFAULT_SRV_SUBDIR})",
    )
    parser.add_argument(
        "--bins",
        default=None,
        help="Field bins as 'low1:high1,low2:high2,...' (default: built-in 10-bin set)",
    )
    parser.add_argument(
        "--channels",
        default=",".join(ASSEMBLY_CHANNELS),
        help="Comma-separated assembly-level channels",
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
    if args.assembly is None:
        parser.error("the following arguments are required: --assembly")

    bins = _parse_bins(args.bins) if args.bins else DEFAULT_BINS
    channels = [c.strip() for c in args.channels.split(",") if c.strip()]

    ingest_assembly(
        assembly_name=args.assembly,
        db_path=args.db,
        records_base=args.records_base,
        srv_subdir=args.srv_subdir,
        bins=bins,
        assembly_channels=channels,
        flow_to_m3s=args.flow_to_m3s,
        reprocess=args.reprocess,
        verbose=not args.quiet,
    )


if __name__ == "__main__":
    main()
