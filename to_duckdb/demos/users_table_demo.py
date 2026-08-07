#!/usr/bin/env python
"""Demo: build and populate the ``users`` table from EXPERIENCES_LOG.

Standalone script — not wired into populate.py / magnetdb.py yet. Reads
``Data/EXPERIENCES_LOG.csv`` (one row per experiment session, keyed by
``UserCode``) and a proposals CSV (keyed by ``Acronym``, possibly typo'd
relative to ``UserCode``), joins them with fuzzy matching, and populates the
``users`` table of a DuckDB database with one row per acronym. By default the
table's contents are fully replaced; pass ``--sync`` to instead add only new
rows and correct mismatched existing ones in place.

Run from the repository root, e.g.::

    python to_duckdb/demos/users_table_demo.py
    python to_duckdb/demos/users_table_demo.py --from 2020-01-01
    python to_duckdb/demos/users_table_demo.py --sync
    python to_duckdb/demos/users_table_demo.py --list
    python to_duckdb/demos/users_table_demo.py --view
    python to_duckdb/demos/users_table_demo.py --view <ACRONYM>
"""

import argparse
import csv
import difflib
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef]

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from crud import _EXP_FILE_TS  # noqa: E402
from schema import ensure_schema  # noqa: E402

FILE_TZ = ZoneInfo("Europe/Paris")
MAGNET_SUFFIX_RE = re.compile(r"[ei]$")
MAGNET_NUMBER_RE = re.compile(r"\d+")
# HStart/HStop embed a 24-hour %H alongside a spurious trailing AM/PM marker
# (e.g. "8/31/06  14:50:56.078 PM"); %p is parsed but has no effect since %H
# already disambiguates the hour.
HLOG_TIMESTAMP_FMT = "%m/%d/%y  %H:%M:%S.%f %p"


def normalize_magnet(magnet: str) -> str:
    """Strip the trailing insert/external suffix from a magnet name."""
    return MAGNET_SUFFIX_RE.sub("", magnet.strip())


def parse_hlog_timestamp(value: str) -> datetime:
    """Parse an EXPERIENCES_LOG ``HStart``/``HStop`` value."""
    return datetime.strptime(value.strip(), HLOG_TIMESTAMP_FMT)


def _housing_sort_key(magnet: str) -> int:
    """Sort key so housings sort numerically (M9 before M10)."""
    match = MAGNET_NUMBER_RE.search(magnet)
    return int(match.group()) if match else 0


def parse_cutoff(value: str) -> datetime:
    """Parse ``--from`` into a naive Europe/Paris local wall-clock datetime.

    Parameters
    ----------
    value : str
        An ISO date or datetime, e.g. ``"2020-01-01"``. May include a UTC
        offset (e.g. ``"2020-01-01T00:00:00+01:00"``); if present it is
        converted to Europe/Paris wall-clock. If absent, `value` is assumed
        to already be Europe/Paris local time — which is how the source
        CSVs store their timestamps (no offset recorded).

    Returns
    -------
    :class:`~datetime.datetime`
        Naive datetime representing Europe/Paris local wall-clock, directly
        comparable to the naive timestamps parsed from the source CSVs.
    """
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is not None:
        dt = dt.astimezone(FILE_TZ).replace(tzinfo=None)
    return dt


def load_log(
    log_path: Path, cutoff: datetime | None
) -> tuple[
    dict[str, list[tuple[str, str | None, datetime, datetime | None]]],
    dict[str, list[datetime]],
    int,
    int,
]:
    """Group EXPERIENCES_LOG sessions by acronym (UserCode).

    Parameters
    ----------
    log_path : :class:`~pathlib.Path`
        Path to ``EXPERIENCES_LOG.csv``.
    cutoff : datetime or None
        Naive Europe/Paris datetime; sessions strictly before it are
        discarded. ``None`` disables filtering.

    Returns
    -------
    sessions : dict[str, list[tuple[str, str | None, datetime, datetime | None]]]
        Acronym -> list of ``(housing, variant, HStart, HStop)`` session
        records. `housing` is the normalized base magnet (e.g. ``"M9"``);
        `variant` is the raw magnet's stripped suffix (``"e"``/``"i"``), or
        ``None`` for magnets with no insert/external variant. ``HStop`` is
        ``None`` when EXPERIENCES_LOG left it blank (session not closed).
    timestamps : dict[str, list[datetime]]
        Acronym -> list of surviving session start timestamps.
    n_total : int
        Total rows read.
    n_discarded : int
        Rows dropped by `cutoff`.

    Raises
    ------
    ValueError
        If a row has an empty ``UserCode`` — acronym is a required field
        and an empty one signals a data-quality problem upstream.
    """
    sessions: dict[str, list[tuple[str, str | None, datetime, datetime | None]]] = (
        defaultdict(list)
    )
    timestamps: dict[str, list[datetime]] = defaultdict(list)
    n_total = 0
    n_discarded = 0
    with open(log_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for lineno, row in enumerate(reader, start=2):
            n_total += 1
            acronym = row["UserCode"].strip()
            if not acronym:
                raise ValueError(
                    f"{log_path}:{lineno}: empty UserCode (acronym) is not allowed"
                )
            ts = datetime.fromisoformat(row["timestamp"].strip())
            if cutoff is not None and ts < cutoff:
                n_discarded += 1
                continue
            raw_magnet = row["Magnet"].strip()
            magnet = normalize_magnet(raw_magnet)
            variant = raw_magnet[-1] if raw_magnet != magnet else None
            hstart = parse_hlog_timestamp(row["HStart"])
            hstop_str = row["HStop"].strip()
            hstop = parse_hlog_timestamp(hstop_str) if hstop_str else None
            sessions[acronym].append((magnet, variant, hstart, hstop))
            timestamps[acronym].append(ts)
    return sessions, timestamps, n_total, n_discarded


def load_proposals(
    proposals_path: Path, cutoff: datetime | None
) -> tuple[dict[str, list[dict[str, str]]], int, int, int]:
    """Index proposal rows by acronym.

    Parameters
    ----------
    proposals_path : :class:`~pathlib.Path`
        Path to the proposals CSV (``Acronym``, ``Research Area``,
        ``Call Number``, ``Access Mode``, ``Experiment Start/End Date``, ...).
    cutoff : datetime or None
        Naive Europe/Paris datetime. Rows whose ``Experiment Start Date`` is
        present and strictly before `cutoff` are discarded; rows with a
        blank date are always kept (unknown, so not assumed to be old).

    Returns
    -------
    acronym_rows : dict[str, list[dict[str, str]]]
        Acronym -> list of matching CSV rows (usually length 1).
    n_total : int
        Total rows read.
    n_discarded : int
        Rows dropped by `cutoff`.
    n_ignored : int
        Rows with empty acronym or invalid start date.
    """
    acronym_rows: dict[str, list[dict[str, str]]] = defaultdict(list)
    n_total = 0
    n_discarded = 0
    n_ignored = 0
    with open(proposals_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            n_total += 1
            acronym = row["Acronym"].strip()
            if not acronym:
                n_ignored += 1
                continue
            if cutoff is not None:
                date_str = row["Experiment Start Date"].strip()
                if date_str:
                    try:
                        start_date = datetime.fromisoformat(date_str).date()
                        # print(f"DEBUG: {acronym} start date {start_date} vs cutoff {cutoff.date()} ({start_date < cutoff.date()})")
                    except ValueError:
                        start_date = None
                        n_ignored += 1
                        #print(f"DEBUG: {acronym} start date {date_str} is invalid")
                    if start_date is not None and start_date < cutoff.date():
                        n_discarded += 1
                        continue
                else:
                    year_str = row["Experiment Year"].strip()
                    if year_str and int(year_str) < cutoff.year:
                        n_discarded += 1
                        continue
                    # print(f"DEBUG: {acronym} has no start date, keeping it")
                                        
            acronym_rows[acronym].append(row)
    return acronym_rows, n_total, n_discarded, n_ignored


def find_proposal_rows(
    acronym: str,
    acronym_rows: dict[str, list[dict[str, str]]],
    acronym_rows_lower: dict[str, str],
    fuzzy_cutoff: float,
) -> tuple[list[dict[str, str]] | None, str | None, str | None]:
    """Find the proposal rows matching a EXPERIENCES_LOG acronym.

    Parameters
    ----------
    acronym : str
        The EXPERIENCES_LOG ``UserCode`` to look up.
    acronym_rows : dict[str, list[dict[str, str]]]
        Mapping from `load_proposals`.
    acronym_rows_lower : dict[str, str]
        Lower-cased acronym -> original-case acronym.
    fuzzy_cutoff : float
        `difflib.get_close_matches` similarity cutoff for typo matching.

    Returns
    -------
    rows : list[dict[str, str]] or None
        Matching proposal rows, or ``None`` if no match was found.
    matched_acronym : str or None
        The proposals-CSV acronym used to resolve the match.
    match_type : str or None
        One of ``"exact"``, ``"fuzzy"``, or ``None``.
    """
    if acronym in acronym_rows:
        return acronym_rows[acronym], acronym, "exact"

    lower_match = acronym_rows_lower.get(acronym.lower())
    if lower_match is not None:
        return acronym_rows[lower_match], lower_match, "exact"

    close = difflib.get_close_matches(
        acronym, acronym_rows.keys(), n=1, cutoff=fuzzy_cutoff
    )
    if close:
        return acronym_rows[close[0]], close[0], "fuzzy"

    return None, None, None


def resolve_proposal_row(
    matched_acronym: str, rows: list[dict[str, str]], session_timestamps: list[datetime]
) -> dict[str, str]:
    """Pick a single proposal row when an acronym matches more than one.

    Tries to match a session timestamp against the row's
    ``Experiment Start/End Date`` range first; falls back to the row with a
    non-empty ``Call Number``/``Research Area`` (the other candidate is
    typically an empty "Submitted" placeholder duplicate).

    Parameters
    ----------
    matched_acronym : str
        The proposals-CSV acronym these `rows` belong to (for warnings).
    rows : list[dict[str, str]]
        Candidate proposal rows sharing the same acronym.
    session_timestamps : list[datetime]
        This acronym's EXPERIENCES_LOG session start times.

    Returns
    -------
    dict[str, str]
        The chosen row.
    """
    if len(rows) == 1:
        return rows[0]

    for row in rows:
        start_str = row["Experiment Start Date"].strip()
        end_str = row["Experiment End Date"].strip()
        if not start_str or not end_str:
            continue
        try:
            start_date = datetime.fromisoformat(start_str).date()
            end_date = datetime.fromisoformat(end_str).date()
        except ValueError:
            continue
        if any(start_date <= ts.date() <= end_date for ts in session_timestamps):
            return row

    complete = [
        row for row in rows if row["Call Number"].strip() or row["Research Area"].strip()
    ]
    if len(complete) == 1:
        print(
            f"WARNING: ambiguous proposal match for acronym '{matched_acronym}' "
            f"({len(rows)} candidate rows); no session date fell inside any "
            "Experiment Start/End Date range, falling back to the row with a "
            "non-empty Call Number/Research Area."
        )
        return complete[0]

    print(
        f"WARNING: ambiguous proposal match for acronym '{matched_acronym}' "
        f"({len(rows)} candidate rows) could not be resolved by date or "
        "completeness; using the first row."
    )
    return rows[0]


def build_users(
    log_path: Path, proposals_path: Path, cutoff: datetime | None, fuzzy_cutoff: float
) -> tuple[list[dict], Counter, dict]:
    """Build the list of `users` rows to insert.

    Parameters
    ----------
    log_path : :class:`~pathlib.Path`
        Path to ``EXPERIENCES_LOG.csv``.
    proposals_path : :class:`~pathlib.Path`
        Path to the proposals CSV.
    cutoff : datetime or None
        Naive Europe/Paris datetime cutoff (see `parse_cutoff`).
    fuzzy_cutoff : float
        `difflib.get_close_matches` similarity cutoff for typo matching.

    Returns
    -------
    users : list[dict]
        One dict per (acronym, housing, session), matching the ``users``
        table columns. Sessions on a magnet's "external" variant (e.g.
        ``"M9e"``) each create their own row, *unless* it overlaps the most
        recently created row for the same acronym+housing+variant (a run
        EXPERIENCES_LOG logged twice under the same variant), in which case
        it's unioned into that row (lowest hstart, highest hstop) instead of
        creating a second one. Sessions on the "insert" variant (``"M9i"``)
        never create a row of their own: if one fully encloses the most
        recently created "external" row for the same acronym+housing (its
        hstart earlier AND its hstop later, both at once), it widens that
        row's hstart/hstop; otherwise it's dropped. Rows left identical
        after merging (from exact-duplicate EXPERIENCES_LOG rows) are
        deduplicated.
    match_counts : Counter
        Counts of ``"exact"``, ``"fuzzy"``, ``"unmatched"`` proposal matches.
    stats : dict
        Row counts read/discarded from both source files, plus
        ``duplicates_removed``, for reporting.
    """
    sessions, timestamps, log_total, log_discarded = load_log(log_path, cutoff)
    acronym_rows, proposals_total, proposals_discarded, proposals_ignored = load_proposals(
        proposals_path, cutoff
    )
    acronym_rows_lower = {a.lower(): a for a in acronym_rows}

    users = []
    match_counts: Counter = Counter()
    for acronym in sorted(sessions):
        rows, matched_acronym, match_type = find_proposal_rows(
            acronym, acronym_rows, acronym_rows_lower, fuzzy_cutoff
        )
        if rows is None:
            match_counts["unmatched"] += 1
            research_area = call_number = access_mode = type_ = None
        else:
            match_counts[match_type] += 1
            if match_type == "fuzzy":
                print(
                    f"WARNING: acronym '{acronym}' not found in proposals; "
                    f"using fuzzy match '{matched_acronym}'"
                )
            row = resolve_proposal_row(matched_acronym, rows, timestamps[acronym])
            research_area = row["Research Area"].strip() or None
            call_number = row["Call Number"].strip() or None
            access_mode = row["Access Mode"].strip() or None
            type_ = row["Type"].strip() or None

        ordered_sessions = sorted(
            sessions[acronym],
            key=lambda item: (_housing_sort_key(item[0]), item[2]),
        )
        last_entry_for_housing: dict[str, dict] = {}
        last_variant_for_housing: dict[str, str | None] = {}
        for magnet, variant, hstart, hstop in ordered_sessions:
            previous_entry = last_entry_for_housing.get(magnet)
            previous_variant = last_variant_for_housing.get(magnet)

            if (
                previous_entry is not None
                and variant is not None
                and variant == previous_variant
                and previous_entry["hstop"] is not None
                and hstart <= previous_entry["hstop"]
            ):
                # EXPERIENCES_LOG occasionally logs the same run twice under
                # the same variant (e.g. two "M9e" rows sharing/overlapping
                # HStop): union them into the existing entry instead of
                # creating a second row.
                if hstart < previous_entry["hstart"]:
                    previous_entry["hstart"] = hstart
                if hstop is not None and (
                    previous_entry["hstop"] is None or hstop > previous_entry["hstop"]
                ):
                    previous_entry["hstop"] = hstop
                continue

            if variant == "i":
                # "insert" sessions never create their own row; they only
                # widen a differently-variant ("external") entry, and only
                # when they fully enclose it (start earlier AND stop later)
                # on both sides at once. Otherwise they're dropped entirely.
                if (
                    previous_entry is not None
                    and hstart < previous_entry["hstart"]
                    and hstop is not None
                    and previous_entry["hstop"] is not None
                    and hstop > previous_entry["hstop"]
                ):
                    previous_entry["hstart"] = hstart
                    previous_entry["hstop"] = hstop
                continue

            entry = {
                "acronym": acronym,
                "research_area": research_area,
                "type": type_,
                "country": None,
                "call_number": call_number,
                "access_mode": access_mode,
                "housing": magnet,
                "hstart": hstart,
                "hstop": hstop,
            }
            users.append(entry)
            last_entry_for_housing[magnet] = entry
            last_variant_for_housing[magnet] = variant

    # EXPERIENCES_LOG itself contains exact-duplicate session rows (the same
    # acronym/housing/HStart/HStop repeated verbatim elsewhere in the file),
    # which would otherwise surface as duplicate merged rows here too.
    seen: set[tuple] = set()
    deduped_users = []
    n_duplicates = 0
    for u in users:
        key = (u["acronym"], u["housing"], u["hstart"], u["hstop"])
        if key in seen:
            n_duplicates += 1
            continue
        seen.add(key)
        deduped_users.append(u)
    users = deduped_users

    stats = {
        "duplicates_removed": n_duplicates,
        "proposals_ignored": proposals_ignored,
        "log_total": log_total,
        "log_discarded": log_discarded,
        "proposals_total": proposals_total,
        "proposals_discarded": proposals_discarded,
    }
    return users, match_counts, stats


_USER_COMPARE_FIELDS = ("research_area", "type", "country", "call_number", "access_mode")


def create_users_table(con, verbose: bool = True) -> None:
    """Create the ``users`` table (and apply schema migrations) if needed.

    Parameters
    ----------
    con:
        Open DuckDB connection.
    verbose : bool
        Print a confirmation line when done.
    """
    ensure_schema(con)
    if verbose:
        print("Ensured 'users' table exists.")


def delete_users_table(con, verbose: bool = True) -> None:
    """Drop the ``users`` table entirely.

    Parameters
    ----------
    con:
        Open DuckDB connection.
    verbose : bool
        Print a confirmation line when done.
    """
    con.execute("DROP TABLE IF EXISTS users")
    if verbose:
        print("Dropped 'users' table.")


def _user_key(u: dict) -> tuple:
    """Build the (acronym, housing, hstart, hstop) identity key for a users row."""
    return (u["acronym"], u["housing"], u["hstart"], u["hstop"])


def fetch_existing_user(con, key: tuple) -> dict | None:
    """Fetch the comparable columns of an existing ``users`` row by key.

    Parameters
    ----------
    con:
        Open DuckDB connection.
    key : tuple
        ``(acronym, housing, hstart, hstop)``, as returned by `_user_key`.

    Returns
    -------
    dict or None
        Mapping over `_USER_COMPARE_FIELDS`, or ``None`` if no row matches.
    """
    acronym, housing, hstart, hstop = key
    row = con.execute(
        "SELECT research_area, type, country, call_number, access_mode "
        "FROM users WHERE acronym = ? AND housing = ? AND hstart = ? "
        "AND hstop IS NOT DISTINCT FROM ?",
        [acronym, housing, hstart, hstop],
    ).fetchone()
    if row is None:
        return None
    return dict(zip(_USER_COMPARE_FIELDS, row))


def insert_users(con, users: list[dict], verbose: bool = True) -> None:
    """Bulk-insert `users` rows with no existence check.

    Parameters
    ----------
    con:
        Open DuckDB connection.
    users : list[dict]
        Rows as built by `build_users`.
    verbose : bool
        Print a count line when done.
    """
    con.executemany(
        "INSERT INTO users "
        "(acronym, research_area, type, country, call_number, access_mode, housing, "
        "hstart, hstop) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            [
                u["acronym"],
                u["research_area"],
                u["type"],
                u["country"],
                u["call_number"],
                u["access_mode"],
                u["housing"],
                u["hstart"],
                u["hstop"],
            ]
            for u in users
        ],
    )
    if verbose:
        print(f"Inserted {len(users)} rows into 'users'")


def replace_all_users(con, users: list[dict], verbose: bool = True) -> None:
    """Replace the entire contents of ``users`` with `users`.

    Parameters
    ----------
    con:
        Open DuckDB connection.
    users : list[dict]
        Rows as built by `build_users`.
    verbose : bool
        Print a count line when done.
    """
    con.execute("DELETE FROM users")
    insert_users(con, users, verbose=verbose)


def sync_users(con, users: list[dict], verbose: bool = True) -> dict:
    """Insert new ``users`` rows and correct mismatched existing ones.

    Existing rows are matched by `_user_key`. A match whose
    `_USER_COMPARE_FIELDS` differ from the freshly computed values is
    updated in place; `experiments_ids` is never read or written here.

    Parameters
    ----------
    con:
        Open DuckDB connection.
    users : list[dict]
        Rows as built by `build_users`.
    verbose : bool
        Print a line per inserted/updated row.

    Returns
    -------
    dict
        ``{"inserted": int, "updated": int, "unchanged": int}``.
    """
    stats = {"inserted": 0, "updated": 0, "unchanged": 0}
    new_users = []
    for u in users:
        key = _user_key(u)
        existing = fetch_existing_user(con, key)
        if existing is None:
            new_users.append(u)
            if verbose:
                print(f"  + {u['acronym']} {u['housing']} {u['hstart']}  (new)")
            continue

        changed = {
            field: (existing[field], u[field])
            for field in _USER_COMPARE_FIELDS
            if existing[field] != u[field]
        }
        if not changed:
            stats["unchanged"] += 1
            continue

        set_clause = ", ".join(f"{field} = ?" for field in changed)
        con.execute(
            f"UPDATE users SET {set_clause} "
            "WHERE acronym = ? AND housing = ? AND hstart = ? "
            "AND hstop IS NOT DISTINCT FROM ?",
            [u[field] for field in changed] + list(key),
        )
        stats["updated"] += 1
        if verbose:
            diffs = ", ".join(
                f"{field}: {old!r} -> {new!r}" for field, (old, new) in changed.items()
            )
            print(f"  ~ {u['acronym']} {u['housing']} {u['hstart']}  ({diffs})")

    if new_users:
        insert_users(con, new_users, verbose=False)
    stats["inserted"] = len(new_users)
    return stats


def update_experiments_ids(con, verbose: bool = True) -> dict:
    """Link each ``users`` row to its ``experiments`` via housing + time range.

    Matches each row's housing (via experiments.site_name's "<housing>_..."
    prefix) and [hstart, hstop] range against experiments' file-embedded
    timestamp. Rows with no hstop have no closed range to contain anything,
    so they're left with experiments_ids = NULL.

    Parameters
    ----------
    con:
        Open DuckDB connection.
    verbose : bool
        Print matched/unmatched counts when done.

    Returns
    -------
    dict
        ``{"matched": int, "unmatched": int}``.
    """
    con.execute(
        f"UPDATE users SET experiments_ids = ("
        f"SELECT LIST(e.id) FROM experiments e "
        f"WHERE split_part(e.site_name, '_', 1) = users.housing "
        f"AND {_EXP_FILE_TS} BETWEEN users.hstart AND users.hstop"
        f") WHERE users.hstop IS NOT NULL"
    )
    matched = con.execute(
        "SELECT COUNT(*) FROM users WHERE experiments_ids IS NOT NULL"
    ).fetchone()[0]
    unmatched = con.execute(
        "SELECT COUNT(*) FROM users WHERE experiments_ids IS NULL"
    ).fetchone()[0]
    if verbose:
        print(f"Records with matched experiments_ids: {matched}")
        print(f"Records with no experiments_ids: {unmatched}")
    return {"matched": matched, "unmatched": unmatched}


def update_overview_records_ids(con, verbose: bool = True) -> dict:
    """Link each ``users`` row to its ``overview_records`` via housing + time range.

    Matches each row's housing against overview_records.housing and each
    record's t0 against [hstart, hstop]. Rows with no hstop have no closed
    range to contain anything, so they're left with overview_records_ids = NULL.

    Parameters
    ----------
    con:
        Open DuckDB connection.
    verbose : bool
        Print matched/unmatched counts when done.

    Returns
    -------
    dict
        ``{"matched": int, "unmatched": int}``.
    """
    con.execute(
        "UPDATE users SET overview_records_ids = ("
        "SELECT LIST(o.filename) FROM overview_records o "
        "WHERE o.housing = users.housing "
        "AND o.t0 BETWEEN users.hstart AND users.hstop "
        "AND o.merged_into IS NULL"
        ") WHERE users.hstop IS NOT NULL"
    )
    matched = con.execute(
        "SELECT COUNT(*) FROM users WHERE overview_records_ids IS NOT NULL"
    ).fetchone()[0]
    unmatched = con.execute(
        "SELECT COUNT(*) FROM users WHERE overview_records_ids IS NULL"
    ).fetchone()[0]
    if verbose:
        print(f"Records with matched overview_records_ids: {matched}")
        print(f"Records with no overview_records_ids: {unmatched}")
    return {"matched": matched, "unmatched": unmatched}


def report_source_stats(users: list[dict], stats: dict, match_counts: Counter) -> None:
    """Print row-count, dedup, and proposal-match stats from `build_users`."""
    print(f"\nRead {stats['log_total']} EXPERIENCES_LOG rows "
          f"({stats['log_discarded']} discarded by --from)")
    print(f"Read {stats['proposals_total']} proposals rows "
          f"({stats['proposals_discarded']} discarded by --from)"
          f"({stats['proposals_ignored']} ignored for empty acronym or invalid start date)")
    print(f"Built {len(users)} users rows, "
          f"{stats['duplicates_removed']} duplicate rows removed")
    print(
        f"Proposal match: {match_counts['exact']} exact, "
        f"{match_counts['fuzzy']} fuzzy, {match_counts['unmatched']} unmatched"
    )


def report_data_quality(con) -> None:
    """Print hstop/research_area coverage of the current ``users`` table contents."""
    empty_hstop = con.execute("SELECT COUNT(*) FROM users WHERE hstop IS NULL").fetchone()[0]
    print(f"Records with empty hstop: {empty_hstop}")
    empty_research_area = con.execute(
        "SELECT COUNT(*) FROM users WHERE research_area IS NULL"
    ).fetchone()[0]
    print(f"Records with empty research_area: {empty_research_area}")
    acronyms_without_research_area = [
        row[0]
        for row in con.execute(
            "SELECT DISTINCT acronym FROM users WHERE research_area IS NULL "
            "ORDER BY acronym"
        ).fetchall()
    ]
    print(
        f"Acronyms without research_area ({len(acronyms_without_research_area)}):"
    )
    for acronym in acronyms_without_research_area:
        print(f"  {acronym}")


def report_experiments_ids_coverage(con) -> None:
    """Print rows missing experiments_ids and experiments shared across rows."""
    rows_no_experiments_ids = con.execute(
        "SELECT * FROM users WHERE experiments_ids IS NULL "
        "ORDER BY acronym, housing, hstart"
    ).df()
    print(f"\nRows with no experiments_ids ({len(rows_no_experiments_ids)}):")
    print(rows_no_experiments_ids.to_string(index=False))

    shared_experiment_ids = con.execute(
        "SELECT experiment_id FROM (SELECT unnest(experiments_ids) AS experiment_id "
        "FROM users WHERE experiments_ids IS NOT NULL) "
        "GROUP BY experiment_id HAVING COUNT(*) > 1 ORDER BY experiment_id"
    ).fetchall()
    print(
        f"Experiments shared across multiple users rows: "
        f"{len(shared_experiment_ids)}"
    )
    for (experiment_id,) in shared_experiment_ids:
        print(f"  experiment {experiment_id}:")
        rows = con.execute(
            "SELECT * FROM users WHERE list_contains(experiments_ids, ?) "
            "ORDER BY acronym, housing, hstart",
            [experiment_id],
        ).df()
        print(rows.to_string(index=False))


def report_overview_records_ids_coverage(con) -> None:
    """Print rows missing overview_records_ids and records shared across rows."""
    rows_no_overview_records_ids = con.execute(
        "SELECT * FROM users WHERE overview_records_ids IS NULL "
        "ORDER BY acronym, housing, hstart"
    ).df()
    print(f"\nRows with no overview_records_ids ({len(rows_no_overview_records_ids)}):")
    print(rows_no_overview_records_ids.to_string(index=False))

    shared_overview_records_ids = con.execute(
        "SELECT filename FROM (SELECT unnest(overview_records_ids) AS filename "
        "FROM users WHERE overview_records_ids IS NOT NULL) "
        "GROUP BY filename HAVING COUNT(*) > 1 ORDER BY filename"
    ).fetchall()
    print(
        f"Overview records shared across multiple users rows: "
        f"{len(shared_overview_records_ids)}"
    )
    for (filename,) in shared_overview_records_ids:
        print(f"  overview_record {filename}:")
        rows = con.execute(
            "SELECT * FROM users WHERE list_contains(overview_records_ids, ?) "
            "ORDER BY acronym, housing, hstart",
            [filename],
        ).df()
        print(rows.to_string(index=False))


# ---------------------------------------------------------------------------
# list/view helpers — mirror crud.py's list_objects()/view_sites()/view_site()
# so this logic can later move into crud.py and be wired into magnetdb.py's
# top-level 'list' command and a future 'user' subcommand.
# ---------------------------------------------------------------------------


def list_users(con) -> list[str]:
    """Return the sorted list of distinct acronyms in ``users``."""
    return [
        row[0]
        for row in con.execute(
            "SELECT DISTINCT acronym FROM users ORDER BY acronym"
        ).fetchall()
    ]


def view_users(con) -> None:
    """Print every users row (all columns), with experiments_ids resolved to filenames."""
    rows = con.execute(
        "SELECT * REPLACE ("
        "  (SELECT list(e.file ORDER BY e.id) FROM experiments e "
        "   WHERE e.id IN (SELECT UNNEST(u.experiments_ids))) AS experiments_ids"
        ") FROM users u ORDER BY acronym, housing, hstart"
    ).df()
    if rows.empty:
        print("No users in database.")
        return
    print(f"Users ({len(rows)} rows):")
    print(rows.to_string(index=False))


def view_user(con, acronym: str) -> None:
    """Print metadata and each housing session for a single acronym."""
    row = con.execute(
        "SELECT research_area, type, country, call_number, access_mode "
        "FROM users WHERE acronym = ? LIMIT 1",
        [acronym],
    ).fetchone()
    if row is None:
        print(f"User '{acronym}' not found.")
        return
    print(f"User : {acronym}")
    print(f"  research_area: {row[0] or '?'}")
    print(f"  type         : {row[1] or '?'}")
    print(f"  country      : {row[2] or '?'}")
    print(f"  call_number  : {row[3] or '?'}")
    print(f"  access_mode  : {row[4] or '?'}")
    sessions = con.execute(
        "SELECT housing, hstart, hstop, experiments_ids "
        "FROM users WHERE acronym = ? ORDER BY housing, hstart",
        [acronym],
    ).fetchall()
    print(f"  sessions ({len(sessions)}):")
    for housing, hstart, hstop, experiments_ids in sessions:
        files = (
            [
                r[0]
                for r in con.execute(
                    "SELECT file FROM experiments WHERE id IN (SELECT UNNEST(?)) "
                    "ORDER BY id",
                    [experiments_ids],
                ).fetchall()
            ]
            if experiments_ids
            else []
        )
        print(f"    {housing}  {hstart} -> {hstop}  {files or '-'}")


def report_sample(con, n: int) -> None:
    """Print up to `n` sample rows from ``users``, with experiments_ids resolved to filenames."""
    sample = con.execute(
        "SELECT * REPLACE ("
        "  (SELECT list(e.file ORDER BY e.id) FROM experiments e "
        "   WHERE e.id IN (SELECT UNNEST(u.experiments_ids))) AS experiments_ids"
        ") FROM users u ORDER BY acronym, housing, hstart LIMIT ?",
        [n],
    ).df()
    print(f"\nSample rows (up to {n}):")
    print(sample.to_string(index=False))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("to_duckdb/test-magnetdb.duckdb"),
        help="Target DuckDB database file.",
    )
    parser.add_argument(
        "--log",
        type=Path,
        default=Path("Data/EXPERIENCES_LOG.csv"),
        help="Input EXPERIENCES_LOG CSV.",
    )
    parser.add_argument(
        "--proposals",
        type=Path,
        default=Path("Data/proposals_2026-07-22.csv"),
        help="Input proposals CSV.",
    )
    parser.add_argument(
        "--from",
        dest="from_date",
        default=None,
        help="Discard EXPERIENCES_LOG/proposals entries before this date "
        "(Europe/Paris local time), e.g. 2020-01-01.",
    )
    parser.add_argument(
        "--fuzzy-cutoff",
        type=float,
        default=0.8,
        help="difflib similarity cutoff for fuzzy acronym matching.",
    )
    parser.add_argument(
        "--sample",
        type=int,
        default=20,
        help="Number of resulting users rows to print.",
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Add new rows and fix mismatched existing rows instead of "
        "replacing the whole table's contents.",
    )
    parser.add_argument(
        "--no-link",
        dest="link",
        action="store_false",
        default=True,
        help="Skip backfilling experiments_ids/overview_records_ids after (re)populating.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List distinct acronyms in 'users' and exit "
        "(prepares magnetdb.py's top-level 'list' integration).",
    )
    parser.add_argument(
        "--view",
        nargs="?",
        const="",
        default=None,
        metavar="ACRONYM",
        help="Show all users (omit ACRONYM) or one acronym's detail, then exit "
        "(prepares a future magnetdb.py 'user view' subcommand, like 'site view').",
    )
    args = parser.parse_args()

    if args.list or args.view is not None:
        with duckdb.connect(str(args.db), read_only=True) as con:
            if args.list:
                acronyms = list_users(con)
                print(f"users ({len(acronyms)}):")
                if acronyms:
                    for acronym in acronyms:
                        print(f"  {acronym}")
                else:
                    print("  (none)")
            if args.view is not None:
                if args.view:
                    view_user(con, args.view)
                else:
                    view_users(con)
        return

    cutoff = parse_cutoff(args.from_date) if args.from_date else None

    users, match_counts, stats = build_users(
        args.log, args.proposals, cutoff, args.fuzzy_cutoff
    )

    con = duckdb.connect(str(args.db))
    try:
        create_users_table(con, verbose=False)
        report_source_stats(users, stats, match_counts)

        if args.sync:
            sync_stats = sync_users(con, users)
            print(f"Sync: {sync_stats['inserted']} inserted, "
                  f"{sync_stats['updated']} updated, "
                  f"{sync_stats['unchanged']} unchanged")
        else:
            replace_all_users(con, users, verbose=False)
            print(f"Replaced 'users' contents with {len(users)} rows ({args.db})")

        report_data_quality(con)

        if args.link:
            update_experiments_ids(con)
            report_experiments_ids_coverage(con)
            update_overview_records_ids(con)
            report_overview_records_ids_coverage(con)

        report_sample(con, args.sample)
    finally:
        con.close()


if __name__ == "__main__":
    main()
