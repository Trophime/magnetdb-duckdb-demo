"""
magnetdb.py
===========
Unified CLI entry point for the student MagnetDB DuckDB.

    python magnetdb.py list                  [--db ...]

    python magnetdb.py check [--db ...] [--entity part|magnet|experiment|operationaldata|all]
                             [--name NAME] [--fix]

    python magnetdb.py db create            [--db ...]
    python magnetdb.py db delete            [--db ...] [--yes]

    python magnetdb.py material add <json_file> [--db ...] [--input-dir ...] [--dry-run]
    python magnetdb.py material view [<name>]   [--db ...] [--nuance NUANCE]
    python magnetdb.py material delete <name>   [--db ...]

    python magnetdb.py magnet add <json_file> [--db ...] [--input-dir ...] [--part-dir ...] [--geometry ...] [--dry-run]
    python magnetdb.py magnet view [<name>]             [--db ...] [--type insert|bitters|supras] [--status STATUS]
    python magnetdb.py magnet check-geometry [<name>]   [--db ...]
    python magnetdb.py magnet delete <name>             [--db ...]

    python magnetdb.py site add <json_file> [--db ...] [--input-dir ...] [--magnet-dir ...] [--dry-run]
    python magnetdb.py site view [<name>]   [--db ...] [--housing HOUSING] [--status STATUS]
    python magnetdb.py site delete <name>   [--db ...]
    python magnetdb.py site update-magnet <site> <magnet> [--db ...] [--z-offset ...]

    python magnetdb.py housing view [<name>]                       [--db ...]
    python magnetdb.py experiments view [--site <site>] [--magnet <magnet>] [--part <part>]
                                        [--from DATETIME] [--to DATETIME] [--db ...]
    python magnetdb.py operationaldata view [--site <site>] [--type TYPE]
                                            [--magnet <magnet>] [--part <part>]
                                            [--from DATETIME] [--to DATETIME] [--db ...]
    python magnetdb.py overview-records view [--site <site>] [--magnet <magnet>] [--part <part>]
                                             [--from DATETIME] [--to DATETIME] [--signatures] [--db ...]

    python magnetdb.py populate operationaldata [--site SITE ...] [--all] [--type ...] [--records-base ...] [--dry-run]
    python magnetdb.py populate experiments     [--site SITE ...] [--all] [--dry-run]
    python magnetdb.py populate overview-records [--site SITE ...] [--all] [--reprocess] [--dry-run]
    python magnetdb.py populate overview-records-from-json <json_file> [--site SITE] [--reprocess] [--dry-run] [--db ...]

    python magnetdb.py hoop-stress compute  [--site SITE ...] [--all] [--db ...] [--magnet-type H|B|S|all]
                                            [--bins 0,100,200,...] [--parquet-dir ...] [--geometries ...]
                                            [--reprocess] [--dry-run] [--use-mrun]
                                            [--records-base ...] [--srv-subdir ...]

    python magnetdb.py hoop-stress barchart <site> [--db ...] [--geometries ...] [--debug]
                                            [--i-h A] [--i-b A] [--i-s A]
    python magnetdb.py hoop-stress history  <site> [--db ...] [--geometries ...] [--debug]
                                            [--pupitre FILE ...] [--records-base DIR] [--srv-subdir DIR]
                                            [--use-mrun] [--check] [--magnet-type H|B|S|all]
    python magnetdb.py hoop-stress stats    <site> [--db ...] [--geometries ...] [--debug]
                                            [--pupitre FILE ...] [--records-base DIR] [--srv-subdir DIR]
                                            [--use-mrun] [--check] [--magnet-type H|B|S|all]
                                            [--output CSV]
    python magnetdb.py hoop-stress fatigue  <site> [--db ...] [--geometries ...] [--debug]
                                            [--pupitre FILE ...] [--records-base DIR] [--srv-subdir DIR]
                                            [--use-mrun] [--check] [--magnet-type H|B|S|all]
                                            [--bins N]
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

from checks import print_check_report, run_checks
from crud import (
    check_geometry_data,
    delete_magnet,
    delete_material,
    delete_site,
    infer_magnet_type,
    insert_experiments,
    insert_magnet,
    insert_magnet_parts,
    insert_material,
    insert_overview_record,
    insert_overview_record_from_dict,
    insert_part,
    insert_site,
    insert_site_magnets,
    list_objects,
    load_json,
    print_geometry_check,
    update_site_magnet,
    upsert_overview_record,
    view_experiments,
    view_housing_config,
    view_housing_configs,
    view_magnet,
    view_magnets,
    view_material,
    view_materials,
    view_operationaldata,
    view_overview_records,
    view_site,
    view_sites,
)
from populate import (
    ALL_POPULATE_TYPES,
    _PBSURV as _DEFAULT_PBSURV,
    _RECORDS_BASE as _DEFAULT_RECORDS_BASE,
    _SRV_SUBDIR as _DEFAULT_SRV_SUBDIR,
    find_and_register_pupitre as _pupitre_find_and_register,
    find_and_register_tdms as _tdms_find_and_register,
    load_site as _load_site,
)
from config import DEFAULT_DB
from schema import COIL_TYPES, ensure_schema


# ---------------------------------------------------------------------------
# list handler
# ---------------------------------------------------------------------------


def cmd_list(args) -> None:
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Error: '{db_path}' does not exist.")
        sys.exit(1)
    with duckdb.connect(str(db_path), read_only=True) as con:
        objects = list_objects(con)
    for entity, names in objects.items():
        print(f"{entity} ({len(names)}):")
        if names:
            for name in names:
                print(f"  {name}")
        else:
            print("  (none)")


# ---------------------------------------------------------------------------
# check handler
# ---------------------------------------------------------------------------


def cmd_check(args) -> None:
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Error: '{db_path}' does not exist.")
        sys.exit(1)
    with duckdb.connect(str(db_path), read_only=not args.fix) as con:
        try:
            results = run_checks(con, entity=args.check_entity, name=args.name, fix=args.fix)
        except ValueError as exc:
            print(f"Error: {exc}")
            sys.exit(1)
    ok = print_check_report(results)
    if not ok:
        sys.exit(1)


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
# material handlers
# ---------------------------------------------------------------------------


def cmd_material_add(args) -> None:
    json_path = Path(args.json_file)
    if args.input_dir:
        json_path = Path(args.input_dir) / json_path
    if not json_path.exists():
        print(f"Error: '{json_path}' not found.")
        sys.exit(1)
    data = load_json(json_path)
    if args.dry_run:
        print(f"[DRY RUN] would insert material '{data.get('name', '?')}'  nuance={data.get('nuance', '?')}")
        return
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Error: '{db_path}' does not exist.")
        sys.exit(1)
    with duckdb.connect(str(db_path)) as con:
        ensure_schema(con)
        insert_material(con, data)


def cmd_material_view(args) -> None:
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Error: '{db_path}' does not exist.")
        sys.exit(1)
    with duckdb.connect(str(db_path), read_only=True) as con:
        if args.name:
            view_material(con, args.name)
        else:
            view_materials(con, nuance_filter=args.nuance)


def cmd_material_delete(args) -> None:
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Error: '{db_path}' does not exist.")
        sys.exit(1)
    with duckdb.connect(str(db_path)) as con:
        delete_material(con, args.name)


# ---------------------------------------------------------------------------
# add_magnet / add_site  (migrated from deprecated/add_magnet.py and add_site.py)
# ---------------------------------------------------------------------------


def _resolve_parts(parts: list, part_dir: Path) -> list[dict]:
    """Return fully-resolved part dicts; string entries are loaded from <part_dir>/<name>.json."""
    resolved = []
    for entry in parts:
        if isinstance(entry, dict):
            resolved.append(entry)
            continue
        name = entry
        json_path = part_dir / f"{name}.json"
        if not json_path.exists():
            print(
                f"Error: part '{name}' is a name reference but '{json_path}' not found.\n"
                f"Place the part definition there or use --part-dir."
            )
            sys.exit(1)
        print(f"  ~ part '{name}' not inline — loading from {json_path.name} …")
        resolved.append(load_json(json_path))
    return resolved


def _validate_magnet(data: dict) -> list[str]:
    errors = []
    if not data.get("name"):
        errors.append("Missing top-level 'name'")
    if not data.get("parts"):
        errors.append("'parts' list is empty or missing")
    for i, part in enumerate(data.get("parts", [])):
        if isinstance(part, str):
            errors.append(f"Part[{i}] '{part}' is an unresolved name reference")
            continue
        if not part.get("name"):
            errors.append(f"Part[{i}] is missing 'name'")
        if not part.get("type"):
            errors.append(f"Part '{part.get('name', i)}' is missing 'type'")
        if not part.get("material") or not part["material"].get("name"):
            errors.append(f"Part '{part.get('name', i)}' is missing 'material.name'")
    return errors


def _add_magnet(
    data: dict,
    db_path,
    dry_run: bool = False,
    part_dir=None,
    geometry_path=None,
) -> None:
    # db_path is created by DuckDB if absent — intentional: `magnet add` bootstraps the DB.
    # `_add_site` requires the file to exist because a site depends on prior magnet records.
    db_path = Path(db_path)
    part_dir = Path(part_dir) if part_dir else Path(".")

    if geometry_path:
        data = {**data, "geometry": str(geometry_path)}

    if data.get("name", "").endswith(".json"):
        data = {**data, "name": data["name"][:-5]}

    raw_parts = data.get("parts") or []
    if any(isinstance(p, str) for p in raw_parts):
        data = {**data, "parts": _resolve_parts(raw_parts, part_dir)}

    errors = _validate_magnet(data)
    if errors:
        print("Validation errors:")
        for e in errors:
            print(f"  • {e}")
        sys.exit(1)

    parts = data["parts"]
    try:
        magnet_type = infer_magnet_type(parts)
    except ValueError as exc:
        print(f"Validation errors:\n  • {exc}")
        sys.exit(1)

    if dry_run:
        coil_parts = [p for p in parts if p.get("type") in COIL_TYPES]
        mats = {p["material"]["name"] for p in parts if p.get("material")}
        print("[dry-run] Validation passed. Would insert:")
        print(f"  magnet   : {data['name']}  [{magnet_type}]  {data.get('status', '')}")
        print(f"  parts    : {len(parts)}  ({len(coil_parts)} coil channel(s))")
        print(f"  materials: {len(mats)}")
        return

    with duckdb.connect(str(db_path)) as con:
        ensure_schema(con)
        print(f"\nAdding magnet '{data['name']}' to {db_path.name} …\n")

        seen_materials: set[str] = set()
        for part in parts:
            mat = part.get("material", {})
            mat_name = mat.get("name")
            if mat_name and mat_name not in seen_materials:
                insert_material(con, mat)
                seen_materials.add(mat_name)

        print()
        for part in parts:
            insert_part(con, part)

        print()
        insert_magnet(con, data, magnet_type)

        print()
        insert_magnet_parts(con, data["name"], parts)

    print("\nDone.")


def _magnet_name(entry) -> str:
    return entry if isinstance(entry, str) else entry["name"]


def _validate_site(data: dict) -> list[str]:
    errors = []
    if not data.get("name"):
        errors.append("Missing 'name'")
    if not data.get("magnets"):
        errors.append("'magnets' list is empty or missing")
    return errors


def _ensure_magnets(
    magnet_entries: list, db_path: Path, magnet_dir: Path, dry_run: bool = False
) -> list[str]:
    """Auto-load magnets absent from the DB; returns a list of error strings."""
    names = [_magnet_name(e) for e in magnet_entries]
    if not names:
        return []

    placeholders = ", ".join("?" * len(names))
    with duckdb.connect(str(db_path)) as chk:
        rows = chk.execute(
            f"SELECT name FROM magnets WHERE name IN ({placeholders})", names
        ).fetchall()
    present = {r[0] for r in rows}

    errors = []
    for name in names:
        if name in present:
            continue
        json_path = magnet_dir / f"{name}.json"
        if not json_path.exists():
            errors.append(
                f"Magnet '{name}' not in DB and '{json_path}' not found. "
                f"Load it manually with:  python magnetdb.py magnet add {name}.json"
            )
            continue
        print(f"  ~ magnet '{name}' not in DB — loading from {json_path.name} …")
        _add_magnet(load_json(json_path), db_path, dry_run=dry_run,
                    part_dir=json_path.parent)
    return errors


def _add_site(data: dict, db_path, dry_run: bool = False, magnet_dir=None) -> None:
    db_path = Path(db_path)
    magnet_dir = Path(magnet_dir) if magnet_dir else Path(".")

    if not db_path.exists():
        print(f"Error: '{db_path}' does not exist.")
        print("Create it first with:  python magnetdb.py db create")
        print("Then add magnets with: python magnetdb.py magnet add <json_file>")
        sys.exit(1)

    if data.get("name", "").endswith(".json"):
        data["name"] = data["name"][:-5]

    errors = _validate_site(data)
    if errors:
        print("Validation errors:")
        for e in errors:
            print(f"  • {e}")
        sys.exit(1)

    missing_errors = _ensure_magnets(
        data.get("magnets", []), db_path, magnet_dir, dry_run=dry_run
    )
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
        return

    with duckdb.connect(str(db_path)) as con:
        ensure_schema(con)
        site_name = data["name"]
        print(f"\nAdding site '{site_name}' to {db_path.name} …\n")

        insert_site(con, data)
        insert_site_magnets(con, site_name, data.get("magnets", []))

        records = data.get("records") or []
        if records:
            insert_experiments(con, site_name, records)

    print("\nDone.")


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
    geometry_path = Path(args.geometry) if args.geometry else None
    if geometry_path and not geometry_path.exists():
        print(f"Error: geometry file '{geometry_path}' not found.")
        sys.exit(1)
    _add_magnet(load_json(json_path), args.db, dry_run=args.dry_run,
                part_dir=part_dir, geometry_path=geometry_path)


def cmd_magnet_view(args) -> None:
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Error: '{db_path}' does not exist.")
        sys.exit(1)
    with duckdb.connect(str(db_path)) as con:
        if args.name:
            view_magnet(con, args.name)
        else:
            view_magnets(con, type_filter=args.type, status_filter=args.status)


def cmd_magnet_check_geometry(args) -> None:
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Error: '{db_path}' does not exist.")
        sys.exit(1)
    with duckdb.connect(str(db_path), read_only=True) as con:
        results = check_geometry_data(con, args.name or None)
    print_geometry_check(results)


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
    _add_site(load_json(json_path), args.db, dry_run=args.dry_run, magnet_dir=magnet_dir)


def cmd_site_view(args) -> None:
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Error: '{db_path}' does not exist.")
        sys.exit(1)
    with duckdb.connect(str(db_path)) as con:
        if args.name:
            view_site(con, args.name)
        else:
            view_sites(con, housing_filter=args.housing, status_filter=args.status)


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
        view_experiments(
            con,
            site_name=args.site,
            magnet_name=args.magnet,
            part_name=args.part,
            from_ts=args.date_from,
            to_ts=args.date_to,
        )


# ---------------------------------------------------------------------------
# operationaldata handlers
# ---------------------------------------------------------------------------


def cmd_operationaldata_view(args) -> None:
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Error: '{db_path}' does not exist.")
        sys.exit(1)
    with duckdb.connect(str(db_path), read_only=True) as con:
        view_operationaldata(
            con,
            site_name=args.site,
            type_filter=args.type,
            magnet_name=args.magnet,
            part_name=args.part,
            from_ts=args.date_from,
            to_ts=args.date_to,
        )


# ---------------------------------------------------------------------------
# overview-records handlers
# ---------------------------------------------------------------------------


def cmd_overview_records_view(args) -> None:
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Error: '{db_path}' does not exist.")
        sys.exit(1)
    with duckdb.connect(str(db_path), read_only=True) as con:
        view_overview_records(
            con,
            site_name=args.site,
            show_signatures=args.signatures,
            magnet_name=args.magnet,
            part_name=args.part,
            from_ts=args.date_from,
            to_ts=args.date_to,
        )


def _resolve_site_names(args, db_path: str) -> list[str]:
    if getattr(args, "all", False):
        with duckdb.connect(db_path, read_only=True) as con:
            return [r[0] for r in con.execute("SELECT name FROM sites ORDER BY name").fetchall()]
    return list(args.site or [])


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
        print("No sites specified. Use --site SITE or --all.")
        sys.exit(1)

    records_base = Path(args.records_base)
    active_types = args.types if args.types else ALL_POPULATE_TYPES
    tdms_types = [t for t in active_types if t != "Pupitre"]
    do_pupitre = "Pupitre" in active_types

    for site_name in site_names:
        site = _load_site(site_name, db_path)
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
        print("No sites specified. Use --site SITE or --all.")
        sys.exit(1)

    records_base = Path(args.records_base)

    for site_name in site_names:
        site = _load_site(site_name, db_path)
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
            {"name": fpath.stem, "description": "", "file": fpath.name}
            for fpath, _ in matches
        ]

        if args.dry_run:
            print(f"  [DRY RUN] {len(records)} pupitre file(s) would be added to experiments")
            continue

        with duckdb.connect(db_path) as con:
            ensure_schema(con)
            insert_experiments(con, site_name, records, verbose=True)


def cmd_populate_overview_records_from_json(args) -> None:
    json_path = Path(args.json_file)
    if not json_path.exists():
        print(f"Error: '{json_path}' not found.")
        sys.exit(1)

    try:
        with open(json_path, encoding="utf-8") as fh:
            records = json.load(fh)
    except json.JSONDecodeError as exc:
        print(f"Error: '{json_path}' is not valid JSON: {exc}")
        sys.exit(1)

    if not isinstance(records, list):
        print("Error: JSON file must contain a top-level array of records.")
        sys.exit(1)

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Error: '{db_path}' does not exist.")
        sys.exit(1)

    site_name = args.site or None

    print(f"\nLoading {len(records)} overview record(s) from {json_path.name} …\n")

    if args.dry_run:
        for rec in records:
            fname = rec.get("filename", "<missing>")
            housing = rec.get("housing", "?")
            dur = rec.get("duration", 0.0)
            print(f"  [dry-run] would insert: {fname}  [{housing}]  duration={float(dur or 0):.1f}s")
        return

    with duckdb.connect(str(db_path)) as con:
        ensure_schema(con)
        for rec in records:
            try:
                insert_overview_record_from_dict(
                    con, rec, site_name=site_name, verbose=True, upsert=args.reprocess
                )
            except (ValueError, KeyError) as exc:
                fname = rec.get("filename", "<unknown>")
                print(f"  [ERROR] {fname}: {exc}")

    print("\nDone.")


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
        print("No sites specified. Use --site SITE or --all.")
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
# hoop-stress handlers
# ---------------------------------------------------------------------------


def cmd_hoop_stress_compute(args) -> None:
    from compute_hoop_stats import DEFAULT_STRESS_BINS, _parse_bins, compute_hoop_stress_history

    db_path = args.db
    if not Path(db_path).exists():
        print(f"Error: '{db_path}' does not exist.")
        sys.exit(1)

    site_names = _resolve_site_names(args, db_path)
    if not site_names:
        print("No sites specified. Use --site SITE or --all.")
        sys.exit(1)

    bins = _parse_bins(args.bins) if args.bins else DEFAULT_STRESS_BINS
    pupitre_datadir = (
        str(Path(args.records_base) / args.srv_subdir) if args.records_base else ""
    )

    for site_name in site_names:
        print(f"\nSite: {site_name}")
        compute_hoop_stress_history(
            site_name=site_name,
            db_path=db_path,
            magnet_type=args.magnet_type,
            bins=bins,
            parquet_dir=args.parquet_dir,
            geometries_dir=args.geometries,
            reprocess=args.reprocess,
            dry_run=args.dry_run,
            use_mrun=args.use_mrun,
            pupitre_datadir=pupitre_datadir,
            verbose=not args.quiet,
        )


def cmd_hoop_stress_barchart(args) -> None:
    from stress_map import cmd_barchart
    cmd_barchart(args)


def _inject_pupitre_datadir(args) -> None:
    """Compute args.pupitre_datadir from --records-base / --srv-subdir."""
    args.pupitre_datadir = (
        str(Path(args.records_base) / args.srv_subdir) if args.records_base else ""
    )


def cmd_hoop_stress_history(args) -> None:
    from stress_map import cmd_history
    _inject_pupitre_datadir(args)
    cmd_history(args)


def cmd_hoop_stress_stats(args) -> None:
    from stress_map import cmd_stats
    _inject_pupitre_datadir(args)
    cmd_stats(args)


def cmd_hoop_stress_fatigue(args) -> None:
    from stress_map import cmd_fatigue
    _inject_pupitre_datadir(args)
    cmd_fatigue(args)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

_DISPATCH = {
    ("list",              None):              cmd_list,
    ("check",             None):              cmd_check,
    ("db",                "create"):          cmd_db_create,
    ("db",                "delete"):          cmd_db_delete,
    ("material",          "add"):             cmd_material_add,
    ("material",          "view"):            cmd_material_view,
    ("material",          "delete"):          cmd_material_delete,
    ("magnet",            "add"):              cmd_magnet_add,
    ("magnet",            "view"):             cmd_magnet_view,
    ("magnet",            "check-geometry"):   cmd_magnet_check_geometry,
    ("magnet",            "delete"):           cmd_magnet_delete,
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
    ("populate",          "overview-records"):           cmd_populate_overview_records,
    ("populate",          "overview-records-from-json"): cmd_populate_overview_records_from_json,
    ("hoop-stress",       "compute"):                    cmd_hoop_stress_compute,
    ("hoop-stress",       "barchart"):                  cmd_hoop_stress_barchart,
    ("hoop-stress",       "history"):                   cmd_hoop_stress_history,
    ("hoop-stress",       "stats"):                     cmd_hoop_stress_stats,
    ("hoop-stress",       "fatigue"):                   cmd_hoop_stress_fatigue,
}


def _db_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument("--db", default=DEFAULT_DB,
                   help=f"DuckDB file (default: {DEFAULT_DB})")


def _input_dir_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument("--input-dir", dest="input_dir", default=None,
                   help="Directory to look up the JSON file in "
                        "(default: use the path given to json_file as-is)")


def _sites_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--site", action="append", metavar="SITE", dest="site",
        help="Site name to process (repeat for multiple sites). Use --all instead to process every site.",
    )
    p.add_argument("--all", action="store_true",
                   help="Process all sites in the database.")


def _time_range_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--from", dest="date_from", default=None, metavar="DATETIME",
        help="Include only records at or after this date/time "
             "(YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)",
    )
    p.add_argument(
        "--to", dest="date_to", default=None, metavar="DATETIME",
        help="Include only records at or before this date/time "
             "(YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)",
    )


def _hs_shared_args(p: argparse.ArgumentParser) -> None:
    """Arguments shared by all hoop-stress visualisation subcommands."""
    p.add_argument("site_name", help="Site name as registered in DuckDB (e.g. M9)")
    _db_arg(p)
    p.add_argument(
        "--geometries", default="geometries",
        help="Directory of YAML geometry files (default: geometries/)",
    )
    p.add_argument("--debug", action="store_true",
                   help="Enable debug output from magnet_setup()")


def _hs_pupitre_args(p: argparse.ArgumentParser) -> None:
    """Arguments for subcommands that read a pupitre time-series file."""
    p.add_argument(
        "--pupitre", nargs="*", default=None, metavar="FILE",
        help="Pupitre file(s) (.txt, .tdms, .csv). "
             "Omit to use all experiment files registered for the site.",
    )
    p.add_argument(
        "--records-base", default=str(_DEFAULT_RECORDS_BASE), dest="records_base",
        metavar="DIR",
        help=f"Root of the records tree (default: {_DEFAULT_RECORDS_BASE})",
    )
    p.add_argument(
        "--srv-subdir", default=_DEFAULT_SRV_SUBDIR, dest="srv_subdir",
        help=f"Subdirectory of records-base for pupitre TXT files "
             f"(default: {_DEFAULT_SRV_SUBDIR})",
    )
    p.add_argument(
        "--use-mrun", action="store_true", dest="use_mrun",
        help="Load via python_magnetrun.MagnetRun.load_mrun() "
             "(supports .tdms and path auto-resolution)",
    )
    p.add_argument(
        "--check", action="store_true",
        help="Validate fast results against bmap.getHoop row by row",
    )
    p.add_argument(
        "--magnet-type", default="all", dest="magnet_type",
        choices=["H", "B", "S", "all"],
        help="Coil type(s) to compute hoop stress for (default: all)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="magnetdb",
        description="Manage a student MagnetDB DuckDB.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    entity = parser.add_subparsers(
        dest="entity", required=True,
        metavar="{list,check,db,material,magnet,site,housing,experiments,operationaldata,overview-records,populate,hoop-stress}",
    )

    # ── list ─────────────────────────────────────────────────────────────────
    list_p = entity.add_parser("list", help="List all objects (materials, magnets, sites, housings).")
    _db_arg(list_p)

    # ── check ────────────────────────────────────────────────────────────────
    check_p = entity.add_parser(
        "check",
        help="Validate database contents (geometry_data coverage, magnet type "
             "consistency, experiment/operationaldata file existence).",
    )
    _db_arg(check_p)
    check_p.add_argument(
        "--entity", dest="check_entity", default="all",
        choices=["all", "part", "magnet", "experiment", "operationaldata"],
        help="Restrict the check to one entity type (default: all)",
    )
    check_p.add_argument(
        "--name", default=None,
        help="Restrict the check to one object (requires --entity other than 'all')",
    )
    check_p.add_argument(
        "--fix", action="store_true",
        help="For magnets: reconstruct missing geometry_data from parts' "
             "geometry_data and write it back to the DB.",
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

    # ── material ─────────────────────────────────────────────────────────────
    mat_p = entity.add_parser("material", help="Manage materials.")
    mat_sub = mat_p.add_subparsers(dest="action", required=True,
                                   metavar="{add,view,delete}")

    ma_add = mat_sub.add_parser("add", help="Add a material from a JSON file.")
    ma_add.add_argument("json_file", help="Path to the material JSON file (or bare name with --input-dir)")
    _db_arg(ma_add)
    _input_dir_arg(ma_add)
    ma_add.add_argument("--dry-run", action="store_true",
                        help="Validate and preview without writing")

    ma_view = mat_sub.add_parser("view", help="List all materials or show one.")
    ma_view.add_argument("name", nargs="?", default=None,
                         help="Material name (omit to list all)")
    ma_view.add_argument("--nuance", default=None,
                         help="Filter list by nuance (ignored when <name> is given)")
    _db_arg(ma_view)

    ma_del = mat_sub.add_parser("delete", help="Delete a material (fails if referenced by a part).")
    ma_del.add_argument("name", help="Material name")
    _db_arg(ma_del)

    # ── magnet ──────────────────────────────────────────────────────────────
    magnet_p = entity.add_parser("magnet", help="Manage magnets.")
    magnet_sub = magnet_p.add_subparsers(dest="action", required=True,
                                         metavar="{add,view,check-geometry,delete}")

    m_add = magnet_sub.add_parser("add", help="Add a magnet from a JSON export.")
    m_add.add_argument("json_file", help="Path to the magnet JSON file (or bare name with --input-dir)")
    _db_arg(m_add)
    _input_dir_arg(m_add)
    m_add.add_argument("--part-dir", dest="part_dir",
                       help="Directory for <part_name>.json files "
                            "(default: same dir as the JSON file)")
    m_add.add_argument("--geometry",
                       help="Path to the assembly-level YAML geometry file "
                            "(Insert, Bitters, …) to store in magnets.geometry_data. "
                            "Required for geometry_config_to_yaml / the 'geometry' "
                            "subcommand of stress_map.py / magnetdb.py hoop-stress.")
    m_add.add_argument("--dry-run", action="store_true",
                       help="Validate and preview without writing")

    m_view = magnet_sub.add_parser("view", help="List all magnets or show one.")
    m_view.add_argument("name", nargs="?", default=None,
                        help="Magnet name (omit to list all)")
    m_view.add_argument("--type", default=None,
                        choices=["insert", "bitters", "supras"],
                        help="Filter list by magnet type (ignored when <name> is given)")
    m_view.add_argument("--status", default=None,
                        help="Filter list by status (ignored when <name> is given)")
    _db_arg(m_view)

    m_chk = magnet_sub.add_parser(
        "check-geometry",
        help="Report geometry_data coverage for magnet assembly and parts.",
    )
    m_chk.add_argument("name", nargs="?", default=None,
                       help="Magnet name (omit to check all magnets)")
    _db_arg(m_chk)

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
    s_view.add_argument("--housing", default=None,
                        help="Filter list by housing name (ignored when <name> is given)")
    s_view.add_argument("--status", default=None,
                        help="Filter list by status (ignored when <name> is given)")
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

    e_view = exp_sub.add_parser("view", help="List experiments, optionally filtered.")
    e_view.add_argument("--site", default=None, metavar="SITE",
                        help="Filter by site name")
    e_view.add_argument("--magnet", default=None, metavar="MAGNET",
                        help="Filter by magnet name (shows all sites that used this magnet)")
    e_view.add_argument("--part", default=None, metavar="PART",
                        help="Filter by part name (shows all sites that used this part)")
    _time_range_args(e_view)
    _db_arg(e_view)

    # ── operationaldata ───────────────────────────────────────────────────────
    opdata_p = entity.add_parser("operationaldata", help="View operationaldata records.")
    opdata_sub = opdata_p.add_subparsers(dest="action", required=True,
                                         metavar="{view}")

    o_view = opdata_sub.add_parser(
        "view", help="List operationaldata records, optionally filtered."
    )
    o_view.add_argument("--site", default=None, metavar="SITE",
                        help="Filter by site name")
    o_view.add_argument(
        "--type", default=None, choices=ALL_POPULATE_TYPES, metavar="TYPE",
        help=f"Filter by file type ({', '.join(ALL_POPULATE_TYPES)})",
    )
    o_view.add_argument("--magnet", default=None, metavar="MAGNET",
                        help="Filter by magnet name (shows all sites that used this magnet)")
    o_view.add_argument("--part", default=None, metavar="PART",
                        help="Filter by part name (shows all sites that used this part)")
    _time_range_args(o_view)
    _db_arg(o_view)

    # ── overview-records ──────────────────────────────────────────────────────
    ovr_p = entity.add_parser("overview-records", help="View overview_records.")
    ovr_sub = ovr_p.add_subparsers(dest="action", required=True,
                                   metavar="{view}")

    ov_view = ovr_sub.add_parser(
        "view", help="List overview_records, optionally filtered."
    )
    ov_view.add_argument("--site", default=None, metavar="SITE",
                         help="Filter by site name")
    ov_view.add_argument("--magnet", default=None, metavar="MAGNET",
                         help="Filter by magnet name (shows all sites that used this magnet)")
    ov_view.add_argument("--part", default=None, metavar="PART",
                         help="Filter by part name (shows all sites that used this part)")
    _time_range_args(ov_view)
    ov_view.add_argument("--signatures", action="store_true",
                         help="Include per-record signature and sync details")
    _db_arg(ov_view)

    # ── populate ─────────────────────────────────────────────────────────────
    pop_p = entity.add_parser("populate", help="Populate data tables from files.")
    pop_sub = pop_p.add_subparsers(dest="action", required=True,
                                   metavar="{operationaldata,experiments,overview-records,overview-records-from-json}")

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

    # populate overview-records-from-json
    p_ov_json = pop_sub.add_parser(
        "overview-records-from-json",
        help="Load overview_records directly from a pre-computed summary JSON file.",
    )
    _db_arg(p_ov_json)
    p_ov_json.add_argument(
        "json_file",
        help=(
            "Path to a JSON file containing an array of overview record dicts "
            "(e.g. summary-2026.json produced by python_magnetrun analysis/cli.py). "
            "Source lists may be plain Python lists or comma-separated strings. "
            "Both 'sources_<key>' and '<key>' column-name aliases are accepted."
        ),
    )
    p_ov_json.add_argument(
        "--site", default=None, metavar="SITE",
        help="Site name to assign to all loaded records (overrides any site_name in the JSON).",
    )
    p_ov_json.add_argument(
        "--reprocess", action="store_true",
        help="Overwrite existing overview_records rows (upsert instead of skip).",
    )
    p_ov_json.add_argument("--dry-run", action="store_true",
                           help="Preview records without writing to the DB.")

    # ── hoop-stress ───────────────────────────────────────────────────────────
    hs_p = entity.add_parser("hoop-stress",
                             help="Compute and visualise per-part hoop-stress statistics.")
    hs_sub = hs_p.add_subparsers(dest="action", required=True,
                                  metavar="{compute,barchart,history,stats,fatigue}")

    hs_compute = hs_sub.add_parser(
        "compute",
        help="Compute hoop-stress time series, bin stats, and fatigue for experiments.",
    )
    _db_arg(hs_compute)
    _sites_arg(hs_compute)
    hs_compute.add_argument(
        "--magnet-type", default="all", choices=["H", "B", "S", "all"],
        dest="magnet_type",
        help="Coil type(s) to compute (default: all)",
    )
    hs_compute.add_argument(
        "--bins", default=None,
        help="Bin edges in MPa as a comma-separated list, e.g. '0,100,200,300,400,500,600' "
             "(default: 0–600 MPa in 100 MPa steps). "
             "Legacy pair format 'l1:h1,l2:h2,...' also accepted.",
    )
    hs_compute.add_argument(
        "--parquet-dir", default=None, dest="parquet_dir",
        help="Output directory for Parquet files (default: <db dir>/hoop_parquet)",
    )
    hs_compute.add_argument(
        "--geometries", default=None,
        help="Override geometry YAML directory",
    )
    hs_compute.add_argument(
        "--reprocess", action="store_true",
        help="Re-compute already-processed experiments",
    )
    hs_compute.add_argument(
        "--dry-run", action="store_true", dest="dry_run",
        help="Discover files but do not write to DB or disk",
    )
    hs_compute.add_argument(
        "--use-mrun", action="store_true", dest="use_mrun",
        help="Load files via python_magnetrun.MagnetRun.load_mrun()",
    )
    hs_compute.add_argument(
        "--records-base", default="", dest="records_base",
        help="Root of the records tree (parent of --srv-subdir)",
    )
    hs_compute.add_argument(
        "--srv-subdir", default=_DEFAULT_SRV_SUBDIR, dest="srv_subdir",
        help=f"Subdirectory of records-base for pupitre TXT files "
             f"(default: {_DEFAULT_SRV_SUBDIR})",
    )
    hs_compute.add_argument(
        "--quiet", action="store_true",
        help="Suppress per-file output",
    )

    hs_bar = hs_sub.add_parser(
        "barchart",
        help="Bar chart of hoop stress at given currents vs Rpe.",
    )
    _hs_shared_args(hs_bar)
    hs_bar.add_argument(
        "--i-h", type=float, default=20000.0, dest="i_h",
        help="Helix current [A] (default: 20000)",
    )
    hs_bar.add_argument(
        "--i-b", type=float, default=0.0, dest="i_b",
        help="Bitter current [A] (default: 0)",
    )
    hs_bar.add_argument(
        "--i-s", type=float, default=0.0, dest="i_s",
        help="Supra current [A] (default: 0)",
    )

    hs_hist = hs_sub.add_parser(
        "history",
        help="Hoop stress vs time from a pupitre file (normalised plot).",
    )
    _hs_shared_args(hs_hist)
    _hs_pupitre_args(hs_hist)

    hs_stats = hs_sub.add_parser(
        "stats",
        help="Descriptive statistics of hoop stress time series.",
    )
    _hs_shared_args(hs_stats)
    _hs_pupitre_args(hs_stats)
    hs_stats.add_argument(
        "--output", default=None,
        help="Save stats table to CSV (default: print only)",
    )

    hs_fat = hs_sub.add_parser(
        "fatigue",
        help="Rainflow cycle counting on hoop stress time series.",
    )
    _hs_shared_args(hs_fat)
    _hs_pupitre_args(hs_fat)
    hs_fat.add_argument(
        "--bins", type=int, default=15,
        help="Number of histogram bins (default: 15)",
    )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    action = getattr(args, "action", None)
    handler = _DISPATCH.get((args.entity, action))
    if handler is None:
        parser.print_help()
        sys.exit(1)
    handler(args)


if __name__ == "__main__":
    main()
