"""
query_cumstats.py
=================
Query and display cumulative operational and experiment statistics from DuckDB.

All queries read only from the pre-computed tables (op_run_scalars,
op_assembly_bin_stats, op_part_bin_stats, exp_run_scalars, exp_assembly_bin_stats,
exp_part_bin_stats) — no raw record files are touched.

Aggregation rules
-----------------
  operating time (h)    = SUM(sum_dt) / 3600
  time-weighted mean    = SUM(sum_x_dt) / SUM(sum_dt)
  time-weighted std     = sqrt(SUM(sum_x2_dt)/SUM(sum_dt) - mean^2)
  cumulative energy/etc = SUM(sum_x_dt)   [for integral channels]
  peak value            = MAX(max_x)

Usage
-----
    # Cumulative scalars for an assembly (operational data)
    python query_cumstats.py --db magnetdb.duckdb --assembly M9_M19061901 scalars

    # Field-bin histogram for an assembly (time + Ptot mean)
    python query_cumstats.py --db magnetdb.duckdb --assembly M9_M19061901 assembly-bins

    # Field-bin stats per magnet
    python query_cumstats.py --db magnetdb.duckdb --magnet M9Bitters magnet-bins

    # Field-bin stats per part
    python query_cumstats.py --db magnetdb.duckdb --part M9Bi part-bins

    # All of the above with plots
    python query_cumstats.py --db magnetdb.duckdb --assembly M9_M19061901 assembly-bins --plot

    # Same queries for experiment data
    python query_cumstats.py --db magnetdb.duckdb --assembly M9_M19061901 exp-scalars
    python query_cumstats.py --db magnetdb.duckdb --assembly M9_M19061901 exp-assembly-bins
    python query_cumstats.py --db magnetdb.duckdb --magnet M9Bitters exp-magnet-bins
    python query_cumstats.py --db magnetdb.duckdb --part M9Bi exp-part-bins

    # Filter experiment queries by experiment name
    python query_cumstats.py --db magnetdb.duckdb --assembly M9_M19061901 --experiment myrun exp-assembly-bins
"""

import argparse
import sys
from pathlib import Path

import duckdb
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import DEFAULT_DB, J_TO_MWH

# optional imports — used only for plotting
try:
    import matplotlib.pyplot as plt
    _HAS_MPL = True
except ImportError:
    _HAS_MPL = False

# ---------------------------------------------------------------------------
# Scalar queries
# ---------------------------------------------------------------------------

def query_scalars(con, *, assembly_name: str | None = None,
                  magnet_name: str | None = None) -> pd.DataFrame:
    """Total scalar stats across all processed files for an assembly or magnet."""
    if assembly_name:
        where = "od.assembly_name = ?"
        params = [assembly_name]
    elif magnet_name:
        where = "sm.magnet_name = ?"
        params = [magnet_name]
    else:
        raise ValueError("Provide assembly_name or magnet_name")

    join = (
        "JOIN assembly_magnets sm ON sm.assembly_name = od.assembly_name" if magnet_name else ""
    )

    return con.execute(f"""
        SELECT
            s.channel,
            COUNT(DISTINCT s.operationaldata_id) AS n_files,
            SUM(s.value)                          AS total
        FROM op_run_scalars s
        JOIN operationaldata od ON od.id = s.operationaldata_id
        {join}
        WHERE {where}
        GROUP BY s.channel
        ORDER BY s.channel
    """, params).df()


# ---------------------------------------------------------------------------
# Assembly-level bin queries
# ---------------------------------------------------------------------------

def query_assembly_bins(
    con,
    assembly_name: str,
    channels: list[str] | None = None,
) -> pd.DataFrame:
    """Cumulative field-bin stats for an assembly.

    Returns one row per (field_bin_low, field_bin_high, channel) with:
      hours, mean_x, std_x, min_x, max_x
    """
    ch_filter = ""
    params: list = [assembly_name]
    if channels:
        placeholders = ",".join("?" * len(channels))
        ch_filter = f"AND s.channel IN ({placeholders})"
        params += channels

    return con.execute(f"""
        SELECT
            s.field_bin_low,
            s.field_bin_high,
            s.channel,
            SUM(s.sum_dt) / 3600                              AS hours,
            SUM(s.sum_x_dt) / NULLIF(SUM(s.sum_dt), 0)       AS mean_x,
            sqrt(
                GREATEST(
                    SUM(s.sum_x2_dt) / NULLIF(SUM(s.sum_dt), 0)
                    - power(SUM(s.sum_x_dt) / NULLIF(SUM(s.sum_dt), 0), 2),
                    0.0
                )
            )                                                  AS std_x,
            MIN(s.min_x)                                       AS min_x,
            MAX(s.max_x)                                       AS max_x
        FROM op_assembly_bin_stats s
        JOIN operationaldata od ON od.id = s.operationaldata_id
        WHERE od.assembly_name = ?
          {ch_filter}
        GROUP BY s.field_bin_low, s.field_bin_high, s.channel
        ORDER BY s.channel, s.field_bin_low
    """, params).df()


# ---------------------------------------------------------------------------
# Magnet-level bin queries
# ---------------------------------------------------------------------------

def query_magnet_bins(
    con,
    magnet_name: str,
    channels: list[str] | None = None,
) -> pd.DataFrame:
    """Cumulative field-bin stats for all parts of a magnet."""
    ch_filter = ""
    params: list = [magnet_name]
    if channels:
        placeholders = ",".join("?" * len(channels))
        ch_filter = f"AND s.channel IN ({placeholders})"
        params += channels

    return con.execute(f"""
        SELECT
            s.part_name,
            s.field_bin_low,
            s.field_bin_high,
            s.channel,
            SUM(s.sum_dt) / 3600                              AS hours,
            SUM(s.sum_x_dt) / NULLIF(SUM(s.sum_dt), 0)       AS mean_x,
            sqrt(
                GREATEST(
                    SUM(s.sum_x2_dt) / NULLIF(SUM(s.sum_dt), 0)
                    - power(SUM(s.sum_x_dt) / NULLIF(SUM(s.sum_dt), 0), 2),
                    0.0
                )
            )                                                  AS std_x,
            MIN(s.min_x)                                       AS min_x,
            MAX(s.max_x)                                       AS max_x
        FROM op_part_bin_stats s
        JOIN operationaldata od  ON od.id = s.operationaldata_id
        JOIN assembly_magnets sm ON sm.assembly_name = od.assembly_name
        JOIN magnet_parts mp     ON mp.magnet_name = sm.magnet_name
                                AND mp.part_name   = s.part_name
        WHERE sm.magnet_name = ?
          {ch_filter}
        GROUP BY s.part_name, s.field_bin_low, s.field_bin_high, s.channel
        ORDER BY s.part_name, s.channel, s.field_bin_low
    """, params).df()


# ---------------------------------------------------------------------------
# Part-level bin queries
# ---------------------------------------------------------------------------

def query_part_bins(
    con,
    part_name: str,
    channels: list[str] | None = None,
) -> pd.DataFrame:
    """Cumulative field-bin stats for a single part across all assemblies and runs."""
    ch_filter = ""
    params: list = [part_name]
    if channels:
        placeholders = ",".join("?" * len(channels))
        ch_filter = f"AND s.channel IN ({placeholders})"
        params += channels

    return con.execute(f"""
        SELECT
            s.field_bin_low,
            s.field_bin_high,
            s.channel,
            SUM(s.sum_dt) / 3600                              AS hours,
            SUM(s.sum_x_dt) / NULLIF(SUM(s.sum_dt), 0)       AS mean_x,
            sqrt(
                GREATEST(
                    SUM(s.sum_x2_dt) / NULLIF(SUM(s.sum_dt), 0)
                    - power(SUM(s.sum_x_dt) / NULLIF(SUM(s.sum_dt), 0), 2),
                    0.0
                )
            )                                                  AS std_x,
            MIN(s.min_x)                                       AS min_x,
            MAX(s.max_x)                                       AS max_x
        FROM op_part_bin_stats s
        WHERE s.part_name = ?
          {ch_filter}
        GROUP BY s.field_bin_low, s.field_bin_high, s.channel
        ORDER BY s.channel, s.field_bin_low
    """, params).df()


# ---------------------------------------------------------------------------
# Experiment scalar queries
# ---------------------------------------------------------------------------

def query_exp_scalars(con, *, assembly_name: str | None = None,
                      magnet_name: str | None = None,
                      experiment_name: str | None = None) -> pd.DataFrame:
    """Total scalar stats across all processed experiments for an assembly or magnet."""
    if assembly_name:
        where = "e.assembly_name = ?"
        params: list = [assembly_name]
    elif magnet_name:
        where = "sm.magnet_name = ?"
        params = [magnet_name]
    else:
        raise ValueError("Provide assembly_name or magnet_name")

    join = (
        "JOIN assembly_magnets sm ON sm.assembly_name = e.assembly_name" if magnet_name else ""
    )
    exp_filter = ""
    if experiment_name:
        exp_filter = "AND e.name = ?"
        params.append(experiment_name)

    return con.execute(f"""
        SELECT
            s.channel,
            COUNT(DISTINCT s.experiment_id) AS n_experiments,
            SUM(s.value)                     AS total
        FROM exp_run_scalars s
        JOIN experiments e ON e.id = s.experiment_id
        {join}
        WHERE {where}
          {exp_filter}
        GROUP BY s.channel
        ORDER BY s.channel
    """, params).df()


# ---------------------------------------------------------------------------
# Experiment assembly-level bin queries
# ---------------------------------------------------------------------------

def query_exp_assembly_bins(
    con,
    assembly_name: str,
    channels: list[str] | None = None,
    experiment_name: str | None = None,
) -> pd.DataFrame:
    """Cumulative field-bin stats for an assembly across all its experiments."""
    params: list = [assembly_name]
    ch_filter = ""
    if channels:
        placeholders = ",".join("?" * len(channels))
        ch_filter = f"AND s.channel IN ({placeholders})"
        params += channels
    exp_filter = ""
    if experiment_name:
        exp_filter = "AND e.name = ?"
        params.append(experiment_name)

    return con.execute(f"""
        SELECT
            s.field_bin_low,
            s.field_bin_high,
            s.channel,
            SUM(s.sum_dt) / 3600                              AS hours,
            SUM(s.sum_x_dt) / NULLIF(SUM(s.sum_dt), 0)       AS mean_x,
            sqrt(
                GREATEST(
                    SUM(s.sum_x2_dt) / NULLIF(SUM(s.sum_dt), 0)
                    - power(SUM(s.sum_x_dt) / NULLIF(SUM(s.sum_dt), 0), 2),
                    0.0
                )
            )                                                  AS std_x,
            MIN(s.min_x)                                       AS min_x,
            MAX(s.max_x)                                       AS max_x
        FROM exp_assembly_bin_stats s
        JOIN experiments e ON e.id = s.experiment_id
        WHERE e.assembly_name = ?
          {ch_filter}
          {exp_filter}
        GROUP BY s.field_bin_low, s.field_bin_high, s.channel
        ORDER BY s.channel, s.field_bin_low
    """, params).df()


# ---------------------------------------------------------------------------
# Experiment magnet-level bin queries
# ---------------------------------------------------------------------------

def query_exp_magnet_bins(
    con,
    magnet_name: str,
    channels: list[str] | None = None,
    experiment_name: str | None = None,
) -> pd.DataFrame:
    """Cumulative field-bin stats for all parts of a magnet across its experiments."""
    params: list = [magnet_name]
    ch_filter = ""
    if channels:
        placeholders = ",".join("?" * len(channels))
        ch_filter = f"AND s.channel IN ({placeholders})"
        params += channels
    exp_filter = ""
    if experiment_name:
        exp_filter = "AND e.name = ?"
        params.append(experiment_name)

    return con.execute(f"""
        SELECT
            s.part_name,
            s.field_bin_low,
            s.field_bin_high,
            s.channel,
            SUM(s.sum_dt) / 3600                              AS hours,
            SUM(s.sum_x_dt) / NULLIF(SUM(s.sum_dt), 0)       AS mean_x,
            sqrt(
                GREATEST(
                    SUM(s.sum_x2_dt) / NULLIF(SUM(s.sum_dt), 0)
                    - power(SUM(s.sum_x_dt) / NULLIF(SUM(s.sum_dt), 0), 2),
                    0.0
                )
            )                                                  AS std_x,
            MIN(s.min_x)                                       AS min_x,
            MAX(s.max_x)                                       AS max_x
        FROM exp_part_bin_stats s
        JOIN experiments e   ON e.id          = s.experiment_id
        JOIN assembly_magnets sm ON sm.assembly_name  = e.assembly_name
        JOIN magnet_parts mp ON mp.magnet_name = sm.magnet_name
                             AND mp.part_name  = s.part_name
        WHERE sm.magnet_name = ?
          {ch_filter}
          {exp_filter}
        GROUP BY s.part_name, s.field_bin_low, s.field_bin_high, s.channel
        ORDER BY s.part_name, s.channel, s.field_bin_low
    """, params).df()


# ---------------------------------------------------------------------------
# Experiment part-level bin queries
# ---------------------------------------------------------------------------

def query_exp_part_bins(
    con,
    part_name: str,
    channels: list[str] | None = None,
    experiment_name: str | None = None,
) -> pd.DataFrame:
    """Cumulative field-bin stats for a single part across all experiments."""
    params: list = [part_name]
    ch_filter = ""
    if channels:
        placeholders = ",".join("?" * len(channels))
        ch_filter = f"AND s.channel IN ({placeholders})"
        params += channels
    exp_filter = ""
    if experiment_name:
        exp_filter = "AND e.name = ?"
        params.append(experiment_name)

    join = "JOIN experiments e ON e.id = s.experiment_id" if experiment_name else ""

    return con.execute(f"""
        SELECT
            s.field_bin_low,
            s.field_bin_high,
            s.channel,
            SUM(s.sum_dt) / 3600                              AS hours,
            SUM(s.sum_x_dt) / NULLIF(SUM(s.sum_dt), 0)       AS mean_x,
            sqrt(
                GREATEST(
                    SUM(s.sum_x2_dt) / NULLIF(SUM(s.sum_dt), 0)
                    - power(SUM(s.sum_x_dt) / NULLIF(SUM(s.sum_dt), 0), 2),
                    0.0
                )
            )                                                  AS std_x,
            MIN(s.min_x)                                       AS min_x,
            MAX(s.max_x)                                       AS max_x
        FROM exp_part_bin_stats s
        {join}
        WHERE s.part_name = ?
          {ch_filter}
          {exp_filter}
        GROUP BY s.field_bin_low, s.field_bin_high, s.channel
        ORDER BY s.channel, s.field_bin_low
    """, params).df()


# ---------------------------------------------------------------------------
# Printing helpers
# ---------------------------------------------------------------------------

_SCALAR_LABELS = {
    "duration_s":          ("Total duration",         "h",   1/3600),
    "duration_field_on_s": ("Field-on duration",      "h",   1/3600),
    "energy_j":            ("Electrical energy",      "MWh", 1/J_TO_MWH),
    "heat_extracted_j":    ("Heat extracted",         "MWh", 1/J_TO_MWH),
}


def print_scalars(df: pd.DataFrame, scope: str) -> None:
    count_col, count_label = (
        ("n_files", "files") if "n_files" in df.columns else ("n_experiments", "experiments")
    )
    print(f"\n{'─'*55}")
    print(f"  Scalar statistics — {scope}")
    print(f"{'─'*55}")
    for _, row in df.iterrows():
        ch = row["channel"]
        label, unit, scale = _SCALAR_LABELS.get(ch, (ch, "", 1.0))
        val = row["total"] * scale
        print(f"  {label:<30}  {val:>12.3f}  {unit}  ({int(row[count_col])} {count_label})")


def print_bins(df: pd.DataFrame, scope: str) -> None:
    for ch, grp in df.groupby("channel"):
        print(f"\n{'─'*70}")
        print(f"  {ch} — {scope}")
        print(f"  {'Bin (T)':<15} {'Hours':>9} {'Mean':>12} {'Std':>10} {'Min':>10} {'Max':>10}")
        print(f"{'─'*70}")
        for _, r in grp.iterrows():
            label = f"{r['field_bin_low']:.1f}–{r['field_bin_high']:.1f}"
            mean  = r["mean_x"] if pd.notna(r["mean_x"]) else float("nan")
            std   = r["std_x"]  if pd.notna(r["std_x"])  else float("nan")
            print(
                f"  {label:<15} {r['hours']:>9.3f} {mean:>12.3f} "
                f"{std:>10.3f} {r['min_x']:>10.3f} {r['max_x']:>10.3f}"
            )


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------

def _bar_bins(ax, grp: pd.DataFrame, label: str, color: str) -> None:
    widths = grp["field_bin_high"] - grp["field_bin_low"]
    ax.bar(
        grp["field_bin_low"], grp["hours"],
        width=widths * 0.85, align="edge",
        label=label, color=color, edgecolor="white", alpha=0.85,
    )


def plot_assembly_bins(df: pd.DataFrame, assembly_name: str) -> None:
    if not _HAS_MPL:
        print("matplotlib not available — skipping plots")
        return
    channels = df["channel"].unique()
    _fig, axes = plt.subplots(1, len(channels), figsize=(7 * len(channels), 5), squeeze=False)
    colors = plt.rcParams["axes.prop_cycle"].by_key()["color"]
    for ax, ch in zip(axes[0], channels):
        grp = df[df["channel"] == ch]
        _bar_bins(ax, grp, ch, colors[0])
        ax.set_xlabel("Magnetic field (T)")
        ax.set_ylabel("Hours")
        ax.set_title(f"{assembly_name} — {ch}")
        ax.grid(axis="y", alpha=0.4)
    plt.tight_layout()
    fname = f"cumstats_assembly_{assembly_name}.png"
    plt.savefig(fname, dpi=150)
    print(f"Saved {fname}")
    plt.show()


def plot_part_bins(df: pd.DataFrame, scope: str, label_col: str = "channel") -> None:
    if not _HAS_MPL:
        print("matplotlib not available — skipping plots")
        return
    channels = df["channel"].unique()
    parts    = df["part_name"].unique() if "part_name" in df.columns else [None]
    colors   = plt.rcParams["axes.prop_cycle"].by_key()["color"]

    for ch in channels:
        sub = df[df["channel"] == ch]
        _fig, ax = plt.subplots(figsize=(10, 5))
        for idx, part in enumerate(parts if parts[0] is not None else [None]):
            grp = sub[sub["part_name"] == part] if part else sub
            if grp.empty:
                continue
            widths = grp["field_bin_high"] - grp["field_bin_low"]
            offset = idx * widths.mean() * 0.4 if len(parts) > 1 else 0
            ax.bar(
                grp["field_bin_low"] + offset, grp["hours"],
                width=widths * 0.85 / max(len(parts), 1),
                align="edge", label=str(part), color=colors[idx % len(colors)],
                edgecolor="white", alpha=0.85,
            )
        ax.set_xlabel("Magnetic field (T)")
        ax.set_ylabel("Hours")
        ax.set_title(f"{scope} — {ch}")
        if parts[0] is not None and len(parts) > 1:
            ax.legend(title="Part")
        ax.grid(axis="y", alpha=0.4)
        plt.tight_layout()
        fname = f"cumstats_{scope.replace(' ', '_')}_{ch}.png"
        plt.savefig(fname, dpi=150)
        print(f"Saved {fname}")
        plt.show()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

SUBCOMMANDS = {
    "scalars":            "Per-run scalar totals (energy, duration, heat) — operational data",
    "assembly-bins":      "Assembly-level field-bin distributions — operational data",
    "magnet-bins":        "Per-part field-bin distributions for a magnet — operational data",
    "part-bins":          "Field-bin distributions for a single part — operational data",
    "exp-scalars":        "Per-experiment scalar totals — experiment data",
    "exp-assembly-bins":  "Assembly-level field-bin distributions — experiment data",
    "exp-magnet-bins":    "Per-part field-bin distributions for a magnet — experiment data",
    "exp-part-bins":      "Field-bin distributions for a single part — experiment data",
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Query cumulative operational statistics from DuckDB.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\n".join(f"  {k:<14} {v}" for k, v in SUBCOMMANDS.items()),
    )
    parser.add_argument("command",    choices=list(SUBCOMMANDS))
    parser.add_argument("--db",       default=DEFAULT_DB)
    parser.add_argument("--assembly", default=None,  help="Assembly name")
    parser.add_argument("--magnet",   default=None,  help="Magnet name")
    parser.add_argument("--part",     default=None,  help="Part name")
    parser.add_argument("--channels",   default=None,
                        help="Comma-separated channel filter, e.g. 'Ptot,tsb'")
    parser.add_argument("--experiment", default=None,
                        help="Filter by experiment name (exp-* commands only)")
    parser.add_argument("--plot",       action="store_true", help="Show and save plots")
    args = parser.parse_args()

    channels = [c.strip() for c in args.channels.split(",")] if args.channels else None

    con = duckdb.connect(args.db, read_only=True)

    if args.command == "scalars":
        if not args.assembly and not args.magnet:
            parser.error("scalars requires --assembly or --magnet")
        df = query_scalars(con, assembly_name=args.assembly, magnet_name=args.magnet)
        scope = args.assembly or args.magnet
        print_scalars(df, scope)

    elif args.command == "assembly-bins":
        if not args.assembly:
            parser.error("assembly-bins requires --assembly")
        df = query_assembly_bins(con, args.assembly, channels)
        print_bins(df, f"assembly {args.assembly}")
        if args.plot:
            plot_assembly_bins(df, args.assembly)

    elif args.command == "magnet-bins":
        if not args.magnet:
            parser.error("magnet-bins requires --magnet")
        df = query_magnet_bins(con, args.magnet, channels)
        print_bins(df, f"magnet {args.magnet}")
        if args.plot:
            plot_part_bins(df, f"magnet {args.magnet}")

    elif args.command == "part-bins":
        if not args.part:
            parser.error("part-bins requires --part")
        df = query_part_bins(con, args.part, channels)
        # no part_name column here — add it for the shared plot helper
        df.insert(0, "part_name", args.part)
        print_bins(df, f"part {args.part}")
        if args.plot:
            plot_part_bins(df, f"part {args.part}")

    elif args.command == "exp-scalars":
        if not args.assembly and not args.magnet:
            parser.error("exp-scalars requires --assembly or --magnet")
        df = query_exp_scalars(
            con, assembly_name=args.assembly, magnet_name=args.magnet,
            experiment_name=args.experiment,
        )
        scope = args.assembly or args.magnet
        print_scalars(df, f"{scope} [experiments]")

    elif args.command == "exp-assembly-bins":
        if not args.assembly:
            parser.error("exp-assembly-bins requires --assembly")
        df = query_exp_assembly_bins(con, args.assembly, channels, args.experiment)
        print_bins(df, f"assembly {args.assembly} [experiments]")
        if args.plot:
            plot_assembly_bins(df, args.assembly)

    elif args.command == "exp-magnet-bins":
        if not args.magnet:
            parser.error("exp-magnet-bins requires --magnet")
        df = query_exp_magnet_bins(con, args.magnet, channels, args.experiment)
        print_bins(df, f"magnet {args.magnet} [experiments]")
        if args.plot:
            plot_part_bins(df, f"magnet {args.magnet} [experiments]")

    elif args.command == "exp-part-bins":
        if not args.part:
            parser.error("exp-part-bins requires --part")
        df = query_exp_part_bins(con, args.part, channels, args.experiment)
        df.insert(0, "part_name", args.part)
        print_bins(df, f"part {args.part} [experiments]")
        if args.plot:
            plot_part_bins(df, f"part {args.part} [experiments]")

    con.close()


if __name__ == "__main__":
    main()
