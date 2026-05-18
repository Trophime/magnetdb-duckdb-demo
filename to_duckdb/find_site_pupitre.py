"""
find_site_pupitre.py  [DEPRECATED — use magnetdb.py instead]
=============================================================

.. deprecated::
   This script is superseded by the unified CLI ``magnetdb.py``.
   Use ``python magnetdb.py populate operationaldata --type Pupitre`` or
   ``python magnetdb.py populate experiments`` instead.
   ``find_site_pupitre.py`` is kept as an importable module for ``magnetdb.py``
   and may be removed as a standalone CLI in a future version.

Load a site by name, then find pupitre TXT files whose filename timestamp
falls within the site's commissioned / decommissioned window.

Matched files are inserted into the ``operationaldata`` table (type = 'Pupitre')
in the DuckDB database, and printed to stdout.

Scanned directory:
    /mnt/LNCMIG-Data/records/srv-data-install/<housing>/

Filename format — YYYY.MM.DD - HH:MM:SS.txt (French local time, Europe/Paris):
    YYYY = 4-digit year
    MM   = 2-digit month
    DD   = 2-digit day
    HH   = hour (24 h)
    MM   = minute
    SS   = second

The timezone of commissioned_at / decommissioned_at stored in DuckDB is
uncertain. Default assumption is UTC; override with --db-tz if needed.

Usage:
    python find_site_pupitre.py M10_M19071101_13
    python find_site_pupitre.py M10_M19071101_13 --db-tz Europe/Paris
    python find_site_pupitre.py M10_M19071101_13 --dry-run
    python find_site_pupitre.py M10_M19071101_13 --records-base /data/records --srv-subdir srv-data-install
"""

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef]

import duckdb

from schema import ensure_schema

DEFAULT_DB    = "student_magnetdb.duckdb"
_RECORDS_BASE = Path("/mnt/LNCMIG-Data/records")
_SRV_SUBDIR   = "srv-data-install"
FILE_TZ       = ZoneInfo("Europe/Paris")  # file timestamps are French local time
FILE_TYPE     = "Pupitre"

# Matches "YYYY.MM.DD - HH:MM:SS.txt"
_FNAME_RE = re.compile(
    r"(\d{4}\.\d{2}\.\d{2} - \d{2}:\d{2}:\d{2})\.txt$",
    re.IGNORECASE,
)
_TS_FMT = "%Y.%m.%d - %H:%M:%S"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_file_ts(filename: str) -> datetime | None:
    """Return a timezone-aware datetime parsed from a pupitre filename, or None."""
    m = _FNAME_RE.search(filename)
    if not m:
        return None
    try:
        naive = datetime.strptime(m.group(1), _TS_FMT)
        return naive.replace(tzinfo=FILE_TZ)
    except ValueError:
        return None


def as_aware(ts: datetime | None, tz: ZoneInfo) -> datetime | None:
    """Attach a timezone to a naive datetime returned by DuckDB."""
    if ts is None:
        return None
    return ts.replace(tzinfo=tz) if ts.tzinfo is None else ts.astimezone(tz)


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def load_site(site_name: str, db_path: str) -> dict | None:
    with duckdb.connect(db_path, read_only=True) as con:
        row = con.execute(
            "SELECT name, housing, status, commissioned_at, decommissioned_at "
            "FROM sites WHERE name = ?",
            [site_name],
        ).fetchone()
    if row is None:
        return None
    return {
        "name":              row[0],
        "housing":           row[1],
        "status":            row[2],
        "commissioned_at":   row[3],
        "decommissioned_at": row[4],
    }


def _next_id(con) -> int:
    return con.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM operationaldata").fetchone()[0]


def insert_operationaldata(con, site_name: str, fpath: Path) -> bool:
    """Insert one pupitre file. Returns True if newly inserted."""
    already = con.execute(
        "SELECT COUNT(*) FROM operationaldata WHERE file = ?", [str(fpath)]
    ).fetchone()[0]
    if already:
        return False
    con.execute(
        "INSERT INTO operationaldata (id, name, description, file, site_name, type, status) "
        "VALUES (?, ?, '', ?, ?, ?, 'pending')",
        [_next_id(con), fpath.stem, str(fpath), site_name, FILE_TYPE],
    )
    return True


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def find_and_register(
    site:         dict,
    db_path:      str,
    db_tz:        ZoneInfo,
    dry_run:      bool,
    records_base: Path = _RECORDS_BASE,
    srv_subdir:   str  = _SRV_SUBDIR,
) -> list[tuple[Path, datetime]]:
    housing = site["housing"]
    if not housing:
        print(f"[WARN] site '{site['name']}' has no housing value.")
        return []

    pupitre_dir = records_base / srv_subdir / housing
    if not pupitre_dir.is_dir():
        print(f"[WARN] pupitre directory not found: {pupitre_dir}")
        return []

    # Bring both bounds into Europe/Paris for comparison with file timestamps
    t_start = as_aware(site["commissioned_at"],   db_tz)
    t_end   = as_aware(site["decommissioned_at"], db_tz)
    if t_start is not None:
        t_start = t_start.astimezone(FILE_TZ)
    if t_end is not None:
        t_end = t_end.astimezone(FILE_TZ)

    matches: list[tuple[Path, datetime]] = []
    for fpath in sorted(pupitre_dir.glob("*.txt")):
        ts = parse_file_ts(fpath.name)
        if ts is None:
            continue
        if t_start is not None and ts < t_start:
            continue
        if t_end is not None and ts > t_end:
            continue
        matches.append((fpath, ts))

    print(f"[OK]   {pupitre_dir}/  — {len(matches)} file(s) matched")

    if matches and not dry_run:
        with duckdb.connect(db_path) as con:
            ensure_schema(con)
            new_count = sum(
                insert_operationaldata(con, site["name"], fpath)
                for fpath, _ in matches
            )
        skipped = len(matches) - new_count
        print(
            f"\noperationaldata: inserted {new_count} new row(s)"
            + (f", {skipped} already present." if skipped else ".")
        )

    return matches


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    import warnings
    warnings.warn(
        "find_site_pupitre.py is deprecated. "
        "Use 'python magnetdb.py populate operationaldata --type Pupitre' "
        "or 'python magnetdb.py populate experiments' instead.",
        DeprecationWarning,
        stacklevel=1,
    )
    parser = argparse.ArgumentParser(
        description=(
            "[DEPRECATED — use: python magnetdb.py populate operationaldata --type Pupitre] "
            "Find pupitre TXT files for a site's operational window "
            "and register them in the 'operationaldata' table (type=Pupitre)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("site_name", help="Site name (e.g. M10_M19071101_13)")
    parser.add_argument("--db", default=DEFAULT_DB,
                        help=f"DuckDB file (default: {DEFAULT_DB})")
    parser.add_argument(
        "--db-tz", default="UTC",
        help=(
            "Timezone of commissioned_at / decommissioned_at in DuckDB. "
            "Default: UTC.  Use 'Europe/Paris' if stored as French local time."
        ),
    )
    parser.add_argument(
        "--records-base", default=str(_RECORDS_BASE), dest="records_base",
        help=f"Root of the records tree (default: {_RECORDS_BASE})",
    )
    parser.add_argument(
        "--srv-subdir", default=_SRV_SUBDIR, dest="srv_subdir",
        help=f"Subdirectory of records-base that holds housing dirs (default: {_SRV_SUBDIR})",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Match files but do not write anything to DuckDB",
    )
    args = parser.parse_args()

    try:
        db_tz = ZoneInfo(args.db_tz)
    except Exception:
        print(f"[ERROR] Unknown timezone: '{args.db_tz}'")
        sys.exit(1)

    site = load_site(args.site_name, args.db)
    if site is None:
        print(f"[ERROR] Site '{args.site_name}' not found in {args.db}")
        sys.exit(1)

    print(f"Site          : {site['name']}")
    print(f"Housing       : {site['housing']}")
    print(f"Status        : {site['status']}")
    print(f"Commissioned  : {site['commissioned_at']}  (treated as {args.db_tz})")
    print(f"Decommissioned: {site['decommissioned_at']}  (treated as {args.db_tz})")
    if args.dry_run:
        print("[DRY RUN — no writes to DuckDB]")
    print()

    matches = find_and_register(
        site, args.db, db_tz,
        dry_run=args.dry_run,
        records_base=Path(args.records_base),
        srv_subdir=args.srv_subdir,
    )

    if not matches:
        print("\nNo matching pupitre files found.")
        return

    col = 40
    print(f"\n{'File':<{col}}  Timestamp (Europe/Paris)")
    print("-" * (col + 32))
    for fpath, ts in matches:
        print(f"{fpath.name:<{col}}  {ts.isoformat()}")
    print(f"\n{len(matches)} file(s) matched.")


if __name__ == "__main__":
    main()
