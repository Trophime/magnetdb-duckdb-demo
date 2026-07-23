"""
Migrate operationaldata.file from absolute paths to paths relative to
--records-base.

Before: /mnt/LNCMIG-Data/records/pbsurv/M10/Overview/250101-0000.tdms
After:  pbsurv/M10/Overview/250101-0000.tdms

Unlike experiments.file (a bare filename), operationaldata.file keeps the
housing/type subdirectory structure because operationaldata.file has a
UNIQUE constraint — two different housings can produce a file with an
identical basename (e.g. matching TDMS timestamps), so truncating to a bare
basename would risk a constraint violation on future inserts. Stripping only
the records_base prefix keeps the value unique while dropping the
machine-specific mount point.

Safe to run multiple times — rows that already contain a relative path (no
leading slash) are not touched by the WHERE clause. Rows whose absolute path
does not fall under --records-base are reported and left untouched.
"""

import argparse
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import DEFAULT_DB
from populate import _RECORDS_BASE as DEFAULT_RECORDS_BASE


def migrate(db_path: str, records_base: Path, dry_run: bool = False) -> None:
    con = duckdb.connect(db_path)

    rows = con.execute(
        "SELECT id, file FROM operationaldata WHERE file LIKE '/%'"
    ).fetchall()

    if not rows:
        print("Nothing to migrate — no absolute paths found.")
        con.close()
        return

    print(f"Found {len(rows)} row(s) with absolute paths.")

    to_update: list[tuple[int, str, str]] = []
    unresolvable: list[tuple[int, str]] = []
    for row_id, file in rows:
        try:
            relpath = str(Path(file).relative_to(records_base))
        except ValueError:
            unresolvable.append((row_id, file))
            continue
        to_update.append((row_id, file, relpath))

    if dry_run:
        print("Sample rows (dry run, no changes written):")
        for row_id, file, relpath in to_update[:5]:
            print(f"  id={row_id}  {file!r}  →  {relpath!r}")
        if unresolvable:
            print(f"\n[WARN] {len(unresolvable)} row(s) not under {records_base} "
                  "— would be left unchanged:")
            for row_id, file in unresolvable[:5]:
                print(f"  id={row_id}  {file!r}")
        con.close()
        return

    for row_id, _file, relpath in to_update:
        con.execute("UPDATE operationaldata SET file = ? WHERE id = ?", [relpath, row_id])
    print(f"Migrated {len(to_update)} row(s).")

    if unresolvable:
        print(f"[WARN] {len(unresolvable)} row(s) not under {records_base} — left unchanged:")
        for row_id, file in unresolvable:
            print(f"  id={row_id}  {file!r}")

    remaining = con.execute(
        "SELECT COUNT(*) FROM operationaldata WHERE file LIKE '/%'"
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
        "--records-base", default=str(DEFAULT_RECORDS_BASE), dest="records_base",
        help=f"Root of the records tree (default: {DEFAULT_RECORDS_BASE})",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be changed without writing anything",
    )
    args = parser.parse_args()
    migrate(args.db, Path(args.records_base), dry_run=args.dry_run)


if __name__ == "__main__":
    main()
