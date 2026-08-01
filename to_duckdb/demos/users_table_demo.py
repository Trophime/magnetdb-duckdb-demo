#!/usr/bin/env python
"""Demo: build and populate the ``users`` table from EXPERIENCES_LOG.

Standalone script — not wired into populate.py / magnetdb.py yet. Reads
``Data/EXPERIENCES_LOG.csv`` (one row per experiment session, keyed by
``UserCode``) and a proposals CSV (keyed by ``Acronym``, possibly typo'd
relative to ``UserCode``), joins them with fuzzy matching, and (re)populates
the ``users`` table of a DuckDB database with one row per acronym.

Run from the repository root, e.g.::

    python to_duckdb/demos/users_table_demo.py
    python to_duckdb/demos/users_table_demo.py --from 2020-01-01
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
    args = parser.parse_args()

    cutoff = parse_cutoff(args.from_date) if args.from_date else None

    users, match_counts, stats = build_users(
        args.log, args.proposals, cutoff, args.fuzzy_cutoff
    )

    con = duckdb.connect(str(args.db))
    try:
        ensure_schema(con)
        con.execute("DELETE FROM users")
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

        print(f"\nRead {stats['log_total']} EXPERIENCES_LOG rows "
              f"({stats['log_discarded']} discarded by --from)")
        print(f"Read {stats['proposals_total']} proposals rows "
              f"({stats['proposals_discarded']} discarded by --from)"
              f"({stats['proposals_ignored']} ignored for empty acronym or invalid start date)")
        print(f"Inserted {len(users)} rows into 'users' ({args.db}), "
              f"{stats['duplicates_removed']} duplicate rows removed")
        print(
            f"Proposal match: {match_counts['exact']} exact, "
            f"{match_counts['fuzzy']} fuzzy, {match_counts['unmatched']} unmatched"
        )

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

        # Match each row's housing (via experiments.site_name's "<housing>_..."
        # prefix) and [hstart, hstop] range against experiments' file-embedded
        # timestamp. Rows with no hstop have no closed range to contain
        # anything, so they're left with experiments_ids = NULL.
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
        print(f"Records with matched experiments_ids: {matched}")
        no_experiments_ids = con.execute(
            "SELECT COUNT(*) FROM users WHERE experiments_ids IS NULL"
        ).fetchone()[0]
        print(f"Records with no experiments_ids: {no_experiments_ids}")

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

        sample = con.execute(
            "SELECT * FROM users ORDER BY acronym, housing, hstart LIMIT ?", [args.sample]
        ).df()
        print(f"\nSample rows (up to {args.sample}):")
        print(sample.to_string(index=False))
    finally:
        con.close()


if __name__ == "__main__":
    main()
