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

    python magnetdb.py housing view [<name>]                       [--db ...]
    python magnetdb.py experiments view [--site <site>]            [--db ...]
    python magnetdb.py operationaldata view [--site <site>] [--type TYPE] [--db ...]
    python magnetdb.py overview-records view [--site <site>] [--signatures] [--db ...]

    python magnetdb.py populate operationaldata [SITE ...] [--all] [--type ...] [--records-base ...] [--dry-run]
    python magnetdb.py populate experiments     [SITE ...] [--all] [--dry-run]
    python magnetdb.py populate overview-records [SITE ...] [--all] [--reprocess] [--dry-run]
"""

import argparse
import json
import sys
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef]

import duckdb

from add_magnet import add_magnet
from add_site import add_site
from crud import (
    delete_magnet,
    delete_site,
    insert_experiments,
    insert_overview_record,
    load_json,
    update_site_magnet,
    upsert_overview_record,
    view_experiments,
    view_housing_config,
    view_housing_configs,
    view_magnet,
    view_magnets,
    view_operationaldata,
    view_overview_records,
    view_site,
    view_sites,
)
from find_site_pupitre import (
    _RECORDS_BASE as _DEFAULT_RECORDS_BASE,
    _SRV_SUBDIR as _DEFAULT_SRV_SUBDIR,
    find_and_register as _pupitre_find_and_register,
)
from find_site_tdms import (
    ALL_TYPES as TDMS_TYPES,
    _PBSURV as _DEFAULT_PBSURV,
    find_and_register as _tdms_find_and_register,
)
from schema import ensure_schema

DEFAULT_DB = "student_magnetdb.duckdb"
ALL_POPULATE_TYPES = TDMS_TYPES + ["Pupitre"]


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
# housing handlers
# ---------------------------------------------------------------------------


def cmd_housing_view(args) -> None:
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Error: '{db_path}' does not exist.")
        sys.exit(1)
    with duckdb.connect(str(db_path), read_only=True) as con:
        if args.name:
            view_housing_config(con, args.name)
        else:
            view_housing_configs(con)


# ---------------------------------------------------------------------------
# experiments handlers
# ---------------------------------------------------------------------------


def cmd_experiments_view(args) -> None:
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Error: '{db_path}' does not exist.")
        sys.exit(1)
    with duckdb.connect(str(db_path), read_only=True) as con:
        view_experiments(con, site_name=args.site)


# ---------------------------------------------------------------------------
# operationaldata handlers
# ---------------------------------------------------------------------------


def cmd_operationaldata_view(args) -> None:
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Error: '{db_path}' does not exist.")
        sys.exit(1)
    with duckdb.connect(str(db_path), read_only=True) as con:
        view_operationaldata(con, site_name=args.site, type_filter=args.type)


# ---------------------------------------------------------------------------
# overview-records handlers
# ---------------------------------------------------------------------------


def cmd_overview_records_view(args) -> None:
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Error: '{db_path}' does not exist.")
        sys.exit(1)
    with duckdb.connect(str(db_path), read_only=True) as con:
        view_overview_records(con, site_name=args.site, show_signatures=args.signatures)


# ---------------------------------------------------------------------------
# populate helpers
# ---------------------------------------------------------------------------


def _load_site_dict(db_path: str, site_name: str) -> dict | None:
    with duckdb.connect(db_path, read_only=True) as con:
        row = con.execute(
            "SELECT name, housing, status, commissioned_at, decommissioned_at "
            "FROM sites WHERE name = ?",
            [site_name],
        ).fetchone()
    if row is None:
        return None
    return {
        "name": row[0],
        "housing": row[1],
        "status": row[2],
        "commissioned_at": row[3],
        "decommissioned_at": row[4],
    }


def _resolve_site_names(args, db_path: str) -> list[str]:
    if getattr(args, "all", False):
        with duckdb.connect(db_path, read_only=True) as con:
            return [r[0] for r in con.execute("SELECT name FROM sites ORDER BY name").fetchall()]
    return list(args.site_names)


# ---------------------------------------------------------------------------
# populate handlers
# ---------------------------------------------------------------------------


def cmd_populate_operationaldata(args) -> None:
    db_path = args.db
    if not Path(db_path).exists():
        print(f"Error: '{db_path}' does not exist.")
        sys.exit(1)
    try:
        db_tz = ZoneInfo(args.db_tz)
    except Exception:
        print(f"Error: Unknown timezone '{args.db_tz}'")
        sys.exit(1)

    site_names = _resolve_site_names(args, db_path)
    if not site_names:
        print("No sites specified. Pass site name(s) or --all.")
        sys.exit(1)

    records_base = Path(args.records_base)
    active_types = args.types if args.types else ALL_POPULATE_TYPES
    tdms_types = [t for t in active_types if t != "Pupitre"]
    do_pupitre = "Pupitre" in active_types

    for site_name in site_names:
        site = _load_site_dict(db_path, site_name)
        if site is None:
            print(f"[SKIP] '{site_name}' not found in DB.")
            continue
        print(f"\nSite: {site_name}  housing={site['housing']}")
        if do_pupitre:
            _pupitre_find_and_register(
                site, db_path, db_tz, dry_run=args.dry_run,
                records_base=records_base, srv_subdir=args.srv_subdir,
            )
        if tdms_types:
            _tdms_find_and_register(
                site, db_path, db_tz, dry_run=args.dry_run,
                type_filter=tdms_types, records_base=records_base, pbsurv=args.pbsurv,
            )


def cmd_populate_experiments(args) -> None:
    db_path = args.db
    if not Path(db_path).exists():
        print(f"Error: '{db_path}' does not exist.")
        sys.exit(1)
    try:
        db_tz = ZoneInfo(args.db_tz)
    except Exception:
        print(f"Error: Unknown timezone '{args.db_tz}'")
        sys.exit(1)

    site_names = _resolve_site_names(args, db_path)
    if not site_names:
        print("No sites specified. Pass site name(s) or --all.")
        sys.exit(1)

    records_base = Path(args.records_base)

    for site_name in site_names:
        site = _load_site_dict(db_path, site_name)
        if site is None:
            print(f"[SKIP] '{site_name}' not found in DB.")
            continue
        print(f"\nSite: {site_name}  housing={site['housing']}")

        # Scan filesystem for matching pupitre TXT files (dry_run=True so
        # find_and_register returns matches without writing to operationaldata).
        matches = _pupitre_find_and_register(
            site, db_path, db_tz, dry_run=True,
            records_base=records_base, srv_subdir=args.srv_subdir,
        )

        if not matches:
            continue

        records = [
            {"name": fpath.stem, "description": "", "file": str(fpath)}
            for fpath, _ in matches
        ]

        if args.dry_run:
            print(f"  [DRY RUN] {len(records)} pupitre file(s) would be added to experiments")
            continue

        with duckdb.connect(db_path) as con:
            ensure_schema(con)
            insert_experiments(con, site_name, records, verbose=True)


def cmd_populate_overview_records(args) -> None:
    try:
        from python_magnetrun.analysis.processing import (
            ProcessingConfig,
            process_overview_file,
        )
    except ImportError:
        print("Error: python_magnetrun is not installed.")
        print("Install it with:  pip install python_magnetrun")
        sys.exit(1)

    db_path = args.db
    if not Path(db_path).exists():
        print(f"Error: '{db_path}' does not exist.")
        sys.exit(1)

    site_names = _resolve_site_names(args, db_path)
    if not site_names:
        print("No sites specified. Pass site name(s) or --all.")
        sys.exit(1)

    insert_fn = upsert_overview_record if args.reprocess else insert_overview_record
    config = ProcessingConfig(dry_run=args.dry_run)

    for site_name in site_names:
        with duckdb.connect(db_path, read_only=True) as con:
            rows = con.execute(
                "SELECT file FROM operationaldata "
                "WHERE site_name = ? AND type = 'Overview' ORDER BY file",
                [site_name],
            ).fetchall()

        if not rows:
            print(f"[INFO] {site_name}: no Overview entries in operationaldata — "
                  "run 'populate operationaldata' first.")
            continue

        print(f"\nSite: {site_name}  ({len(rows)} Overview file(s))")
        for (fpath,) in rows:
            if not Path(fpath).exists():
                print(f"  [SKIP] {Path(fpath).name} — file not found")
                continue
            if args.dry_run:
                print(f"  [DRY RUN] would process {Path(fpath).name}")
                continue
            try:
                record = process_overview_file(fpath, config)
                with duckdb.connect(db_path) as con:
                    ensure_schema(con)
                    insert_fn(con, record, site_name=site_name, verbose=True)
            except Exception as exc:
                print(f"  [ERROR] {Path(fpath).name}: {exc}")


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

_DISPATCH = {
    ("db",                "create"):          cmd_db_create,
    ("db",                "delete"):          cmd_db_delete,
    ("magnet",            "add"):             cmd_magnet_add,
    ("magnet",            "view"):            cmd_magnet_view,
    ("magnet",            "delete"):          cmd_magnet_delete,
    ("site",              "add"):             cmd_site_add,
    ("site",              "view"):            cmd_site_view,
    ("site",              "delete"):          cmd_site_delete,
    ("site",              "update-magnet"):   cmd_site_update_magnet,
    ("housing",           "view"):            cmd_housing_view,
    ("experiments",       "view"):            cmd_experiments_view,
    ("operationaldata",   "view"):            cmd_operationaldata_view,
    ("overview-records",  "view"):            cmd_overview_records_view,
    ("populate",          "operationaldata"): cmd_populate_operationaldata,
    ("populate",          "experiments"):     cmd_populate_experiments,
    ("populate",          "overview-records"): cmd_populate_overview_records,
}


def _db_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument("--db", default=DEFAULT_DB,
                   help=f"DuckDB file (default: {DEFAULT_DB})")


def _input_dir_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument("--input-dir", dest="input_dir", default=None,
                   help="Directory to look up the JSON file in "
                        "(default: use the path given to json_file as-is)")


def _sites_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument("site_names", nargs="*", metavar="SITE",
                   help="Site name(s). Use --all to process every site in the DB.")
    p.add_argument("--all", action="store_true",
                   help="Process all sites in the database.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="magnetdb",
        description="Manage a student MagnetDB DuckDB.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    entity = parser.add_subparsers(
        dest="entity", required=True,
        metavar="{db,magnet,site,housing,experiments,operationaldata,overview-records,populate}",
    )

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

    # ── housing ──────────────────────────────────────────────────────────────
    housing_p = entity.add_parser("housing", help="View housing configurations.")
    housing_sub = housing_p.add_subparsers(dest="action", required=True,
                                           metavar="{view}")

    h_view = housing_sub.add_parser("view", help="List all housings or show one.")
    h_view.add_argument("name", nargs="?", default=None,
                        help="Housing name (omit to list all)")
    _db_arg(h_view)

    # ── experiments ───────────────────────────────────────────────────────────
    exp_p = entity.add_parser("experiments", help="View experiment records.")
    exp_sub = exp_p.add_subparsers(dest="action", required=True,
                                   metavar="{view}")

    e_view = exp_sub.add_parser("view", help="List experiments, optionally filtered by site.")
    e_view.add_argument("--site", default=None, metavar="SITE",
                        help="Filter by site name (omit to list all)")
    _db_arg(e_view)

    # ── operationaldata ───────────────────────────────────────────────────────
    opdata_p = entity.add_parser("operationaldata", help="View operationaldata records.")
    opdata_sub = opdata_p.add_subparsers(dest="action", required=True,
                                         metavar="{view}")

    o_view = opdata_sub.add_parser(
        "view", help="List operationaldata records, optionally filtered."
    )
    o_view.add_argument("--site", default=None, metavar="SITE",
                        help="Filter by site name (omit to list all)")
    o_view.add_argument(
        "--type", default=None, choices=ALL_POPULATE_TYPES, metavar="TYPE",
        help=f"Filter by type ({', '.join(ALL_POPULATE_TYPES)})",
    )
    _db_arg(o_view)

    # ── overview-records ──────────────────────────────────────────────────────
    ovr_p = entity.add_parser("overview-records", help="View overview_records.")
    ovr_sub = ovr_p.add_subparsers(dest="action", required=True,
                                   metavar="{view}")

    ov_view = ovr_sub.add_parser(
        "view", help="List overview_records, optionally filtered by site."
    )
    ov_view.add_argument("--site", default=None, metavar="SITE",
                         help="Filter by site name (omit to list all)")
    ov_view.add_argument("--signatures", action="store_true",
                         help="Include per-record signature and sync details")
    _db_arg(ov_view)

    # ── populate ─────────────────────────────────────────────────────────────
    pop_p = entity.add_parser("populate", help="Populate data tables from files.")
    pop_sub = pop_p.add_subparsers(dest="action", required=True,
                                   metavar="{operationaldata,experiments,overview-records}")

    # populate operationaldata
    p_opdata = pop_sub.add_parser(
        "operationaldata",
        help="Scan filesystem and register TDMS/pupitre files in operationaldata.",
    )
    _db_arg(p_opdata)
    _sites_arg(p_opdata)
    p_opdata.add_argument(
        "--type", nargs="+", choices=ALL_POPULATE_TYPES, dest="types", metavar="TYPE",
        help=f"File type(s) to scan ({', '.join(ALL_POPULATE_TYPES)}). Default: all.",
    )
    p_opdata.add_argument(
        "--records-base", default=str(_DEFAULT_RECORDS_BASE), dest="records_base",
        help=f"Root of the records tree (default: {_DEFAULT_RECORDS_BASE})",
    )
    p_opdata.add_argument(
        "--srv-subdir", default=_DEFAULT_SRV_SUBDIR, dest="srv_subdir",
        help=f"Subdirectory of records-base for pupitre TXT files (default: {_DEFAULT_SRV_SUBDIR})",
    )
    p_opdata.add_argument(
        "--pbsurv", default=_DEFAULT_PBSURV,
        help=f"Subdirectory of records-base for TDMS files (default: {_DEFAULT_PBSURV})",
    )
    p_opdata.add_argument(
        "--db-tz", default="UTC", dest="db_tz",
        help="Timezone of commissioned_at / decommissioned_at in the DB (default: UTC)",
    )
    p_opdata.add_argument("--dry-run", action="store_true",
                          help="Match files but do not write to the DB.")

    # populate experiments
    p_exp = pop_sub.add_parser(
        "experiments",
        help="Scan filesystem for pupitre TXT files and register them in experiments.",
    )
    _db_arg(p_exp)
    _sites_arg(p_exp)
    p_exp.add_argument(
        "--records-base", default=str(_DEFAULT_RECORDS_BASE), dest="records_base",
        help=f"Root of the records tree (default: {_DEFAULT_RECORDS_BASE})",
    )
    p_exp.add_argument(
        "--srv-subdir", default=_DEFAULT_SRV_SUBDIR, dest="srv_subdir",
        help=f"Subdirectory of records-base for pupitre TXT files (default: {_DEFAULT_SRV_SUBDIR})",
    )
    p_exp.add_argument(
        "--db-tz", default="UTC", dest="db_tz",
        help="Timezone of commissioned_at / decommissioned_at in the DB (default: UTC)",
    )
    p_exp.add_argument("--dry-run", action="store_true",
                       help="Match files but do not write to the DB.")

    # populate overview-records
    p_ov = pop_sub.add_parser(
        "overview-records",
        help="Process Overview TDMS files (from operationaldata) via python_magnetrun.",
    )
    _db_arg(p_ov)
    _sites_arg(p_ov)
    p_ov.add_argument(
        "--reprocess", action="store_true",
        help="Overwrite existing overview_records rows (upsert instead of skip).",
    )
    p_ov.add_argument("--dry-run", action="store_true",
                      help="Discover files but do not write to the DB.")

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
