#!/usr/bin/env python
"""Demo: list the distinct keyword values used in ``proposals.csv`` columns.

Read-only — prints the sorted set of non-empty values found for each
requested column (default: ``Type``, ``Access Mode``, ``Research Area``).
Useful for spotting typos/variants before relying on these columns as
enums elsewhere (e.g. ``users_table_demo.py``'s ``Supra``/``Supra``
exclusion).

Run from the repository root, e.g.::

    python to_duckdb/demos/list_proposal_keywords.py
    python to_duckdb/demos/list_proposal_keywords.py --columns Type
"""

import argparse
import csv
from pathlib import Path

DEFAULT_COLUMNS = ["Type", "Access Mode", "Research Area"]


def load_keywords(proposals_path: Path, column: str) -> list[str]:
    """Return the sorted distinct non-empty values of `column`.

    Parameters
    ----------
    proposals_path : :class:`~pathlib.Path`
        Path to the proposals CSV.
    column : str
        Name of the CSV column to collect values from.

    Returns
    -------
    list[str]
        Sorted distinct values, blanks excluded.
    """
    with open(proposals_path, newline="", encoding="utf-8-sig") as f:
        values = {row[column].strip() for row in csv.DictReader(f) if row[column].strip()}
    return sorted(values)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--proposals",
        type=Path,
        default=Path("Data/proposals.csv"),
        help="Input proposals CSV.",
    )
    parser.add_argument(
        "--columns",
        nargs="+",
        default=DEFAULT_COLUMNS,
        help="CSV column names to list keywords for.",
    )
    args = parser.parse_args()

    for column in args.columns:
        keywords = load_keywords(args.proposals, column)
        print(f"{column} ({len(keywords)} values):")
        for value in keywords:
            print(f"  - {value}")
        print()


if __name__ == "__main__":
    main()
