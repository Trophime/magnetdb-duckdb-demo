"""
Migrate experiments.file from absolute paths to bare filenames.

Before: /mnt/LNCMIG-Data/records/srv-data-install/M10/2025.04.30 - 13:06:03.txt
After:  2025.04.30 - 13:06:03.txt

Safe to run multiple times — rows that already contain only a filename are
not touched by the WHERE clause.
"""

import argparse
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import DEFAULT_DB


def migrate(db_path: str, dry_run: bool = False) -> None:
    con = duckdb.connect(db_path)

    count = con.execute(
        "SELECT COUNT(*) FROM experiments WHERE file LIKE '/%'"
    ).fetchone()[0]

    if count == 0:
        print("Nothing to migrate — no absolute paths found.")
        con.close()
        return

    print(f"Found {count} row(s) with absolute paths.")

    if dry_run:
        rows = con.execute(
            "SELECT id, site_name, file FROM experiments WHERE file LIKE '/%' LIMIT 5"
        ).fetchall()
        print("Sample rows (dry run, no changes written):")
        for row in rows:
            print(f"  id={row[0]}  site={row[1]}  {row[2]!r}  →  {Path(row[2]).name!r}")
        con.close()
        return

    con.execute(
        "UPDATE experiments "
        "SET file = regexp_extract(file, '[^/]+$', 0) "
        "WHERE file LIKE '/%'"
    )
    print(f"Migrated {count} row(s).")

    remaining = con.execute(
        "SELECT COUNT(*) FROM experiments WHERE file LIKE '/%'"
    ).fetchone()[0]
    if remaining:
        print(f"[WARN] {remaining} row(s) still have absolute paths — check manually.")
    else:
        print("Verification passed: no absolute paths remain.")

    con.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB, help="DuckDB file path")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be changed without writing anything",
    )
    args = parser.parse_args()
    migrate(args.db, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
