#!/usr/bin/env python
"""Plot rainflow fatigue cycles for a magnet's parts across a list of experiments.

Reads the already-persisted fatigue results from ``hoop_stress_fatigue``
(per-experiment, per-part cycle totals) and ``hoop_stress_fatigue_bins``
(per-experiment, per-part rainflow range-bin matrix), both written by
``magnetdb.py hoop-stress compute``. No fatigue computation is performed
here — pairs with no rows in either table are skipped with a hint pointing
at that command.

``--parts`` is optional: when omitted (or empty), it defaults to every part
of ``--magnet`` whose type is ``helix``, ``bitter``, or ``supra`` (the coil
types the hoop-stress pipeline covers); when given explicitly, the same type
filter is applied and anything else is dropped with a warning.

For each part, three PNGs are produced (all experiments combined onto a
single figure each):

  - ``fatigue_cycles_<magnet>_<part>.png``    — cycle count per experiment
  - ``fatigue_histogram_<magnet>_<part>.png`` — cycle histogram (stress-range
    bins), grouped by experiment
  - ``fatigue_combined_<magnet>_<part>.png``  — the same histogram summed
    across the whole experiment list

A cycle-count table (experiments x parts, with row/column totals and a
grand-total ``TOTAL`` row) is printed to stdout.

Run from the repository root, e.g.::

    python to_duckdb/demos/plot_magnet_fatigue.py --magnet M9Bitters \\
        --experiments "2023.06.09 - 09:43:40" "2023.06.09 - 10:21:37"
    python to_duckdb/demos/plot_magnet_fatigue.py --magnet M9Bitters \\
        --parts M9Be --experiments "2023.06.09 - 09:43:40" \\
        --db to_duckdb/test-magnetdb.duckdb --output-dir stage/
"""

import argparse
import re
import sys
from pathlib import Path

import duckdb
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import DEFAULT_DB  # noqa: E402

_COIL_TYPES = ("helix", "bitter", "supra")


def _get_experiment_row(con, experiment_name: str) -> dict | None:
    row = con.execute(
        "SELECT id, assembly_name FROM experiments WHERE name = ?",
        [experiment_name],
    ).fetchone()
    if row is None:
        return None
    return {"id": row[0], "assembly_name": row[1]}


def _get_parts_for_magnet(con, magnet_name: str) -> list[str]:
    rows = con.execute(
        """
        SELECT p.name
        FROM magnet_parts mp
        JOIN parts p ON p.name = mp.part_name
        WHERE mp.magnet_name = ? AND LOWER(p.type) IN ('helix', 'bitter', 'supra')
        ORDER BY mp.rank NULLS LAST, mp.part_name
        """,
        [magnet_name],
    ).fetchall()
    return [r[0] for r in rows]


def _filter_parts_by_type(con, part_names: list[str]) -> list[str]:
    kept = []
    for name in part_names:
        row = con.execute("SELECT type FROM parts WHERE name = ?", [name]).fetchone()
        if row is None:
            print(f"[WARN] part {name!r} not found in parts table, skipping")
            continue
        part_type = (row[0] or "").lower()
        if part_type not in _COIL_TYPES:
            print(f"[WARN] part {name!r} has type {row[0]!r}, not helix/bitter/supra, skipping")
            continue
        kept.append(name)
    return kept


def _get_n_cycles(con, experiment_id: int, part_name: str) -> float | None:
    row = con.execute(
        "SELECT n_cycles FROM hoop_stress_fatigue WHERE experiment_id = ? AND part_name = ?",
        [experiment_id, part_name],
    ).fetchone()
    return row[0] if row is not None else None


def _get_range_histogram(con, experiment_id: int, part_name: str) -> list[tuple[float, float, float]]:
    return con.execute(
        """
        SELECT range_bin_low, range_bin_high, SUM(count) AS n
        FROM hoop_stress_fatigue_bins
        WHERE experiment_id = ? AND part_name = ?
        GROUP BY range_bin_low, range_bin_high
        ORDER BY range_bin_low
        """,
        [experiment_id, part_name],
    ).fetchall()


def _sanitize(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name)


def _empty_axes(ax, message: str) -> None:
    ax.text(0.5, 0.5, message, ha="center", va="center", transform=ax.transAxes, color="gray")
    ax.set_xticks([])
    ax.set_yticks([])


def _save(fig, output_dir: Path, filename: str) -> None:
    fig.tight_layout()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_png = output_dir / filename
    fig.savefig(output_png, dpi=150)
    plt.close(fig)
    print(f"  Plot saved to {output_png}")


def plot_cycles_per_experiment(
    magnet: str, part: str, exp_names: list[str], n_cycles: list[float | None], output_dir: Path,
) -> None:
    fig, ax = plt.subplots(figsize=(max(6, len(exp_names) * 0.8), 5))
    if any(v is not None for v in n_cycles):
        ax.bar(exp_names, [v if v is not None else 0.0 for v in n_cycles])
        ax.set_ylabel("Cycles")
        ax.tick_params(axis="x", rotation=45)
        for label in ax.get_xticklabels():
            label.set_ha("right")
    else:
        _empty_axes(ax, "no fatigue data available")
    ax.set_title(f"{magnet} — {part} — cycles per experiment")
    _save(fig, output_dir, f"fatigue_cycles_{_sanitize(magnet)}_{_sanitize(part)}.png")


def plot_histogram_by_experiment(
    magnet: str, part: str, exp_names: list[str],
    bins_per_exp: dict[str, list[tuple[float, float, float]]], output_dir: Path,
) -> None:
    fig, ax = plt.subplots(figsize=(max(8, len(exp_names) * 1.5), 6))
    all_edges = sorted({(low, high) for rows in bins_per_exp.values() for low, high, _ in rows})
    if all_edges:
        labels = [f"{low:g}-{high:g}" for low, high in all_edges]
        x = np.arange(len(all_edges))
        n_exp = len(exp_names)
        width = 0.8 / n_exp
        for i, exp_name in enumerate(exp_names):
            lookup = {(low, high): n for low, high, n in bins_per_exp.get(exp_name, [])}
            values = [lookup.get(edge, 0.0) for edge in all_edges]
            ax.bar(x + i * width - 0.4 + width / 2, values, width=width, label=exp_name)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=45, ha="right")
        ax.set_xlabel("Stress range bin [MPa]")
        ax.set_ylabel("Cycles")
        ax.legend(fontsize="small")
    else:
        _empty_axes(ax, "no fatigue-bin data available")
    ax.set_title(f"{magnet} — {part} — cycle histogram per experiment")
    _save(fig, output_dir, f"fatigue_histogram_{_sanitize(magnet)}_{_sanitize(part)}.png")


def plot_combined_histogram(
    magnet: str, part: str, bins_per_exp: dict[str, list[tuple[float, float, float]]], output_dir: Path,
) -> None:
    fig, ax = plt.subplots(figsize=(8, 5))
    combined: dict[tuple[float, float], float] = {}
    for rows in bins_per_exp.values():
        for low, high, n in rows:
            combined[(low, high)] = combined.get((low, high), 0.0) + n
    if combined:
        edges = sorted(combined.keys())
        labels = [f"{low:g}-{high:g}" for low, high in edges]
        ax.bar(labels, [combined[e] for e in edges])
        ax.set_xlabel("Stress range bin [MPa]")
        ax.set_ylabel("Cycles (summed over experiments)")
        ax.tick_params(axis="x", rotation=45)
    else:
        _empty_axes(ax, "no fatigue-bin data available")
    ax.set_title(f"{magnet} — {part} — combined cycle histogram ({len(bins_per_exp)} experiments)")
    _save(fig, output_dir, f"fatigue_combined_{_sanitize(magnet)}_{_sanitize(part)}.png")


def build_table(exp_names: list[str], parts: list[str], n_cycles_map: dict[str, dict[str, float]]) -> pd.DataFrame:
    table = pd.DataFrame(
        [[n_cycles_map[exp_name][part] for part in parts] for exp_name in exp_names],
        index=exp_names, columns=parts, dtype=float,
    )
    table["Total"] = table.sum(axis=1)
    total_row = table.sum(axis=0)
    total_row.name = "TOTAL"
    return pd.concat([table, total_row.to_frame().T])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--magnet", required=True, help="Magnet name (magnets.name)")
    parser.add_argument("--experiments", required=True, nargs="+", help="Experiment names (experiments.name)")
    parser.add_argument(
        "--parts", nargs="*", default=None,
        help="Part names (parts.name), restricted to helix/bitter/supra types. "
             "Default: all helix/bitter/supra parts of --magnet.",
    )
    parser.add_argument("--db", default=DEFAULT_DB, help=f"DuckDB file (default: {DEFAULT_DB})")
    parser.add_argument("--output-dir", default=".", help="Directory to save PNG figures into (default: .)")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Error: '{db_path}' does not exist.")
        sys.exit(1)

    output_dir = Path(args.output_dir)

    with duckdb.connect(str(db_path), read_only=True) as con:
        if args.parts:
            parts = _filter_parts_by_type(con, args.parts)
        else:
            parts = _get_parts_for_magnet(con, args.magnet)
        if not parts:
            print("Error: no eligible helix/bitter/supra parts to analyze.")
            sys.exit(1)

        valid_experiments = []
        for name in args.experiments:
            exp = _get_experiment_row(con, name)
            if exp is None:
                print(f"[WARN] experiment {name!r} not found in experiments table, skipping")
                continue
            valid_experiments.append((name, exp["id"], exp["assembly_name"]))
        if not valid_experiments:
            print("Error: no valid experiments to analyze.")
            sys.exit(1)

        exp_names = [e[0] for e in valid_experiments]
        n_cycles_map: dict[str, dict[str, float]] = {name: {} for name in exp_names}

        for part in parts:
            print(f"[{part}]")
            cycles_list = []
            bins_per_exp = {}
            for exp_name, exp_id, assembly_name in valid_experiments:
                n = _get_n_cycles(con, exp_id, part)
                if n is None:
                    print(f"  [WARN] {exp_name}: no hoop_stress_fatigue row for part {part!r}. "
                          f"Run `python magnetdb.py hoop-stress compute --assembly {assembly_name}` first.")
                cycles_list.append(n)
                n_cycles_map[exp_name][part] = n if n is not None else 0.0

                rows = _get_range_histogram(con, exp_id, part)
                if not rows:
                    print(f"  [WARN] {exp_name}: no hoop_stress_fatigue_bins rows for part {part!r}.")
                else:
                    bins_per_exp[exp_name] = rows

            plot_cycles_per_experiment(args.magnet, part, exp_names, cycles_list, output_dir)
            plot_histogram_by_experiment(args.magnet, part, exp_names, bins_per_exp, output_dir)
            plot_combined_histogram(args.magnet, part, bins_per_exp, output_dir)

        table = build_table(exp_names, parts, n_cycles_map)
        print()
        print(table.to_string())


if __name__ == "__main__":
    main()
