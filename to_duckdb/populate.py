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

    load_assembly(assembly_name, db_path)          → dict | None
    find_and_register_pupitre(...)         → list[(Path, datetime)]
    find_and_register_tdms(...)            → list[(Path, datetime, str)]
    resolve_operationaldata_path(...)      → Path
    fill_operationaldata_metadata(...)     → dict   (t_start / t_end / mode)
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
_UTC          = ZoneInfo("UTC")

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
    # pigbrother Stats files: per-signal 1 s statistics (lower-case "s" on disk)
    "SignalStats": "Fichiers_stats",
    "Trigger":  "Fichiers_Manuel_Trig",
}
TDMS_TYPES = list(_TDMS_SUBDIR_NAMES)

# strptime format by timestamp length, for names written with either precision
_MINUTE_OR_SECOND: dict[int, str] = {11: "%y%m%d-%H%M", 13: "%y%m%d-%H%M%S"}

# Per-type: (compiled pattern, strptime format or {length: format})
# Overview/Archive: YYDDMM-HHMM  (French day-first, minute precision)
# Spike/Default/Trigger: YYMMDD-HHMMSS (ISO order, second precision)
# SignalStats: YYMMDD-HHMMSS, or YYMMDD-HHMM with a stray extra underscore
#              in legacy names (e.g. M9_Stats__190304-1459.tdms)
_TDMS_TS_PATTERNS: dict[str, tuple[re.Pattern, str | dict[int, str]]] = {
    "Overview": (re.compile(r"(\d{6}-\d{4})\.tdms$",   re.IGNORECASE), "%y%m%d-%H%M"),
    "Archive":  (re.compile(r"(\d{6}-\d{4})\.tdms$",   re.IGNORECASE), "%y%m%d-%H%M"),
    "Spike":    (re.compile(r"_Spikes_(\d{6}-\d{6})",  re.IGNORECASE), "%y%m%d-%H%M%S"),
    "Default":  (re.compile(r"_Default_(\d{6}-\d{6})", re.IGNORECASE), "%y%m%d-%H%M%S"),
    "SignalStats": (
        re.compile(r"_Stats_+(\d{6}-\d{4}(?:\d{2})?)(?!\d)", re.IGNORECASE), _MINUTE_OR_SECOND,
    ),
    "Trigger":  (re.compile(r"_ManuelTrig_(\d{6}-\d{6})", re.IGNORECASE), "%y%m%d-%H%M%S"),
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


def load_assembly(assembly_name: str, db_path: str) -> dict | None:
    """Return the assembly row as a dict, or None if not found."""
    with duckdb.connect(db_path, read_only=True) as con:
        row = con.execute(
            "SELECT name, housing, status, commissioned_at, decommissioned_at "
            "FROM assemblies WHERE name = ?",
            [assembly_name],
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
    con, assembly_name: str, fpath: Path, file_type: str, records_base: Path
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
        "INSERT INTO operationaldata (name, description, file, assembly_name, type, status) "
        "VALUES (?, '', ?, ?, ?, 'pending')",
        [fpath.stem, relpath, assembly_name, file_type],
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


# Incident captures are not read: t_start = t_end = the time in their name
# (about 8 h saved on the first metadata pass, mostly Spike files).
_NAME_ONLY_TYPES = frozenset({"Spike", "Default", "Trigger"})

# Default / Trigger captures start at their name time and last 30, 60 or 90 s
# (measured on 2015-2026 files, 2026-11-13). Only those named less than this
# before an Overview start can overlap it while their name time lies outside
# it, so only they are read, for their real end.
_INCIDENT_END_TYPES = ("Default", "Trigger")
_MAX_INCIDENT_CAPTURE_S = 90


def _local_to_db(ts: str, db_tz: ZoneInfo) -> datetime:
    """Convert a ``python_magnetrun`` local (Europe/Paris) timestamp to naive *db_tz*."""
    from python_magnetrun.utils.files import TIMESTAMP_FORMAT

    local = datetime.strptime(ts, TIMESTAMP_FORMAT).replace(tzinfo=FILE_TZ)
    return local.astimezone(db_tz).replace(tzinfo=None)


def _overview_mode(path: Path, housing: str | None, verbose: bool) -> str | None:
    """Operating mode of one Overview file (IH / IB channels of *housing* at the file time), or None."""
    from python_magnetrun import magnetdata

    from crud import _overview_current_channels, _parse_overview_filename, infer_operating_mode

    try:
        df = magnetdata.load_magnetdata(str(path)).Data["Courants_Alimentations"]
    except Exception as exc:  # noqa: BLE001 — any unreadable TDMS leaves mode NULL
        if verbose:
            print(f"  ! {path.name}: could not read Courants_Alimentations: {exc}")
        return None
    try:
        ih, ib = _overview_current_channels(housing, _parse_overview_filename(path.stem)[1])
        return infer_operating_mode(df, ih=ih, ib=ib)
    except ValueError as exc:
        if verbose:
            print(f"  ! {path.name}: {exc}")
        return None


def fill_operationaldata_metadata(
    con,
    assembly_name: str,
    types: list[str] | None = None,
    reprocess: bool = False,
    records_base: Path = _RECORDS_BASE,
    db_tz: ZoneInfo = _UTC,
    dry_run: bool = False,
    verbose: bool = True,
) -> dict:
    """Store each file's start/end time, and the mode of Overview files, once.

    Start/end come from ``python_magnetrun``'s metadata-only path
    (:func:`python_magnetrun.utils.files.extract_data` with ``key=None``:
    TDMS properties, Archive mtime, last pupitre line), so no data is loaded
    except for Overview files, whose ``Courants_Alimentations`` group is
    loaded once to infer the operating mode. Spike, Default and Trigger
    captures (:data:`_NAME_ONLY_TYPES`) are not read: both ``t_start`` and
    ``t_end`` are the time in their name. A second pass then reads the
    Default and Trigger files named less than
    :data:`_MAX_INCIDENT_CAPTURE_S` before the start of an Overview of the
    same housing, and stores their real ``t_end``, so the SQL builder can
    match a capture that starts just before an overview. Each row is
    written as soon as it is computed, so an interrupted run resumes where
    it stopped.

    Parameters
    ----------
    con : duckdb.DuckDBPyConnection
        Open connection with the current schema.
    assembly_name : str
        ``operationaldata.assembly_name`` of the rows to fill.
    types : list[str], optional
        Restrict to these ``operationaldata.type`` values; all types when
        omitted.
    reprocess : bool, optional
        Recompute rows that already have ``t_end``; by default only rows
        with ``t_end IS NULL`` are processed.
    records_base : :class:`~pathlib.Path`, optional
        Root of the records tree (default: :data:`_RECORDS_BASE`).
    db_tz : :class:`~zoneinfo.ZoneInfo`, optional
        Timezone of the stored naive timestamps (default UTC, the
        convention of ``overview_records.t0``).
    dry_run : bool, optional
        Compute but write nothing.
    verbose : bool, optional
        Print one line per file.

    Returns
    -------
    dict
        ``{"filled": int, "no_time_range": int, "incident_ends": int,
        "errors": list[tuple[str, str]]}``; ``filled`` counts the rows
        written (or that would be, with *dry_run*), ``incident_ends`` the
        Default / Trigger files read for their end.
    """
    from python_magnetrun.utils import files as mr_files

    housing_row = con.execute(
        "SELECT housing FROM assemblies WHERE name = ?", [assembly_name]
    ).fetchone()
    housing = housing_row[0] if housing_row else None

    conditions = ["assembly_name = ?"]
    params: list = [assembly_name]
    if types:
        conditions.append(f"type IN ({', '.join('?' * len(types))})")
        params.extend(types)
    if not reprocess:
        conditions.append("t_end IS NULL")
    rows = con.execute(
        f"SELECT id, file, type FROM operationaldata WHERE {' AND '.join(conditions)} ORDER BY id",
        params,
    ).fetchall()

    counts: dict = {"filled": 0, "no_time_range": 0, "incident_ends": 0, "errors": []}
    for od_id, relpath, file_type in rows:
        path = resolve_operationaldata_path(relpath, records_base)
        if file_type in _NAME_ONLY_TYPES:
            named = parse_tdms_file_ts(path.name, file_type)
            if named is None:
                counts["no_time_range"] += 1
                if verbose:
                    print(f"  ! {relpath}: no timestamp in the file name")
                continue
            t_start = t_end = named.astimezone(db_tz).replace(tzinfo=None)
        else:
            try:
                start, end, _skip = mr_files.extract_data(
                    str(path), housing, assembly="", key=None, dry_run=False
                )
            except (OSError, ValueError, RuntimeError, UnicodeDecodeError) as exc:
                counts["errors"].append((relpath, str(exc)))
                if verbose:
                    print(f"  [ERROR] {relpath}: {exc}")
                continue
            if not start or not end:
                counts["no_time_range"] += 1
                if verbose:
                    print(f"  ! {relpath}: no time range (start={start!r}, end={end!r})")
                continue
            t_start, t_end = _local_to_db(start, db_tz), _local_to_db(end, db_tz)

        mode = _overview_mode(path, housing, verbose) if file_type == "Overview" else None
        if not dry_run:
            con.execute(
                "UPDATE operationaldata SET t_start = ?, t_end = ?, mode = ? WHERE id = ?",
                [t_start, t_end, mode, od_id],
            )
        counts["filled"] += 1
        if verbose:
            prefix = "[dry-run] " if dry_run else ""
            suffix = f"  mode={mode}" if file_type == "Overview" else ""
            print(f"  {prefix}{relpath}  {t_start} → {t_end}{suffix}")

    if not types or set(types) & set(_INCIDENT_END_TYPES):
        _fill_incident_ends(
            con, assembly_name, housing, records_base, db_tz, dry_run, verbose, counts
        )
    return counts


def _fill_incident_ends(
    con, assembly_name, housing, records_base, db_tz, dry_run, verbose, counts
) -> None:
    """Read the real end of Default/Trigger files named just before an Overview start (updates *counts*)."""
    from python_magnetrun.utils import files as mr_files

    rows = con.execute(
        f"""
        SELECT od.id, od.file FROM operationaldata od
        WHERE od.assembly_name = ? AND od.type IN ({', '.join('?' * len(_INCIDENT_END_TYPES))})
          AND od.t_end = od.t_start
          AND EXISTS (
              SELECT 1 FROM operationaldata ov JOIN assemblies a ON a.name = ov.assembly_name
              WHERE ov.type = 'Overview' AND a.housing = ?
                AND ov.t_start > od.t_start
                AND ov.t_start < od.t_start + INTERVAL {_MAX_INCIDENT_CAPTURE_S} SECOND)
        ORDER BY od.id
        """,
        [assembly_name, *_INCIDENT_END_TYPES, housing],
    ).fetchall()

    for od_id, relpath in rows:
        path = resolve_operationaldata_path(relpath, records_base)
        try:
            _start, end, _skip = mr_files.extract_data(
                str(path), housing, assembly="", key=None, dry_run=False
            )
        except (OSError, ValueError, RuntimeError, UnicodeDecodeError) as exc:
            counts["errors"].append((relpath, str(exc)))
            if verbose:
                print(f"  [ERROR] {relpath}: {exc}")
            continue
        if not end:
            counts["no_time_range"] += 1
            if verbose:
                print(f"  ! {relpath}: no end time")
            continue
        t_end = _local_to_db(end, db_tz)
        if not dry_run:
            con.execute("UPDATE operationaldata SET t_end = ? WHERE id = ?", [t_end, od_id])
        counts["incident_ends"] += 1
        if verbose:
            prefix = "[dry-run] " if dry_run else ""
            print(f"  {prefix}{relpath}  end read: {t_end}")


def _assembly_window(
    assembly: dict, db_tz: ZoneInfo
) -> tuple[datetime | None, datetime | None]:
    """Return (t_start, t_end) both expressed in FILE_TZ (Europe/Paris)."""
    t_start = as_aware(assembly["commissioned_at"],   db_tz)
    t_end   = as_aware(assembly["decommissioned_at"], db_tz)
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
        return datetime.strptime(m.group(1), _PUPITRE_TS_FMT).replace(tzinfo=FILE_TZ)
    except ValueError:
        return None


def load_pupitre_skip_list(
    path: Path,
    records_base: Path = _RECORDS_BASE,
    srv_subdir: str = _SRV_SUBDIR,
) -> frozenset[str]:
    """Read the list of pupitre files the build must not load (data issue #18).

    The file is JSON: ``{"description": ..., "files": [{"file":
    "<housing>/<file name>", "reason": ...}, ...]}``, with ``file`` relative to
    ``records_base / srv_subdir``. The housing folder is part of the key, so a
    copy stored under the wrong housing is skipped while the original, which
    has the same file name, is kept.

    Parameters
    ----------
    path : :class:`~pathlib.Path`
        The JSON skip list (``hifimagnet-projects/magnetdb.json/pupitre_skip.json``).
    records_base : :class:`~pathlib.Path`, optional
        Root of the records tree, to warn about listed files that do not exist.
    srv_subdir : str, optional
        Subdirectory of *records_base* holding the pupitre TXT files.

    Returns
    -------
    frozenset[str]
        ``"<housing>/<file name>"`` keys.

    Raises
    ------
    ValueError
        If an entry has no ``reason`` or its ``file`` is not ``<housing>/<file name>``.
    """
    import json

    keys = set()
    for entry in json.loads(Path(path).read_text(encoding="utf-8")).get("files", []):
        key = entry.get("file", "")
        parts = key.split("/")
        if len(parts) != 2 or not all(parts) or not entry.get("reason"):
            raise ValueError(
                f"{path}: invalid entry {entry!r} "
                "(needs 'file' = '<housing>/<file name>' and a 'reason')"
            )
        if not (Path(records_base) / srv_subdir / key).exists():
            print(f"[WARN] {Path(path).name}: {key} not found under {Path(records_base) / srv_subdir}")
        keys.add(key)
    return frozenset(keys)


def split_skipped(
    matches: list[tuple[Path, datetime]], housing: str, skip: frozenset[str]
) -> tuple[list[tuple[Path, datetime]], list[tuple[Path, datetime]]]:
    """Split pupitre *matches* of *housing* into (kept, excluded by the *skip* list)."""
    kept, excluded = [], []
    for match in matches:
        (excluded if f"{housing}/{match[0].name}" in skip else kept).append(match)
    return kept, excluded


def find_and_register_pupitre(
    assembly:         dict,
    db_path:      str,
    db_tz:        ZoneInfo,
    dry_run:      bool,
    records_base: Path = _RECORDS_BASE,
    srv_subdir:   str  = _SRV_SUBDIR,
    skip:         frozenset[str] = frozenset(),
) -> list[tuple[Path, datetime]]:
    """Scan for pupitre TXT files in the assembly's operational window.

    Returns matched (path, timestamp) pairs, without the files of the *skip*
    list (:func:`load_pupitre_skip_list`). Writes to operationaldata unless
    *dry_run* is True.
    """
    housing = assembly["housing"]
    if not housing:
        print(f"[WARN] assembly '{assembly['name']}' has no housing value.")
        return []

    pupitre_dir = records_base / srv_subdir / housing
    if not pupitre_dir.is_dir():
        print(f"[WARN] pupitre directory not found: {pupitre_dir}")
        return []

    t_start, t_end = _assembly_window(assembly, db_tz)

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

    matches, excluded = split_skipped(matches, housing, skip)
    print(f"[OK]   {pupitre_dir}/  — {len(matches)} file(s) matched")
    for fpath, _ in excluded:
        print(f"[SKIP] {housing}/{fpath.name}  (listed in the skip file)")

    if matches and not dry_run:
        from crud import _log_operation

        with duckdb.connect(db_path) as con:
            ensure_schema(con)
            new_count = sum(
                _insert_operationaldata(con, assembly["name"], fpath, "Pupitre", records_base)
                for fpath, _ in matches
            )
            skipped = len(matches) - new_count
            _log_operation(
                con, "populate", "operationaldata", assembly["name"],
                details={"inserted": new_count, "skipped": skipped, "excluded": len(excluded)},
            )
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
    token = m.group(1)
    if isinstance(fmt, dict):
        # pick by length: strptime is lenient about digit counts
        fmt = fmt[len(token)]
    try:
        return datetime.strptime(token, fmt).replace(tzinfo=FILE_TZ)
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
    assembly:         dict,
    db_path:      str,
    db_tz:        ZoneInfo,
    dry_run:      bool,
    type_filter:  list[str] | None = None,
    records_base: Path = _RECORDS_BASE,
    pbsurv:       str  = _PBSURV,
) -> list[tuple[Path, datetime, str]]:
    """Scan for TDMS files in the assembly's operational window.

    Returns matched (path, timestamp, type) triples. Writes to operationaldata
    unless *dry_run* is True.
    """
    housing = assembly["housing"]
    if not housing:
        print(f"[WARN] assembly '{assembly['name']}' has no housing value.")
        return []

    t_start, t_end = _assembly_window(assembly, db_tz)

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
        from crud import _log_operation

        with duckdb.connect(db_path) as con:
            ensure_schema(con)
            new_count = sum(
                _insert_operationaldata(con, assembly["name"], fpath, file_type, records_base)
                for fpath, _, file_type in matches
            )
            skipped = len(matches) - new_count
            _log_operation(
                con, "populate", "operationaldata", assembly["name"],
                details={"inserted": new_count, "skipped": skipped},
            )
        print(
            f"\noperationaldata: inserted {new_count} new row(s)"
            + (f", {skipped} already present." if skipped else ".")
        )

    return matches
