#!/usr/bin/env python
"""Demo: help resolve ``users`` rows with no ``research_area``.

Standalone script — not wired into ``users_table_demo.py`` or
``magnetdb.py`` yet. Splits ``users`` rows with ``research_area IS NULL``
into two buckets:

- **Tech Staff**: acronym is ``"EXPLOIT."`` or contains ``"test"``
  (case-insensitive) — these are internal LNCMI exploitation/testing
  sessions, never backed by a real proposal, so searching ``proposals.csv``
  for them is pointless. Reported only, unless ``--apply-tech-staff`` is
  passed, in which case ``research_area`` is set to ``"LNCMI Tech Staff"``.
- **Candidate search**: the remaining genuinely-unmatched acronyms
  (``research_area``/``call_number``/``access_mode`` all ``NULL``) are
  searched against ``proposals.csv`` for proposals whose date coverage
  overlaps that acronym's session ``hstart``/``hstop``, ranked by acronym
  similarity. Read-only — prints candidates for manual review, does not
  write anything back.

Run from the repository root, e.g.::

    python to_duckdb/demos/find_research_area_candidates.py
    python to_duckdb/demos/find_research_area_candidates.py --apply-tech-staff
    python to_duckdb/demos/find_research_area_candidates.py --acronym GSO02
    python to_duckdb/demos/find_research_area_candidates.py --top 5 --min-score 0.5
"""

import argparse
import csv
import difflib
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import duckdb

TECH_STAFF_RESEARCH_AREA = "LNCMI Tech Staff"


def load_proposals(proposals_path: Path) -> list[dict[str, str]]:
    """Load usable proposal rows from `proposals_path`.

    Parameters
    ----------
    proposals_path : :class:`~pathlib.Path`
        Path to the proposals CSV.

    Returns
    -------
    list[dict[str, str]]
        Rows with a non-empty ``Acronym``, excluding ``Type == Access
        Mode == "Supra"`` placeholder/internal entries (never a match
        candidate) — same exclusions ``users_table_demo.py``'s
        ``load_proposals`` applies.
    """
    with open(proposals_path, newline="", encoding="utf-8-sig") as f:
        rows = [row for row in csv.DictReader(f) if row["Acronym"].strip()]
    return [
        row
        for row in rows
        if not (row["Type"].strip() == "Supra" and row["Access Mode"].strip() == "Supra")
    ]


def _is_tech_staff_acronym_sql() -> str:
    """SQL boolean expression identifying a tech-staff placeholder acronym."""
    return "(acronym = 'EXPLOIT.' OR acronym ILIKE '%test%')"


def fetch_tech_staff_rows(con) -> list[tuple[str, int]]:
    """Return per-acronym row counts for the tech-staff bucket.

    Parameters
    ----------
    con:
        Open DuckDB connection.

    Returns
    -------
    list[tuple[str, int]]
        ``(acronym, row_count)`` pairs, sorted by acronym, for rows with
        ``research_area IS NULL`` whose acronym is ``"EXPLOIT."`` or
        contains ``"test"`` (case-insensitive).
    """
    return con.execute(
        f"SELECT acronym, COUNT(*) FROM users WHERE research_area IS NULL "
        f"AND {_is_tech_staff_acronym_sql()} GROUP BY acronym ORDER BY acronym"
    ).fetchall()


def apply_tech_staff(con, verbose: bool = True) -> int:
    """Set ``research_area = 'LNCMI Tech Staff'`` on the tech-staff bucket.

    Only ``research_area`` is written; ``call_number``/``access_mode``/
    ``type`` are left untouched.

    Parameters
    ----------
    con:
        Open (read-write) DuckDB connection.
    verbose : bool
        Print the resulting row count when done.

    Returns
    -------
    int
        Total rows now carrying ``research_area = 'LNCMI Tech Staff'``.
    """
    con.execute(
        f"UPDATE users SET research_area = ? WHERE research_area IS NULL "
        f"AND {_is_tech_staff_acronym_sql()}",
        [TECH_STAFF_RESEARCH_AREA],
    )
    count = con.execute(
        "SELECT COUNT(*) FROM users WHERE research_area = ?",
        [TECH_STAFF_RESEARCH_AREA],
    ).fetchone()[0]
    if verbose:
        print(f"Set research_area = '{TECH_STAFF_RESEARCH_AREA}' on {count} rows")
    return count


def fetch_unmatched_sessions(
    con,
) -> dict[str, list[tuple[str, datetime, datetime | None]]]:
    """Group genuinely-unmatched sessions by acronym.

    Parameters
    ----------
    con:
        Open DuckDB connection.

    Returns
    -------
    dict[str, list[tuple[str, datetime, datetime | None]]]
        Acronym -> list of ``(housing, hstart, hstop)`` sessions, for rows
        with ``research_area``/``call_number``/``access_mode`` all
        ``NULL`` and excluding the tech-staff bucket (see
        `fetch_tech_staff_rows`).
    """
    rows = con.execute(
        f"SELECT acronym, housing, hstart, hstop FROM users "
        f"WHERE research_area IS NULL AND call_number IS NULL AND access_mode IS NULL "
        f"AND NOT {_is_tech_staff_acronym_sql()} ORDER BY acronym, hstart"
    ).fetchall()
    sessions: dict[str, list[tuple[str, datetime, datetime | None]]] = defaultdict(list)
    for acronym, housing, hstart, hstop in rows:
        sessions[acronym].append((housing, hstart, hstop))
    return sessions


def find_candidates(
    acronym: str,
    sessions: list[tuple[str, datetime, datetime | None]],
    proposals: list[dict[str, str]],
    top: int,
    min_score: float,
) -> list[tuple[float, str, str, dict[str, str]]]:
    """Find and rank candidate proposals for one acronym's sessions.

    A proposal is a candidate if either its ``Experiment Start/End Date``
    range overlaps any of `acronym`'s closed (``hstop`` set) session
    ranges, or (when it only has an ``Experiment Year``) that year is
    among `acronym`'s session years.

    Parameters
    ----------
    acronym : str
        The unmatched ``users.acronym`` value.
    sessions : list[tuple[str, datetime, datetime | None]]
        This acronym's ``(housing, hstart, hstop)`` sessions.
    proposals : list[dict[str, str]]
        Usable proposal rows, as returned by `load_proposals`.
    top : int
        Maximum number of candidates to return.
    min_score : float
        Minimum acronym-similarity score (see below) to keep a candidate.

    Returns
    -------
    list[tuple[float, str, str, dict[str, str]]]
        ``(score, match_basis, match_detail, proposal_row)``, sorted by
        `score` descending and capped at `top`. `score` is
        ``difflib.SequenceMatcher`` ratio between `acronym` and the
        candidate's ``Acronym`` (case-insensitive). `match_basis` is
        ``"date"`` or ``"year"``; `match_detail` is the overlapping date
        range or the matching year.
    """
    years = {hstart.year for _, hstart, _ in sessions}
    ranges = [
        (hstart.date(), hstop.date()) for _, hstart, hstop in sessions if hstop is not None
    ]

    candidates: list[tuple[str, str, dict[str, str]]] = []
    for row in proposals:
        start_str = row["Experiment Start Date"].strip()
        end_str = row["Experiment End Date"].strip()
        year_str = row["Experiment Year"].strip()
        if start_str and end_str:
            try:
                start_date = datetime.fromisoformat(start_str).date()
                end_date = datetime.fromisoformat(end_str).date()
            except ValueError:
                continue
            if any(start_date <= e and end_date >= s for s, e in ranges):
                candidates.append(("date", f"{start_str} -> {end_str}", row))
        elif year_str:
            try:
                if int(year_str) in years:
                    candidates.append(("year", year_str, row))
            except ValueError:
                pass

    scored = [
        (
            difflib.SequenceMatcher(
                None, acronym.lower(), row["Acronym"].strip().lower()
            ).ratio(),
            basis,
            detail,
            row,
        )
        for basis, detail, row in candidates
    ]
    scored = [c for c in scored if c[0] >= min_score]
    scored.sort(key=lambda c: -c[0])
    return scored[:top]


def print_candidates(
    acronym: str,
    sessions: list[tuple[str, datetime, datetime | None]],
    candidates: list[tuple[float, str, str, dict[str, str]]],
) -> None:
    """Print one acronym's session summary and ranked candidates."""
    housings = sorted({housing for housing, _, _ in sessions})
    hstarts = [hstart for _, hstart, _ in sessions]
    print(
        f"\nAcronym: {acronym}  ({len(sessions)} sessions, housing "
        f"{', '.join(housings)}, {min(hstarts).date()} -> {max(hstarts).date()})"
    )
    if not candidates:
        print("  (no candidates found)")
        return
    for i, (score, basis, detail, row) in enumerate(candidates, start=1):
        research_area = row["Research Area"].strip() or "(none)"
        call_number = row["Call Number"].strip() or "?"
        access_mode = row["Access Mode"].strip() or "?"
        print(
            f"  {i}. {row['Acronym']:<15} score={score:.3f}  "
            f"research_area={research_area}  call_number={call_number}  "
            f"access_mode={access_mode}  match={basis} {detail}"
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
        "--proposals",
        type=Path,
        default=Path("Data/proposals.csv"),
        help="Input proposals CSV.",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=10,
        help="Maximum number of candidates to print per acronym.",
    )
    parser.add_argument(
        "--acronym",
        default=None,
        help="Restrict the candidate search to a single acronym.",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=0.0,
        help="Minimum acronym-similarity score for a candidate to be shown.",
    )
    parser.add_argument(
        "--apply-tech-staff",
        action="store_true",
        help="Write research_area='LNCMI Tech Staff' for the tech-staff bucket "
        "(EXPLOIT./*test* acronyms). Without this flag, that bucket is only "
        "reported, not written.",
    )
    args = parser.parse_args()

    con = duckdb.connect(str(args.db), read_only=not args.apply_tech_staff)
    try:
        tech_staff_rows = fetch_tech_staff_rows(con)
        total_tech_staff = sum(count for _, count in tech_staff_rows)
        print(
            f"LNCMI Tech Staff bucket (EXPLOIT./*test* acronyms): "
            f"{total_tech_staff} rows across {len(tech_staff_rows)} acronyms"
        )
        for acronym, count in tech_staff_rows:
            print(f"  {acronym}: {count}")

        if args.apply_tech_staff:
            apply_tech_staff(con)
        else:
            print(
                "  (dry run — pass --apply-tech-staff to write "
                f"research_area='{TECH_STAFF_RESEARCH_AREA}')"
            )

        sessions_by_acronym = fetch_unmatched_sessions(con)
        if args.acronym:
            sessions_by_acronym = {
                acronym: sessions
                for acronym, sessions in sessions_by_acronym.items()
                if acronym == args.acronym
            }
        proposals = load_proposals(args.proposals)

        print(f"\nCandidate search: {len(sessions_by_acronym)} unmatched acronyms")
        for acronym, sessions in sessions_by_acronym.items():
            candidates = find_candidates(
                acronym, sessions, proposals, args.top, args.min_score
            )
            print_candidates(acronym, sessions, candidates)
    finally:
        con.close()


if __name__ == "__main__":
    main()
