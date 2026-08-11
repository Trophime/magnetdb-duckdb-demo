#!/usr/bin/env python
"""Compare overview-file Energy against pupitre-derived Energy_j, per overview record.

For each live (``merged_into IS NULL``) ``overview_records`` row:

- Reads the TDMS ``Infos/Energy`` scalar [MWh] from every file in
  ``sources_overview`` and sums them.
- Matches every file in ``sources_pupitre`` to its ``experiments`` row (by
  ``(site_name, basename)``) and sums the matched rows' ``energy_j``
  [J] from ``exp_run_scalars``, converting the total to MWh.

Prints one row per overview record with both totals and their difference.
Rows/files that are missing on disk, unmatched, or not yet processed by
``compute_exp_stats.py`` are counted rather than raising.

Run from the repository root, e.g.::

    python to_duckdb/demos/compare_overview_pupitre_energy.py --db to_duckdb/magnetdb.duckdb
    python to_duckdb/demos/compare_overview_pupitre_energy.py --db to_duckdb/magnetdb.duckdb --site M9_M19061901
    python to_duckdb/demos/compare_overview_pupitre_energy.py --db to_duckdb/magnetdb.duckdb --csv energy_compare.csv
"""

import argparse
import sys
from pathlib import Path

import duckdb
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import DEFAULT_DB, J_TO_MWH  # noqa: E402


def _load_experiment_index(con, site: str | None) -> dict[tuple[str, str], int]:
    """Map ``(site_name, basename(file))`` to ``experiments.id``, warning once on collisions."""
    where = "WHERE site_name = ?" if site else ""
    params = [site] if site else []
    rows = con.execute(
        f"SELECT id, site_name, file FROM experiments {where}", params
    ).fetchall()

    index: dict[tuple[str, str], int] = {}
    collisions = 0
    for exp_id, site_name, file in rows:
        key = (site_name, Path(file).name)
        if key in index:
            collisions += 1
            continue
        index[key] = exp_id
    if collisions:
        print(f"  [WARN] {collisions} duplicate (site, basename) experiment file names ignored")
    return index


def _load_energy_by_experiment(con) -> dict[int, float]:
    """Map ``experiments.id`` to its ``energy_j`` value from ``exp_run_scalars``."""
    rows = con.execute(
        "SELECT experiment_id, value FROM exp_run_scalars WHERE channel = 'energy_j'"
    ).fetchall()
    return dict(rows)


def sum_overview_energy_mwh(paths: list[str]) -> tuple[float, int, int]:
    """Sum the TDMS ``Infos/Energy`` scalar [MWh] across *paths*.

    Parameters
    ----------
    paths : list of str
        Overview TDMS file paths (``overview_records.sources_overview``).

    Returns
    -------
    tuple
        ``(total_mwh, n_ok, n_failed)``.
    """
    from python_magnetrun.magnetdata import load_magnetdata

    total = 0.0
    n_ok = 0
    n_failed = 0
    for path in paths:
        try:
            md = load_magnetdata(path)
            total += float(md.Groups["Infos"]["Energy"][:][0])
            n_ok += 1
        except Exception as exc:
            print(f"  [SKIP] overview {path}: {exc}")
            n_failed += 1
    return total, n_ok, n_failed


def sum_pupitre_energy_mwh(
    paths: list[str],
    site_name: str,
    exp_index: dict[tuple[str, str], int],
    energy_by_exp: dict[int, float],
) -> tuple[float, int, int, int]:
    """Sum ``energy_j`` [converted to MWh] for the experiments matched to *paths*.

    Parameters
    ----------
    paths : list of str
        Pupitre file paths (``overview_records.sources_pupitre``).
    site_name : str
        Site name the overview record belongs to; used to scope the
        ``(site_name, basename)`` experiment lookup.
    exp_index : dict
        ``(site_name, basename(file))`` -> ``experiments.id``, from
        :func:`_load_experiment_index`.
    energy_by_exp : dict
        ``experiments.id`` -> ``energy_j`` [J], from
        :func:`_load_energy_by_experiment`.

    Returns
    -------
    tuple
        ``(total_mwh, n_matched, n_unmatched, n_no_energy)``.
    """
    total_j = 0.0
    n_matched = 0
    n_unmatched = 0
    n_no_energy = 0
    for path in paths:
        exp_id = exp_index.get((site_name, Path(path).name))
        if exp_id is None:
            n_unmatched += 1
            continue
        value = energy_by_exp.get(exp_id)
        if value is None:
            n_no_energy += 1
            continue
        total_j += value
        n_matched += 1
    return total_j / J_TO_MWH, n_matched, n_unmatched, n_no_energy


def compare_records(con, site: str | None = None) -> pd.DataFrame:
    """Build the per-overview-record energy comparison table.

    Parameters
    ----------
    con : duckdb.DuckDBPyConnection
        Read-only connection to the magnetdb database.
    site : str, optional
        Restrict to ``overview_records.site_name = site`` when given.

    Returns
    -------
    pandas.DataFrame
        One row per live overview record, with overview/pupitre energy
        totals [MWh], their difference, and match/skip counts.
    """
    where = "WHERE merged_into IS NULL"
    params: list[str] = []
    if site:
        where += " AND site_name = ?"
        params.append(site)

    records = con.execute(
        f"SELECT filename, site_name, sources_overview, sources_pupitre "
        f"FROM overview_records {where} ORDER BY filename",
        params,
    ).fetchall()

    exp_index = _load_experiment_index(con, site)
    energy_by_exp = _load_energy_by_experiment(con)

    rows = []
    for filename, site_name, sources_overview, sources_pupitre in records:
        print(f"processing {filename}")
        ovr_mwh, ovr_ok, ovr_failed = sum_overview_energy_mwh(sources_overview or [])
        pup_mwh, pup_matched, pup_unmatched, pup_no_energy = sum_pupitre_energy_mwh(
            sources_pupitre or [], site_name, exp_index, energy_by_exp
        )
        diff_mwh = ovr_mwh - pup_mwh
        rel_diff_pct = (diff_mwh / ovr_mwh * 100.0) if ovr_mwh else float("nan")

        rows.append(
            {
                "filename": filename,
                "site_name": site_name,
                "overview_energy_mwh": ovr_mwh,
                "overview_files_ok": ovr_ok,
                "overview_files_failed": ovr_failed,
                "pupitre_energy_mwh": pup_mwh,
                "pupitre_files_matched": pup_matched,
                "pupitre_files_unmatched": pup_unmatched,
                "pupitre_files_no_energy": pup_no_energy,
                "diff_mwh": diff_mwh,
                "rel_diff_pct": rel_diff_pct,
            }
        )

    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db", default=DEFAULT_DB, help=f"DuckDB file (default: {DEFAULT_DB})"
    )
    parser.add_argument("--site", default=None, help="Restrict to this site_name")
    parser.add_argument("--csv", default=None, help="Optional path to write results as CSV")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Error: '{db_path}' does not exist.")
        sys.exit(1)

    with duckdb.connect(str(db_path), read_only=True) as con:
        df = compare_records(con, site=args.site)

    if df.empty:
        print("No live overview_records rows found.")
        return

    print()
    print(df.to_string(index=False))

    if args.csv:
        df.to_csv(args.csv, index=False)
        print(f"\nWrote {len(df)} rows to {args.csv}")


if __name__ == "__main__":
    main()
