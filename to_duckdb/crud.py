"""
crud.py
=======
CRUD helpers for the student magnetdb DuckDB.

All functions accept an open ``duckdb.DuckDBPyConnection``.
Callers are responsible for opening, committing, and closing the connection
and for calling ``schema.ensure_schema(con)`` before the first write.

Public API
----------
exists(con, table, name)
load_geometry_json(path)
infer_magnet_type(parts)

insert_material(con, mat, verbose)
insert_part(con, part, verbose)
insert_magnet(con, data, magnet_type, verbose)
insert_magnet_parts(con, magnet_name, parts, verbose)
insert_magnet_part_row(con, magnet_name, part_name, rank, coil_index)

parse_timestamp(value)
insert_site(con, data, verbose)
insert_site_magnets(con, site_name, magnet_entries, verbose)
insert_experiments(con, site_name, records, verbose)

update_site_magnet(con, site_name, magnet_name, **kwargs)
"""

import json
import re
from pathlib import Path

from schema import COIL_TYPES

# ---------------------------------------------------------------------------
# JSON loading
# ---------------------------------------------------------------------------

_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")


def load_json(path) -> dict:
    """Read a JSON file, stripping trailing commas before parsing.

    Many hand-edited or tool-generated JSON files contain trailing commas
    (e.g. ``{"a": 1,}``), which the standard ``json`` module rejects.
    This function removes them so such files load cleanly.
    """
    text = Path(path).read_text()
    text = _TRAILING_COMMA_RE.sub(r"\1", text)
    return json.loads(text)


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def exists(con, table: str, name: str) -> bool:
    return con.execute(f"SELECT 1 FROM {table} WHERE name = ?", [name]).fetchone() is not None


def load_geometry_json(geometry_path) -> str | None:
    """Serialise a geometry YAML via python_magnetgeo; returns None on failure.

    Resolves the path to absolute and chdir to its parent before loading so
    that relative paths embedded in the YAML (e.g. sub-component files) are
    resolved correctly.
    """
    if not geometry_path:
        return None
    path = Path(geometry_path).resolve()
    if not path.exists():
        return None
    try:
        import os
        import yaml as _yaml
        from python_magnetgeo.deserialize import serialize_instance
        orig_dir = os.getcwd()
        try:
            os.chdir(path.parent)
            with open(path.name) as f:
                obj = _yaml.load(f, Loader=_yaml.FullLoader)
        finally:
            os.chdir(orig_dir)
        return json.dumps(obj, default=serialize_instance)
    except Exception as exc:
        print(f"  [WARN] Could not serialize geometry '{geometry_path}': {exc}")
        return None


def infer_magnet_type(parts: list[dict]) -> str:
    """Infer magnet assembly type from the types of its constituent parts."""
    coil_types = {p.get("type") for p in parts if p.get("type") in COIL_TYPES}
    if coil_types == {"helix"}:
        return "insert"
    if coil_types == {"bitter"}:
        return "bitters"
    if len(coil_types) > 1:
        return "hybrid"
    return "unknown"


# ---------------------------------------------------------------------------
# Material
# ---------------------------------------------------------------------------


def insert_material(con, mat: dict, verbose: bool = True) -> None:
    """Insert a material row; skip silently if it already exists."""
    name = mat["name"]
    if exists(con, "materials", name):
        if verbose:
            print(f"  ~ material  {name}  (already exists, skipped)")
        return
    con.execute(
        "INSERT INTO materials VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            name,
            mat.get("description") or None,
            mat.get("nuance") or None,
            mat.get("t_ref"),
            mat.get("volumic_mass"),
            mat.get("specific_heat"),
            mat.get("alpha"),
            mat.get("electrical_conductivity"),
            mat.get("thermal_conductivity"),
            mat.get("magnet_permeability"),
            mat.get("young"),
            mat.get("poisson"),
            mat.get("expansion_coefficient"),
            mat.get("rpe"),
        ],
    )
    if verbose:
        print(f"  + material  {name}  [{mat.get('nuance', '?')}]")


# ---------------------------------------------------------------------------
# Part
# ---------------------------------------------------------------------------


def insert_part(con, part: dict, verbose: bool = True) -> None:
    """Insert a part row; skip silently if it already exists.

    ``part`` may carry ``material_name`` (seeds format) or a nested
    ``material.name`` dict (JSON-export format).
    """
    name = part["name"]
    if exists(con, "parts", name):
        if verbose:
            print(f"  ~ part      {name}  (already exists, skipped)")
        return
    material_name = part.get("material_name") or (part.get("material") or {}).get("name")
    geometry_data = part.get("geometry_data") or load_geometry_json(part.get("geometry"))
    con.execute(
        """
        INSERT INTO parts
            (name, type, status, material_name, geometry, geometry_data, cad, design_office_reference)
        VALUES (?,?,?,?,?,?,?,?)
        """,
        [
            name,
            part.get("type"),
            part.get("status"),
            material_name,
            part.get("geometry") or None,
            geometry_data,
            part.get("cad") or None,
            part.get("design_office_reference") or None,
        ],
    )
    if verbose:
        print(f"  + part      {name}  [{part.get('type', '?')}]")


# ---------------------------------------------------------------------------
# Magnet
# ---------------------------------------------------------------------------


def insert_magnet(con, data: dict, magnet_type: str, verbose: bool = True) -> None:
    """Insert a magnet row; skip silently if it already exists."""
    name = data["name"]
    if exists(con, "magnets", name):
        if verbose:
            print(f"  ~ magnet    {name}  (already exists, skipped)")
        return
    geometry_data = data.get("geometry_data") or load_geometry_json(data.get("geometry"))
    con.execute(
        """
        INSERT INTO magnets
            (name, type, status, geometry, geometry_data, design_office_reference)
        VALUES (?,?,?,?,?,?)
        """,
        [
            name,
            magnet_type,
            data.get("status"),
            data.get("geometry") or None,
            geometry_data,
            data.get("design_office_reference") or None,
        ],
    )
    if verbose:
        print(f"  + magnet    {name}  [{magnet_type}]  {data.get('status', '')}")


def insert_magnet_parts(con, magnet_name: str, parts: list[dict], verbose: bool = True) -> None:
    """Link parts to a magnet, computing coil_index for helix/bitter parts.

    ``parts`` must be a list of part dicts, each with at least ``name`` and
    ``type`` keys (i.e. the raw parts list from the magnet JSON export).
    """
    coil_counter = 0
    inserted = 0
    skipped = 0
    for rank, part in enumerate(parts):
        part_name = part["name"]
        part_type = part.get("type", "")

        coil_index = None
        if part_type in COIL_TYPES:
            coil_counter += 1
            coil_index = coil_counter

        if con.execute(
            "SELECT 1 FROM magnet_parts WHERE magnet_name = ? AND part_name = ?",
            [magnet_name, part_name],
        ).fetchone():
            skipped += 1
            continue

        con.execute(
            "INSERT INTO magnet_parts VALUES (?,?,?,?)",
            [magnet_name, part_name, rank, coil_index],
        )
        inserted += 1

    if verbose:
        print(
            f"  + magnet_parts  {inserted} inserted,  {skipped} already present"
            f"  ({coil_counter} coil channel(s))"
        )


def insert_magnet_part_row(
    con, magnet_name: str, part_name: str, rank: int, coil_index: int | None
) -> None:
    """Insert a single pre-computed magnet_parts row (used by seeds_to_duckdb)."""
    if con.execute(
        "SELECT 1 FROM magnet_parts WHERE magnet_name = ? AND part_name = ?",
        [magnet_name, part_name],
    ).fetchone():
        return
    con.execute(
        "INSERT INTO magnet_parts VALUES (?,?,?,?)",
        [magnet_name, part_name, rank, coil_index],
    )


# ---------------------------------------------------------------------------
# Site
# ---------------------------------------------------------------------------


def parse_timestamp(value) -> str | None:
    if not value or str(value).lower() in ("none", "null", ""):
        return None
    return str(value)


def insert_site(con, data: dict, verbose: bool = True) -> None:
    """Insert a site row; skip silently if it already exists."""
    name = data["name"]
    if exists(con, "sites", name):
        if verbose:
            print(f"  ~ site      {name}  (already exists, skipped)")
        return
    con.execute(
        "INSERT INTO sites VALUES (?,?,?,?,?,?)",
        [
            name,
            data.get("description") or None,
            data.get("status", "in_study"),
            data.get("housing") or None,
            parse_timestamp(data.get("commissioned_at")),
            parse_timestamp(data.get("decommissioned_at")),
        ],
    )
    if verbose:
        print(f"  + site      {name}  [{data.get('housing', '?')}]  {data.get('status', '')}")


def _magnet_entry_name(entry) -> str:
    return entry if isinstance(entry, str) else entry["name"]


def insert_site_magnets(
    con, site_name: str, magnet_entries: list, verbose: bool = True
) -> None:
    """Link magnets to a site.

    Each entry in *magnet_entries* is either a plain magnet name string or a
    dict with optional positional/temporal fields (z_offset, r_offset,
    parallax, commissioned_at, decommissioned_at, metadata).
    """
    for entry in magnet_entries:
        magnet_name = _magnet_entry_name(entry)
        extra = entry if isinstance(entry, dict) else {}

        if con.execute(
            "SELECT 1 FROM site_magnets WHERE site_name = ? AND magnet_name = ?",
            [site_name, magnet_name],
        ).fetchone():
            if verbose:
                print(f"  ~ magnet    {magnet_name}  (already linked, skipped)")
            continue

        con.execute(
            """
            INSERT INTO site_magnets
                (site_name, magnet_name, z_offset, r_offset, parallax,
                 commissioned_at, decommissioned_at, metadata)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            [
                site_name,
                magnet_name,
                extra.get("z_offset", 0.0),
                extra.get("r_offset", 0.0),
                extra.get("parallax", 0.0),
                parse_timestamp(extra.get("commissioned_at")),
                parse_timestamp(extra.get("decommissioned_at")),
                json.dumps(extra.get("metadata", {})),
            ],
        )
        if verbose:
            row = con.execute("SELECT type FROM magnets WHERE name = ?", [magnet_name]).fetchone()
            print(f"  + magnet    {magnet_name}  ({row[0] if row else '?'})")


def insert_experiments(
    con, site_name: str, records: list[dict], verbose: bool = True
) -> None:
    """Insert experiment/record rows for a site; skip duplicates by file name."""
    row = con.execute("SELECT COALESCE(MAX(id), 0) FROM experiments").fetchone()
    next_id = (row[0] or 0) + 1
    inserted = 0
    skipped = 0

    for i, rec in enumerate(records):
        file_name = rec.get("file") or rec.get("name") or rec.get("record_file")
        if con.execute(
            "SELECT 1 FROM experiments WHERE site_name = ? AND file = ?",
            [site_name, file_name],
        ).fetchone():
            skipped += 1
            continue

        con.execute(
            "INSERT INTO experiments VALUES (?,?,?,?,?,'pending')",
            [
                next_id + i,
                rec.get("name") or file_name,
                rec.get("description") or None,
                file_name,
                site_name,
            ],
        )
        inserted += 1

    if verbose:
        print(f"  + records   {inserted} inserted,  {skipped} already present")


# ---------------------------------------------------------------------------
# Update helpers
# ---------------------------------------------------------------------------

_FLOAT_FIELDS = frozenset({"z_offset", "r_offset", "parallax"})
_TIMESTAMP_FIELDS = frozenset({"commissioned_at", "decommissioned_at"})
_JSON_FIELDS = frozenset({"metadata"})
_SITE_MAGNET_FIELDS = _FLOAT_FIELDS | _TIMESTAMP_FIELDS | _JSON_FIELDS


# ---------------------------------------------------------------------------
# View helpers
# ---------------------------------------------------------------------------


def view_magnets(con) -> None:
    rows = con.execute("SELECT name, type, status FROM magnets ORDER BY name").fetchall()
    if not rows:
        print("No magnets in database.")
        return
    print(f"{'Name':<30} {'Type':<10} Status")
    print("-" * 55)
    for name, type_, status in rows:
        print(f"{name:<30} {type_ or '?':<10} {status or ''}")


def view_magnet(con, name: str) -> None:
    row = con.execute(
        "SELECT name, type, status, design_office_reference FROM magnets WHERE name = ?",
        [name],
    ).fetchone()
    if not row:
        print(f"Magnet '{name}' not found.")
        return
    print(f"Magnet : {row[0]}")
    print(f"  type  : {row[1] or '?'}")
    print(f"  status: {row[2] or ''}")
    print(f"  ref   : {row[3] or ''}")
    parts = con.execute(
        "SELECT p.name, p.type, mp.rank, mp.coil_index "
        "FROM magnet_parts mp JOIN parts p ON mp.part_name = p.name "
        "WHERE mp.magnet_name = ? ORDER BY mp.rank",
        [name],
    ).fetchall()
    if parts:
        print(f"  parts ({len(parts)}):")
        for pname, ptype, rank, coil_index in parts:
            ci = f"  coil#{coil_index}" if coil_index else ""
            print(f"    [{rank}] {pname}  ({ptype or '?'}){ci}")


def view_sites(con) -> None:
    rows = con.execute("SELECT name, housing, status FROM sites ORDER BY name").fetchall()
    if not rows:
        print("No sites in database.")
        return
    print(f"{'Name':<40} {'Housing':<15} Status")
    print("-" * 65)
    for name, housing, status in rows:
        print(f"{name:<40} {housing or '?':<15} {status or ''}")


def view_site(con, name: str) -> None:
    row = con.execute(
        "SELECT name, housing, status, commissioned_at, decommissioned_at "
        "FROM sites WHERE name = ?",
        [name],
    ).fetchone()
    if not row:
        print(f"Site '{name}' not found.")
        return
    print(f"Site : {row[0]}")
    print(f"  housing          : {row[1] or '?'}")
    print(f"  status           : {row[2] or ''}")
    print(f"  commissioned_at  : {row[3] or ''}")
    print(f"  decommissioned_at: {row[4] or ''}")
    magnets = con.execute(
        "SELECT magnet_name, z_offset, r_offset "
        "FROM site_magnets WHERE site_name = ? ORDER BY magnet_name",
        [name],
    ).fetchall()
    if magnets:
        print(f"  magnets ({len(magnets)}):")
        for mname, z, r in magnets:
            print(f"    {mname}  (z={z}, r={r})")
    count = con.execute(
        "SELECT COUNT(*) FROM experiments WHERE site_name = ?", [name]
    ).fetchone()[0]
    print(f"  experiments: {count}")


# ---------------------------------------------------------------------------
# Delete helpers
# ---------------------------------------------------------------------------


def delete_magnet(con, name: str) -> None:
    if not exists(con, "magnets", name):
        print(f"Magnet '{name}' not found.")
        return
    con.execute("DELETE FROM magnet_parts WHERE magnet_name = ?", [name])
    con.execute("DELETE FROM magnets WHERE name = ?", [name])
    print(f"Deleted magnet '{name}' and its part links.")


def delete_site(con, name: str) -> None:
    if not exists(con, "sites", name):
        print(f"Site '{name}' not found.")
        return
    con.execute("DELETE FROM experiments WHERE site_name = ?", [name])
    con.execute("DELETE FROM site_magnets WHERE site_name = ?", [name])
    con.execute("DELETE FROM sites WHERE name = ?", [name])
    print(f"Deleted site '{name}', its magnet links, and its experiments.")


# ---------------------------------------------------------------------------
# Update helpers
# ---------------------------------------------------------------------------


def update_site_magnet(con, site_name: str, magnet_name: str, **kwargs) -> None:
    """Update positional/temporal fields on an existing site_magnets row.

    Accepted kwargs: z_offset, r_offset, parallax, commissioned_at,
    decommissioned_at, metadata.  Only non-None values are updated.
    Raises ValueError if the (site_name, magnet_name) row does not exist.
    """
    updates = {k: v for k, v in kwargs.items() if k in _SITE_MAGNET_FIELDS and v is not None}
    if not updates:
        print("Nothing to update.")
        return

    if not con.execute(
        "SELECT 1 FROM site_magnets WHERE site_name = ? AND magnet_name = ?",
        [site_name, magnet_name],
    ).fetchone():
        raise ValueError(f"No link between site '{site_name}' and magnet '{magnet_name}'.")

    set_clauses = []
    values = []
    for field, value in updates.items():
        set_clauses.append(f"{field} = ?")
        if field in _TIMESTAMP_FIELDS:
            values.append(parse_timestamp(value))
        elif field in _JSON_FIELDS:
            values.append(json.dumps(value) if not isinstance(value, str) else value)
        else:
            values.append(float(value))

    values.extend([site_name, magnet_name])
    con.execute(
        f"UPDATE site_magnets SET {', '.join(set_clauses)} "
        "WHERE site_name = ? AND magnet_name = ?",
        values,
    )
    print(f"Updated site_magnets ({site_name}, {magnet_name}): {sorted(updates)}")
