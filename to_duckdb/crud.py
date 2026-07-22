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
view_materials(con)
view_material(con, name)
delete_material(con, name)
insert_part(con, part, verbose)
insert_magnet(con, data, magnet_type, verbose)
insert_magnet_parts(con, magnet_name, parts, verbose)
insert_magnet_part_row(con, magnet_name, part_name, rank, coil_index)
check_geometry_data(con, name)
print_geometry_check(results)

parse_timestamp(value)
insert_site(con, data, verbose, create_housing)
insert_housing_config_from_magnetrun(con, housing_name, verbose)
insert_site_magnets(con, site_name, magnet_entries, verbose)
insert_experiments(con, site_name, records, verbose)

update_site_magnet(con, site_name, magnet_name, **kwargs)

insert_overview_record(con, record, site_name, verbose)
upsert_overview_record(con, record, site_name, verbose)
insert_overview_record_from_dict(con, data, site_name, verbose, upsert)
attach_site_to_overview_record(con, filename, site_name, verbose)
"""

import json
import re
from pathlib import Path
from typing import Any

from enums import COIL_PART_TO_MAGNET_TYPE
from schema import COIL_TYPES

# ---------------------------------------------------------------------------
# Housing config derivation constants
# ---------------------------------------------------------------------------

_COIL_TO_SUFFIX: dict[str, str] = {"Insert": "H", "Bitter": "B"}
_SUFFIX_TO_COIL: dict[str, str] = {v: k for k, v in _COIL_TO_SUFFIX.items()}
_H_UCOILS: list[str] = [f"Ucoil{i}" for i in range(1, 15)]
_B_UCOILS: list[str] = ["Ucoil15", "Ucoil16"]

_PIGBROTHER_FORMULA_MAP: dict[str, dict] = {
    "Courants_Alimentations/Référence_GR1": {
        "formula": "Courants_Alimentations/Référence_GR1 = Référence_A1 + Référence_A2",
        "symbol": "I_ref_GR1",
        "unit": "ampere",
        "label": "GR1 Reference Current",
        "description": "Group 1 reference current sum from power supply outputs",
    },
    "Courants_Alimentations/Référence_GR2": {
        "formula": "Courants_Alimentations/Référence_GR2 = Référence_A3 + Référence_A4",
        "symbol": "I_ref_GR2",
        "unit": "ampere",
        "label": "GR2 Reference Current",
        "description": "Group 2 reference current sum from power supply outputs",
    },
}

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
    """Infer magnet assembly type from the types of its constituent parts.

    Exactly one coil part type (helix, bitter, or supra) must be present —
    mixed (hybrid) or coil-less assemblies are not supported by the schema.

    Raises
    ------
    ValueError
        If zero or more than one distinct coil part type is found.
    """
    coil_types = {p.get("type") for p in parts if p.get("type") in COIL_TYPES}
    if len(coil_types) != 1:
        raise ValueError(
            "Parts must contain exactly one coil type (helix, bitter, or "
            f"supra); found {sorted(coil_types) or 'none'}. Mixed/hybrid or "
            "coil-less assemblies are not supported."
        )
    return COIL_PART_TO_MAGNET_TYPE[coil_types.pop()].value


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


def view_materials(con, nuance_filter: str | None = None) -> None:
    conditions, params = [], []
    if nuance_filter:
        conditions.append("nuance = ?")
        params.append(nuance_filter)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = con.execute(
        f"SELECT name, nuance, t_ref FROM materials {where} ORDER BY name", params
    ).fetchall()
    if not rows:
        qualifier = f" with nuance '{nuance_filter}'" if nuance_filter else ""
        print(f"No materials{qualifier} in database.")
        return
    print(f"{'Name':<30} {'Nuance':<15} t_ref")
    print("-" * 55)
    for name, nuance, t_ref in rows:
        print(f"{name:<30} {nuance or '?':<15} {t_ref or ''}")


def view_material(con, name: str) -> None:
    row = con.execute(
        "SELECT name, description, nuance, t_ref, volumic_mass, specific_heat, alpha, "
        "electrical_conductivity, thermal_conductivity, magnet_permeability, "
        "young, poisson, expansion_coefficient, rpe "
        "FROM materials WHERE name = ?",
        [name],
    ).fetchone()
    if not row:
        print(f"Material '{name}' not found.")
        return
    labels = [
        "description", "nuance", "t_ref", "volumic_mass", "specific_heat", "alpha",
        "electrical_conductivity", "thermal_conductivity", "magnet_permeability",
        "young", "poisson", "expansion_coefficient", "rpe",
    ]
    print(f"Material: {row[0]}")
    for label, value in zip(labels, row[1:]):
        if value is not None and value != "":
            print(f"  {label:<26}: {value}")


def delete_material(con, name: str) -> None:
    if not exists(con, "materials", name):
        print(f"Material '{name}' not found.")
        return
    ref = con.execute(
        "SELECT name FROM parts WHERE material_name = ? LIMIT 1", [name]
    ).fetchone()
    if ref:
        print(f"Error: material '{name}' is referenced by part '{ref[0]}'. Remove the part first.")
        return
    con.execute("DELETE FROM materials WHERE name = ?", [name])
    print(f"Deleted material '{name}'.")


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
    geometry_data = part.get("geometry_data") or load_geometry_json(part.get("geometry") or part.get("geometry_config"))
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
    geometry_data = data.get("geometry_data") or load_geometry_json(data.get("geometry") or data.get("geometry_config"))
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


def insert_site(
    con, data: dict, verbose: bool = True, create_housing: bool = True
) -> None:
    """Insert a site row; skip silently if it already exists.

    The ``housing`` field in *data* is treated as a ``housing_config.name``
    foreign key.

    Parameters
    ----------
    con:
        Open DuckDB connection.
    data:
        Site dict with at least a ``name`` key.  ``housing`` must match a
        ``housing_config.name`` value.
    verbose:
        Print status lines.
    create_housing:
        When ``True`` (default) and the housing config is not yet in the DB,
        auto-create it from the ``python_magnetrun`` bundled JSON files.  Set
        to ``False`` to raise :exc:`ValueError` instead when the config is
        missing.
    """
    name = data["name"]
    if exists(con, "sites", name):
        if verbose:
            print(f"  ~ site      {name}  (already exists, skipped)")
        return

    housing = data.get("housing") or None
    if housing is not None:
        if con.execute(
            "SELECT 1 FROM housing_config WHERE name = ?", [housing]
        ).fetchone() is None:
            if create_housing:
                insert_housing_config_from_magnetrun(con, housing, verbose=verbose)
            else:
                raise ValueError(
                    f"Housing config '{housing}' not found in housing_config table. "
                    "Call insert_housing_config() first, or pass create_housing=True."
                )

    con.execute(
        "INSERT INTO sites VALUES (?,?,?,?,?,?)",
        [
            name,
            data.get("description") or None,
            data.get("status", "in_study"),
            housing,
            parse_timestamp(data.get("commissioned_at")),
            parse_timestamp(data.get("decommissioned_at")),
        ],
    )
    if verbose:
        print(f"  + site      {name}  [{housing or '?'}]  {data.get('status', '')}")


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
# Geometry-data check helpers
# ---------------------------------------------------------------------------


def check_geometry_data(con, name: str | None = None) -> list[dict]:
    """Return one status dict per magnet (and its parts) describing geometry_data coverage.

    Each dict has the keys:

    ``magnet``
        Magnet name.
    ``magnet_has_geometry``
        True when ``magnets.geometry_data IS NOT NULL``.
    ``parts``
        List of ``{"name": str, "type": str, "has_geometry": bool}`` for every
        linked part, ordered by rank.
    ``parts_ok``
        Number of parts with ``geometry_data IS NOT NULL``.
    ``parts_total``
        Total number of linked parts.

    Parameters
    ----------
    con  : open DuckDB connection
    name : restrict to one magnet; ``None`` checks all magnets
    """
    if name:
        magnet_rows = con.execute(
            "SELECT name, geometry_data IS NOT NULL FROM magnets WHERE name = ?",
            [name],
        ).fetchall()
    else:
        magnet_rows = con.execute(
            "SELECT name, geometry_data IS NOT NULL FROM magnets ORDER BY name"
        ).fetchall()

    results = []
    for magnet_name, magnet_has_geo in magnet_rows:
        part_rows = con.execute(
            """
            SELECT p.name, p.type, p.geometry_data IS NOT NULL
            FROM magnet_parts mp
            JOIN parts p ON p.name = mp.part_name
            WHERE mp.magnet_name = ?
            ORDER BY mp.rank
            """,
            [magnet_name],
        ).fetchall()
        parts = [{"name": pn, "type": pt, "has_geometry": bool(hg)} for pn, pt, hg in part_rows]
        results.append({
            "magnet":              magnet_name,
            "magnet_has_geometry": bool(magnet_has_geo),
            "parts":               parts,
            "parts_ok":            sum(1 for p in parts if p["has_geometry"]),
            "parts_total":         len(parts),
        })
    return results


def print_geometry_check(results: list[dict]) -> None:
    """Print a human-readable geometry_data coverage report."""
    if not results:
        print("No magnets found.")
        return

    for r in results:
        magnet_ok = "✓" if r["magnet_has_geometry"] else "✗"
        parts_ok  = r["parts_ok"]
        parts_tot = r["parts_total"]
        status    = "OK" if r["magnet_has_geometry"] and parts_ok == parts_tot else "INCOMPLETE"
        print(f"[{status}] {r['magnet']}  assembly={magnet_ok}  parts={parts_ok}/{parts_tot}")
        for p in r["parts"]:
            mark = "✓" if p["has_geometry"] else "✗"
            print(f"        {mark} {p['name']}  ({p['type']})")


# ---------------------------------------------------------------------------
# View helpers
# ---------------------------------------------------------------------------


def view_magnets(
    con,
    type_filter: str | None = None,
    status_filter: str | None = None,
) -> None:
    conditions, params = [], []
    if type_filter:
        conditions.append("type = ?")
        params.append(type_filter)
    if status_filter:
        conditions.append("status = ?")
        params.append(status_filter)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = con.execute(
        f"SELECT name, type, status FROM magnets {where} ORDER BY name", params
    ).fetchall()
    if not rows:
        parts = []
        if type_filter:
            parts.append(f"type '{type_filter}'")
        if status_filter:
            parts.append(f"status '{status_filter}'")
        qualifier = " matching " + ", ".join(parts) if parts else ""
        print(f"No magnets{qualifier} in database.")
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


def view_sites(
    con,
    housing_filter: str | None = None,
    status_filter: str | None = None,
) -> None:
    conditions, params = [], []
    if housing_filter:
        conditions.append("housing = ?")
        params.append(housing_filter)
    if status_filter:
        conditions.append("status = ?")
        params.append(status_filter)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = con.execute(
        f"SELECT name, housing, status FROM sites {where} ORDER BY name", params
    ).fetchall()
    if not rows:
        parts = []
        if housing_filter:
            parts.append(f"housing '{housing_filter}'")
        if status_filter:
            parts.append(f"status '{status_filter}'")
        qualifier = " matching " + ", ".join(parts) if parts else ""
        print(f"No sites{qualifier} in database.")
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
# View helpers — housing_config, experiments, operationaldata, overview_records
# ---------------------------------------------------------------------------


def view_housing_configs(con) -> None:
    rows = con.execute(
        "SELECT name, formats FROM housing_config ORDER BY name"
    ).fetchall()
    if not rows:
        print("No housing configs in database.")
        return
    print(f"{'Name':<12} Formats")
    print("-" * 50)
    for name, formats in rows:
        fmts = ", ".join(formats) if formats else "—"
        print(f"{name:<12} {fmts}")


def view_housing_config(con, name: str) -> None:
    row = con.execute(
        "SELECT name, coil_assignment, formats, extra_config "
        "FROM housing_config WHERE name = ?",
        [name],
    ).fetchone()
    if not row:
        print(f"Housing config '{name}' not found.")
        return
    print(f"Housing: {row[0]}")
    print(f"  formats        : {', '.join(row[2]) if row[2] else '—'}")
    assignment = row[1] or {}
    if assignment:
        print("  coil_assignment:")
        for coil, gr in assignment.items():
            print(f"    {coil} → {gr}")
    extra = row[3]
    if extra:
        if isinstance(extra, str):
            extra = json.loads(extra)
        if isinstance(extra, dict):
            for k, v in extra.items():
                print(f"  {k}: {v}")


# SQL fragments for timestamp extraction from file paths (experiments / operationaldata
# have no timestamp column; the timestamp is encoded in the filename).
# Used only when --from / --to filtering is requested.
#
# _EXP_FILE_TS  : pupitre TXT pattern  "YYYY.MM.DD - HH:MM:SS.txt"
# _OD_FILE_TS   : COALESCE of pupitre + TDMS Overview/Archive (%y%m%d) +
#                 TDMS Spike/Default (%y%m%d)
#
# NOTE: these strings reference the table aliases used in their respective queries
# ("e.file" and "od.file").  They must NOT be used in f-string templates directly;
# instead assign to a local variable first so that the regex quantifiers {N} are
# treated as ordinary characters and not as f-string placeholders.
_EXP_FILE_TS = (
    "TRY_STRPTIME("
    "regexp_extract(e.file, '(\\d{4}\\.\\d{2}\\.\\d{2} - \\d{2}:\\d{2}:\\d{2})', 1),"
    " '%Y.%m.%d - %H:%M:%S')"
)

_OD_FILE_TS = (
    "COALESCE("
    "TRY_STRPTIME(regexp_extract(od.file,"
    " '(\\d{4}\\.\\d{2}\\.\\d{2} - \\d{2}:\\d{2}:\\d{2})', 1), '%Y.%m.%d - %H:%M:%S'),"
    " TRY_STRPTIME(regexp_extract(od.file,"
    " '([0-9]{6}-[0-9]{4})\\.tdms$', 1), '%y%m%d-%H%M'),"
    " TRY_STRPTIME(regexp_extract(od.file,"
    " '(?:Spikes|Default)_([0-9]{6}-[0-9]{6})', 1), '%y%m%d-%H%M%S')"
    ")"
)


def view_experiments(
    con,
    site_name: str | None = None,
    magnet_name: str | None = None,
    part_name: str | None = None,
    from_ts: str | None = None,
    to_ts: str | None = None,
) -> None:
    joins, conditions, params = [], [], []

    if site_name:
        conditions.append("e.site_name = ?")
        params.append(site_name)
    if magnet_name or part_name:
        joins.append("JOIN site_magnets sm ON sm.site_name = e.site_name")
        if magnet_name:
            conditions.append("sm.magnet_name = ?")
            params.append(magnet_name)
    if part_name:
        joins.append("JOIN magnet_parts mp ON mp.magnet_name = sm.magnet_name")
        conditions.append("mp.part_name = ?")
        params.append(part_name)

    join_sql = " ".join(joins)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    distinct = "DISTINCT " if (magnet_name or part_name) else ""

    if from_ts or to_ts:
        ts_expr = _EXP_FILE_TS
        ts_conds, ts_params = [], list(params)
        if from_ts:
            ts_conds.append("file_ts >= CAST(? AS TIMESTAMP)")
            ts_params.append(from_ts)
        if to_ts:
            ts_conds.append("file_ts <= CAST(? AS TIMESTAMP)")
            ts_params.append(to_ts)
        ts_where = "WHERE " + " AND ".join(ts_conds)
        rows = con.execute(
            f"SELECT id, name, file, site_name, status FROM ("
            f"SELECT {distinct}e.id, e.name, e.file, e.site_name, e.status,"
            f" {ts_expr} AS file_ts"
            f" FROM experiments e {join_sql} {where}"
            f") t {ts_where} ORDER BY site_name, id",
            ts_params,
        ).fetchall()
    else:
        rows = con.execute(
            f"SELECT {distinct}e.id, e.name, e.file, e.site_name, e.status "
            f"FROM experiments e {join_sql} {where} ORDER BY e.site_name, e.id",
            params,
        ).fetchall()

    labels = []
    if site_name:
        labels.append(f"site={site_name}")
    if magnet_name:
        labels.append(f"magnet={magnet_name}")
    if part_name:
        labels.append(f"part={part_name}")
    if from_ts:
        labels.append(f"from={from_ts}")
    if to_ts:
        labels.append(f"to={to_ts}")
    qualifier = "  " + "  ".join(labels) if labels else ""

    if not rows:
        print(f"No experiments{qualifier.replace('  ', ' for ', 1).replace('  ', ', ')}.")
        return

    print(f"experiments{qualifier}  ({len(rows)} row(s))\n")
    col_s = max((len(r[3] or "") for r in rows), default=20)
    col_f = min(max((len(r[2] or "") for r in rows), default=40), 60)
    print(f"{'ID':<6} {'Site':<{col_s}} {'File':<{col_f}} Status")
    print("-" * (col_s + col_f + 14))
    for id_, name, file_, site_, status in rows:
        print(f"{id_:<6} {(site_ or ''):<{col_s}} {(file_ or '')[:col_f]:<{col_f}} {status or ''}")


def view_operationaldata(
    con,
    site_name: str | None = None,
    type_filter: str | None = None,
    magnet_name: str | None = None,
    part_name: str | None = None,
    from_ts: str | None = None,
    to_ts: str | None = None,
) -> None:
    joins, conditions, params = [], [], []

    if site_name:
        conditions.append("od.site_name = ?")
        params.append(site_name)
    if type_filter:
        conditions.append("od.type = ?")
        params.append(type_filter)
    if magnet_name or part_name:
        joins.append("JOIN site_magnets sm ON sm.site_name = od.site_name")
        if magnet_name:
            conditions.append("sm.magnet_name = ?")
            params.append(magnet_name)
    if part_name:
        joins.append("JOIN magnet_parts mp ON mp.magnet_name = sm.magnet_name")
        conditions.append("mp.part_name = ?")
        params.append(part_name)

    join_sql = " ".join(joins)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    distinct = "DISTINCT " if (magnet_name or part_name) else ""

    if from_ts or to_ts:
        ts_expr = _OD_FILE_TS
        ts_conds, ts_params = [], list(params)
        if from_ts:
            ts_conds.append("file_ts >= CAST(? AS TIMESTAMP)")
            ts_params.append(from_ts)
        if to_ts:
            ts_conds.append("file_ts <= CAST(? AS TIMESTAMP)")
            ts_params.append(to_ts)
        ts_where = "WHERE " + " AND ".join(ts_conds)
        rows = con.execute(
            f"SELECT id, name, file, type, site_name, status FROM ("
            f"SELECT {distinct}od.id, od.name, od.file, od.type, od.site_name, od.status,"
            f" {ts_expr} AS file_ts"
            f" FROM operationaldata od {join_sql} {where}"
            f") t {ts_where} ORDER BY site_name, type, id",
            ts_params,
        ).fetchall()
    else:
        rows = con.execute(
            f"SELECT {distinct}od.id, od.name, od.file, od.type, od.site_name, od.status "
            f"FROM operationaldata od {join_sql} {where} ORDER BY od.site_name, od.type, od.id",
            params,
        ).fetchall()

    labels = []
    if site_name:
        labels.append(f"site={site_name}")
    if type_filter:
        labels.append(f"type={type_filter}")
    if magnet_name:
        labels.append(f"magnet={magnet_name}")
    if part_name:
        labels.append(f"part={part_name}")
    if from_ts:
        labels.append(f"from={from_ts}")
    if to_ts:
        labels.append(f"to={to_ts}")
    qualifier = "  " + "  ".join(labels) if labels else ""

    if not rows:
        print(f"No operationaldata{qualifier.replace('  ', ' for ', 1).replace('  ', ', ')}.")
        return

    print(f"operationaldata{qualifier}  ({len(rows)} row(s))\n")
    col_s = max((len(r[4] or "") for r in rows), default=20)
    col_t = max((len(r[3] or "") for r in rows), default=10)
    col_f = min(max((len(r[2] or "") for r in rows), default=40), 60)
    print(f"{'ID':<6} {'Site':<{col_s}} {'Type':<{col_t}} {'File':<{col_f}} Status")
    print("-" * (col_s + col_t + col_f + 16))
    for id_, name, file_, type_, site_, status in rows:
        print(f"{id_:<6} {(site_ or ''):<{col_s}} {(type_ or ''):<{col_t}} {(file_ or '')[:col_f]:<{col_f}} {status or ''}")


def _duration_str(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def view_overview_records(
    con,
    site_name: str | None = None,
    show_signatures: bool = False,
    magnet_name: str | None = None,
    part_name: str | None = None,
    from_ts: str | None = None,
    to_ts: str | None = None,
) -> None:
    joins, conditions, params = [], [], []

    if site_name:
        conditions.append("ovr.site_name = ?")
        params.append(site_name)
    if magnet_name or part_name:
        joins.append("JOIN site_magnets sm ON sm.site_name = ovr.site_name")
        if magnet_name:
            conditions.append("sm.magnet_name = ?")
            params.append(magnet_name)
    if part_name:
        joins.append("JOIN magnet_parts mp ON mp.magnet_name = sm.magnet_name")
        conditions.append("mp.part_name = ?")
        params.append(part_name)
    if from_ts:
        conditions.append("ovr.t0 >= CAST(? AS TIMESTAMP)")
        params.append(from_ts)
    if to_ts:
        conditions.append("ovr.t0 <= CAST(? AS TIMESTAMP)")
        params.append(to_ts)

    join_sql = " ".join(joins)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    distinct = "DISTINCT " if (magnet_name or part_name) else ""

    rows = con.execute(
        f"SELECT {distinct}ovr.filename, ovr.housing, ovr.mode, ovr.t0, ovr.duration, ovr.teb, ovr.bp, "
        f"len(ovr.sources_overview) + len(ovr.sources_archive) + len(ovr.sources_pupitre) "
        f"+ len(ovr.sources_default) + len(ovr.sources_trigger) + len(ovr.sources_spike) "
        f"+ len(ovr.sources_hybrid_kHz) + len(ovr.sources_hybrid_rms) + len(ovr.sources_hybrid_trigger) "
        f"  AS n_sources, "
        f"ovr.signatures, ovr.sync_info "
        f"FROM overview_records ovr {join_sql} {where} ORDER BY ovr.t0 NULLS LAST, ovr.filename",
        params,
    ).fetchall()

    labels = []
    if site_name:
        labels.append(f"site={site_name}")
    if magnet_name:
        labels.append(f"magnet={magnet_name}")
    if part_name:
        labels.append(f"part={part_name}")
    if from_ts:
        labels.append(f"from={from_ts}")
    if to_ts:
        labels.append(f"to={to_ts}")
    qualifier = "  " + "  ".join(labels) if labels else ""

    if not rows:
        print(f"No overview_records{qualifier.replace('  ', ' for ', 1).replace('  ', ', ')}.")
        return

    print(f"overview_records{qualifier}  ({len(rows)} row(s))\n")

    col_f = max((len(r[0]) for r in rows), default=20)
    col_m = max((len(r[2] or "") for r in rows), default=4)
    print(
        f"{'Filename':<{col_f}}  {'t0':<19}  {'Duration':<8}  {'Mode':<{col_m}}  teb    bp   n_src"
    )
    print("-" * (col_f + col_m + 65))

    for filename, housing, mode, t0, duration, teb, bp, n_src, sigs, sync in rows:
        t0_str = str(t0)[:19] if t0 else "—"
        dur_str = _duration_str(duration)
        print(
            f"{filename:<{col_f}}  {t0_str:<19}  {dur_str:<8}  {(mode or ''):<{col_m}}"
            f"  {teb or 0:5.1f}  {bp or 0:5.1f}  {n_src or 0}"
        )

        if show_signatures and sigs:
            if isinstance(sigs, str):
                sigs = json.loads(sigs)
            if isinstance(sigs, dict):
                for key, vals in sigs.items():
                    mn = vals.get("min", float("nan"))
                    mx = vals.get("max", float("nan"))
                    avg = vals.get("mean", float("nan"))
                    print(f"    {key}: min={mn:.2f}  max={mx:.2f}  mean={avg:.2f}")
            if sync:
                if isinstance(sync, str):
                    sync = json.loads(sync)
                ts = sync.get("timeshift_seconds") if isinstance(sync, dict) else None
                if ts is not None:
                    print(f"    sync timeshift: {ts:.3f} s")


# ---------------------------------------------------------------------------
# Delete helpers
# ---------------------------------------------------------------------------


def list_objects(con) -> dict[str, list[str]]:
    """Return a dict mapping each entity type to its sorted list of names."""
    return {
        "materials": [r[0] for r in con.execute("SELECT name FROM materials ORDER BY name").fetchall()],
        "magnets":   [r[0] for r in con.execute("SELECT name FROM magnets ORDER BY name").fetchall()],
        "sites":     [r[0] for r in con.execute("SELECT name FROM sites ORDER BY name").fetchall()],
        "housings":  [r[0] for r in con.execute("SELECT name FROM housing_config ORDER BY name").fetchall()],
    }


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


# ---------------------------------------------------------------------------
# Housing config
# ---------------------------------------------------------------------------


def _derive_housing_config_dict(
    name: str,
    coil_assignment: dict[str, str],
    formats: list[str],
    extra_config: dict | None,
) -> dict[str, Any]:
    """Derive a full housing-config dict from a ``coil_assignment`` mapping.

    Parameters
    ----------
    name:
        Housing identifier, e.g. ``"M9"``.
    coil_assignment:
        ``{"Insert": "GR1", "Bitter": "GR2"}`` or vice-versa.
    formats:
        List of supported format names (``"pupitre"``, ``"pigbrother"``, …).
    extra_config:
        Optional dict of extra/override fields stored verbatim (hybrid fields
        for M8: ``reference_gr{1,2}_hybrid``, ``hybrid_formula_map``, …).

    Returns
    -------
    dict
        Ready to serialise as ``<name>-housing-config.json``.
    """
    gr_to_coil = {gr: coil for coil, gr in coil_assignment.items()}
    gr1_coil = gr_to_coil["GR1"]
    gr2_coil = gr_to_coil["GR2"]
    s1 = _COIL_TO_SUFFIX[gr1_coil]
    s2 = _COIL_TO_SUFFIX[gr2_coil]

    gr1_ucoils = _H_UCOILS if gr1_coil == "Insert" else _B_UCOILS
    gr2_ucoils = _H_UCOILS if gr2_coil == "Insert" else _B_UCOILS

    label1 = "Upper Coil Current" if s1 == "H" else "Lower Coil Current"
    label2 = "Upper Coil Current" if s2 == "H" else "Lower Coil Current"
    desc1 = f"{'Upper' if s1 == 'H' else 'Lower'} coil current sum from DCCT sensors"
    desc2 = f"{'Upper' if s2 == 'H' else 'Lower'} coil current sum from DCCT sensors"

    pupitre_formula_map = {
        f"I{s1}": {
            "formula": f"I{s1} = Idcct1 + Idcct2",
            "symbol": f"I_{s1}",
            "unit": "ampere",
            "label": label1,
            "description": desc1,
        },
        f"I{s2}": {
            "formula": f"I{s2} = Idcct3 + Idcct4",
            "symbol": f"I_{s2}",
            "unit": "ampere",
            "label": label2,
            "description": desc2,
        },
    }

    cfg: dict[str, Any] = {
        "name": name,
        "formats": formats,
        "reference_gr1_current": f"I{s1}",
        "reference_gr2_current": f"I{s2}",
        "reference_gr1_flow": f"Flow{s1}",
        "reference_gr2_flow": f"Flow{s2}",
        "reference_gr1_rpm": f"Rpm{s1}",
        "reference_gr2_rpm": f"Rpm{s2}",
        "reference_gr1_pin": f"HP{s1}",
        "reference_gr2_pin": f"HP{s2}",
        "voltage_channels_gr1": gr1_ucoils,
        "voltage_channels_gr2": gr2_ucoils,
        "reference_gr1_voltage": f"U{s1}",
        "reference_gr2_voltage": f"U{s2}",
        "pupitre_formula_map": pupitre_formula_map,
        "pigbrother_formula_map": (
            _PIGBROTHER_FORMULA_MAP if "pigbrother" in formats else {}
        ),
        "hybrid_formula_map": {},
        "hybrid_voltage_mask_map": {},
    }

    if extra_config:
        cfg.update(extra_config)

    return cfg


def _housing_config_data_from_magnetrun(housing_name: str) -> dict:
    """Load and convert a bundled python_magnetrun housing config to DB insert format.

    Uses ``python_magnetrun.housing_config.get_bundled_housing_config_path`` to
    locate the JSON file for *housing_name* (e.g. ``"M8"``, ``"M9"``, ``"M10"``),
    then derives the compact ``coil_assignment`` from the ``reference_gr1_current``
    field (suffix ``"H"`` → Insert, ``"B"`` → Bitter).

    Raises
    ------
    ImportError
        If ``python_magnetrun`` is not installed.
    ValueError
        If no bundled JSON exists for *housing_name* or the suffix cannot be
        mapped to a coil type.
    """
    try:
        from python_magnetrun.housing_config import get_bundled_housing_config_path
    except ImportError as exc:
        raise ImportError(
            "python_magnetrun is not installed — cannot auto-create housing config."
        ) from exc

    json_path = get_bundled_housing_config_path(housing_name)
    if not json_path.exists():
        raise ValueError(
            f"No bundled housing config for '{housing_name}' in python_magnetrun. "
            f"Expected: {json_path}"
        )

    raw = json.loads(json_path.read_text(encoding="utf-8"))

    gr1_current = raw.get("reference_gr1_current", "")
    suffix = gr1_current[-1] if gr1_current else ""
    gr1_coil = _SUFFIX_TO_COIL.get(suffix)
    if gr1_coil is None:
        raise ValueError(
            f"Cannot infer coil_assignment for '{housing_name}': "
            f"reference_gr1_current={gr1_current!r} has unknown suffix {suffix!r}. "
            f"Expected one of {list(_SUFFIX_TO_COIL)}"
        )
    gr2_coil = "Bitter" if gr1_coil == "Insert" else "Insert"

    extra: dict = {}
    for key in (
        "reference_gr1_hybrid",
        "reference_gr2_hybrid",
        "hybrid_formula_map",
        "hybrid_voltage_mask_map",
    ):
        val = raw.get(key)
        if val:
            extra[key] = val

    return {
        "name": housing_name,
        "coil_assignment": {gr1_coil: "GR1", gr2_coil: "GR2"},
        "formats": list(raw.get("formats", [])),
        "extra_config": extra or None,
    }


def insert_housing_config_from_magnetrun(
    con, housing_name: str, verbose: bool = True
) -> None:
    """Insert a housing_config row loaded from the python_magnetrun bundled JSON.

    This is the preferred way to populate M8, M9, and M10 configs: the JSON
    files inside the ``python_magnetrun`` package are the authoritative source.
    The function is idempotent — it skips silently if the row already exists.

    Parameters
    ----------
    con:
        Open DuckDB connection.
    housing_name:
        Housing identifier matching a bundled JSON, e.g. ``"M9"``.
    verbose:
        Print a status line when inserting.

    Raises
    ------
    ImportError
        If ``python_magnetrun`` is not installed.
    ValueError
        If no bundled JSON is found for *housing_name*.
    """
    if exists(con, "housing_config", housing_name):
        if verbose:
            print(f"  ~ housing_config  {housing_name}  (already exists, skipped)")
        return
    data = _housing_config_data_from_magnetrun(housing_name)
    insert_housing_config(con, data, verbose=verbose)


def insert_housing_config(con, data: dict, verbose: bool = True) -> None:
    """Insert or replace a housing_config row.

    Parameters
    ----------
    data:
        Dict with keys:

        - ``name`` (str) — housing identifier, e.g. ``"M9"``
        - ``coil_assignment`` (dict) — ``{"Insert": "GR1", "Bitter": "GR2"}``
        - ``formats`` (list[str]) — e.g. ``["pupitre", "pigbrother"]``
        - ``extra_config`` (dict | None) — optional hybrid/override fields
    """
    name = data["name"]
    con.execute(
        """
        INSERT OR REPLACE INTO housing_config
            (name, coil_assignment, formats, extra_config)
        VALUES (?, ?, ?, ?)
        """,
        [
            name,
            data["coil_assignment"],
            data["formats"],
            json.dumps(data["extra_config"]) if data.get("extra_config") else None,
        ],
    )
    if verbose:
        print(f"  + housing_config  {name}  {data['coil_assignment']}")


def export_housing_config_json(
    con, name: str, output_dir: str | Path = "."
) -> Path:
    """Write ``<output_dir>/<name>-housing-config.json`` from the DB row.

    Returns the path of the written file.
    Raises ``ValueError`` if no row for *name* exists in the table.
    """
    row = con.execute(
        "SELECT coil_assignment, formats, extra_config FROM housing_config WHERE name = ?",
        [name],
    ).fetchone()
    if row is None:
        raise ValueError(f"No housing_config row found for {name!r}")

    coil_assignment, formats, extra_config_raw = row
    extra_config = json.loads(extra_config_raw) if extra_config_raw else None

    cfg_dict = _derive_housing_config_dict(
        name, dict(coil_assignment), list(formats), extra_config
    )

    dest = Path(output_dir) / f"{name}-housing-config.json"
    with open(dest, "w") as fh:
        json.dump(cfg_dict, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(f"  Wrote {dest}")
    return dest


# ---------------------------------------------------------------------------
# Overview record
# ---------------------------------------------------------------------------


def _fileset_lists(sources) -> dict[str, list[str]]:
    """Extract FileSet field lists, returning empty lists for None sources."""
    if sources is None:
        empty: list[str] = []
        return {k: empty for k in (
            "overview", "archive", "pupitre", "default", "trigger", "spike",
            "hybrid_kHz", "hybrid_rms", "hybrid_trigger", "hybrid_vprocess",
            "pigbrother_runlog", "pupitre_runlog",
        )}
    return {
        "overview":           list(getattr(sources, "overview", []) or []),
        "archive":            list(getattr(sources, "archive", []) or []),
        "pupitre":            list(getattr(sources, "pupitre", []) or []),
        "default":            list(getattr(sources, "default", []) or []),
        "trigger":            list(getattr(sources, "trigger", []) or []),
        "spike":              list(getattr(sources, "spike", []) or []),
        "hybrid_kHz":         list(getattr(sources, "hybrid_kHz", []) or []),
        "hybrid_rms":         list(getattr(sources, "hybrid_rms", []) or []),
        "hybrid_trigger":     list(getattr(sources, "hybrid_trigger", []) or []),
        "hybrid_vprocess":    list(getattr(sources, "hybrid_vprocess", []) or []),
        "pigbrother_runlog":  list(getattr(sources, "pigbrother_runlog", []) or []),
        "pupitre_runlog":     list(getattr(sources, "pupitre_runlog", []) or []),
    }


def insert_overview_record(
    con, record, site_name: str | None = None, verbose: bool = True
) -> None:
    """Insert an OverviewRecord row; skip silently if filename already exists.

    Parameters
    ----------
    con:
        Open DuckDB connection.
    record:
        An ``OverviewRecord`` dataclass instance (``data`` attribute is ignored).
    site_name:
        Site name FK (references ``sites.name``).  Pass ``None`` to leave unset.
    verbose:
        Print a status line when inserting.
    """
    filename = record.filename
    if con.execute(
        "SELECT 1 FROM overview_records WHERE filename = ?", [filename]
    ).fetchone():
        if verbose:
            print(f"  ~ overview_record  {filename}  (already exists, skipped)")
        return

    src = _fileset_lists(record.sources)
    t0 = str(record.t0) if record.t0 is not None else None

    con.execute(
        """
        INSERT INTO overview_records (
            filename, site_name, housing, mode, t0, duration, teb, bp,
            sources_overview, sources_archive, sources_pupitre,
            sources_default, sources_trigger, sources_spike,
            sources_hybrid_kHz, sources_hybrid_rms, sources_hybrid_trigger,
            sources_hybrid_vprocess, sources_pigbrother_runlog, sources_pupitre_runlog,
            signatures, sync_info, flow_params, metrics, debitbrut
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        [
            filename,
            site_name,
            record.housing,
            record.mode or None,
            t0,
            float(record.duration),
            float(record.teb),
            float(record.BP),
            src["overview"],
            src["archive"],
            src["pupitre"],
            src["default"],
            src["trigger"],
            src["spike"],
            src["hybrid_kHz"],
            src["hybrid_rms"],
            src["hybrid_trigger"],
            src["hybrid_vprocess"],
            src["pigbrother_runlog"],
            src["pupitre_runlog"],
            json.dumps(record.signatures),
            json.dumps(record.sync_info),
            json.dumps(record.flow_params),
            json.dumps(record.metrics),
            json.dumps(record.debitbrut),
        ],
    )
    if verbose:
        print(f"  + overview_record  {filename}  [{record.housing}]  duration={record.duration:.1f}s")


def upsert_overview_record(
    con, record, site_name: str | None = None, verbose: bool = True
) -> None:
    """Insert or replace an OverviewRecord row (idempotent re-processing).

    Parameters
    ----------
    con:
        Open DuckDB connection.
    record:
        An ``OverviewRecord`` dataclass instance (``data`` attribute is ignored).
    site_name:
        Site name FK (references ``sites.name``).  Pass ``None`` to leave unset.
    verbose:
        Print a status line when upserting.
    """
    src = _fileset_lists(record.sources)
    t0 = str(record.t0) if record.t0 is not None else None

    con.execute(
        """
        INSERT OR REPLACE INTO overview_records (
            filename, site_name, housing, mode, t0, duration, teb, bp,
            sources_overview, sources_archive, sources_pupitre,
            sources_default, sources_trigger, sources_spike,
            sources_hybrid_kHz, sources_hybrid_rms, sources_hybrid_trigger,
            sources_hybrid_vprocess, sources_pigbrother_runlog, sources_pupitre_runlog,
            signatures, sync_info, flow_params, metrics, debitbrut
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        [
            record.filename,
            site_name,
            record.housing,
            record.mode or None,
            t0,
            float(record.duration),
            float(record.teb),
            float(record.BP),
            src["overview"],
            src["archive"],
            src["pupitre"],
            src["default"],
            src["trigger"],
            src["spike"],
            src["hybrid_kHz"],
            src["hybrid_rms"],
            src["hybrid_trigger"],
            src["hybrid_vprocess"],
            src["pigbrother_runlog"],
            src["pupitre_runlog"],
            json.dumps(record.signatures),
            json.dumps(record.sync_info),
            json.dumps(record.flow_params),
            json.dumps(record.metrics),
            json.dumps(record.debitbrut),
        ],
    )
    if verbose:
        print(f"  ~ overview_record  {record.filename}  [{record.housing}]  (upserted)")


def insert_overview_record_from_dict(
    con, data: dict, site_name: str | None = None, verbose: bool = True, upsert: bool = False
) -> None:
    """Insert (or upsert) an overview_record row from a plain dict.

    Accepts the dict format produced by ``find_site_overview_records --json``,
    the pandas-records JSON written by ``magnetrun analysis/cli.py``, or any
    dict whose keys match the ``overview_records`` table columns.

    Source lists may be given as Python ``list[str]`` **or** as a
    comma-separated string (as written by ``cli.py``).  Both the canonical
    ``sources_<key>`` column names and the short ``<key>`` aliases used by
    ``cli.py`` are accepted (e.g. ``sources_overview`` or ``overview``).

    Parameters
    ----------
    con:
        Open DuckDB connection.
    data:
        Dict representing one overview record.  ``filename`` is required.
    site_name:
        Site name FK.  If *data* already contains ``site_name`` that value
        is used; this argument takes precedence when not ``None``.
    verbose:
        Print a status line.
    upsert:
        If ``True`` use ``INSERT OR REPLACE``; otherwise skip duplicates.
    """
    filename = data.get("filename")
    if not filename:
        raise ValueError("Record dict is missing required key 'filename'")

    def _to_list(v) -> list[str]:
        if v is None:
            return []
        if isinstance(v, list):
            return [str(x) for x in v if x]
        return [x.strip() for x in str(v).split(",") if x.strip()]

    _source_keys = [
        "overview", "archive", "pupitre", "default", "trigger", "spike",
        "hybrid_kHz", "hybrid_rms", "hybrid_trigger", "hybrid_vprocess",
        "pigbrother_runlog", "pupitre_runlog",
    ]

    def _get_sources(key: str) -> list[str]:
        return _to_list(data.get(f"sources_{key}", data.get(key)))

    def _json_field(key: str) -> str:
        v = data.get(key, {})
        if isinstance(v, (dict, list)):
            return json.dumps(v)
        return v if isinstance(v, str) else "{}"

    t0_raw = data.get("t0")
    t0 = str(t0_raw) if t0_raw is not None else None

    effective_site = site_name if site_name is not None else data.get("site_name")
    bp = float(data.get("bp", data.get("BP", 0.0)) or 0.0)

    row = [
        filename,
        effective_site,
        data.get("housing") or None,
        data.get("mode") or None,
        t0,
        float(data.get("duration") or 0.0),
        float(data.get("teb") or 0.0),
        bp,
        _get_sources("overview"),
        _get_sources("archive"),
        _get_sources("pupitre"),
        _get_sources("default"),
        _get_sources("trigger"),
        _get_sources("spike"),
        _get_sources("hybrid_kHz"),
        _get_sources("hybrid_rms"),
        _get_sources("hybrid_trigger"),
        _get_sources("hybrid_vprocess"),
        _get_sources("pigbrother_runlog"),
        _get_sources("pupitre_runlog"),
        _json_field("signatures"),
        _json_field("sync_info"),
        _json_field("flow_params"),
        _json_field("metrics"),
        _json_field("debitbrut"),
    ]

    if upsert:
        con.execute(
            """
            INSERT OR REPLACE INTO overview_records (
                filename, site_name, housing, mode, t0, duration, teb, bp,
                sources_overview, sources_archive, sources_pupitre,
                sources_default, sources_trigger, sources_spike,
                sources_hybrid_kHz, sources_hybrid_rms, sources_hybrid_trigger,
                sources_hybrid_vprocess, sources_pigbrother_runlog, sources_pupitre_runlog,
                signatures, sync_info, flow_params, metrics, debitbrut
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            row,
        )
        if verbose:
            housing = data.get("housing", "?")
            print(f"  ~ overview_record  {filename}  [{housing}]  (upserted)")
    else:
        if con.execute(
            "SELECT 1 FROM overview_records WHERE filename = ?", [filename]
        ).fetchone():
            if verbose:
                print(f"  ~ overview_record  {filename}  (already exists, skipped)")
            return
        con.execute(
            """
            INSERT INTO overview_records (
                filename, site_name, housing, mode, t0, duration, teb, bp,
                sources_overview, sources_archive, sources_pupitre,
                sources_default, sources_trigger, sources_spike,
                sources_hybrid_kHz, sources_hybrid_rms, sources_hybrid_trigger,
                sources_hybrid_vprocess, sources_pigbrother_runlog, sources_pupitre_runlog,
                signatures, sync_info, flow_params, metrics, debitbrut
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            row,
        )
        if verbose:
            housing = data.get("housing", "?")
            dur = float(data.get("duration") or 0.0)
            print(f"  + overview_record  {filename}  [{housing}]  duration={dur:.1f}s")


def attach_site_to_overview_record(
    con, filename: str, site_name: str, verbose: bool = True
) -> None:
    """Set or overwrite site_name and housing on an existing overview_record row.

    The housing value is taken from sites.housing for the given site_name.

    Parameters
    ----------
    con:
        Open DuckDB connection.
    filename:
        Primary key of the overview_records row (basename without extension).
    site_name:
        Site name to attach (must exist in the sites table).
    verbose:
        Print a status line on success.

    Raises
    ------
    ValueError
        If *filename* is not found in overview_records, or *site_name* is not
        found in sites.
    """
    if con.execute(
        "SELECT 1 FROM overview_records WHERE filename = ?", [filename]
    ).fetchone() is None:
        raise ValueError(f"No overview_record found for filename '{filename}'")

    row = con.execute(
        "SELECT housing FROM sites WHERE name = ?", [site_name]
    ).fetchone()
    if row is None:
        raise ValueError(f"No site found for site_name '{site_name}'")
    housing = row[0]

    con.execute(
        "UPDATE overview_records SET site_name = ?, housing = ? WHERE filename = ?",
        [site_name, housing, filename],
    )
    if verbose:
        print(f"  ~ overview_record  {filename}  site_name → {site_name}  housing → {housing}")


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
