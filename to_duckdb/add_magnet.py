"""
add_magnet.py  [DEPRECATED — use magnetdb.py instead]

Superseded by ``python magnetdb.py magnet add <json_file> [options]``.
See DEPRECATED.md for full documentation.
"""

import argparse
import json
import sys
from pathlib import Path

import duckdb

from schema import COIL_TYPES
from crud import (
    infer_magnet_type,
    insert_magnet,
    insert_magnet_parts,
    insert_material,
    insert_part,
    load_json,
)
from schema import ensure_schema


# ---------------------------------------------------------------------------
# Part resolution
# ---------------------------------------------------------------------------


def _resolve_parts(parts: list, part_dir: Path) -> list[dict]:
    """Return a list of fully-resolved part dicts.

    String entries are resolved by loading ``<part_dir>/<name>.json``.
    Exits with an error message if a referenced JSON file is not found.
    """
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


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate(data: dict) -> list[str]:
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


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def add_magnet(
    data: dict,
    db_path,
    dry_run: bool = False,
    part_dir=None,
    geometry_path=None,
) -> None:
    """Insert a magnet and its parts/materials into the student DuckDB.

    Parameters
    ----------
    data          : dict matching the MagnetDB magnet JSON export format
    db_path       : path to the .duckdb file (created if it does not exist)
    dry_run       : if True, validate only — do not write
    part_dir      : directory to search for <part_name>.json files when a part
                    entry is a plain name string (default: current directory)
    geometry_path : optional path to the assembly-level YAML geometry file
                    (Insert, Bitters, …) to store in magnets.geometry_data.
                    Takes precedence over any ``geometry`` key already present
                    in *data*.
    """
    db_path = Path(db_path)
    part_dir = Path(part_dir) if part_dir else Path(".")

    # Inject assembly geometry path so insert_magnet can populate geometry_data
    if geometry_path:
        data = {**data, "geometry": str(geometry_path)}

    # Normalise: strip accidental .json suffix from name
    if data.get("name", "").endswith(".json"):
        data = {**data, "name": data["name"][:-5]}

    # Resolve name-only part references before validation
    raw_parts = data.get("parts") or []
    if any(isinstance(p, str) for p in raw_parts):
        data = {**data, "parts": _resolve_parts(raw_parts, part_dir)}

    errors = _validate(data)
    if errors:
        print("Validation errors:")
        for e in errors:
            print(f"  • {e}")
        sys.exit(1)

    parts = data["parts"]
    magnet_type = infer_magnet_type(parts)

    if dry_run:
        coil_parts = [p for p in parts if p.get("type") in COIL_TYPES]
        mats = {p["material"]["name"] for p in parts if p.get("material")}
        print("[dry-run] Validation passed. Would insert:")
        print(f"  magnet   : {data['name']}  [{magnet_type}]  {data.get('status', '')}")
        print(f"  parts    : {len(parts)}  ({len(coil_parts)} coil channel(s))")
        print(f"  materials: {len(mats)}")
        return

    con = duckdb.connect(str(db_path))
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

    con.close()
    print("\nDone.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    import warnings
    warnings.warn(
        "add_magnet.py is deprecated. Use 'python magnetdb.py magnet add' instead.",
        DeprecationWarning,
        stacklevel=1,
    )
    parser = argparse.ArgumentParser(
        description="[DEPRECATED — use: python magnetdb.py magnet add] "
                    "Add a magnet to the student DuckDB from a MagnetDB JSON export.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("json_file", help="Path to the magnet JSON file")
    parser.add_argument(
        "--db",
        default="student_magnetdb.duckdb",
        help="Target DuckDB file (default: student_magnetdb.duckdb; created if absent)",
    )
    parser.add_argument(
        "--part-dir",
        default=None,
        dest="part_dir",
        help=(
            "Directory to search for <part_name>.json files when a part is a "
            "name-only reference (default: same directory as the magnet JSON file)"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and preview without writing to the DB",
    )
    args = parser.parse_args()

    json_path = Path(args.json_file)
    if not json_path.exists():
        print(f"Error: '{json_path}' not found.")
        sys.exit(1)

    part_dir = args.part_dir if args.part_dir else json_path.parent
    data = load_json(json_path)
    add_magnet(data, args.db, dry_run=args.dry_run, part_dir=part_dir)


if __name__ == "__main__":
    main()
