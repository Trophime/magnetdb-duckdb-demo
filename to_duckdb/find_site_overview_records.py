"""
find_site_overview_records.py  [DEPRECATED — use magnetdb.py instead]
======================================================================

.. deprecated::
   This script is superseded by the unified CLI ``magnetdb.py``.
   Use ``python magnetdb.py populate overview-records`` to process overview
   files, or query ``overview_records`` directly via DuckDB.
   ``find_site_overview_records.py`` is kept as an importable module for
   ``magnetdb.py`` and may be removed as a standalone CLI in a future version.

Query all overview_records attached to a site given by its name.

Each row corresponds to one processed OverviewRecord (one overview TDMS file)
and carries the experiment metadata: start time, duration, housing, mode,
pupitre parameters (teb, bp), source-file counts, signature keys, and
synchronisation info.

Usage:
    python find_site_overview_records.py M10_M19071101_13
    python find_site_overview_records.py M10_M19071101_13 --db my.duckdb
    python find_site_overview_records.py M10_M19071101_13 --json
    python find_site_overview_records.py M10_M19071101_13 --signatures
"""

import argparse
import json
import sys

import duckdb

DEFAULT_DB = "student_magnetdb.duckdb"

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

_SELECT = """
    SELECT
        r.filename,
        r.housing,
        r.mode,
        r.t0,
        r.duration,
        r.teb,
        r.bp,
        len(r.sources_overview)          AS n_overview,
        len(r.sources_archive)           AS n_archive,
        len(r.sources_pupitre)           AS n_pupitre,
        len(r.sources_default)           AS n_default,
        len(r.sources_trigger)           AS n_trigger,
        len(r.sources_spike)             AS n_spike,
        len(r.sources_hybrid_kHz)        AS n_hybrid_kHz,
        len(r.sources_hybrid_rms)        AS n_hybrid_rms,
        len(r.sources_hybrid_trigger)    AS n_hybrid_trigger,
        r.signatures,
        r.sync_info,
        r.flow_params,
        r.metrics,
        r.debitbrut
    FROM overview_records r
    WHERE r.site_name = ?
    ORDER BY r.t0 NULLS LAST, r.filename
"""

_COLUMNS = [
    "filename", "housing", "mode", "t0", "duration", "teb", "bp",
    "n_overview", "n_archive", "n_pupitre",
    "n_default", "n_trigger", "n_spike",
    "n_hybrid_kHz", "n_hybrid_rms", "n_hybrid_trigger",
    "signatures", "sync_info", "flow_params", "metrics", "debitbrut",
]


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


def fetch_overview_records(site_name: str, db_path: str) -> list[dict]:
    with duckdb.connect(db_path, read_only=True) as con:
        rows = con.execute(_SELECT, [site_name]).fetchall()
    return [dict(zip(_COLUMNS, row)) for row in rows]


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _parse_json(value) -> dict:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return {}


def _duration_str(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _source_summary(rec: dict) -> str:
    parts = []
    for key, label in [
        ("n_overview",       "ov"),
        ("n_archive",        "arch"),
        ("n_pupitre",        "pup"),
        ("n_default",        "def"),
        ("n_trigger",        "trig"),
        ("n_spike",          "spk"),
        ("n_hybrid_kHz",     "hkHz"),
        ("n_hybrid_rms",     "hrms"),
        ("n_hybrid_trigger", "htrig"),
    ]:
        n = rec.get(key) or 0
        if n:
            parts.append(f"{label}={n}")
    return " ".join(parts) if parts else "—"


def print_table(records: list[dict], show_signatures: bool) -> None:
    col_f  = max((len(r["filename"]) for r in records), default=20)
    col_t  = 19  # "YYYY-MM-DD HH:MM:SS"
    col_dur = 8
    col_m  = max((len(r.get("mode") or "") for r in records), default=4)

    header = (
        f"{'Filename':<{col_f}}  {'t0':<{col_t}}  {'Duration':<{col_dur}}"
        f"  {'Mode':<{col_m}}  teb    bp     sources"
    )
    print(header)
    print("-" * len(header))

    for r in records:
        t0_str   = str(r["t0"])[:col_t] if r["t0"] else "—"
        dur_str  = _duration_str(r["duration"])
        mode_str = (r.get("mode") or "")[:col_m]
        src_str  = _source_summary(r)
        print(
            f"{r['filename']:<{col_f}}  {t0_str:<{col_t}}  {dur_str:<{col_dur}}"
            f"  {mode_str:<{col_m}}  {r['teb'] or 0:5.1f}  {r['bp'] or 0:5.1f}  {src_str}"
        )

        if show_signatures:
            sigs = _parse_json(r.get("signatures"))
            if sigs:
                for key, vals in sigs.items():
                    mn  = vals.get("min",  float("nan"))
                    mx  = vals.get("max",  float("nan"))
                    avg = vals.get("mean", float("nan"))
                    print(f"    {key}: min={mn:.2f}  max={mx:.2f}  mean={avg:.2f}")

            sync = _parse_json(r.get("sync_info"))
            if sync:
                ts = sync.get("timeshift_seconds")
                if ts is not None:
                    print(f"    sync timeshift: {ts:.3f} s")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    import warnings
    warnings.warn(
        "find_site_overview_records.py is deprecated. "
        "Use 'python magnetdb.py populate overview-records' to process files, "
        "or query overview_records directly via DuckDB.",
        DeprecationWarning,
        stacklevel=1,
    )
    parser = argparse.ArgumentParser(
        description=(
            "[DEPRECATED — use: python magnetdb.py populate overview-records] "
            "List all overview_records for a given site."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("site_name", help="Site name (e.g. M10_M19071101_13)")
    parser.add_argument(
        "--db", default=DEFAULT_DB,
        help=f"DuckDB file (default: {DEFAULT_DB})",
    )
    parser.add_argument(
        "--json", action="store_true", dest="as_json",
        help="Print results as JSON array instead of a table",
    )
    parser.add_argument(
        "--signatures", action="store_true",
        help="Include per-record signature and sync details in table output",
    )
    args = parser.parse_args()

    site = load_site(args.site_name, args.db)
    if site is None:
        print(f"[ERROR] Site '{args.site_name}' not found in {args.db}")
        sys.exit(1)

    print(f"Site          : {site['name']}")
    print(f"Housing       : {site['housing']}")
    print(f"Status        : {site['status']}")
    print(f"Commissioned  : {site['commissioned_at']}")
    print(f"Decommissioned: {site['decommissioned_at']}")
    print()

    records = fetch_overview_records(args.site_name, args.db)

    if not records:
        print("No overview_records found for this site.")
        return

    print(f"{len(records)} overview record(s) found.\n")

    if args.as_json:
        # Stringify non-serialisable types before dumping
        def _serialise(v):
            return str(v) if not isinstance(v, (str, int, float, bool, list, dict, type(None))) else v

        out = []
        for r in records:
            row = {k: _serialise(v) for k, v in r.items()}
            for field in ("signatures", "sync_info", "flow_params", "metrics", "debitbrut"):
                row[field] = _parse_json(row.get(field))
            out.append(row)
        print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        print_table(records, show_signatures=args.signatures)


if __name__ == "__main__":
    main()
