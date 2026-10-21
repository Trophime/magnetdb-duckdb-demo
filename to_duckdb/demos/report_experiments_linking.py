#!/usr/bin/env python
"""Demo: report ``experiments`` not linked to any ``users`` row, and clock drift.

Standalone script — companion to ``users_table_demo.py``, run after it has
linked ``experiments_ids``. Works from the experiments side, whereas
``find_linking_candidates.py`` works from the ``users`` side.

Two reports:

- **Unlinked experiments**: per housing, how many experiments (from
  ``--from`` on) appear in no ``users.experiments_ids``, then one line per
  file with the nearest same-housing session (acronym and signed distance
  in minutes; negative = before ``hstart``, positive = after ``hstop``)
  and any other housing with a session covering the file's timestamp.
- **Clock drift**: for each session, the offset of the nearest experiment
  file (within ±90 min) from ``hstart``. Normally the first file starts a
  few minutes after ``hstart``; a file starting well *before* it suggests
  the acquisition PC clock lags behind EXPERIENCES_LOG (seen on M5 in
  2023–2026). Prints the median offset per housing and year, then the
  sessions whose file starts more than ``--drift-threshold`` minutes
  before ``hstart``.

Both pupitre filenames (``"YYYY.MM.DD - HH:MM:SS.txt"``) and
``hstart``/``hstop`` are Europe/Paris local time, so no timezone
conversion is needed. Read-only — never writes anything back.

Run from the repository root, e.g.::

    python to_duckdb/demos/report_experiments_linking.py
    python to_duckdb/demos/report_experiments_linking.py --housing M5
    python to_duckdb/demos/report_experiments_linking.py --drift-threshold 10 --no-rows
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from crud import _EXP_FILE_TS  # noqa: E402

DRIFT_WINDOW_MIN = 90

# Signed distance [min] from experiment `x.ts` to users row `u`'s
# [hstart, hstop]: negative before hstart, positive after hstop, 0 inside.
_SIGNED_DISTANCE_MIN = (
    "CASE WHEN x.ts < u.hstart THEN (epoch(x.ts) - epoch(u.hstart)) / 60 "
    "WHEN x.ts > u.hstop THEN (epoch(x.ts) - epoch(u.hstop)) / 60 ELSE 0 END"
)


def _filter_housing(df: pd.DataFrame, housing_filter: set[str] | None) -> pd.DataFrame:
    """Keep only rows whose ``housing`` is in `housing_filter` (all if ``None``)."""
    if housing_filter is None:
        return df
    return df[df["housing"].str.upper().isin(housing_filter)]


def report_unlinked_experiments(
    con,
    from_ts: datetime,
    housing_filter: set[str] | None = None,
    show_rows: bool = True,
) -> pd.DataFrame:
    """Print and return experiments that no ``users`` row links to.

    Parameters
    ----------
    con:
        Open DuckDB connection.
    from_ts : datetime
        Only experiments whose file timestamp is at or after this naive
        Europe/Paris datetime are considered.
    housing_filter : set[str] or None
        Upper-cased housings to report (e.g. ``{"M5"}``). ``None`` reports
        every housing.
    show_rows : bool
        Print one line per unlinked file, not only the per-housing counts.

    Returns
    -------
    :class:`~pandas.DataFrame`
        One row per unlinked experiment: ``housing``, ``file``, ``ts``,
        ``nearest_acronym``, ``nearest_distance_min`` (signed [min],
        ``NaN`` when the housing has no closed session) and
        ``other_housings`` (comma-separated housings with a session
        covering ``ts``, or ``None``).
    """
    experiments = con.execute(
        f"WITH linked AS (SELECT DISTINCT UNNEST(experiments_ids) AS id FROM users "
        f"WHERE experiments_ids IS NOT NULL) "
        f"SELECT e.id, e.file, split_part(e.assembly_name, '_', 1) AS housing, "
        f"{_EXP_FILE_TS} AS ts, e.id IN (SELECT id FROM linked) AS linked "
        f"FROM experiments e WHERE {_EXP_FILE_TS} >= ?",
        [from_ts],
    ).df()
    experiments = _filter_housing(experiments, housing_filter)
    unlinked = experiments[~experiments["linked"]]

    con.register("_unlinked", unlinked[["id", "housing", "ts"]])
    try:
        details = con.execute(
            f"SELECT x.id, "
            f"(SELECT arg_min(u.acronym, abs({_SIGNED_DISTANCE_MIN})) FROM users u "
            f" WHERE u.housing = x.housing AND u.hstop IS NOT NULL) AS nearest_acronym, "
            f"(SELECT round(arg_min({_SIGNED_DISTANCE_MIN}, abs({_SIGNED_DISTANCE_MIN})), 1) "
            f" FROM users u WHERE u.housing = x.housing AND u.hstop IS NOT NULL) "
            f"AS nearest_distance_min, "
            f"(SELECT string_agg(DISTINCT u.housing, ',' ORDER BY u.housing) FROM users u "
            f" WHERE u.housing <> x.housing AND x.ts BETWEEN u.hstart AND u.hstop) "
            f"AS other_housings "
            f"FROM _unlinked x"
        ).df()
    finally:
        con.unregister("_unlinked")
    result = (
        unlinked.merge(details, on="id")
        .drop(columns=["id", "linked"])
        .sort_values(["housing", "ts"])
        .reset_index(drop=True)
    )

    print(f"\nUnlinked experiments since {from_ts.date()}: {len(result)} / {len(experiments)}")
    totals = experiments.groupby("housing").size()
    counts = result.groupby("housing").size()
    for housing, total in totals.items():
        print(f"  {housing}: {counts.get(housing, 0)} / {total}")
    if show_rows and not result.empty:
        print(result.to_string(index=False))
    return result


def report_clock_drift(
    con,
    from_ts: datetime,
    threshold: float,
    housing_filter: set[str] | None = None,
    show_rows: bool = True,
) -> pd.DataFrame:
    """Print per-housing/year file offsets from ``hstart`` and flag early files.

    Parameters
    ----------
    con:
        Open DuckDB connection.
    from_ts : datetime
        Only sessions starting at or after this naive Europe/Paris
        datetime are considered.
    threshold : float
        A session is flagged when its nearest file starts more than this
        many minutes before ``hstart`` [min].
    housing_filter : set[str] or None
        Upper-cased housings to report. ``None`` reports every housing.
    show_rows : bool
        Print the flagged sessions, not only the per-housing/year summary.

    Returns
    -------
    :class:`~pandas.DataFrame`
        Flagged sessions: ``housing``, ``acronym``, ``hstart``, ``hstop``,
        ``file`` and ``offset_min`` (file timestamp minus ``hstart``
        [min], negative = before ``hstart``).
    """
    offsets = con.execute(
        f"SELECT any_value(u.housing) AS housing, any_value(u.acronym) AS acronym, "
        f"any_value(u.hstart) AS hstart, any_value(u.hstop) AS hstop, "
        f"arg_min(x.file, abs(epoch(x.ts) - epoch(u.hstart))) AS file, "
        f"round(arg_min((epoch(x.ts) - epoch(u.hstart)) / 60, "
        f"abs(epoch(x.ts) - epoch(u.hstart))), 1) AS offset_min "
        f"FROM users u JOIN ("
        f"  SELECT e.file, split_part(e.assembly_name, '_', 1) AS housing, "
        f"  {_EXP_FILE_TS} AS ts FROM experiments e"
        f") x ON x.housing = u.housing "
        f"AND x.ts BETWEEN u.hstart - INTERVAL {DRIFT_WINDOW_MIN} MINUTE "
        f"AND u.hstart + INTERVAL {DRIFT_WINDOW_MIN} MINUTE "
        f"WHERE u.hstop IS NOT NULL AND u.hstart >= ? "
        f"GROUP BY u.rowid",
        [from_ts],
    ).df()
    offsets = _filter_housing(offsets, housing_filter)

    print(
        f"\nOffset of nearest file (±{DRIFT_WINDOW_MIN} min) from hstart [min], "
        "per housing/year: median [q25, q75] (sessions)"
    )
    summary = (
        offsets.assign(year=offsets["hstart"].dt.year)
        .groupby(["housing", "year"])["offset_min"]
        .agg(["median", lambda s: s.quantile(0.25), lambda s: s.quantile(0.75), "size"])
    )
    for (housing, year), (median, q25, q75, size) in summary.iterrows():
        print(f"  {housing} {year}: {median:.1f} [{q25:.1f}, {q75:.1f}] ({int(size)})")

    flagged = (
        offsets[offsets["offset_min"] < -threshold]
        .sort_values(["housing", "hstart"])
        .reset_index(drop=True)
    )
    print(f"Sessions whose nearest file starts > {threshold:g} min before hstart: {len(flagged)}")
    if show_rows and not flagged.empty:
        print(flagged.to_string(index=False))
    return flagged


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("to_duckdb/test-magnetdb.duckdb"),
        help="Target DuckDB database file.",
    )
    parser.add_argument(
        "--housing",
        nargs="+",
        default=["ALL"],
        metavar="HOUSING",
        help="Restrict both reports to these housings (e.g. --housing M5). "
        "ALL (default) reports every housing.",
    )
    parser.add_argument(
        "--from",
        dest="from_date",
        default="2018-01-01",
        help="Ignore experiments/sessions before this date (Europe/Paris local time).",
    )
    parser.add_argument(
        "--drift-threshold",
        type=float,
        default=5.0,
        help="Flag sessions whose nearest file starts more than this many "
        "minutes before hstart.",
    )
    parser.add_argument(
        "--no-rows",
        dest="show_rows",
        action="store_false",
        default=True,
        help="Print only the summary counts, not the per-file/per-session listings.",
    )
    args = parser.parse_args()

    if len(args.housing) == 1 and args.housing[0].upper() == "ALL":
        housing_filter = None
    else:
        housing_filter = {h.upper() for h in args.housing}
    from_ts = datetime.fromisoformat(args.from_date)

    pd.set_option("display.width", 250)
    with duckdb.connect(str(args.db), read_only=True) as con:
        report_unlinked_experiments(con, from_ts, housing_filter, args.show_rows)
        report_clock_drift(con, from_ts, args.drift_threshold, housing_filter, args.show_rows)


if __name__ == "__main__":
    main()
