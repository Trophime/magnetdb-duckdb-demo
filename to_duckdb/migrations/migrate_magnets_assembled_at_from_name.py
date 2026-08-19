"""
Backfill magnets.assembled_at from each magnet's coded name.

LNCMI magnet names follow the convention ``M`` + ``YYMMDD`` (assembly date)
+ 2-digit serial, e.g. ``M23012001`` -> 2023-01-20. Names that don't match
(e.g. the hand-built Bitter magnets ``M9Bitters``, ``M10Bitters``) are left
untouched (``assembled_at`` stays NULL).

Idempotent: only rows where ``assembled_at IS NULL`` are considered, so
re-running is a no-op once every matching name has been backfilled.
"""

import argparse
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import DEFAULT_DB
from crud import assembled_at_from_name
from schema import ensure_schema


def migrate(db_path: str, dry_run: bool = False) -> None:
    con = duckdb.connect(db_path)
    ensure_schema(con)

    rows = con.execute(
        "SELECT name FROM magnets WHERE assembled_at IS NULL"
    ).fetchall()

    if not rows:
        print("Nothing to migrate — no magnets with assembled_at IS NULL.")
        con.close()
        return

    matched: list[tuple[str, str]] = []
    unmatched: list[str] = []
    for (name,) in rows:
        assembled_at = assembled_at_from_name(name)
        if assembled_at is None:
            unmatched.append(name)
        else:
            matched.append((name, assembled_at))

    print(f"{len(matched)}/{len(rows)} magnet name(s) matched the MYYMMDDXX convention.")

    if dry_run:
        print("Sample matches (dry run, no changes written):")
        for name, assembled_at in matched[:5]:
            print(f"  {name!r}  ->  {assembled_at}")
        if unmatched:
            print(f"\n{len(unmatched)} unmatched name(s), left NULL:")
            for name in unmatched[:10]:
                print(f"  {name!r}")
        con.close()
        return

    for name, assembled_at in matched:
        con.execute("UPDATE magnets SET assembled_at = ? WHERE name = ?", [assembled_at, name])
    print(f"Migrated {len(matched)} row(s).")

    if unmatched:
        print(f"{len(unmatched)} unmatched name(s), left NULL:")
        for name in unmatched:
            print(f"  {name!r}")

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
