#!/usr/bin/env python
"""Demo: find likely ``experiments``/``overview_records`` candidates by timestamp proximity.

Standalone script — not wired into ``users_table_demo.py`` or
``magnetdb.py`` yet. Companion to ``find_research_area_candidates.py``.

For ``users`` rows with no ``experiments_ids`` (resp. no
``overview_records_ids``), searches same-housing ``experiments``
(resp. live ``overview_records``) for the nearest file(s) by the
timestamp embedded in the filename, and scores them by proximity to
``[hstart, hstop]``. Both the pupitre filename
(``"YYYY.MM.DD - HH:MM:SS.txt"``) and the Overview filename
(``"<housing>_Overview_YYMMDD-HHMM"``) embed Europe/Paris local time
directly — same convention as ``hstart``/``hstop`` — so no timezone
conversion is needed here (this intentionally reads the raw filename
rather than ``overview_records.t0``, which is stored in UTC).

Read-only — prints candidates for manual review, never writes anything
back.

Run from the repository root, e.g.::

    python to_duckdb/demos/find_linking_candidates.py
    python to_duckdb/demos/find_linking_candidates.py --acronym GIS0122
    python to_duckdb/demos/find_linking_candidates.py --top 5 --max-distance-hours 6
"""

import argparse
import bisect
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import duckdb

_EXP_FILE_TS_SQL = (
    r"TRY_STRPTIME(regexp_extract(file, '(\d{4}\.\d{2}\.\d{2} - \d{2}:\d{2}:\d{2})', 1), "
    r"'%Y.%m.%d - %H:%M:%S')"
)
_OVERVIEW_FILENAME_TS_RE = re.compile(r"(\d{6}-\d{4})$")
_OVERVIEW_FILENAME_TS_FMT = "%y%m%d-%H%M"


def build_experiments_index(con) -> dict[str, list[tuple[datetime, str]]]:
    """Build a per-housing, timestamp-sorted index of ``experiments``.

    Parameters
    ----------
    con:
        Open DuckDB connection.

    Returns
    -------
    dict[str, list[tuple[datetime, str]]]
        Housing -> list of ``(timestamp, file)``, sorted by timestamp.
        `timestamp` is parsed from `file`'s embedded
        ``"YYYY.MM.DD - HH:MM:SS"`` (Europe/Paris local, same as
        `_EXP_FILE_TS` in ``crud.py``). Rows with no ``assembly_name`` or
        an unparseable `file` are skipped.
    """
    rows = con.execute(
        f"SELECT file, split_part(assembly_name, '_', 1) AS housing, "
        f"{_EXP_FILE_TS_SQL} AS ts FROM experiments WHERE assembly_name IS NOT NULL"
    ).fetchall()
    by_housing: dict[str, list[tuple[datetime, str]]] = defaultdict(list)
    for file, housing, ts in rows:
        if ts is not None:
            by_housing[housing].append((ts, file))
    for entries in by_housing.values():
        entries.sort(key=lambda entry: entry[0])
    return by_housing


def build_overview_index(con) -> dict[str, list[tuple[datetime, str]]]:
    """Build a per-housing, timestamp-sorted index of live ``overview_records``.

    Parameters
    ----------
    con:
        Open DuckDB connection.

    Returns
    -------
    dict[str, list[tuple[datetime, str]]]
        Housing -> list of ``(timestamp, filename)``, sorted by
        timestamp. `timestamp` is parsed straight from `filename`'s
        embedded ``YYMMDD-HHMM`` (Europe/Paris local, per
        ``_parse_overview_filename`` in ``crud.py``) — deliberately not
        read from the ``t0`` column, which is stored in UTC. Only
        ``merged_into IS NULL`` (live) rows are considered.
    """
    rows = con.execute(
        "SELECT filename, housing FROM overview_records WHERE merged_into IS NULL"
    ).fetchall()
    by_housing: dict[str, list[tuple[datetime, str]]] = defaultdict(list)
    for filename, housing in rows:
        match = _OVERVIEW_FILENAME_TS_RE.search(filename)
        if not match:
            continue
        try:
            ts = datetime.strptime(match.group(1), _OVERVIEW_FILENAME_TS_FMT)
        except ValueError:
            continue
        by_housing[housing].append((ts, filename))
    for entries in by_housing.values():
        entries.sort(key=lambda entry: entry[0])
    return by_housing


def fetch_unmatched(con, id_column: str) -> list[tuple[str, str, datetime, datetime | None]]:
    """Fetch ``users`` rows where `id_column` is NULL.

    Parameters
    ----------
    con:
        Open DuckDB connection.
    id_column : str
        ``"experiments_ids"`` or ``"overview_records_ids"``.

    Returns
    -------
    list[tuple[str, str, datetime, datetime | None]]
        ``(acronym, housing, hstart, hstop)`` rows, ordered by acronym,
        housing, hstart.
    """
    return con.execute(
        f"SELECT acronym, housing, hstart, hstop FROM users "
        f"WHERE {id_column} IS NULL ORDER BY acronym, housing, hstart"
    ).fetchall()


def _nearest_candidates(
    entries: list[tuple[datetime, str]],
    keys: list[datetime],
    hstart: datetime,
    hstop: datetime | None,
    top: int,
    max_distance_hours: float,
) -> list[tuple[str, float, float]]:
    """Find the nearest indexed entries to a session window.

    Searches around both `hstart` and the window end (`hstop`, or
    `hstart` again for an open session) via `bisect`, since for a wide
    window the nearest-before-start and nearest-after-end candidates can
    sit far apart in `entries`.

    Parameters
    ----------
    entries : list[tuple[datetime, str]]
        Timestamp-sorted ``(timestamp, label)`` pairs for one housing.
    keys : list[datetime]
        The timestamps from `entries`, as a separate list for `bisect`.
    hstart : datetime
        Session start.
    hstop : datetime or None
        Session end, or ``None`` for an open session.
    top : int
        Maximum number of candidates to return.
    max_distance_hours : float
        Only candidates within this many hours of the window are kept.

    Returns
    -------
    list[tuple[str, float, float]]
        ``(label, signed_distance_seconds, score)``, sorted by score
        descending and capped at `top`. `signed_distance_seconds` is
        ``0.0`` inside the window, negative before `hstart`, positive
        after the window end. `score` is ``1 / (1 + distance_hours)``.
    """
    window_end = hstop if hstop is not None else hstart
    max_distance_seconds = max_distance_hours * 3600

    candidate_idxs: set[int] = set()
    for anchor in (hstart, window_end):
        i = bisect.bisect_left(keys, anchor)
        for j in (i - 1, i, i + 1):
            if 0 <= j < len(entries):
                candidate_idxs.add(j)

    scored = []
    for idx in candidate_idxs:
        ts, label = entries[idx]
        if hstart <= ts <= window_end:
            signed_distance = 0.0
        elif ts < hstart:
            signed_distance = (ts - hstart).total_seconds()
        else:
            signed_distance = (ts - window_end).total_seconds()
        if abs(signed_distance) > max_distance_seconds:
            continue
        score = 1 / (1 + abs(signed_distance) / 3600)
        scored.append((label, signed_distance, score))

    scored.sort(key=lambda entry: -entry[2])
    return scored[:top]


def _format_distance(signed_distance: float) -> str:
    """Human-readable label for a signed distance in seconds."""
    if signed_distance == 0.0:
        return "within window"
    direction = "before hstart" if signed_distance < 0 else "after hstop"
    magnitude = abs(signed_distance)
    if magnitude < 60:
        text = f"{magnitude:.1f}s"
    elif magnitude < 3600:
        text = f"{magnitude / 60:.1f}min"
    elif magnitude < 86400:
        text = f"{magnitude / 3600:.2f}h"
    else:
        text = f"{magnitude / 86400:.1f}d"
    return f"{text} {direction}"


def report_section(
    label: str,
    unmatched_rows: list[tuple[str, str, datetime, datetime | None]],
    index_by_housing: dict[str, list[tuple[datetime, str]]],
    top: int,
    max_distance_hours: float,
    acronym_filter: str | None,
) -> None:
    """Print nearest-candidate results for one id column.

    Parameters
    ----------
    label : str
        Section label, e.g. ``"experiments_ids"``.
    unmatched_rows : list[tuple[str, str, datetime, datetime | None]]
        Rows from `fetch_unmatched`.
    index_by_housing : dict[str, list[tuple[datetime, str]]]
        Index from `build_experiments_index`/`build_overview_index`.
    top : int
        Maximum candidates printed per row.
    max_distance_hours : float
        Only candidates within this many hours of the window are shown.
    acronym_filter : str or None
        Restrict to this acronym only, if given.
    """
    results = []
    no_candidate = 0
    for acronym, housing, hstart, hstop in unmatched_rows:
        if acronym_filter and acronym != acronym_filter:
            continue
        entries = index_by_housing.get(housing, [])
        candidates: list[tuple[str, float, float]] = []
        if entries:
            keys = [entry[0] for entry in entries]
            candidates = _nearest_candidates(
                entries, keys, hstart, hstop, top, max_distance_hours
            )
        if candidates:
            results.append((acronym, housing, hstart, hstop, candidates))
        else:
            no_candidate += 1

    total = len(results) + no_candidate
    print(
        f"\n{label} candidates: {len(results)} rows with a same-housing candidate "
        f"within {max_distance_hours}h, {no_candidate} with none (of {total} considered)"
    )
    for acronym, housing, hstart, hstop, candidates in results:
        hstop_str = hstop if hstop is not None else "(open)"
        print(f"  {acronym}  {housing}  {hstart} -> {hstop_str}")
        for i, (candidate_label, signed_distance, score) in enumerate(candidates, start=1):
            print(
                f"    {i}. {candidate_label}  score={score:.3f}  "
                f"distance={_format_distance(signed_distance)}"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("to_duckdb/test-magnetdb.duckdb"),
        help="Target DuckDB database file.",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=3,
        help="Maximum number of candidates to print per row.",
    )
    parser.add_argument(
        "--max-distance-hours",
        type=float,
        default=24.0,
        help="Only show candidates within this many hours of the session window.",
    )
    parser.add_argument(
        "--acronym",
        default=None,
        help="Restrict the search to a single acronym.",
    )
    args = parser.parse_args()

    con = duckdb.connect(str(args.db), read_only=True)
    try:
        experiments_index = build_experiments_index(con)
        experiments_unmatched = fetch_unmatched(con, "experiments_ids")
        report_section(
            "experiments_ids",
            experiments_unmatched,
            experiments_index,
            args.top,
            args.max_distance_hours,
            args.acronym,
        )

        overview_index = build_overview_index(con)
        overview_unmatched = fetch_unmatched(con, "overview_records_ids")
        report_section(
            "overview_records_ids",
            overview_unmatched,
            overview_index,
            args.top,
            args.max_distance_hours,
            args.acronym,
        )
    finally:
        con.close()


if __name__ == "__main__":
    main()
