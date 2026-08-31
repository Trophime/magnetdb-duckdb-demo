#!/usr/bin/env python
"""Plot magnetic field and hoop stress for a magnet across a list of experiments.

For each experiment given via ``--experiments``:

  - Loads the raw pupitre file (via ``python_magnetrun.MagnetRun.load_mrun``, the
    same call the dashboard's File Viewer page uses) and plots its ``Field`` [T]
    channel vs ``t``.
  - Looks up ``hoop_stress_processed.parquet_path`` for the experiment and, **if
    the Parquet file already exists on disk**, loads it directly and plots the
    hoop-stress [MPa] columns for the magnet's parts vs ``t``. No hoop-stress
    computation is performed here — if the Parquet is missing, that panel is
    skipped with a hint pointing at ``magnetdb.py hoop-stress compute``.

One PNG figure (Field on top, hoop stress on bottom, sharing the time axis) is
saved per experiment.

Run from the repository root, e.g.::

    python to_duckdb/demos/plot_magnet_stress.py --magnet M19061901 \\
        --experiments "2019.06.19 - 17:00:45" "2019.06.19 - 17:04:21"
    python to_duckdb/demos/plot_magnet_stress.py --magnet M19061901 \\
        --experiments "2019.06.19 - 17:00:45" --db to_duckdb/test-magnetdb.duckdb
"""

import argparse
import re
import sys
from pathlib import Path

import duckdb
import matplotlib.pyplot as plt
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import DEFAULT_DB  # noqa: E402


def _get_experiment_row(con, experiment_name: str) -> dict | None:
    row = con.execute(
        """
        SELECT e.id, e.file, e.assembly_name, a.housing
        FROM experiments e
        LEFT JOIN assemblies a ON a.name = e.assembly_name
        WHERE e.name = ?
        """,
        [experiment_name],
    ).fetchone()
    if row is None:
        return None
    return {"id": row[0], "file": row[1], "assembly_name": row[2], "housing": row[3]}


def _get_parts_for_magnet(con, magnet_name: str) -> list[str]:
    rows = con.execute(
        """
        SELECT p.name
        FROM magnet_parts mp
        JOIN parts p ON p.name = mp.part_name
        WHERE mp.magnet_name = ?
        ORDER BY mp.rank NULLS LAST, mp.part_name
        """,
        [magnet_name],
    ).fetchall()
    return [r[0] for r in rows]


def _get_hoop_parquet_path(con, experiment_id: int, db_path: Path) -> Path | None:
    row = con.execute(
        """
        SELECT parquet_path
        FROM hoop_stress_processed
        WHERE experiment_id = ? AND parquet_path IS NOT NULL
        ORDER BY processed_at DESC
        LIMIT 1
        """,
        [experiment_id],
    ).fetchone()
    if row is None or not row[0]:
        return None
    path = Path(row[0])
    if not path.is_absolute():
        path = db_path.parent / path
    return path


def _load_field_series(exp: dict, experiment_name: str) -> pd.DataFrame | None:
    from python_magnetrun.MagnetRun import load_mrun

    filename = Path(str(exp["file"])).name
    try:
        mrun = load_mrun(
            filename=filename,
            housing=exp["housing"] or "unknown",
            assembly=exp["assembly_name"] or "",
        )
    except Exception as exc:
        print(f"  [WARN] {experiment_name}: cannot load {filename}: {exc}")
        return None

    df = mrun.MagnetData.Data
    if "Field" not in df.columns or "t" not in df.columns:
        print(f"  [WARN] {experiment_name}: no 'Field'/'t' column in {filename}")
        return None

    return df[["t", "Field"]]


def _load_hoop_series(con, exp: dict, experiment_name: str, db_path: Path, part_names: list[str]) -> pd.DataFrame | None:
    pq_path = _get_hoop_parquet_path(con, exp["id"], db_path)
    if pq_path is None:
        print(f"  [WARN] {experiment_name}: no hoop-stress Parquet recorded. Run "
              f"`python magnetdb.py hoop-stress compute --assembly {exp['assembly_name']}` first.")
        return None
    if not pq_path.exists():
        print(f"  [WARN] {experiment_name}: hoop-stress Parquet recorded but missing on disk: {pq_path}")
        return None

    df = pd.read_parquet(pq_path)
    cols = [c for c in part_names if c in df.columns]
    if not cols:
        print(f"  [WARN] {experiment_name}: none of the magnet's parts {part_names} "
              f"found in {pq_path.name} (columns: {list(df.columns)})")
        return None
    return df[["t"] + cols]


def _sanitize(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name)


def plot_experiment(
    con, db_path: Path, magnet_name: str, part_names: list[str],
    experiment_name: str, output_dir: Path,
) -> None:
    print(f"[{experiment_name}]")
    exp = _get_experiment_row(con, experiment_name)
    if exp is None:
        print(f"  [WARN] {experiment_name}: not found in experiments table, skipping")
        return

    field_df = _load_field_series(exp, experiment_name)
    hoop_df = _load_hoop_series(con, exp, experiment_name, db_path, part_names)

    if field_df is None and hoop_df is None:
        print(f"  [SKIP] {experiment_name}: nothing to plot")
        return

    fig, (ax_field, ax_hoop) = plt.subplots(2, 1, sharex=True, figsize=(10, 7))
    fig.suptitle(f"{magnet_name} — {experiment_name}")

    if field_df is not None:
        ax_field.plot(field_df["t"], field_df["Field"])
    else:
        ax_field.text(0.5, 0.5, "no Field data available", ha="center", va="center",
                       transform=ax_field.transAxes, color="gray")
    ax_field.set_ylabel("Field [T]")
    ax_field.grid(True, alpha=0.3)

    if hoop_df is not None:
        for col in hoop_df.columns:
            if col == "t":
                continue
            ax_hoop.plot(hoop_df["t"], hoop_df[col], label=col)
        ax_hoop.legend()
    else:
        ax_hoop.text(0.5, 0.5, "no hoop-stress Parquet available", ha="center", va="center",
                      transform=ax_hoop.transAxes, color="gray")
    ax_hoop.set_ylabel("Hoop stress [MPa]")
    ax_hoop.set_xlabel("t [s]")
    ax_hoop.grid(True, alpha=0.3)

    fig.tight_layout()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_png = output_dir / f"stress_{_sanitize(magnet_name)}_{_sanitize(experiment_name)}.png"
    fig.savefig(output_png, dpi=150)
    plt.close(fig)
    print(f"  Plot saved to {output_png}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--magnet", required=True, help="Magnet name (magnets.name)")
    parser.add_argument("--experiments", required=True, nargs="+", help="Experiment names (experiments.name)")
    parser.add_argument("--db", default=DEFAULT_DB, help=f"DuckDB file (default: {DEFAULT_DB})")
    parser.add_argument("--output-dir", default=".", help="Directory to save PNG figures into (default: .)")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Error: '{db_path}' does not exist.")
        sys.exit(1)

    output_dir = Path(args.output_dir)

    with duckdb.connect(str(db_path), read_only=True) as con:
        part_names = _get_parts_for_magnet(con, args.magnet)
        if not part_names:
            print(f"[WARN] no parts found for magnet {args.magnet!r}; "
                  "hoop-stress panels will be empty for all experiments")

        for experiment_name in args.experiments:
            plot_experiment(
                con, db_path, args.magnet, part_names,
                experiment_name, output_dir,
            )


if __name__ == "__main__":
    main()
