"""
select_experiments_by_time.py
==============================
Select experiments whose name-embedded timestamp (French local time,
Europe/Paris — parsed from the pupitre filename "YYYY.MM.DD - HH:MM:SS")
falls within a given operational-day range.

``start``/``end`` are plain dates (``YYYY-MM-DD``). A range boundary
covers the facility's 08:00→07:00-next-day operational day:
    start  → "{start} 08:00:00"
    end    → "{end + 1 day} 07:00:00"

If ``end`` is omitted, all experiments from ``start`` 08:00 up to now
(Europe/Paris) are returned.

Usage
-----
    python select_experiments_by_time.py START [END] [--db magnetdb.duckdb]
"""

import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb

from config import DEFAULT_DB
from crud import view_experiments
from populate import FILE_TZ


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("start", help="Range start date (YYYY-MM-DD)")
    parser.add_argument(
        "end", nargs="?", default=None,
        help="Range end date (YYYY-MM-DD); default: now",
    )
    parser.add_argument(
        "--db", default=DEFAULT_DB, help=f"DuckDB file (default: {DEFAULT_DB})"
    )
    args = parser.parse_args()

    from_ts = f"{args.start} 08:00:00"
    if args.end is not None:
        end_date = date.fromisoformat(args.end) + timedelta(days=1)
        to_ts = f"{end_date.isoformat()} 07:00:00"
    else:
        to_ts = datetime.now(FILE_TZ).strftime("%Y-%m-%d %H:%M:%S")

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Error: '{db_path}' does not exist.")
        sys.exit(1)

    with duckdb.connect(str(db_path), read_only=True) as con:
        view_experiments(con, from_ts=from_ts, to_ts=to_ts)


if __name__ == "__main__":
    main()
