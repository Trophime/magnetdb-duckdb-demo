#!/usr/bin/env python
"""List ``experiments`` rows with their file-embedded timestamp.

Prints each row's ``file`` column alongside the timestamp DuckDB parses out
of it via ``_EXP_FILE_TS`` (the pupitre "YYYY.MM.DD - HH:MM:SS" pattern).
Rows whose filename doesn't match that pattern print ``None`` for the
timestamp.

Run from the repository root, e.g.::

    python to_duckdb/demos/list_experiments_ts.py
    python to_duckdb/demos/list_experiments_ts.py --db to_duckdb/test-magnetdb.duckdb
"""

import argparse
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import DEFAULT_DB  # noqa: E402
from crud import _EXP_FILE_TS  # noqa: E402


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
            f"SELECT e.file, {_EXP_FILE_TS} AS file_ts FROM experiments e ORDER BY e.id"
        ).fetchall()

    for file, file_ts in rows:
        print(f"{file:<60} {file_ts}")


if __name__ == "__main__":
    main()
