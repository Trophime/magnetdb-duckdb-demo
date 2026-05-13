"""
magnetdb.py
===========
Unified CLI entry point for the student MagnetDB DuckDB.

    python magnetdb.py db create            [--db ...]
    python magnetdb.py db delete            [--db ...] [--yes]

    python magnetdb.py magnet add <json_file> [--db ...] [--input-dir ...] [--part-dir ...] [--dry-run]
    python magnetdb.py magnet view [<name>]   [--db ...]
    python magnetdb.py magnet delete <name>   [--db ...]

    python magnetdb.py site add <json_file> [--db ...] [--input-dir ...] [--magnet-dir ...] [--dry-run]
    python magnetdb.py site view [<name>]   [--db ...]
    python magnetdb.py site delete <name>   [--db ...]
    python magnetdb.py site update-magnet <site> <magnet> [--db ...] [--z-offset ...]
"""

import argparse
import json
import sys
from pathlib import Path

import duckdb

from add_magnet import add_magnet
from add_site import add_site
from crud import (
    delete_magnet,
    delete_site,
    load_json,
    update_site_magnet,
    view_magnet,
    view_magnets,
    view_site,
    view_sites,
)
from schema import ensure_schema

DEFAULT_DB = "student_magnetdb.duckdb"


# ---------------------------------------------------------------------------
# db handlers
# ---------------------------------------------------------------------------


def cmd_db_create(args) -> None:
    db_path = Path(args.db)
    if db_path.exists():
        print(f"Database '{db_path}' already exists.")
        sys.exit(1)
    with duckdb.connect(str(db_path)) as con:
        ensure_schema(con)
    print(f"Created database '{db_path}'.")


def cmd_db_delete(args) -> None:
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Error: '{db_path}' does not exist.")
        sys.exit(1)
    if not args.yes:
        answer = input(f"Delete '{db_path}'? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("Aborted.")
            return
    db_path.unlink()
    wal = db_path.with_suffix(".duckdb.wal")
    if wal.exists():
        wal.unlink()
    print(f"Deleted '{db_path}'.")


# ---------------------------------------------------------------------------
# magnet handlers
# ---------------------------------------------------------------------------


def cmd_magnet_add(args) -> None:
    json_path = Path(args.json_file)
    if args.input_dir:
        json_path = Path(args.input_dir) / json_path
    if not json_path.exists():
        print(f"Error: '{json_path}' not found.")
        sys.exit(1)
    part_dir = Path(args.part_dir) if args.part_dir else json_path.parent
    add_magnet(load_json(json_path), args.db, dry_run=args.dry_run, part_dir=part_dir)


def cmd_magnet_view(args) -> None:
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Error: '{db_path}' does not exist.")
        sys.exit(1)
    with duckdb.connect(str(db_path)) as con:
        if args.name:
            view_magnet(con, args.name)
        else:
            view_magnets(con)


def cmd_magnet_delete(args) -> None:
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Error: '{db_path}' does not exist.")
        sys.exit(1)
    with duckdb.connect(str(db_path)) as con:
        delete_magnet(con, args.name)


# ---------------------------------------------------------------------------
# site handlers
# ---------------------------------------------------------------------------


def cmd_site_add(args) -> None:
    json_path = Path(args.json_file)
    if args.input_dir:
        json_path = Path(args.input_dir) / json_path
    if not json_path.exists():
        print(f"Error: '{json_path}' not found.")
        sys.exit(1)
    magnet_dir = Path(args.magnet_dir) if args.magnet_dir else json_path.parent
    add_site(load_json(json_path), args.db, dry_run=args.dry_run, magnet_dir=magnet_dir)


def cmd_site_view(args) -> None:
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Error: '{db_path}' does not exist.")
        sys.exit(1)
    with duckdb.connect(str(db_path)) as con:
        if args.name:
            view_site(con, args.name)
        else:
            view_sites(con)


def cmd_site_delete(args) -> None:
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Error: '{db_path}' does not exist.")
        sys.exit(1)
    with duckdb.connect(str(db_path)) as con:
        delete_site(con, args.name)


def cmd_site_update_magnet(args) -> None:
    metadata = None
    if args.metadata:
        try:
            metadata = json.loads(args.metadata)
        except json.JSONDecodeError as exc:
            print(f"Error: --metadata is not valid JSON: {exc}")
            sys.exit(1)
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Error: '{db_path}' does not exist.")
        sys.exit(1)
    with duckdb.connect(str(db_path)) as con:
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
            sys.exit(1)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

_DISPATCH = {
    ("db",     "create"):        cmd_db_create,
    ("db",     "delete"):        cmd_db_delete,
    ("magnet", "add"):           cmd_magnet_add,
    ("magnet", "view"):          cmd_magnet_view,
    ("magnet", "delete"):        cmd_magnet_delete,
    ("site",   "add"):           cmd_site_add,
    ("site",   "view"):          cmd_site_view,
    ("site",   "delete"):        cmd_site_delete,
    ("site",   "update-magnet"): cmd_site_update_magnet,
}


def _db_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument("--db", default=DEFAULT_DB,
                   help=f"DuckDB file (default: {DEFAULT_DB})")


def _input_dir_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument("--input-dir", dest="input_dir", default=None,
                   help="Directory to look up the JSON file in "
                        "(default: use the path given to json_file as-is)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="magnetdb",
        description="Manage a student MagnetDB DuckDB.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    entity = parser.add_subparsers(dest="entity", required=True,
                                   metavar="{db,magnet,site}")

    # ── db ───────────────────────────────────────────────────────────────────
    db_p = entity.add_parser("db", help="Manage the DuckDB database file.")
    db_sub = db_p.add_subparsers(dest="action", required=True,
                                 metavar="{create,delete}")

    db_create = db_sub.add_parser("create", help="Create a new database and initialise the schema.")
    _db_arg(db_create)

    db_del = db_sub.add_parser("delete", help="Delete the database file.")
    _db_arg(db_del)
    db_del.add_argument("--yes", "-y", action="store_true",
                        help="Skip confirmation prompt")

    # ── magnet ──────────────────────────────────────────────────────────────
    magnet_p = entity.add_parser("magnet", help="Manage magnets.")
    magnet_sub = magnet_p.add_subparsers(dest="action", required=True,
                                         metavar="{add,view,delete}")

    m_add = magnet_sub.add_parser("add", help="Add a magnet from a JSON export.")
    m_add.add_argument("json_file", help="Path to the magnet JSON file (or bare name with --input-dir)")
    _db_arg(m_add)
    _input_dir_arg(m_add)
    m_add.add_argument("--part-dir", dest="part_dir",
                       help="Directory for <part_name>.json files "
                            "(default: same dir as the JSON file)")
    m_add.add_argument("--dry-run", action="store_true",
                       help="Validate and preview without writing")

    m_view = magnet_sub.add_parser("view", help="List all magnets or show one.")
    m_view.add_argument("name", nargs="?", default=None,
                        help="Magnet name (omit to list all)")
    _db_arg(m_view)

    m_del = magnet_sub.add_parser("delete", help="Delete a magnet and its part links.")
    m_del.add_argument("name", help="Magnet name")
    _db_arg(m_del)

    # ── site ─────────────────────────────────────────────────────────────────
    site_p = entity.add_parser("site", help="Manage sites.")
    site_sub = site_p.add_subparsers(dest="action", required=True,
                                     metavar="{add,view,delete,update-magnet}")

    s_add = site_sub.add_parser("add", help="Add a site from a JSON export.")
    s_add.add_argument("json_file", help="Path to the site JSON file (or bare name with --input-dir)")
    _db_arg(s_add)
    _input_dir_arg(s_add)
    s_add.add_argument("--magnet-dir",
                       help="Directory for <magnet_name>.json files "
                            "(default: same dir as the JSON file)")
    s_add.add_argument("--dry-run", action="store_true",
                       help="Validate and preview without writing")

    s_view = site_sub.add_parser("view", help="List all sites or show one.")
    s_view.add_argument("name", nargs="?", default=None,
                        help="Site name (omit to list all)")
    _db_arg(s_view)

    s_del = site_sub.add_parser("delete",
                                 help="Delete a site, its magnet links, and experiments.")
    s_del.add_argument("name", help="Site name")
    _db_arg(s_del)

    s_upd = site_sub.add_parser("update-magnet",
                                 help="Update SiteMagnet fields for a site/magnet pair.")
    s_upd.add_argument("site_name", help="Site name")
    s_upd.add_argument("magnet_name", help="Magnet name")
    _db_arg(s_upd)
    s_upd.add_argument("--z-offset", type=float, dest="z_offset", help="z offset (m)")
    s_upd.add_argument("--r-offset", type=float, dest="r_offset", help="r offset (m)")
    s_upd.add_argument("--parallax", type=float, help="Parallax angle")
    s_upd.add_argument("--commissioned-at", dest="commissioned_at",
                       help="Commissioning timestamp (YYYY-MM-DD or datetime)")
    s_upd.add_argument("--decommissioned-at", dest="decommissioned_at",
                       help="Decommissioning timestamp (YYYY-MM-DD or datetime)")
    s_upd.add_argument("--metadata", help="JSON string for metadata field")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    handler = _DISPATCH.get((args.entity, args.action))
    if handler is None:
        parser.print_help()
        sys.exit(1)
    handler(args)


if __name__ == "__main__":
    main()
