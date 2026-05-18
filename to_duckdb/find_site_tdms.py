"""
find_site_tdms.py  [DEPRECATED — use magnetdb.py instead]
==========================================================

.. deprecated::
   This script is superseded by the unified CLI ``magnetdb.py``.
   Use ``python magnetdb.py populate operationaldata`` instead.
   ``find_site_tdms.py`` is kept as an importable module for ``magnetdb.py``
   and may be removed as a standalone CLI in a future version.

Load a site by name, then find TDMS files in all known subdirectories whose
filename timestamp falls within the site's commissioned / decommissioned window.

Matched files are inserted into a ``operationaldata`` table (same columns as
``experiments``, plus a ``type`` field) in the DuckDB database, and printed
to stdout.

Scanned directories and their type labels
-----------------------------------------
    /mnt/LNCMIG-Data/records/pbsurv/<housing>/Overview/        → type = Overview
    /mnt/LNCMIG-Data/records/pbsurv/<housing>/Fichiers_Archive/ → type = Archive
    /mnt/LNCMIG-Data/records/pbsurv/<housing>/Fichiers_Spike/  → type = Spike
    /mnt/LNCMIG-Data/records/pbsurv/<housing>/Fichiers_Default/ → type = Default

Timestamp formats (all in French local time, Europe/Paris):
    Overview / Archive  YYDDMM-HHMM   (6+4 digits, French day-first, minute precision)
        YY = year, DD = day, MM = month, HH = hour, MM = minute
    Spike               YYMMDD-HHMMSS  (6+6 digits, ISO date order, second precision)
        e.g. M10_Spikes_250615-021640.tdms
    Default             YYMMDD-HHMMSS  (6+6 digits, ISO date order, second precision)
        optional suffix after timestamp, e.g. M10_Default_240718-124401_Courants50Hz.tdms

The timezone of commissioned_at / decommissioned_at stored in DuckDB is
uncertain. Default assumption is UTC; override with --db-tz if needed.

Usage:
    python find_site_tdms.py M10_M19071101_13
    python find_site_tdms.py M10_M19071101_13 --db-tz Europe/Paris
    python find_site_tdms.py M10_M19071101_13 --dry-run
    python find_site_tdms.py M10_M19071101_13 --type Archive Spike
    python find_site_tdms.py M10_M19071101_13 --records-base /data/records
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
_PBSURV       = "pbsurv"
FILE_TZ       = ZoneInfo("Europe/Paris")  # file timestamps are always French local

# subdir names per type; full path = (records_base / pbsurv) / housing / subdir
_SUBDIR_NAMES: dict[str, str] = {
    "Overview": "Overview",
    "Archive":  "Fichiers_Archive",
    "Spike":    "Fichiers_Spike",
    "Default":  "Fichiers_Default",
}
ALL_TYPES = list(_SUBDIR_NAMES)

# Per-type: (compiled regex capturing the timestamp, strptime format)
# Overview/Archive: YYDDMM-HHMM  (French day-first, minute precision, 6+4 digits)
# Spike/Default:    YYMMDD-HHMMSS (ISO date order, second precision, 6+6 digits)
#   Default allows an optional suffix after the timestamp, e.g. _Courants50Hz
_TS_PATTERNS: dict[str, tuple[re.Pattern, str]] = {
    "Overview": (re.compile(r"(\d{6}-\d{4})\.tdms$",    re.IGNORECASE), "%y%d%m-%H%M"),
    "Archive":  (re.compile(r"(\d{6}-\d{4})\.tdms$",    re.IGNORECASE), "%y%d%m-%H%M"),
    "Spike":    (re.compile(r"_Spikes_(\d{6}-\d{6})",   re.IGNORECASE), "%y%m%d-%H%M%S"),
    "Default":  (re.compile(r"_Default_(\d{6}-\d{6})",  re.IGNORECASE), "%y%m%d-%H%M%S"),
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def parse_file_ts(filename: str, file_type: str) -> datetime | None:
    """Return a timezone-aware datetime parsed from a TDMS filename, or None."""
    pattern, fmt = _TS_PATTERNS[file_type]
    m = pattern.search(filename)
    if not m:
        return None
    try:
        naive = datetime.strptime(m.group(1), fmt)
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
        "name": row[0],
        "housing": row[1],
        "status": row[2],
        "commissioned_at": row[3],
        "decommissioned_at": row[4],
    }


def _next_id(con) -> int:
    return con.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM operationaldata").fetchone()[0]


def insert_operationaldata(con, site_name: str, fpath: Path, file_type: str) -> bool:
    """Insert one TDMS file. Returns True if newly inserted, False if already present."""
    already = con.execute(
        "SELECT COUNT(*) FROM operationaldata WHERE file = ?", [str(fpath)]
    ).fetchone()[0]
    if already:
        return False
    con.execute(
        "INSERT INTO operationaldata (id, name, description, file, site_name, type, status) "
        "VALUES (?, ?, '', ?, ?, ?, 'pending')",
        [_next_id(con), fpath.stem, str(fpath), site_name, file_type],
    )
    return True


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def scan_subdir(
    subdir: Path,
    file_type: str,
    t_start: datetime | None,
    t_end: datetime | None,
) -> list[tuple[Path, datetime, str]]:
    """Scan one subdirectory and return matching (path, timestamp, type) tuples."""
    if not subdir.is_dir():
        return []
    matches = []
    for fpath in sorted(subdir.glob("*.tdms")):
        ts = parse_file_ts(fpath.name, file_type)
        if ts is None:
            continue
        if t_start is not None and ts < t_start:
            continue
        if t_end is not None and ts > t_end:
            continue
        matches.append((fpath, ts, file_type))
    return matches


def find_and_register(
    site:         dict,
    db_path:      str,
    db_tz:        ZoneInfo,
    dry_run:      bool,
    type_filter:  list[str] | None = None,
    records_base: Path = _RECORDS_BASE,
    pbsurv:       str  = _PBSURV,
) -> list[tuple[Path, datetime, str]]:
    housing = site["housing"]
    if not housing:
        print(f"[WARN] site '{site['name']}' has no housing value.")
        return []

    # Bring both bounds into Europe/Paris for comparison with file timestamps
    t_start = as_aware(site["commissioned_at"], db_tz)
    t_end = as_aware(site["decommissioned_at"], db_tz)
    if t_start is not None:
        t_start = t_start.astimezone(FILE_TZ)
    if t_end is not None:
        t_end = t_end.astimezone(FILE_TZ)

    active_types = type_filter if type_filter else ALL_TYPES
    matches: list[tuple[Path, datetime, str]] = []

    pbsurv_dir = records_base / pbsurv
    for file_type in active_types:
        subdir = pbsurv_dir / housing / _SUBDIR_NAMES[file_type]
        found = scan_subdir(subdir, file_type, t_start, t_end)
        if not subdir.is_dir():
            print(f"[SKIP] {subdir}/  not found")
        elif not found:
            print(f"[INFO] {subdir}/  — no matching files")
        else:
            print(f"[OK]   {subdir}/  — {len(found)} file(s)")
        matches.extend(found)

    if matches and not dry_run:
        with duckdb.connect(db_path) as con:
            ensure_schema(con)
            new_count = sum(
                insert_operationaldata(con, site["name"], fpath, file_type)
                for fpath, _, file_type in matches
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
        "find_site_tdms.py is deprecated. "
        "Use 'python magnetdb.py populate operationaldata' instead.",
        DeprecationWarning,
        stacklevel=1,
    )
    parser = argparse.ArgumentParser(
        description=(
            "[DEPRECATED — use: python magnetdb.py populate operationaldata] "
            "Find TDMS files for a site's operational window "
            "and register them in the 'operationaldata' table."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("site_name", help="Site name (e.g. M10_M19071101_13)")
    parser.add_argument("--db", default=DEFAULT_DB, help=f"DuckDB file (default: {DEFAULT_DB})")
    parser.add_argument(
        "--db-tz",
        default="UTC",
        help=(
            "Timezone of commissioned_at / decommissioned_at in DuckDB. "
            "Default: UTC.  Use 'Europe/Paris' if stored as French local time."
        ),
    )
    parser.add_argument(
        "--type",
        nargs="+",
        choices=ALL_TYPES,
        dest="types",
        metavar="TYPE",
        help=(
            f"Restrict scan to one or more file types " f"({', '.join(ALL_TYPES)}). Default: all."
        ),
    )
    parser.add_argument(
        "--records-base", default=str(_RECORDS_BASE), dest="records_base",
        help=f"Root of the records tree (default: {_RECORDS_BASE})",
    )
    parser.add_argument(
        "--pbsurv", default=_PBSURV,
        help=f"Subdirectory of records-base that holds housing dirs (default: {_PBSURV})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
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
        site,
        args.db,
        db_tz,
        dry_run=args.dry_run,
        type_filter=args.types,
        records_base=Path(args.records_base),
        pbsurv=args.pbsurv,
    )

    if not matches:
        print("\nNo matching TDMS files found.")
        return

    col_f = 55
    col_t = 10
    print(f"\n{'File':<{col_f}}  {'Type':<{col_t}}  Timestamp (Europe/Paris)")
    print("-" * (col_f + col_t + 32))
    for fpath, ts, file_type in matches:
        print(f"{fpath.name:<{col_f}}  {file_type:<{col_t}}  {ts.isoformat()}")
    print(f"\n{len(matches)} file(s) matched.")


if __name__ == "__main__":
    main()
