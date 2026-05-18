"""
add_site.py  [DEPRECATED — use magnetdb.py instead]
====================================================

.. deprecated::
   This script is superseded by the unified CLI ``magnetdb.py``.
   Use ``python magnetdb.py site <subcommand> [options]`` instead.
   ``add_site.py`` is kept for backward compatibility only and may be
   removed in a future version.

Add a site to a student DuckDB database from a MagnetDB site JSON export.

Magnets referenced in the JSON that are not yet in the database are loaded
automatically from a same-named JSON file (e.g. M19071101.json) found in
the same directory as the site JSON (or the directory given by --magnet-dir).

JSON format (as exported from MagnetDB)
----------------------------------------
{
    "name":               "M10_M19071101_13",
    "description":        "",
    "status":             "in_operation",
    "housing":            "M10",
    "commissioned_at":    "2025-11-12 00:00:00",
    "decommissioned_at":  "None",
    "magnets": [
        "M19071101",
        {
            "name":               "M10Bitters",
            "z_offset":           0.0,
            "r_offset":           0.0,
            "parallax":           0.0,
            "commissioned_at":    "2025-11-12 00:00:00",
            "decommissioned_at":  null,
            "metadata":           {}
        }
    ],
    "records": [
        {"name": "M10_2025.11.13---09:14:21.txt", "description": "", "file": "..."},
        ...
    ]
}

Usage
-----
    python add_site.py add M10_M19071101_13.json
    python add_site.py add M10_M19071101_13.json --db path/to/student.duckdb --dry-run
    python add_site.py add M10_M19071101_13.json --magnet-dir /path/to/magnet/jsons
    python add_site.py update-magnet M10_M19071101_13 M19071101 --z-offset 12.5
"""

import argparse
import json
import sys
from pathlib import Path

import duckdb

from add_magnet import add_magnet
from crud import (
    insert_site,
    insert_site_magnets,
    load_json,
    update_site_magnet,
)
from schema import ensure_schema


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _magnet_name(entry) -> str:
    return entry if isinstance(entry, str) else entry["name"]


def _ensure_magnets(magnet_entries: list, db_path: Path, magnet_dir: Path, dry_run: bool = False) -> list[str]:
    """Auto-load magnets that are absent from the DB.

    Returns a list of error strings for magnets that could not be resolved.
    """
    errors = []
    for entry in magnet_entries:
        name = _magnet_name(entry)
        with duckdb.connect(str(db_path)) as chk:
            found = chk.execute("SELECT 1 FROM magnets WHERE name = ?", [name]).fetchone() is not None
        if found:
            continue
        json_path = magnet_dir / f"{name}.json"
        if not json_path.exists():
            errors.append(
                f"Magnet '{name}' not in DB and '{json_path}' not found. "
                f"Load it manually with:  python add_magnet.py {name}.json"
            )
            continue
        print(f"  ~ magnet '{name}' not in DB — loading from {json_path.name} …")
        add_magnet(load_json(json_path), db_path, dry_run=dry_run,
                   part_dir=json_path.parent)
    return errors


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate(data: dict) -> list[str]:
    errors = []
    if not data.get("name"):
        errors.append("Missing 'name'")
    if not data.get("magnets"):
        errors.append("'magnets' list is empty or missing")
    return errors


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def add_site(data: dict, db_path, dry_run: bool = False, magnet_dir=None) -> None:
    """Insert a site and its records into the student DuckDB.

    Parameters
    ----------
    data       : dict matching the MagnetDB site JSON export format
    db_path    : path to the .duckdb file (must already exist)
    dry_run    : if True, validate only — do not write
    magnet_dir : directory to search for <magnet_name>.json files when a
                 magnet is missing from the DB (default: current directory)
    """
    db_path = Path(db_path)
    magnet_dir = Path(magnet_dir) if magnet_dir else Path(".")

    if not db_path.exists():
        print(f"Error: '{db_path}' does not exist.")
        print("Create it first with:  python seeds_to_duckdb.py  or  python add_magnet.py")
        sys.exit(1)

    # Normalise: strip accidental .json suffix from name
    if data.get("name", "").endswith(".json"):
        data["name"] = data["name"][:-5]

    errors = _validate(data)
    if errors:
        print("Validation errors:")
        for e in errors:
            print(f"  • {e}")
        sys.exit(1)

    # Auto-load missing magnets before opening our write connection.
    missing_errors = _ensure_magnets(data.get("magnets", []), db_path, magnet_dir, dry_run=dry_run)
    if missing_errors:
        print("Errors resolving magnets:")
        for e in missing_errors:
            print(f"  • {e}")
        sys.exit(1)

    if dry_run:
        magnet_names = [_magnet_name(e) for e in data.get("magnets", [])]
        print("[dry-run] Validation passed. Would insert:")
        print(f"  site     : {data['name']}  [{data.get('housing', '?')}]")
        print(f"  magnets  : {magnet_names}")
        print(f"  records  : {len(data.get('records', []))}")
        return

    con = duckdb.connect(str(db_path))
    ensure_schema(con)

    site_name = data["name"]
    print(f"\nAdding site '{site_name}' to {db_path.name} …\n")

    insert_site(con, data)
    insert_site_magnets(con, site_name, data.get("magnets", []))

    con.close()
    print("\nDone.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    import warnings
    warnings.warn(
        "add_site.py is deprecated. Use 'python magnetdb.py site ...' instead.",
        DeprecationWarning,
        stacklevel=1,
    )
    parser = argparse.ArgumentParser(
        description="[DEPRECATED — use: python magnetdb.py site ...] "
                    "Manage sites in the student DuckDB.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_p = subparsers.add_parser("add", help="Add a site from a JSON export file.")
    add_p.add_argument("json_file", help="Path to the site JSON file")
    add_p.add_argument(
        "--db",
        default="student_magnetdb.duckdb",
        help="Target DuckDB file (default: student_magnetdb.duckdb)",
    )
    add_p.add_argument(
        "--magnet-dir",
        default=None,
        help=(
            "Directory to search for <magnet_name>.json files when a magnet is "
            "missing from the DB (default: same directory as the site JSON file)"
        ),
    )
    add_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and preview without writing to the DB",
    )

    upd_p = subparsers.add_parser(
        "update-magnet",
        help="Update SiteMagnet fields for a given site/magnet pair.",
    )
    upd_p.add_argument("site_name", help="Name of the site")
    upd_p.add_argument("magnet_name", help="Name of the magnet")
    upd_p.add_argument("--db", default="student_magnetdb.duckdb",
                       help="Target DuckDB file (default: student_magnetdb.duckdb)")
    upd_p.add_argument("--z-offset", type=float, dest="z_offset", help="z offset (m)")
    upd_p.add_argument("--r-offset", type=float, dest="r_offset", help="r offset (m)")
    upd_p.add_argument("--parallax", type=float, help="parallax angle")
    upd_p.add_argument("--commissioned-at", dest="commissioned_at",
                       help="Commissioning timestamp (YYYY-MM-DD or datetime)")
    upd_p.add_argument("--decommissioned-at", dest="decommissioned_at",
                       help="Decommissioning timestamp (YYYY-MM-DD or datetime)")
    upd_p.add_argument("--metadata", help="JSON string for metadata field")

    args = parser.parse_args()

    if args.command == "add":
        json_path = Path(args.json_file)
        if not json_path.exists():
            print(f"Error: '{json_path}' not found.")
            sys.exit(1)
        magnet_dir = args.magnet_dir if args.magnet_dir else json_path.parent
        add_site(load_json(json_path), args.db,
                 dry_run=args.dry_run, magnet_dir=magnet_dir)

    elif args.command == "update-magnet":
        metadata = None
        if args.metadata:
            try:
                metadata = json.loads(args.metadata)
            except json.JSONDecodeError as exc:
                print(f"Error: --metadata is not valid JSON: {exc}")
                sys.exit(1)
        db_path = Path(args.db)
        con = duckdb.connect(str(db_path))
        ensure_schema(con)
        try:
            update_site_magnet(
                con,
                args.site_name,
                args.magnet_name,
                z_offset=args.z_offset,
                r_offset=args.r_offset,
                parallax=args.parallax,
                commissioned_at=args.commissioned_at,
                decommissioned_at=args.decommissioned_at,
                metadata=metadata,
            )
        except ValueError as exc:
            print(f"Error: {exc}")
            con.close()
            sys.exit(1)
        con.close()


if __name__ == "__main__":
    main()
