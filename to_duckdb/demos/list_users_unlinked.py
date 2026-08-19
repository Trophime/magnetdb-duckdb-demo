#!/usr/bin/env python
"""List ``users`` rows with no linked experiments or overview records.

Prints every ``users`` row whose ``experiments_ids`` and
``overview_records_ids`` are both ``NULL``.

Run from the repository root, e.g.::

    python to_duckdb/demos/list_users_unlinked.py
    python to_duckdb/demos/list_users_unlinked.py --db to_duckdb/test-magnetdb.duckdb
"""

import argparse
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import DEFAULT_DB  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db", default=DEFAULT_DB, help=f"DuckDB file (default: {DEFAULT_DB})"
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Error: '{db_path}' does not exist.")
        sys.exit(1)

    with duckdb.connect(str(db_path), read_only=True) as con:
        rows = con.execute(
            "SELECT * FROM users "
            "WHERE experiments_ids IS NULL AND overview_records_ids IS NULL "
            "ORDER BY acronym, housing, hstart"
        ).df()

    print(f"Rows with no experiments_ids and no overview_records_ids ({len(rows)}):")
    print(rows.to_string(index=False))


if __name__ == "__main__":
    main()
