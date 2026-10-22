"""
check_experiment_files.py
=========================
Record pupitre file quality on ``experiments`` (step E of
PLAN_digital_twin_schema.md).

For each experiment whose file has not been checked yet this script sets:
  header_class    = full | short | data | empty   (line 1 of the file)
  file_integrity  = ok | truncated | unreadable
                    truncated:  rows dropped from a corrupt tail (crash:
                                NUL padding, then stale rows from an older
                                run), or last line incomplete
                    unreadable: python_magnetrun cannot load any data row
  file_checks     = {"reason": ..., "rows_read": ..., "rows_dropped": ...}
  file_checked_at = now()

Experiments whose file is missing are left unchecked (the records base may
just be wrong) and counted.

Usage
-----
    python check_experiment_files.py --db magnetdb-2026-10-08.duckdb
    python check_experiment_files.py --db magnetdb-2026-10-08.duckdb --assembly M10_A230509_00 --recheck
"""

import argparse
import json
from pathlib import Path

import duckdb
from config import DEFAULT_DB
from populate import _RECORDS_BASE, _SRV_SUBDIR
from python_magnetrun.magnetdata import load_magnetdata
from python_magnetrun.utils.validation import classify_pupitre_header
from schema import ensure_schema

DEFAULT_RECORDS_BASE = str(_RECORDS_BASE)


def check_file(path: Path) -> dict:
    """Classify and load one pupitre file.

    Parameters
    ----------
    path : :class:`~pathlib.Path`
        Existing pupitre ``.txt`` file.

    Returns
    -------
    dict
        ``header_class``, ``file_integrity`` and ``file_checks`` values for
        the ``experiments`` row.
    """
    header_class = classify_pupitre_header(str(path))
    try:
        md = load_magnetdata(str(path))
        rows_read = len(md.Data)
        rows_dropped = md.rows_dropped
        truncated = md.truncated
    except Exception as exc:
        return {
            "header_class": header_class,
            "file_integrity": "unreadable",
            "file_checks": {"reason": f"{type(exc).__name__}: {exc}"},
        }
    checks = {"rows_read": rows_read, "rows_dropped": rows_dropped}
    if rows_dropped:
        checks["reason"] = "corrupt_tail"
    elif truncated:
        checks["reason"] = "incomplete_last_line"
    return {
        "header_class": header_class,
        "file_integrity": "truncated" if truncated else "ok",
        "file_checks": checks,
    }


def check_experiments(
    db_path: str,
    assembly: str | None = None,
    records_base: str = DEFAULT_RECORDS_BASE,
    srv_subdir: str = _SRV_SUBDIR,
    recheck: bool = False,
    verbose: bool = True,
) -> dict:
    """Fill the file quality columns of ``experiments``.

    The file path is ``records_base / srv_subdir / housing / file``, or
    ``experiments.file`` itself when it is absolute (as in
    ``compute_exp_stats.py``).

    Parameters
    ----------
    db_path : str
        DuckDB file.
    assembly : str, optional
        Only check the experiments of this assembly; all when ``None``.
    records_base : str, optional
        Root of the records tree.
    srv_subdir : str, optional
        Subdirectory of *records_base* holding the pupitre TXT files.
    recheck : bool, optional
        Also check experiments already checked.
    verbose : bool, optional
        Print non-ok files and a final summary.

    Returns
    -------
    dict
        ``{"checked": int, "skipped": int, "missing": int}``.
    """
    con = duckdb.connect(db_path)
    ensure_schema(con)
    exp_df = con.execute(
        """
        SELECT e.id, e.file, s.housing, e.file_checked_at IS NOT NULL AS already_checked
        FROM experiments e
        JOIN assemblies s ON s.name = e.assembly_name
        WHERE ? IS NULL OR e.assembly_name = ?
        ORDER BY e.id
        """,
        [assembly, assembly],
    ).df()

    results = {"checked": 0, "skipped": 0, "missing": 0}
    for row in exp_df.itertuples():
        if row.already_checked and not recheck:
            results["skipped"] += 1
            continue
        f = Path(row.file)
        path = f if f.is_absolute() else Path(records_base) / srv_subdir / row.housing / row.file
        if not path.exists():
            results["missing"] += 1
            continue

        quality = check_file(path)
        con.execute(
            """
            UPDATE experiments
            SET header_class = ?, file_integrity = ?, file_checks = ?, file_checked_at = now()
            WHERE id = ?
            """,
            [
                quality["header_class"],
                quality["file_integrity"],
                json.dumps(quality["file_checks"]),
                int(row.id),
            ],
        )
        results["checked"] += 1
        if verbose and quality["file_integrity"] != "ok":
            print(f"  {quality['file_integrity']:<10} {path}  {quality['file_checks']}")

    con.close()
    if verbose:
        print(
            f"\nDone — {results['checked']} checked, {results['skipped']} skipped, "
            f"{results['missing']} missing"
        )
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Record pupitre file quality on experiments.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--db", default=DEFAULT_DB, help="DuckDB file path")
    parser.add_argument("--assembly", default=None, help="Assembly name (default: all)")
    parser.add_argument(
        "--records-base",
        default=DEFAULT_RECORDS_BASE,
        dest="records_base",
        help=f"Root directory for record files (default: {DEFAULT_RECORDS_BASE})",
    )
    parser.add_argument(
        "--srv-subdir",
        default=_SRV_SUBDIR,
        dest="srv_subdir",
        help=f"Subdirectory under records-base for pupitre TXT files (default: {_SRV_SUBDIR})",
    )
    parser.add_argument(
        "--recheck", action="store_true", help="Re-check files already checked"
    )
    parser.add_argument("--quiet", action="store_true", help="Only print the summary")
    args = parser.parse_args()

    check_experiments(
        db_path=args.db,
        assembly=args.assembly,
        records_base=args.records_base,
        srv_subdir=args.srv_subdir,
        recheck=args.recheck,
        verbose=not args.quiet,
    )


if __name__ == "__main__":
    main()
