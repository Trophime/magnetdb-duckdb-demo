"""
populate.py
===========
File-system scanning and operationaldata registration for pupitre TXT
and TDMS archive files.

Used by ``magnetdb.py populate operationaldata`` and
``magnetdb.py populate experiments``.

Public API
----------
    TDMS_TYPES              list of known TDMS file-type names
    ALL_POPULATE_TYPES      TDMS_TYPES + ["Pupitre"]
    _RECORDS_BASE           default filesystem root for all records
    _SRV_SUBDIR             default subdirectory for pupitre TXT files
    _PBSURV                 default subdirectory for TDMS files

    load_site(site_name, db_path)          → dict | None
    find_and_register_pupitre(...)         → list[(Path, datetime)]
    find_and_register_tdms(...)            → list[(Path, datetime, str)]
    resolve_operationaldata_path(...)      → Path
"""

import re
import sys
from datetime import datetime
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef]

import duckdb

from python_magnetrun.data_dirs import PIGBROTHER_DATA_DIR, PUPITRE_DATA_DIR
from schema import ensure_schema

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

_SRV_SUBDIR   = "srv-data-install"   # pupitre TXT:  records_base / srv_subdir / housing
_PBSURV       = "pbsurv"             # TDMS files:   records_base / pbsurv    / housing / subdir
FILE_TZ       = ZoneInfo("Europe/Paris")

# Default records root follows python_magnetrun's data-directory resolution
# (MAGNETRUN_PUPITRE_DATA_DIR env var > data_dirs.json > hard-coded default),
# so `MAGNETRUN_PUPITRE_DATA_DIR=/x/srv-data-install` also redirects to_duckdb.
_RECORDS_BASE = Path(PUPITRE_DATA_DIR).parent

if Path(PUPITRE_DATA_DIR).name != _SRV_SUBDIR:
    print(
        f"[WARN] populate.py: PUPITRE_DATA_DIR ({PUPITRE_DATA_DIR!r}) does not end "
        f"with the conventional {_SRV_SUBDIR!r} subdir; _RECORDS_BASE={_RECORDS_BASE} "
        "may not be what you expect. Check MAGNETRUN_PUPITRE_DATA_DIR / "
        "~/.config/python_magnetrun/data_dirs.json.",
        file=sys.stderr,
    )
if Path(PIGBROTHER_DATA_DIR).name != _PBSURV:
    print(
        f"[WARN] populate.py: PIGBROTHER_DATA_DIR ({PIGBROTHER_DATA_DIR!r}) does not "
        f"end with the conventional {_PBSURV!r} subdir. Check "
        "MAGNETRUN_PIGBROTHER_DATA_DIR / ~/.config/python_magnetrun/data_dirs.json.",
        file=sys.stderr,
    )
if Path(PIGBROTHER_DATA_DIR).parent != _RECORDS_BASE:
    print(
        f"[WARN] populate.py: PIGBROTHER_DATA_DIR's root ({Path(PIGBROTHER_DATA_DIR).parent}) "
        f"does not match _RECORDS_BASE ({_RECORDS_BASE}) derived from PUPITRE_DATA_DIR. "
        "TDMS lookups under _RECORDS_BASE / _PBSURV may point at the wrong tree. "
        "Check MAGNETRUN_PUPITRE_DATA_DIR / MAGNETRUN_PIGBROTHER_DATA_DIR / "
        "~/.config/python_magnetrun/data_dirs.json.",
        file=sys.stderr,
    )

# ---------------------------------------------------------------------------
# TDMS type registry
# ---------------------------------------------------------------------------

# subdir name on disk per logical type
_TDMS_SUBDIR_NAMES: dict[str, str] = {
    "Overview": "Overview",
    "Archive":  "Fichiers_Archive",
    "Spike":    "Fichiers_Spike",
    "Default":  "Fichiers_Default",
}
TDMS_TYPES = list(_TDMS_SUBDIR_NAMES)

# Per-type: (compiled pattern, strptime format)
# Overview/Archive: YYDDMM-HHMM  (French day-first, minute precision)
# Spike/Default:    YYMMDD-HHMMSS (ISO order, second precision)
_TDMS_TS_PATTERNS: dict[str, tuple[re.Pattern, str]] = {
    "Overview": (re.compile(r"(\d{6}-\d{4})\.tdms$",   re.IGNORECASE), "%y%m%d-%H%M"),
    "Archive":  (re.compile(r"(\d{6}-\d{4})\.tdms$",   re.IGNORECASE), "%y%m%d-%H%M"),
    "Spike":    (re.compile(r"_Spikes_(\d{6}-\d{6})",  re.IGNORECASE), "%y%m%d-%H%M%S"),
    "Default":  (re.compile(r"_Default_(\d{6}-\d{6})", re.IGNORECASE), "%y%m%d-%H%M%S"),
}

# ---------------------------------------------------------------------------
# Pupitre filename pattern  "YYYY.MM.DD - HH:MM:SS.txt"
# ---------------------------------------------------------------------------

_PUPITRE_FNAME_RE = re.compile(
    r"(\d{4}\.\d{2}\.\d{2} - \d{2}:\d{2}:\d{2})\.txt$",
    re.IGNORECASE,
)
_PUPITRE_TS_FMT = "%Y.%m.%d - %H:%M:%S"

# Convenience aggregate used by magnetdb.py --type filter
ALL_POPULATE_TYPES = TDMS_TYPES + ["Pupitre"]

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def as_aware(ts: datetime | None, tz: ZoneInfo) -> datetime | None:
    """Attach *tz* to a naive datetime (e.g. returned by DuckDB), or re-express."""
    if ts is None:
        return None
    return ts.replace(tzinfo=tz) if ts.tzinfo is None else ts.astimezone(tz)


def load_site(site_name: str, db_path: str) -> dict | None:
    """Return the site row as a dict, or None if not found."""
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


def _insert_operationaldata(
    con, site_name: str, fpath: Path, file_type: str, records_base: Path
) -> bool:
    """Insert one file record. Returns True if newly inserted, False if already present."""
    try:
        relpath = str(fpath.relative_to(records_base))
    except ValueError:
        relpath = str(fpath)
    already = con.execute(
        "SELECT COUNT(*) FROM operationaldata WHERE file = ?", [relpath]
    ).fetchone()[0]
    if already:
        return False
    con.execute(
        "INSERT INTO operationaldata (name, description, file, site_name, type, status) "
        "VALUES (?, '', ?, ?, ?, 'pending')",
        [fpath.stem, relpath, site_name, file_type],
    )
    return True


def resolve_operationaldata_path(relpath: str, records_base: Path = _RECORDS_BASE) -> Path:
    """Rebuild the on-disk path for a value stored in ``operationaldata.file``.

    Parameters
    ----------
    relpath : str
        Value of the ``file`` column: a path relative to *records_base*
        (an already-absolute legacy path is also accepted and returned
        unchanged).
    records_base : :class:`~pathlib.Path`, optional
        Root of the records tree (default: :data:`_RECORDS_BASE`).

    Returns
    -------
    Path
        Absolute path where the file is expected to live on disk.
    """
    return records_base / relpath


def _site_window(
    site: dict, db_tz: ZoneInfo
) -> tuple[datetime | None, datetime | None]:
    """Return (t_start, t_end) both expressed in FILE_TZ (Europe/Paris)."""
    t_start = as_aware(site["commissioned_at"],   db_tz)
    t_end   = as_aware(site["decommissioned_at"], db_tz)
    if t_start is not None:
        t_start = t_start.astimezone(FILE_TZ)
    if t_end is not None:
        t_end = t_end.astimezone(FILE_TZ)
    return t_start, t_end


# ---------------------------------------------------------------------------
# Pupitre
# ---------------------------------------------------------------------------

def parse_pupitre_file_ts(filename: str) -> datetime | None:
    """Return a timezone-aware datetime parsed from a pupitre filename, or None."""
    m = _PUPITRE_FNAME_RE.search(filename)
    if not m:
        return None
    try:
        naive = datetime.strptime(m.group(1), _PUPITRE_TS_FMT)
        return naive.replace(tzinfo=FILE_TZ)
    except ValueError:
        return None


def find_and_register_pupitre(
    site:         dict,
    db_path:      str,
    db_tz:        ZoneInfo,
    dry_run:      bool,
    records_base: Path = _RECORDS_BASE,
    srv_subdir:   str  = _SRV_SUBDIR,
) -> list[tuple[Path, datetime]]:
    """Scan for pupitre TXT files in the site's operational window.

    Returns matched (path, timestamp) pairs. Writes to operationaldata
    unless *dry_run* is True.
    """
    housing = site["housing"]
    if not housing:
        print(f"[WARN] site '{site['name']}' has no housing value.")
        return []

    pupitre_dir = records_base / srv_subdir / housing
    if not pupitre_dir.is_dir():
        print(f"[WARN] pupitre directory not found: {pupitre_dir}")
        return []

    t_start, t_end = _site_window(site, db_tz)

    matches: list[tuple[Path, datetime]] = []
    for fpath in sorted(pupitre_dir.glob("*.txt")):
        ts = parse_pupitre_file_ts(fpath.name)
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
                _insert_operationaldata(con, site["name"], fpath, "Pupitre", records_base)
                for fpath, _ in matches
            )
        skipped = len(matches) - new_count
        print(
            f"\noperationaldata: inserted {new_count} new row(s)"
            + (f", {skipped} already present." if skipped else ".")
        )

    return matches


# ---------------------------------------------------------------------------
# TDMS
# ---------------------------------------------------------------------------

def parse_tdms_file_ts(filename: str, file_type: str) -> datetime | None:
    """Return a timezone-aware datetime parsed from a TDMS filename, or None."""
    pattern, fmt = _TDMS_TS_PATTERNS[file_type]
    m = pattern.search(filename)
    if not m:
        return None
    try:
        naive = datetime.strptime(m.group(1), fmt)
        return naive.replace(tzinfo=FILE_TZ)
    except ValueError:
        return None


def scan_tdms_subdir(
    subdir:    Path,
    file_type: str,
    t_start:   datetime | None,
    t_end:     datetime | None,
) -> list[tuple[Path, datetime, str]]:
    """Scan one TDMS subdirectory; return matching (path, timestamp, type) tuples."""
    if not subdir.is_dir():
        return []
    matches = []
    for fpath in sorted(subdir.glob("*.tdms")):
        ts = parse_tdms_file_ts(fpath.name, file_type)
        if ts is None:
            continue
        if t_start is not None and ts < t_start:
            continue
        if t_end is not None and ts > t_end:
            continue
        matches.append((fpath, ts, file_type))
    return matches


def find_and_register_tdms(
    site:         dict,
    db_path:      str,
    db_tz:        ZoneInfo,
    dry_run:      bool,
    type_filter:  list[str] | None = None,
    records_base: Path = _RECORDS_BASE,
    pbsurv:       str  = _PBSURV,
) -> list[tuple[Path, datetime, str]]:
    """Scan for TDMS files in the site's operational window.

    Returns matched (path, timestamp, type) triples. Writes to operationaldata
    unless *dry_run* is True.
    """
    housing = site["housing"]
    if not housing:
        print(f"[WARN] site '{site['name']}' has no housing value.")
        return []

    t_start, t_end = _site_window(site, db_tz)

    active_types = type_filter if type_filter else TDMS_TYPES
    matches: list[tuple[Path, datetime, str]] = []

    pbsurv_dir = records_base / pbsurv
    for file_type in active_types:
        subdir = pbsurv_dir / housing / _TDMS_SUBDIR_NAMES[file_type]
        found = scan_tdms_subdir(subdir, file_type, t_start, t_end)
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
                _insert_operationaldata(con, site["name"], fpath, file_type, records_base)
                for fpath, _, file_type in matches
            )
        skipped = len(matches) - new_count
        print(
            f"\noperationaldata: inserted {new_count} new row(s)"
            + (f", {skipped} already present." if skipped else ".")
        )

    return matches
