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
insert_assembly(con, data, verbose, create_housing)
decommission_assembly(con, name, decommissioned_at, description, attachments, verbose)
insert_housing_config_from_magnetrun(con, housing_name, verbose)
insert_assembly_magnets(con, assembly_name, magnet_entries, verbose)
insert_experiments(con, assembly_name, records, verbose)

update_part_status(con, name, status, description, changed_at, attachments, verbose)
update_magnet_status(con, name, status, description, changed_at, attachments, dead_parts, verbose)
update_part_from_json(con, data, dry_run, verbose)
update_magnet_from_json(con, data, dry_run, verbose)
update_assembly_from_json(con, data, dry_run, verbose)

view_parts(con, type_filter, status_filter)
view_part(con, name)

update_assembly_magnet(con, assembly_name, magnet_name, **kwargs)

insert_overview_record(con, record, assembly_name, verbose)
upsert_overview_record(con, record, assembly_name, verbose)
insert_overview_record_from_dict(con, data, assembly_name, verbose, upsert)
attach_assembly_to_overview_record(con, filename, assembly_name, verbose)
infer_overview_record_fields(con, filename, db_tz, verbose)
infer_operating_mode(df)
"""

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from enums import COIL_PART_TO_MAGNET_TYPE, AssemblyStatus, LifecycleStatus
from populate import FILE_TZ, as_aware
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


def _valid_lifecycle_status(status: str) -> str:
    """Validate *status* against :class:`~enums.LifecycleStatus`; returns it unchanged."""
    valid = {s.value for s in LifecycleStatus}
    if status not in valid:
        raise ValueError(f"Invalid status '{status}'; must be one of {sorted(valid)}.")
    return status


def _append_status_history(
    con,
    table: str,
    name: str,
    status: str,
    description: str = "",
    changed_at=None,
    attachments: list[dict] | None = None,
) -> None:
    """Append one event to *table*.status_history for the row named *name*.

    *table* must be one of ``"parts"``, ``"magnets"``, ``"assemblies"`` (all
    three carry a ``status_history JSON`` column with the same shape).
    """
    event = {
        "status": status,
        "date": parse_timestamp(changed_at) or datetime.now().isoformat(),
        "description": description or "",
        "attachments": attachments or [],
    }
    row = con.execute(f"SELECT status_history FROM {table} WHERE name = ?", [name]).fetchone()
    history = json.loads(row[0]) if row and row[0] else []
    history.append(event)
    con.execute(f"UPDATE {table} SET status_history = ? WHERE name = ?", [json.dumps(history), name])


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
    status = _valid_lifecycle_status(part.get("status") or LifecycleStatus.IN_STOCK.value)
    con.execute(
        """
        INSERT INTO parts
            (name, type, status, material_name, geometry, geometry_data, cad, design_office_reference, manufactured_at)
        VALUES (?,?,?,?,?,?,?,?,?)
        """,
        [
            name,
            part.get("type"),
            status,
            material_name,
            part.get("geometry") or None,
            geometry_data,
            part.get("cad") or None,
            part.get("design_office_reference") or None,
            manufactured_at_from_name(name),
        ],
    )
    if verbose:
        print(f"  + part      {name}  [{part.get('type', '?')}]  {status}")


def update_part_from_json(con, data: dict, dry_run: bool = False, verbose: bool = True) -> None:
    """Refresh a part's descriptive/geometry fields from a JSON payload.

    Only keys present in *data* are written; a key absent from *data* leaves
    the corresponding column untouched — this is a partial refresh, not a
    full re-sync. ``name``, ``type``, ``status``, and ``status_history`` are
    never touched here; see :func:`update_part_status` for lifecycle changes.

    Parameters
    ----------
    con:
        Open DuckDB connection.
    data:
        Part dict; only ``material_name``/``material.name``, ``geometry``,
        ``geometry_data``, ``cad``, and ``design_office_reference`` are
        consulted. ``geometry_data`` is recomputed via
        :func:`load_geometry_json` when ``geometry``/``geometry_config`` is
        present but ``geometry_data`` itself is not.
    dry_run:
        When ``True``, report which fields would change without writing.
    verbose:
        Print status lines.

    Raises
    ------
    ValueError
        If the part is not found, or *data* sets ``material_name`` to a name
        not present in ``materials``.
    """
    name = data["name"]
    if not exists(con, "parts", name):
        raise ValueError(f"Part '{name}' not found in DB — nothing to update.")

    fields: dict = {}
    if "material_name" in data or "material" in data:
        material_name = data.get("material_name") or (data.get("material") or {}).get("name")
        if material_name and con.execute(
            "SELECT 1 FROM materials WHERE name = ?", [material_name]
        ).fetchone() is None:
            raise ValueError(
                f"Material '{material_name}' not found — add it with "
                "'material add' first, or fix the JSON."
            )
        fields["material_name"] = material_name
    if "geometry" in data:
        fields["geometry"] = data.get("geometry") or None
    if "geometry_data" in data:
        fields["geometry_data"] = data.get("geometry_data") or None
    elif "geometry" in data or "geometry_config" in data:
        fields["geometry_data"] = load_geometry_json(data.get("geometry") or data.get("geometry_config"))
    if "cad" in data:
        fields["cad"] = data.get("cad") or None
    if "design_office_reference" in data:
        fields["design_office_reference"] = data.get("design_office_reference") or None

    if not fields:
        if verbose:
            print(f"  ~ part      {name}  (no descriptive fields in JSON, nothing to update)")
        return

    if dry_run:
        if verbose:
            print(f"[dry-run] part '{name}': would update {', '.join(fields)}")
        return

    set_clause = ", ".join(f"{col} = ?" for col in fields)
    con.execute(f"UPDATE parts SET {set_clause} WHERE name = ?", [*fields.values(), name])
    if verbose:
        print(f"  ~ part      {name}  updated: {', '.join(fields)}")


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
    status = _valid_lifecycle_status(data.get("status") or LifecycleStatus.IN_STOCK.value)
    con.execute(
        """
        INSERT INTO magnets
            (name, type, status, geometry, geometry_data, design_office_reference, assembled_at)
        VALUES (?,?,?,?,?,?,?)
        """,
        [
            name,
            magnet_type,
            status,
            data.get("geometry") or None,
            geometry_data,
            data.get("design_office_reference") or None,
            assembled_at_from_name(name),
        ],
    )
    if verbose:
        print(f"  + magnet    {name}  [{magnet_type}]  {status}")


def update_magnet_from_json(con, data: dict, dry_run: bool = False, verbose: bool = True) -> None:
    """Refresh a magnet's descriptive/geometry fields from a JSON payload.

    Only keys present in *data* are written; a key absent from *data* leaves
    the corresponding column untouched — this is a partial refresh, not a
    full re-sync. ``name``, ``type``, ``status``, ``status_history``, and
    linked ``parts`` are never touched here; see :func:`update_magnet_status`
    for lifecycle changes.

    Parameters
    ----------
    con:
        Open DuckDB connection.
    data:
        Magnet dict; only ``geometry``, ``geometry_data``, and
        ``design_office_reference`` are consulted. ``geometry_data`` is
        recomputed via :func:`load_geometry_json` when
        ``geometry``/``geometry_config`` is present but ``geometry_data``
        itself is not.
    dry_run:
        When ``True``, report which fields would change without writing.
    verbose:
        Print status lines.

    Raises
    ------
    ValueError
        If the magnet is not found.
    """
    name = data["name"]
    if not exists(con, "magnets", name):
        raise ValueError(f"Magnet '{name}' not found in DB — nothing to update.")

    fields: dict = {}
    if "geometry" in data:
        fields["geometry"] = data.get("geometry") or None
    if "geometry_data" in data:
        fields["geometry_data"] = data.get("geometry_data") or None
    elif "geometry" in data or "geometry_config" in data:
        fields["geometry_data"] = load_geometry_json(data.get("geometry") or data.get("geometry_config"))
    if "design_office_reference" in data:
        fields["design_office_reference"] = data.get("design_office_reference") or None

    if not fields:
        if verbose:
            print(f"  ~ magnet    {name}  (no descriptive fields in JSON, nothing to update)")
        return

    if dry_run:
        if verbose:
            print(f"[dry-run] magnet '{name}': would update {', '.join(fields)}")
        return

    set_clause = ", ".join(f"{col} = ?" for col in fields)
    con.execute(f"UPDATE magnets SET {set_clause} WHERE name = ?", [*fields.values(), name])
    if verbose:
        print(f"  ~ magnet    {name}  updated: {', '.join(fields)}")


def _reclaim_reused_parts(con, new_magnet_name: str, part_names: list[str], verbose: bool = True) -> None:
    """Retire whichever still-active magnet(s) currently hold *part_names*
    and close their open assembly link(s), freeing the parts for reuse by
    *new_magnet_name*.

    "Currently hold" is determined from ``magnet_parts`` history joined to
    ``magnets.status`` (not a part's own ``status`` field), since a part can
    accumulate rows across every magnet it's ever belonged to. A part with
    no such active holder is left untouched — the caller's own in-stock
    check then raises for that case, same as before this function existed.
    An old magnet's already-closed assembly link (explicit
    ``decommissioned_at``) is never reopened or overridden.
    """
    retire_at = _fallback_decommission_at(assembled_at_from_name(new_magnet_name))

    old_magnets: dict[str, None] = {}
    for part_name in part_names:
        rows = con.execute(
            "SELECT DISTINCT mp.magnet_name FROM magnet_parts mp "
            "JOIN magnets m ON m.name = mp.magnet_name "
            "WHERE mp.part_name = ? AND mp.magnet_name != ? "
            "AND m.status NOT IN (?, ?)",
            [part_name, new_magnet_name, LifecycleStatus.RETIRED.value, LifecycleStatus.DEAD.value],
        ).fetchall()
        for (old_magnet,) in rows:
            old_magnets.setdefault(old_magnet, None)

    for old_magnet in old_magnets:
        update_magnet_status(
            con, old_magnet, LifecycleStatus.RETIRED.value,
            description=f"Superseded by magnet '{new_magnet_name}'.",
            changed_at=retire_at, verbose=verbose,
        )
        open_links = con.execute(
            "SELECT assembly_name FROM assembly_magnets "
            "WHERE magnet_name = ? AND decommissioned_at IS NULL",
            [old_magnet],
        ).fetchall()
        for (open_assembly,) in open_links:
            decommission_assembly(
                con, open_assembly, decommissioned_at=retire_at,
                description=f"Auto-closed: magnet '{old_magnet}' retired.",
                verbose=verbose,
            )


def insert_magnet_parts(con, magnet_name: str, parts: list[dict], verbose: bool = True) -> None:
    """Link parts to a magnet, computing coil_index for helix/bitter parts.

    ``parts`` must be a list of part dicts, each with at least ``name`` and
    ``type`` keys (i.e. the raw parts list from the magnet JSON export).

    Every part must end up ``in_stock`` before linking — validated up front,
    before any row is inserted, so a rejected call leaves zero
    ``magnet_parts`` rows rather than a partial set. A part already linked
    to *magnet_name* itself is exempt (an idempotent re-call skips it,
    regardless of its current status). A part that already exists with a
    non-``in_stock`` status is otherwise first offered to
    :func:`_reclaim_reused_parts`: if some other still-active magnet
    currently holds it, that magnet is retired (and its open assembly link
    closed) to free the part. A non-``in_stock`` part with no such holder
    (e.g. one set directly via ``part update-status``) still raises.

    Each newly-linked part (not one already present, skipped as a
    duplicate) is then promoted to ``in_operation`` via
    :func:`update_part_status` — attaching a part to a magnet commits it,
    independent of whether that magnet is ever linked to an assembly.

    Raises
    ------
    ValueError
        If a part is not found, or its status is not ``"in_stock"`` and no
        active holder can be reclaimed for it.
    """
    part_names = [p["name"] for p in parts]
    if part_names:
        placeholders = ", ".join("?" * len(part_names))
        status_by_name = dict(
            con.execute(
                f"SELECT name, status FROM parts WHERE name IN ({placeholders})",
                part_names,
            ).fetchall()
        )
        for part_name in part_names:
            if part_name not in status_by_name:
                raise ValueError(f"Part '{part_name}' not found in database.")

        already_linked = {
            r[0] for r in con.execute(
                f"SELECT part_name FROM magnet_parts WHERE magnet_name = ? "
                f"AND part_name IN ({placeholders})",
                [magnet_name] + part_names,
            ).fetchall()
        }

        non_in_stock = [
            p for p in part_names
            if status_by_name[p] != LifecycleStatus.IN_STOCK.value and p not in already_linked
        ]
        if non_in_stock:
            _reclaim_reused_parts(con, magnet_name, non_in_stock, verbose=verbose)
            status_by_name = dict(
                con.execute(
                    f"SELECT name, status FROM parts WHERE name IN ({placeholders})",
                    part_names,
                ).fetchall()
            )

        for part_name in part_names:
            if part_name in already_linked:
                continue
            status = status_by_name[part_name]
            if status != LifecycleStatus.IN_STOCK.value:
                raise ValueError(
                    f"Part '{part_name}' has status '{status}', not 'in_stock' — "
                    "cannot link it to a magnet. Use 'part update-status' to reset "
                    "it first."
                )

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

        update_part_status(
            con, part_name, LifecycleStatus.IN_OPERATION.value,
            description=f"Attached to magnet '{magnet_name}'.",
            changed_at=assembled_at_from_name(magnet_name), verbose=verbose,
        )

    if verbose:
        print(
            f"  + magnet_parts  {inserted} inserted,  {skipped} already present"
            f"  ({coil_counter} coil channel(s))"
        )


def insert_magnet_part_row(
    con, magnet_name: str, part_name: str, rank: int, coil_index: int | None
) -> None:
    """Insert a single pre-computed magnet_parts row.

    Low-level and unvalidated — skips the in-stock-parts check
    ``insert_magnet_parts`` enforces. Has no live production caller today
    (``deprecated/seeds_to_duckdb.py`` is dead code); used by tests to seed
    exact DB state directly.
    """
    if con.execute(
        "SELECT 1 FROM magnet_parts WHERE magnet_name = ? AND part_name = ?",
        [magnet_name, part_name],
    ).fetchone():
        return
    con.execute(
        "INSERT INTO magnet_parts VALUES (?,?,?,?)",
        [magnet_name, part_name, rank, coil_index],
    )


_DOWN_CASCADE_STATUSES = frozenset(
    {LifecycleStatus.RETIRED.value, LifecycleStatus.DEAD.value}
)


def _cascade_parts_status(
    con,
    magnet_name: str,
    from_statuses: set,
    to_status: str,
    changed_at=None,
    verbose: bool = True,
) -> None:
    """Move every part of *magnet_name* currently in *from_statuses* to *to_status*."""
    rows = con.execute(
        "SELECT p.name, p.status FROM magnet_parts mp JOIN parts p ON p.name = mp.part_name "
        "WHERE mp.magnet_name = ?",
        [magnet_name],
    ).fetchall()
    for part_name, status in rows:
        if status in from_statuses:
            con.execute("UPDATE parts SET status = ? WHERE name = ?", [to_status, part_name])
            _append_status_history(
                con, "parts", part_name, to_status,
                description=f"Cascaded from magnet '{magnet_name}'.",
                changed_at=changed_at,
            )
            if verbose:
                print(f"  ~ part      {part_name}  status → {to_status}  (cascaded from magnet '{magnet_name}')")


def _set_magnet_status(
    con,
    name: str,
    status: str,
    description: str = "",
    changed_at=None,
    attachments: list[dict] | None = None,
    verbose: bool = True,
    cascade: bool = True,
) -> None:
    """Set a magnet's status, log the change, and cascade to its parts.

    Downward (``retired``/``dead``) pulls ``NULL``/``in_operation`` parts to
    ``in_stock``; upward (``in_operation``, the commissioning cascade) pushes
    ``NULL``/``in_stock`` parts to ``in_operation``. Either cascade is a
    no-op once its target parts have already moved, so re-calling with the
    same status is safe (logs an event, cascades nothing).
    """
    con.execute("UPDATE magnets SET status = ? WHERE name = ?", [status, name])
    _append_status_history(con, "magnets", name, status, description, changed_at, attachments)
    if verbose:
        print(f"  ~ magnet    {name}  status → {status}")
    if not cascade:
        return
    if status in _DOWN_CASCADE_STATUSES:
        _cascade_parts_status(
            con, name, {None, LifecycleStatus.IN_OPERATION.value},
            LifecycleStatus.IN_STOCK.value, changed_at, verbose,
        )
    elif status == LifecycleStatus.IN_OPERATION.value:
        _cascade_parts_status(
            con, name, {None, LifecycleStatus.IN_STOCK.value},
            LifecycleStatus.IN_OPERATION.value, changed_at, verbose,
        )


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def parse_timestamp(value) -> str | None:
    if not value or str(value).lower() in ("none", "null", ""):
        return None
    return str(value)


def _date_from_coded_name(name: str, prefix_pattern: str) -> str | None:
    """Parse a ``YYMMDD`` date out of an LNCMI coded name, or None.

    Matches ``^{prefix_pattern}(\\d{6})\\d{2}$`` (date + 2-digit serial) and
    parses the captured group as ``%y%m%d``. Returns ``None`` for
    non-conforming names (e.g. hand-built Bitter magnets/parts) or invalid
    dates (e.g. month 13).
    """
    match = re.match(rf"^{prefix_pattern}(\d{{6}})\d{{2}}$", name)
    if not match:
        return None
    yy, mm, dd = (int(match.group(1)[i : i + 2]) for i in (0, 2, 4))
    year = 1900 + yy if yy >= 69 else 2000 + yy
    try:
        return date(year, mm, dd).isoformat()
    except ValueError:
        return None


def assembled_at_from_name(name: str) -> str | None:
    """Derive a magnet's assembly date from its coded ``name`` (``MYYMMDDXX``)."""
    return _date_from_coded_name(name, "M")


def manufactured_at_from_name(name: str) -> str | None:
    """Derive a part's manufacture date from its coded ``name`` (``[HR]YYMMDDXX``)."""
    return _date_from_coded_name(name, "[HR]")


def _fallback_decommission_at(reference) -> str | None:
    """Return a safe auto-close fallback timestamp anchored to *reference*
    (an incoming ``commissioned_at``/``assembled_at`` value), or ``None``.

    Same calendar day at ``07:00``, matching the incoming side's ``08:00``
    — the same-day handoff pairing already used throughout the source data.
    A bare date (no time-of-day, e.g. from :func:`assembled_at_from_name`)
    is treated as defaulting to that convention's ``08:00`` anchor. An
    explicit timestamp is respected as-is and the result clamped to never
    land after it, so an auto-closed predecessor can never appear to still
    be open past the successor's actual, explicitly-given start.
    """
    if not reference:
        return None
    reference = str(reference)
    if len(reference) <= 10:  # bare date, no explicit time-of-day
        reference = f"{reference} 08:00:00"
    same_day_07 = f"{reference[:10]} 07:00:00"
    return min(reference, same_day_07)


def _assembly_is_active(con, name: str) -> bool:
    """True if *name* is a non-``in_study`` assembly with no ``decommissioned_at``."""
    row = con.execute(
        "SELECT status, decommissioned_at FROM assemblies WHERE name = ?", [name]
    ).fetchone()
    if row is None:
        return False
    status, decommissioned_at = row
    return decommissioned_at is None and status != AssemblyStatus.IN_STUDY.value


def _resolve_housing_overlap(
    con, housing: str, name: str, commissioned_at, decommissioned_at, verbose: bool = True
) -> None:
    """Enforce the per-housing no-overlap invariant for a new non-``in_study``
    assembly, auto-closing a still-open predecessor when it started first.

    Raises
    ------
    ValueError
        If *name*'s window would overlap another non-``in_study`` assembly on
        *housing* in a way auto-close cannot resolve.
    """
    if commissioned_at is None:
        return

    still_open_but_later = con.execute(
        "SELECT name FROM assemblies WHERE housing = ? AND status != ? "
        "AND decommissioned_at IS NULL AND name != ? AND commissioned_at > CAST(? AS TIMESTAMP)",
        [housing, AssemblyStatus.IN_STUDY.value, name, commissioned_at],
    ).fetchone()
    if still_open_but_later is not None:
        raise ValueError(
            f"Assembly '{name}' starts ({commissioned_at}) before still-open "
            f"assembly '{still_open_but_later[0]}' on housing '{housing}'."
        )

    open_predecessor = con.execute(
        "SELECT name FROM assemblies WHERE housing = ? AND status != ? "
        "AND decommissioned_at IS NULL AND name != ?",
        [housing, AssemblyStatus.IN_STUDY.value, name],
    ).fetchone()
    if open_predecessor is not None:
        decommission_assembly(
            con, open_predecessor[0], decommissioned_at=_fallback_decommission_at(commissioned_at),
            description=f"Auto-closed: superseded by assembly '{name}'.",
            verbose=verbose,
        )

    overlap = con.execute(
        """
        SELECT name, commissioned_at, decommissioned_at FROM assemblies
        WHERE housing = ? AND status != ? AND name != ?
          AND commissioned_at < COALESCE(CAST(? AS TIMESTAMP), TIMESTAMP '9999-12-31')
          AND COALESCE(decommissioned_at, TIMESTAMP '9999-12-31') > CAST(? AS TIMESTAMP)
        LIMIT 1
        """,
        [housing, AssemblyStatus.IN_STUDY.value, name, decommissioned_at, commissioned_at],
    ).fetchone()
    if overlap is not None:
        other_name, other_start, other_end = overlap
        raise ValueError(
            f"Assembly '{name}' [{commissioned_at}, {decommissioned_at or '...'}) overlaps "
            f"assembly '{other_name}' [{other_start}, {other_end or '...'}) on housing '{housing}'."
        )


def insert_assembly(
    con, data: dict, verbose: bool = True, create_housing: bool = True
) -> None:
    """Insert an assembly row; skip silently if it already exists.

    The ``housing`` field in *data* is treated as a ``housing_config.name``
    foreign key. Unless ``status == "in_study"`` (an explicit opt-out),
    ``status`` is derived from ``decommissioned_at`` (``in_operation`` if
    unset, else ``disassembled``) — a caller-supplied contradicting value is
    overridden — and the per-housing no-overlap invariant is enforced,
    auto-closing (via :func:`decommission_assembly`) a still-open assembly
    already on this housing.

    Parameters
    ----------
    con:
        Open DuckDB connection.
    data:
        Assembly dict with at least a ``name`` key.  ``housing`` must match a
        ``housing_config.name`` value.
    verbose:
        Print status lines.
    create_housing:
        When ``True`` (default) and the housing config is not yet in the DB,
        auto-create it from the ``python_magnetrun`` bundled JSON files.  Set
        to ``False`` to raise :exc:`ValueError` instead when the config is
        missing.

    Raises
    ------
    ValueError
        If *housing* is missing and ``create_housing`` is ``False``, or the
        new assembly's window overlaps another non-``in_study`` assembly on
        the same housing.
    """
    name = data["name"]
    if exists(con, "assemblies", name):
        if verbose:
            print(f"  ~ assembly      {name}  (already exists, skipped)")
        return

    housing = data.get("housing") or None
    if housing is not None and con.execute(
        "SELECT 1 FROM housing_config WHERE name = ?", [housing]
    ).fetchone() is None:
        if create_housing:
            insert_housing_config_from_magnetrun(con, housing, verbose=verbose)
        else:
            raise ValueError(
                f"Housing config '{housing}' not found in housing_config table. "
                "Call insert_housing_config() first, or pass create_housing=True."
            )

    commissioned_at = parse_timestamp(data.get("commissioned_at"))
    decommissioned_at = parse_timestamp(data.get("decommissioned_at"))
    status = data.get("status")

    if status == AssemblyStatus.IN_STUDY.value:
        pass  # explicit opt-out: skip derivation/overlap/auto-close entirely
    else:
        status = (
            AssemblyStatus.IN_OPERATION.value
            if decommissioned_at is None
            else AssemblyStatus.DISASSEMBLED.value
        )
        if housing is not None:
            _resolve_housing_overlap(
                con, housing, name, commissioned_at, decommissioned_at, verbose=verbose
            )

    con.execute(
        """
        INSERT INTO assemblies
            (name, description, status, housing, commissioned_at, decommissioned_at)
        VALUES (?,?,?,?,?,?)
        """,
        [name, data.get("description") or None, status, housing, commissioned_at, decommissioned_at],
    )
    if verbose:
        print(f"  + assembly      {name}  [{housing or '?'}]  {status or ''}")


def update_assembly_from_json(con, data: dict, dry_run: bool = False, verbose: bool = True) -> None:
    """Refresh an assembly's ``description`` from a JSON payload.

    Only writes ``description``, and only when that key is present in
    *data* — this is a partial refresh, not a full re-sync. ``name``,
    ``status``, ``status_history``, ``housing``,
    ``commissioned_at``/``decommissioned_at``, and linked ``magnets``/
    ``records`` are never touched here.

    Parameters
    ----------
    con:
        Open DuckDB connection.
    data:
        Assembly dict; only ``description`` is consulted.
    dry_run:
        When ``True``, report whether ``description`` would change without
        writing.
    verbose:
        Print status lines.

    Raises
    ------
    ValueError
        If the assembly is not found.
    """
    name = data["name"]
    if not exists(con, "assemblies", name):
        raise ValueError(f"Assembly '{name}' not found in DB — nothing to update.")

    if "description" not in data:
        if verbose:
            print(f"  ~ assembly      {name}  (no descriptive fields in JSON, nothing to update)")
        return

    if dry_run:
        if verbose:
            print(f"[dry-run] assembly '{name}': would update description")
        return

    con.execute(
        "UPDATE assemblies SET description = ? WHERE name = ?",
        [data.get("description") or None, name],
    )
    if verbose:
        print(f"  ~ assembly      {name}  updated: description")


def _cascade_assembly_disassembly(con, assembly_name: str, decommissioned_at, verbose: bool = True) -> None:
    """Close open ``assembly_magnets`` rows for *assembly_name* and cascade
    its ``NULL``/``in_operation`` magnets to ``in_stock`` (their parts are
    left untouched — parts only cascade when a magnet is explicitly
    ``retired`` or marked ``dead``). Naturally idempotent: a link already
    closed by a prior call is skipped."""
    magnet_rows = con.execute(
        "SELECT magnet_name FROM assembly_magnets "
        "WHERE assembly_name = ? AND decommissioned_at IS NULL",
        [assembly_name],
    ).fetchall()
    con.execute(
        "UPDATE assembly_magnets SET decommissioned_at = ? "
        "WHERE assembly_name = ? AND decommissioned_at IS NULL",
        [decommissioned_at, assembly_name],
    )
    for (magnet_name,) in magnet_rows:
        row = con.execute("SELECT status FROM magnets WHERE name = ?", [magnet_name]).fetchone()
        if row is None:
            continue
        status = row[0]
        if status is None or status == LifecycleStatus.IN_OPERATION.value:
            _set_magnet_status(
                con, magnet_name, LifecycleStatus.IN_STOCK.value,
                description=f"Assembly '{assembly_name}' disassembled.",
                changed_at=decommissioned_at, verbose=verbose,
            )


def decommission_assembly(
    con,
    name: str,
    decommissioned_at=None,
    description: str = "",
    attachments: list[dict] | None = None,
    verbose: bool = True,
) -> None:
    """Disassemble an assembly: close it and cascade its magnets to ``in_stock``.

    Parameters
    ----------
    con:
        Open DuckDB connection.
    name:
        Assembly name.
    decommissioned_at:
        Timestamp used only if the assembly doesn't already have one; an
        already-set value on the assembly row always wins (so a re-call —
        e.g. from an auto-close path with no date of its own — backfills any
        still-open ``assembly_magnets`` link and logs status_history with
        the assembly's true original date, not a fresh fallback). Defaults
        to now if the assembly has none and none is passed in.
    description:
        Free-text note appended to ``status_history``.
    attachments:
        Attachment records (e.g. ``[{"kind": ..., "path": ...}]``) appended
        to ``status_history``.
    verbose:
        Print status lines.

    Raises
    ------
    ValueError
        If the assembly does not exist.
    """
    if not exists(con, "assemblies", name):
        raise ValueError(f"Assembly '{name}' not found.")

    existing = con.execute(
        "SELECT decommissioned_at FROM assemblies WHERE name = ?", [name]
    ).fetchone()[0]
    decommissioned_at = (
        parse_timestamp(existing) or parse_timestamp(decommissioned_at) or datetime.now().isoformat()
    )
    con.execute(
        "UPDATE assemblies SET status = ?, decommissioned_at = COALESCE(decommissioned_at, CAST(? AS TIMESTAMP)) "
        "WHERE name = ?",
        [AssemblyStatus.DISASSEMBLED.value, decommissioned_at, name],
    )
    _append_status_history(
        con, "assemblies", name, AssemblyStatus.DISASSEMBLED.value,
        description=description, changed_at=decommissioned_at, attachments=attachments,
    )
    if verbose:
        print(f"  ~ assembly  {name}  status → disassembled")

    _cascade_assembly_disassembly(con, name, decommissioned_at, verbose=verbose)


def _magnet_entry_name(entry) -> str:
    return entry if isinstance(entry, str) else entry["name"]


def insert_assembly_magnets(
    con, assembly_name: str, magnet_entries: list, verbose: bool = True
) -> None:
    """Link magnets to an assembly.

    Each entry in *magnet_entries* is either a plain magnet name string or a
    dict with optional positional/temporal fields (z_offset, r_offset,
    parallax, commissioned_at, decommissioned_at, metadata).

    For an entry with no ``decommissioned_at`` (i.e. an open link): if the
    magnet already has an open link to a *different* assembly (moved to a
    new housing), that other assembly is auto-closed via
    :func:`decommission_assembly` — fallback ``07:00`` same day as this
    entry's own ``commissioned_at``, or *assembly_name*'s own
    ``commissioned_at`` if the entry doesn't carry one, when no explicit
    ``decommissioned_at`` is already recorded for it — mirroring the
    same-housing auto-close in :func:`_resolve_housing_overlap`. Then, if
    *assembly_name* is currently active (see :func:`_assembly_is_active`),
    the magnet (and its parts) cascade from ``in_stock`` to ``in_operation``
    (the commissioning cascade).
    """
    assembly_active = _assembly_is_active(con, assembly_name)
    assembly_row = con.execute(
        "SELECT commissioned_at FROM assemblies WHERE name = ?", [assembly_name]
    ).fetchone()
    assembly_commissioned_at = assembly_row[0] if assembly_row else None

    for entry in magnet_entries:
        magnet_name = _magnet_entry_name(entry)
        extra = entry if isinstance(entry, dict) else {}

        if con.execute(
            "SELECT 1 FROM assembly_magnets WHERE assembly_name = ? AND magnet_name = ?",
            [assembly_name, magnet_name],
        ).fetchone():
            if verbose:
                print(f"  ~ magnet    {magnet_name}  (already linked, skipped)")
            continue

        link_decommissioned_at = parse_timestamp(extra.get("decommissioned_at"))

        if link_decommissioned_at is None:
            other = con.execute(
                "SELECT assembly_name FROM assembly_magnets "
                "WHERE magnet_name = ? AND decommissioned_at IS NULL AND assembly_name != ?",
                [magnet_name, assembly_name],
            ).fetchone()
            if other is not None:
                reference = parse_timestamp(extra.get("commissioned_at")) or assembly_commissioned_at
                decommission_assembly(
                    con, other[0],
                    decommissioned_at=_fallback_decommission_at(reference),
                    description=f"Auto-closed: magnet '{magnet_name}' moved to assembly '{assembly_name}'.",
                    verbose=verbose,
                )

        con.execute(
            """
            INSERT INTO assembly_magnets
                (assembly_name, magnet_name, z_offset, r_offset, parallax,
                 commissioned_at, decommissioned_at, metadata)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            [
                assembly_name,
                magnet_name,
                extra.get("z_offset", 0.0),
                extra.get("r_offset", 0.0),
                extra.get("parallax", 0.0),
                parse_timestamp(extra.get("commissioned_at")),
                link_decommissioned_at,
                json.dumps(extra.get("metadata", {})),
            ],
        )
        if verbose:
            row = con.execute("SELECT type FROM magnets WHERE name = ?", [magnet_name]).fetchone()
            print(f"  + magnet    {magnet_name}  ({row[0] if row else '?'})")

        if assembly_active and link_decommissioned_at is None:
            status_row = con.execute(
                "SELECT status FROM magnets WHERE name = ?", [magnet_name]
            ).fetchone()
            status = status_row[0] if status_row else None
            if status is None or status == LifecycleStatus.IN_STOCK.value:
                _set_magnet_status(
                    con, magnet_name, LifecycleStatus.IN_OPERATION.value,
                    description=f"Commissioned into assembly '{assembly_name}'.",
                    verbose=verbose,
                )


def insert_experiments(
    con, assembly_name: str, records: list[dict], verbose: bool = True
) -> None:
    """Insert experiment/record rows for an assembly; skip duplicates by file name."""
    row = con.execute("SELECT COALESCE(MAX(id), 0) FROM experiments").fetchone()
    next_id = (row[0] or 0) + 1
    inserted = 0
    skipped = 0

    for i, rec in enumerate(records):
        file_name = rec.get("file") or rec.get("name") or rec.get("record_file")
        if con.execute(
            "SELECT 1 FROM experiments WHERE assembly_name = ? AND file = ?",
            [assembly_name, file_name],
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
                assembly_name,
            ],
        )
        inserted += 1

    if verbose:
        print(f"  + records   {inserted} inserted,  {skipped} already present")


# ---------------------------------------------------------------------------
# Status updates (parts, magnets)
# ---------------------------------------------------------------------------


def update_part_status(
    con,
    name: str,
    status: str,
    description: str = "",
    changed_at=None,
    attachments: list[dict] | None = None,
    verbose: bool = True,
) -> None:
    """Set a part's lifecycle status and append a ``status_history`` event.

    Parameters
    ----------
    con:
        Open DuckDB connection.
    name:
        Part name.
    status:
        One of :class:`~enums.LifecycleStatus`'s values.
    description:
        Free-text note appended to ``status_history``.
    changed_at:
        Timestamp; defaults to now.
    attachments:
        Attachment records appended to ``status_history``.
    verbose:
        Print status lines.

    Raises
    ------
    ValueError
        If the part does not exist, or *status* is not a valid
        :class:`~enums.LifecycleStatus`.
    """
    if not exists(con, "parts", name):
        raise ValueError(f"Part '{name}' not found.")
    _valid_lifecycle_status(status)
    con.execute("UPDATE parts SET status = ? WHERE name = ?", [status, name])
    _append_status_history(con, "parts", name, status, description, changed_at, attachments)
    if verbose:
        print(f"  ~ part      {name}  status → {status}")


def update_magnet_status(
    con,
    name: str,
    status: str,
    description: str = "",
    changed_at=None,
    attachments: list[dict] | None = None,
    dead_parts: list[str] | None = None,
    verbose: bool = True,
) -> None:
    """Set a magnet's lifecycle status, enforcing the dead-part invariant and
    cascading to its parts.

    Parameters
    ----------
    con:
        Open DuckDB connection.
    name:
        Magnet name.
    status:
        One of :class:`~enums.LifecycleStatus`'s values.
    description:
        Free-text note appended to ``status_history``.
    changed_at:
        Timestamp; defaults to now.
    attachments:
        Attachment records appended to ``status_history``.
    dead_parts:
        Required (non-empty) when ``status == "dead"``; each name must
        belong to this magnet (via ``magnet_parts``) and is itself set (or
        confirmed, if already dead) to ``"dead"`` before the magnet's own
        status is updated. Rejected when ``status != "dead"``. The special
        value ``"ALL"`` (used alone, not combined with explicit names)
        resolves to every part currently linked to this magnet. A part
        that is already ``"dead"`` is re-confirmed rather than rejected,
        printing a warning.
    verbose:
        Print status lines.

    Raises
    ------
    ValueError
        If the magnet does not exist, *status* is invalid, ``dead_parts`` is
        missing/empty for a ``"dead"`` call, a name in ``dead_parts`` doesn't
        belong to this magnet, ``dead_parts`` is given for a non-``dead``
        status, ``"ALL"`` is combined with explicit part names, or ``"ALL"``
        is given but the magnet has no linked parts.
    """
    if not exists(con, "magnets", name):
        raise ValueError(f"Magnet '{name}' not found.")
    _valid_lifecycle_status(status)

    if status == LifecycleStatus.DEAD.value:
        if not dead_parts:
            raise ValueError("Marking a magnet 'dead' requires at least one dead part.")
        linked_status = {
            r[0]: r[1] for r in con.execute(
                "SELECT p.name, p.status FROM magnet_parts mp "
                "JOIN parts p ON p.name = mp.part_name WHERE mp.magnet_name = ?", [name]
            ).fetchall()
        }
        if "ALL" in dead_parts:
            if len(dead_parts) > 1:
                raise ValueError("'ALL' cannot be combined with explicit part names.")
            if not linked_status:
                raise ValueError(f"Magnet '{name}' has no linked parts to mark dead.")
            dead_parts = sorted(linked_status)
        unknown = [p for p in dead_parts if p not in linked_status]
        if unknown:
            raise ValueError(f"Part(s) {unknown} do not belong to magnet '{name}'.")
        for part_name in dead_parts:
            if linked_status[part_name] == LifecycleStatus.DEAD.value:
                print(f"  *** WARNING: part '{part_name}' is already dead — re-confirming. ***")
            update_part_status(
                con, part_name, LifecycleStatus.DEAD.value,
                description=description, changed_at=changed_at, verbose=verbose,
            )
    elif dead_parts:
        raise ValueError("dead_parts is only valid with status='dead'.")

    _set_magnet_status(
        con, name, status, description=description, changed_at=changed_at,
        attachments=attachments, verbose=verbose,
    )

    if status == LifecycleStatus.DEAD.value and not description and not attachments:
        print(
            "\n"
            "  *** WARNING: magnet marked 'dead' with no description or attachment. ***\n"
            "  *** Consider attaching an incident report, e.g.:                     ***\n"
            "  ***   magnet update-status <name> --status dead --dead-part <part>   ***\n"
            "  ***     --description \"...\" --attachment report=<path>              ***\n"
        )


# ---------------------------------------------------------------------------
# Update helpers
# ---------------------------------------------------------------------------

_FLOAT_FIELDS = frozenset({"z_offset", "r_offset", "parallax"})
_TIMESTAMP_FIELDS = frozenset({"commissioned_at", "decommissioned_at"})
_JSON_FIELDS = frozenset({"metadata"})
_ASSEMBLY_MAGNET_FIELDS = _FLOAT_FIELDS | _TIMESTAMP_FIELDS | _JSON_FIELDS


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


def _print_status_history(raw) -> None:
    """Print a ``status_history`` JSON column's entries, if any."""
    if not raw:
        return
    history = json.loads(raw) if isinstance(raw, str) else raw
    if not history:
        return
    print(f"  status_history ({len(history)}):")
    for event in history:
        attachments = event.get("attachments") or []
        att = f"  attachments={attachments}" if attachments else ""
        print(
            f"    [{event.get('date', '?')}] {event.get('status', '?')}"
            f"  {event.get('description', '')}{att}"
        )


def view_parts(
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
        f"SELECT name, type, status FROM parts {where} ORDER BY name", params
    ).fetchall()
    if not rows:
        parts = []
        if type_filter:
            parts.append(f"type '{type_filter}'")
        if status_filter:
            parts.append(f"status '{status_filter}'")
        qualifier = " matching " + ", ".join(parts) if parts else ""
        print(f"No parts{qualifier} in database.")
        return
    print(f"{'Name':<30} {'Type':<10} Status")
    print("-" * 55)
    for name, type_, status in rows:
        print(f"{name:<30} {type_ or '?':<10} {status or ''}")


def view_part(con, name: str) -> None:
    row = con.execute(
        "SELECT name, type, status, material_name, design_office_reference, status_history "
        "FROM parts WHERE name = ?",
        [name],
    ).fetchone()
    if not row:
        print(f"Part '{name}' not found.")
        return
    print(f"Part  : {row[0]}")
    print(f"  type    : {row[1] or '?'}")
    print(f"  status  : {row[2] or ''}")
    print(f"  material: {row[3] or ''}")
    print(f"  ref     : {row[4] or ''}")
    _print_status_history(row[5])


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
        "SELECT name, type, status, design_office_reference, status_history FROM magnets WHERE name = ?",
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
    _print_status_history(row[4])


def view_assemblies(
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
        f"SELECT name, housing, status FROM assemblies {where} ORDER BY name", params
    ).fetchall()
    if not rows:
        parts = []
        if housing_filter:
            parts.append(f"housing '{housing_filter}'")
        if status_filter:
            parts.append(f"status '{status_filter}'")
        qualifier = " matching " + ", ".join(parts) if parts else ""
        print(f"No assemblies{qualifier} in database.")
        return
    print(f"{'Name':<40} {'Housing':<15} Status")
    print("-" * 65)
    for name, housing, status in rows:
        print(f"{name:<40} {housing or '?':<15} {status or ''}")


def view_assembly(con, name: str) -> None:
    row = con.execute(
        "SELECT name, housing, status, commissioned_at, decommissioned_at "
        "FROM assemblies WHERE name = ?",
        [name],
    ).fetchone()
    if not row:
        print(f"Assembly '{name}' not found.")
        return
    print(f"Assembly : {row[0]}")
    print(f"  housing          : {row[1] or '?'}")
    print(f"  status           : {row[2] or ''}")
    print(f"  commissioned_at  : {row[3] or ''}")
    print(f"  decommissioned_at: {row[4] or ''}")
    magnets = con.execute(
        "SELECT magnet_name, z_offset, r_offset "
        "FROM assembly_magnets WHERE assembly_name = ? ORDER BY magnet_name",
        [name],
    ).fetchall()
    if magnets:
        print(f"  magnets ({len(magnets)}):")
        for mname, z, r in magnets:
            print(f"    {mname}  (z={z}, r={r})")
    count = con.execute(
        "SELECT COUNT(*) FROM experiments WHERE assembly_name = ?", [name]
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
    assembly_name: str | None = None,
    magnet_name: str | None = None,
    part_name: str | None = None,
    from_ts: str | None = None,
    to_ts: str | None = None,
) -> None:
    joins, conditions, params = [], [], []

    if assembly_name:
        conditions.append("e.assembly_name = ?")
        params.append(assembly_name)
    if magnet_name or part_name:
        joins.append("JOIN assembly_magnets sm ON sm.assembly_name = e.assembly_name")
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
            f"SELECT id, name, file, assembly_name, status FROM ("
            f"SELECT {distinct}e.id, e.name, e.file, e.assembly_name, e.status,"
            f" {ts_expr} AS file_ts"
            f" FROM experiments e {join_sql} {where}"
            f") t {ts_where} ORDER BY assembly_name, id",
            ts_params,
        ).fetchall()
    else:
        rows = con.execute(
            f"SELECT {distinct}e.id, e.name, e.file, e.assembly_name, e.status "
            f"FROM experiments e {join_sql} {where} ORDER BY e.assembly_name, e.id",
            params,
        ).fetchall()

    labels = []
    if assembly_name:
        labels.append(f"assembly={assembly_name}")
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
    print(f"{'ID':<6} {'Assembly':<{col_s}} {'File':<{col_f}} Status")
    print("-" * (col_s + col_f + 14))
    for id_, name, file_, assembly_, status in rows:
        print(f"{id_:<6} {(assembly_ or ''):<{col_s}} {(file_ or '')[:col_f]:<{col_f}} {status or ''}")


def view_operationaldata(
    con,
    assembly_name: str | None = None,
    type_filter: str | None = None,
    magnet_name: str | None = None,
    part_name: str | None = None,
    from_ts: str | None = None,
    to_ts: str | None = None,
) -> None:
    joins, conditions, params = [], [], []

    if assembly_name:
        conditions.append("od.assembly_name = ?")
        params.append(assembly_name)
    if type_filter:
        conditions.append("od.type = ?")
        params.append(type_filter)
    if magnet_name or part_name:
        joins.append("JOIN assembly_magnets sm ON sm.assembly_name = od.assembly_name")
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
            f"SELECT id, name, file, type, assembly_name, status FROM ("
            f"SELECT {distinct}od.id, od.name, od.file, od.type, od.assembly_name, od.status,"
            f" {ts_expr} AS file_ts"
            f" FROM operationaldata od {join_sql} {where}"
            f") t {ts_where} ORDER BY assembly_name, type, id",
            ts_params,
        ).fetchall()
    else:
        rows = con.execute(
            f"SELECT {distinct}od.id, od.name, od.file, od.type, od.assembly_name, od.status "
            f"FROM operationaldata od {join_sql} {where} ORDER BY od.assembly_name, od.type, od.id",
            params,
        ).fetchall()

    labels = []
    if assembly_name:
        labels.append(f"assembly={assembly_name}")
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
    print(f"{'ID':<6} {'Assembly':<{col_s}} {'Type':<{col_t}} {'File':<{col_f}} Status")
    print("-" * (col_s + col_t + col_f + 16))
    for id_, name, file_, type_, assembly_, status in rows:
        print(f"{id_:<6} {(assembly_ or ''):<{col_s}} {(type_ or ''):<{col_t}} {(file_ or '')[:col_f]:<{col_f}} {status or ''}")


def _duration_str(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def view_overview_records(
    con,
    assembly_name: str | None = None,
    show_signatures: bool = False,
    magnet_name: str | None = None,
    part_name: str | None = None,
    from_ts: str | None = None,
    to_ts: str | None = None,
) -> None:
    joins, conditions, params = [], ["ovr.merged_into IS NULL"], []

    if assembly_name:
        conditions.append("ovr.assembly_name = ?")
        params.append(assembly_name)
    if magnet_name or part_name:
        joins.append("JOIN assembly_magnets sm ON sm.assembly_name = ovr.assembly_name")
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
    if assembly_name:
        labels.append(f"assembly={assembly_name}")
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
        "assemblies":     [r[0] for r in con.execute("SELECT name FROM assemblies ORDER BY name").fetchall()],
        "housings":  [r[0] for r in con.execute("SELECT name FROM housing_config ORDER BY name").fetchall()],
    }


def delete_magnet(con, name: str) -> None:
    if not exists(con, "magnets", name):
        print(f"Magnet '{name}' not found.")
        return
    con.execute("DELETE FROM magnet_parts WHERE magnet_name = ?", [name])
    con.execute("DELETE FROM magnets WHERE name = ?", [name])
    print(f"Deleted magnet '{name}' and its part links.")


def delete_assembly(con, name: str) -> None:
    if not exists(con, "assemblies", name):
        print(f"Assembly '{name}' not found.")
        return
    con.execute("DELETE FROM experiments WHERE assembly_name = ?", [name])
    con.execute("DELETE FROM assembly_magnets WHERE assembly_name = ?", [name])
    con.execute("DELETE FROM assemblies WHERE name = ?", [name])
    print(f"Deleted assembly '{name}', its magnet links, and its experiments.")


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


_OVERVIEW_SOURCE_LIST_COLUMNS = [
    "sources_overview", "sources_archive", "sources_pupitre",
    "sources_default", "sources_trigger", "sources_spike",
    "sources_hybrid_kHz", "sources_hybrid_rms", "sources_hybrid_trigger",
    "sources_hybrid_vprocess", "sources_pigbrother_runlog", "sources_pupitre_runlog",
]
_OVERVIEW_JSON_COLUMNS = [
    "signatures", "sync_info", "flow_params", "metrics", "debitbrut", "plateaux",
]
_OVERVIEW_RECORD_COLUMNS = (
    ["filename", "assembly_name", "housing", "mode", "t0", "duration", "teb", "bp"]
    + _OVERVIEW_SOURCE_LIST_COLUMNS
    + _OVERVIEW_JSON_COLUMNS
)


def _execute_overview_record_write(con, columns: dict) -> None:
    """INSERT OR REPLACE one overview_records row from a *columns* dict."""
    values = [
        json.dumps(columns[col]) if col in _OVERVIEW_JSON_COLUMNS else columns[col]
        for col in _OVERVIEW_RECORD_COLUMNS
    ]
    con.execute(
        f"INSERT OR REPLACE INTO overview_records ({', '.join(_OVERVIEW_RECORD_COLUMNS)}) "
        f"VALUES ({', '.join(['?'] * len(_OVERVIEW_RECORD_COLUMNS))})",
        values,
    )


def _write_overview_record_row(
    con, columns: dict, on_conflict: str, verbose: bool = True
) -> None:
    """Write one overview_records row (plain insert/replace, no cross-row merge).

    Pupitre-duplicate detection and merging is handled separately, as a
    table-wide sweep, by :func:`merge_duplicate_pupitre_records` (run from
    ``populate overview-records-infer``) — not here.

    Parameters
    ----------
    con:
        Open DuckDB connection.
    columns : dict
        Maps every ``overview_records`` column name to its Python value
        (JSON columns as ``dict``, not yet serialized).
    on_conflict : str
        ``"skip"`` — if ``columns["filename"]`` already exists, print a
        status line and return without writing. ``"replace"`` — always
        write (matches ``INSERT OR REPLACE`` semantics).
    verbose : bool
        Print a status line describing what happened.
    """
    filename = columns["filename"]

    if on_conflict == "skip" and con.execute(
        "SELECT 1 FROM overview_records WHERE filename = ?", [filename]
    ).fetchone():
        if verbose:
            print(f"  ~ overview_record  {filename}  (already exists, skipped)")
        return

    _execute_overview_record_write(con, columns)
    if verbose:
        if on_conflict == "replace":
            print(f"  ~ overview_record  {filename}  [{columns.get('housing')}]  (upserted)")
        else:
            dur = float(columns.get("duration") or 0.0)
            print(f"  + overview_record  {filename}  [{columns.get('housing')}]  duration={dur:.1f}s")

    if columns.get("assembly_name") is not None:
        _postprocess_overview_record(con, filename, verbose=verbose)


def _overview_record_to_columns(record, assembly_name: str | None) -> dict:
    """Build a ``_write_overview_record_row`` columns dict from an OverviewRecord.

    Parameters
    ----------
    record:
        An ``OverviewRecord`` dataclass instance (``data`` attribute is ignored).
    assembly_name : str or None
        Assembly name FK (references ``assemblies.name``).

    Returns
    -------
    dict
        Maps every ``overview_records`` column name to its Python value.
    """
    src = _fileset_lists(record.sources)
    return {
        "filename": record.filename,
        "assembly_name": assembly_name,
        "housing": record.housing,
        "mode": record.mode or None,
        "t0": str(record.t0) if record.t0 is not None else None,
        "duration": float(record.duration),
        "teb": float(record.teb),
        "bp": float(record.BP),
        "sources_overview": src["overview"],
        "sources_archive": src["archive"],
        "sources_pupitre": src["pupitre"],
        "sources_default": src["default"],
        "sources_trigger": src["trigger"],
        "sources_spike": src["spike"],
        "sources_hybrid_kHz": src["hybrid_kHz"],
        "sources_hybrid_rms": src["hybrid_rms"],
        "sources_hybrid_trigger": src["hybrid_trigger"],
        "sources_hybrid_vprocess": src["hybrid_vprocess"],
        "sources_pigbrother_runlog": src["pigbrother_runlog"],
        "sources_pupitre_runlog": src["pupitre_runlog"],
        "signatures": record.signatures,
        "sync_info": record.sync_info,
        "flow_params": record.flow_params,
        "metrics": record.metrics,
        "debitbrut": record.debitbrut,
        "plateaux": {},
    }


def insert_overview_record(
    con, record, assembly_name: str | None = None, verbose: bool = True
) -> None:
    """Insert an OverviewRecord row; skip silently if filename already exists.

    Pupitre-duplicate detection/merging is not done here — see
    :func:`merge_duplicate_pupitre_records`, run separately from
    ``populate overview-records-infer``.

    If *assembly_name* is given, also runs :func:`_postprocess_overview_record`
    (sets ``mode``) right after inserting.

    Parameters
    ----------
    con:
        Open DuckDB connection.
    record:
        An ``OverviewRecord`` dataclass instance (``data`` attribute is ignored).
    assembly_name:
        Assembly name FK (references ``assemblies.name``).  Pass ``None`` to leave unset.
    verbose:
        Print a status line when inserting.
    """
    _write_overview_record_row(
        con, _overview_record_to_columns(record, assembly_name), on_conflict="skip", verbose=verbose
    )


def upsert_overview_record(
    con, record, assembly_name: str | None = None, verbose: bool = True
) -> None:
    """Insert or replace an OverviewRecord row (idempotent re-processing).

    Pupitre-duplicate detection/merging is not done here — see
    :func:`merge_duplicate_pupitre_records`, run separately from
    ``populate overview-records-infer``.

    If *assembly_name* is given, also runs :func:`_postprocess_overview_record`
    (sets ``mode``) right after upserting.

    Parameters
    ----------
    con:
        Open DuckDB connection.
    record:
        An ``OverviewRecord`` dataclass instance (``data`` attribute is ignored).
    assembly_name:
        Assembly name FK (references ``assemblies.name``).  Pass ``None`` to leave unset.
    verbose:
        Print a status line when upserting.
    """
    _write_overview_record_row(
        con, _overview_record_to_columns(record, assembly_name), on_conflict="replace", verbose=verbose
    )


def insert_overview_record_from_dict(
    con, data: dict, assembly_name: str | None = None, verbose: bool = True, upsert: bool = False
) -> None:
    """Insert (or upsert) an overview_record row from a plain dict.

    Accepts the dict format produced by ``find_assembly_overview_records --json``,
    the pandas-records JSON written by ``magnetrun analysis/cli.py``, or any
    dict whose keys match the ``overview_records`` table columns.

    Source lists may be given as Python ``list[str]`` **or** as a
    comma-separated string (as written by ``cli.py``).  Both the canonical
    ``sources_<key>`` column names and the short ``<key>`` aliases used by
    ``cli.py`` are accepted (e.g. ``sources_overview`` or ``overview``).
    Each item is reduced to its basename (``Path(x).name``) before storage.

    Pupitre-duplicate detection/merging is not done here — see
    :func:`merge_duplicate_pupitre_records`, run separately from
    ``populate overview-records-infer``.

    If an assembly name ends up set (from *assembly_name* or ``data["assembly_name"]``),
    also runs :func:`_postprocess_overview_record` (sets ``mode``) right
    after writing the row.

    Parameters
    ----------
    con:
        Open DuckDB connection.
    data:
        Dict representing one overview record.  ``filename`` is required.
    assembly_name:
        Assembly name FK.  If *data* already contains ``assembly_name`` that value
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
            items = []
        elif isinstance(v, list):
            items = [str(x) for x in v if x]
        else:
            items = [x.strip() for x in str(v).split(",") if x.strip()]
        return [Path(x).name for x in items]

    _source_keys = [
        "overview", "archive", "pupitre", "default", "trigger", "spike",
        "hybrid_kHz", "hybrid_rms", "hybrid_trigger", "hybrid_vprocess",
        "pigbrother_runlog", "pupitre_runlog",
    ]

    def _get_sources(key: str) -> list[str]:
        return _to_list(data.get(f"sources_{key}", data.get(key)))

    def _json_field_dict(key: str) -> dict:
        v = data.get(key, {})
        if isinstance(v, dict):
            return v
        if isinstance(v, str) and v:
            try:
                parsed = json.loads(v)
            except json.JSONDecodeError:
                return {}
            return parsed if isinstance(parsed, dict) else {}
        return {}

    t0_raw = data.get("t0")
    t0 = str(t0_raw) if t0_raw is not None else None

    effective_assembly = assembly_name if assembly_name is not None else data.get("assembly_name")
    bp = float(data.get("bp", data.get("BP", 0.0)) or 0.0)

    columns = {
        "filename": filename,
        "assembly_name": effective_assembly,
        "housing": data.get("housing") or None,
        "mode": data.get("mode") or None,
        "t0": t0,
        "duration": float(data.get("duration") or 0.0),
        "teb": float(data.get("teb") or 0.0),
        "bp": bp,
        **{f"sources_{key}": _get_sources(key) for key in _source_keys},
        "signatures": _json_field_dict("signatures"),
        "sync_info": _json_field_dict("sync_info"),
        "flow_params": _json_field_dict("flow_params"),
        "metrics": _json_field_dict("metrics"),
        "debitbrut": _json_field_dict("debitbrut"),
        "plateaux": _json_field_dict("plateaux"),
    }

    _write_overview_record_row(
        con, columns, on_conflict="replace" if upsert else "skip", verbose=verbose
    )


def attach_assembly_to_overview_record(
    con, filename: str, assembly_name: str, verbose: bool = True
) -> None:
    """Set or overwrite assembly_name and housing on an existing overview_record row.

    The housing value is taken from assemblies.housing for the given assembly_name.
    Also runs :func:`_postprocess_overview_record` (sets ``mode``) now that
    ``assembly_name`` is known.

    Parameters
    ----------
    con:
        Open DuckDB connection.
    filename:
        Primary key of the overview_records row (basename without extension).
    assembly_name:
        Assembly name to attach (must exist in the assemblies table).
    verbose:
        Print a status line on success.

    Raises
    ------
    ValueError
        If *filename* is not found in overview_records, or *assembly_name* is not
        found in assemblies.
    """
    if con.execute(
        "SELECT 1 FROM overview_records WHERE filename = ?", [filename]
    ).fetchone() is None:
        raise ValueError(f"No overview_record found for filename '{filename}'")

    row = con.execute(
        "SELECT housing FROM assemblies WHERE name = ?", [assembly_name]
    ).fetchone()
    if row is None:
        raise ValueError(f"No assembly found for assembly_name '{assembly_name}'")
    housing = row[0]

    con.execute(
        "UPDATE overview_records SET assembly_name = ?, housing = ? WHERE filename = ?",
        [assembly_name, housing, filename],
    )
    if verbose:
        print(f"  ~ overview_record  {filename}  assembly_name → {assembly_name}  housing → {housing}")
    _postprocess_overview_record(con, filename, verbose=verbose)


# overview_records.filename follows python_magnetrun's
# "<housing>_Overview_<YYMMDD-HHMM>" convention (no extension).
_OVERVIEW_FILENAME_TS_RE = re.compile(r"(\d{6}-\d{4})$")
_OVERVIEW_FILENAME_TS_FMT = "%y%m%d-%H%M"


def _parse_overview_filename(filename: str) -> tuple[str, datetime | None]:
    """Split an overview_records filename into ``(housing, t0)``.

    Parameters
    ----------
    filename : str
        Value of ``overview_records.filename``.

    Returns
    -------
    tuple[str, datetime | None]
        ``housing`` is the ``_``-separated prefix.  ``t0`` is timezone-aware
        (Europe/Paris), or ``None`` if the trailing timestamp segment does
        not match the expected ``YYMMDD-HHMM`` pattern.
    """
    housing = filename.split("_")[0]
    m = _OVERVIEW_FILENAME_TS_RE.search(filename)
    if not m:
        return housing, None
    try:
        return housing, datetime.strptime(
            m.group(1), _OVERVIEW_FILENAME_TS_FMT
        ).replace(tzinfo=FILE_TZ)
    except ValueError:
        return housing, None


def _find_assembly_for_timestamp(con, housing: str, t0: datetime, db_tz) -> str | None:
    """Return the unique assembly whose operational window contains *t0*.

    Parameters
    ----------
    con:
        Open DuckDB connection.
    housing : str
        Housing identifier (e.g. ``"M9"``).
    t0 : datetime
        Timezone-aware timestamp (Europe/Paris) to match.
    db_tz : zoneinfo.ZoneInfo
        Timezone the ``assemblies.commissioned_at`` / ``decommissioned_at``
        columns are stored in.

    Returns
    -------
    str or None
        The matching ``assemblies.name``, or ``None`` if zero or more than one
        assembly matches (ambiguous — left for manual resolution).
    """
    rows = con.execute(
        "SELECT name, commissioned_at, decommissioned_at FROM assemblies WHERE housing = ?",
        [housing],
    ).fetchall()

    matches = []
    for name, commissioned_at, decommissioned_at in rows:
        t_start = as_aware(commissioned_at, db_tz)
        t_end = as_aware(decommissioned_at, db_tz)
        if t_start is not None:
            t_start = t_start.astimezone(FILE_TZ)
        if t_end is not None:
            t_end = t_end.astimezone(FILE_TZ)
        if (t_start is None or t0 >= t_start) and (t_end is None or t0 <= t_end):
            matches.append(name)

    return matches[0] if len(matches) == 1 else None


def resolve_overview_assembly(
    con, filename: str, db_tz
) -> tuple[str | None, datetime | None, str | None]:
    """Resolve ``(housing, t0, assembly_name)`` for an overview_records filename.

    ``housing`` is always the ``_``-separated prefix of *filename* (see
    :func:`_parse_overview_filename`), returned even when ``t0``/``assembly_name``
    cannot be determined.  ``t0`` and ``assembly_name`` are only both set when the
    filename's timestamp parses **and** it falls in exactly one assembly's
    commissioned/decommissioned window (see :func:`_find_assembly_for_timestamp`).

    Parameters
    ----------
    con:
        Open DuckDB connection.
    filename : str
        An ``overview_records.filename`` value (or candidate for one).
    db_tz : zoneinfo.ZoneInfo
        Timezone of the DB's ``commissioned_at``/``decommissioned_at`` columns.

    Returns
    -------
    tuple[str | None, datetime | None, str | None]
        ``(housing, t0, assembly_name)``. ``housing`` is set whenever *filename*
        has a ``_``-separated prefix. ``t0`` (naive, expressed in *db_tz*) is
        set whenever the filename's timestamp parses, independent of whether
        an assembly was matched. ``assembly_name`` is ``None`` unless exactly one assembly's
        window contains ``t0``.
    """
    housing, t0 = _parse_overview_filename(filename)
    if t0 is None:
        return housing, None, None

    assembly_name = _find_assembly_for_timestamp(con, housing, t0, db_tz)
    t0_db = t0.astimezone(db_tz).replace(tzinfo=None)
    return housing, t0_db, assembly_name


def _mean_across_frames(dfs: list, column: str) -> float:
    """Samples-weighted mean of *column* across every frame in *dfs*."""
    total, count = 0.0, 0
    for df in dfs:
        if column not in df.columns:
            continue
        values = df[column].dropna()
        total += float(values.sum())
        count += len(values)
    return total / count if count else 0.0


def infer_operating_mode(df) -> str:
    """Classify the operating mode from the IH(IB) relation near IB = 0.

    Ported from the housing_summary mode-inference heuristic: fits a line
    to ``Courant_GR1`` (IH) vs ``Courant_GR2`` (IB) for IB in a low-current
    window and classifies the slope.

    Parameters
    ----------
    df : :class:`~pandas.DataFrame`
        Must contain ``Courant_GR1`` and ``Courant_GR2`` columns (bare TDMS
        channel names from the ``Courants_Alimentations`` group).

    Returns
    -------
    str
        ``"NORMAL"``, ``"ECO"``, or ``"UNKNOWN"``. Only one of ``Courant_GR1``/
        ``Courant_GR2`` present means a single-channel housing, not an
        inconclusive fit, so ``"NORMAL"`` is returned in that case.

    Raises
    ------
    ValueError
        If neither ``Courant_GR1`` nor ``Courant_GR2`` is present — this
        indicates a malformed/incomplete source file, not a classification
        outcome.
    """
    import numpy as np

    ib_zero_threshold = 50
    ih_zero_threshold = 50

    has_ih = "Courant_GR1" in df
    has_ib = "Courant_GR2" in df
    if not has_ih and not has_ib:
        raise ValueError(
            "infer_operating_mode: neither Courant_GR1 nor Courant_GR2 present"
        )
    if has_ih != has_ib:
        return "NORMAL"

    try:
        IH = np.asarray(df["Courant_GR1"], dtype=float)
        IB = np.asarray(df["Courant_GR2"], dtype=float)
    except TypeError:
        return "UNKNOWN"

    mask = np.isfinite(IH) & np.isfinite(IB)
    IH, IB = IH[mask], IB[mask]

    if len(IH) == 0:
        return "UNKNOWN"
    if np.nanmax(np.abs(IH)) < ih_zero_threshold:
        return "NORMAL"
    if np.nanmax(np.abs(IB)) < ib_zero_threshold:
        return "NORMAL"

    fit_max_current = 0.25 * np.nanmax(IB)
    fit_mask = (ib_zero_threshold < IB) & (IB < fit_max_current)
    if fit_mask.sum() < 10:
        fit_mask = IB > ib_zero_threshold

    x, y = IB[fit_mask], IH[fit_mask]
    if len(x) < 2:
        return "UNKNOWN"

    slope, _shift = np.polyfit(x, y, 1)
    return "NORMAL" if 0.66 <= slope <= 1.5 else "ECO"


def _resolve_source_path(name: str, housing: str | None) -> str:
    """Resolve a possibly-bare ``sources_*`` filename to a loadable path.

    ``overview_records.sources_*`` columns store basenames only (see
    :func:`insert_overview_record_from_dict`), so a name read back from the
    DB must be re-expanded against ``PIGBROTHER_DATA_DIR``/``PUPITRE_DATA_DIR``
    (env var > ``data_dirs.json`` > hard-coded default; see
    :mod:`python_magnetrun.data_dirs`) before it can be loaded. Already-
    qualified paths, or names that don't resolve to an existing file, are
    returned unchanged.

    Parameters
    ----------
    name : str
        Basename or path of a ``.tdms``/``.txt`` source file.
    housing : str or None
        Housing identifier (e.g. ``"M9"``), needed to locate the ``.txt``
        pupitre subdirectory.

    Returns
    -------
    str
        Resolved path if found, otherwise *name* unchanged.
    """
    from python_magnetrun.data_dirs import PIGBROTHER_DATA_DIR, PUPITRE_DATA_DIR
    from python_magnetrun.utils.files import expand_input_files

    datadir = {".tdms": PIGBROTHER_DATA_DIR, ".txt": PUPITRE_DATA_DIR}
    return expand_input_files([name], datadir, housing=housing)[0]


def _postprocess_overview_record(con, filename: str, verbose: bool = True) -> str:
    """Run mode inference (and future enrichment steps) once assembly_name is known.

    Called from every code path that sets ``overview_records.assembly_name``:
    the insert/upsert/from_dict writers, :func:`attach_assembly_to_overview_record`,
    and :func:`infer_overview_record_fields`.  A no-op until ``assembly_name`` is
    non-NULL and at least one overview source file is on record and readable.

    Parameters
    ----------
    con:
        Open DuckDB connection.
    filename : str
        Primary key of the ``overview_records`` row.
    verbose : bool
        Print a status line when a field is updated.

    Returns
    -------
    str
        ``"applied"``, ``"skipped_no_assembly"``, ``"skipped_no_sources"``,
        ``"skipped_no_mode_data"``, or ``"not_found"``.
    """
    row = con.execute(
        "SELECT assembly_name, sources_overview FROM overview_records WHERE filename = ?",
        [filename],
    ).fetchone()
    if row is None:
        return "not_found"

    assembly_name, sources_overview = row
    if assembly_name is None:
        return "skipped_no_assembly"
    if not sources_overview:
        return "skipped_no_sources"

    housing, _ = _parse_overview_filename(filename)
    overview_path = _resolve_source_path(sources_overview[0], housing)

    from python_magnetrun.magnetdata import load_magnetdata

    try:
        mdata = load_magnetdata(overview_path)
        df_overview = mdata.Data["Courants_Alimentations"]
    except Exception as exc:
        if verbose:
            print(f"  ! overview_record {filename}: could not read {overview_path}: {exc}")
        return "skipped_no_sources"

    try:
        mode = infer_operating_mode(df_overview)
    except ValueError as exc:
        if verbose:
            print(f"  ! overview_record {filename}: {exc}")
        return "skipped_no_mode_data"

    con.execute(
        "UPDATE overview_records SET mode = ? WHERE filename = ?",
        [mode, filename],
    )
    if verbose:
        print(f"  ~ overview_record  {filename}  mode → {mode}")
    return "applied"


def infer_overview_record_fields(
    con, filename: str, db_tz, verbose: bool = True
) -> str:
    """Infer ``housing``/``t0``/``assembly_name``/``duration``/``teb``/``bp`` for one row.

    ``housing`` and ``t0`` are parsed from *filename* (python_magnetrun's
    ``<housing>_Overview_<YYMMDD-HHMM>`` convention); ``assembly_name`` is the
    unique ``assemblies`` row whose commissioned/decommissioned window contains
    ``t0``.  ``duration`` is only re-estimated when the stored value is
    ``0``: read directly from the single ``sources_overview`` file when
    there's exactly one, otherwise as ``(last file's t0 + duration) -
    first file's t0`` across the first and last ``sources_overview``
    entries.  ``teb``/``bp`` are the samples-weighted mean of the ``teb``/``BP``
    columns across every existing ``sources_pupitre`` file.  Requires
    ``python_magnetrun`` to be installed when either source list is
    non-empty.  On success, also runs :func:`_postprocess_overview_record`
    (which sets ``mode`` now that ``assembly_name`` is known).  ``signatures``,
    ``sync_info``, ``flow_params``, ``metrics``, ``debitbrut``, and
    ``plateaux`` are left untouched.

    Parameters
    ----------
    con:
        Open DuckDB connection.
    filename : str
        Primary key of the ``overview_records`` row to update.
    db_tz : zoneinfo.ZoneInfo
        Timezone of the DB's ``commissioned_at``/``decommissioned_at``
        columns.
    verbose : bool
        Print a status line.

    Returns
    -------
    str
        ``"resolved"``, ``"no_assembly_match"``, ``"bad_filename"``, or
        ``"not_found"``.
    """
    row = con.execute(
        "SELECT sources_overview, sources_pupitre, duration FROM overview_records WHERE filename = ?",
        [filename],
    ).fetchone()
    if row is None:
        if verbose:
            print(f"  ! overview_record {filename}: not found")
        return "not_found"
    sources_overview, sources_pupitre, duration_db = row

    housing, t0_db, assembly_name = resolve_overview_assembly(con, filename, db_tz)
    if t0_db is None:
        if verbose:
            print(f"  ! overview_record {filename}: could not parse timestamp from filename")
        return "bad_filename"

    if assembly_name is None:
        if verbose:
            print(
                f"  ! overview_record {filename}: no unique assembly match "
                f"for housing={housing} t0={t0_db}"
            )
        return "no_assembly_match"

    duration = float(duration_db or 0.0)
    if not duration and sources_overview:
        from python_magnetrun.magnetdata import load_magnetdata

        try:
            if len(sources_overview) == 1:
                overview_path = _resolve_source_path(sources_overview[0], housing)
                duration = float(load_magnetdata(overview_path).getDuration())
            else:
                first_path = _resolve_source_path(sources_overview[0], housing)
                last_path = _resolve_source_path(sources_overview[-1], housing)
                first_md = load_magnetdata(first_path)
                last_md = load_magnetdata(last_path)
                last_end = last_md.start_timestamp + timedelta(seconds=last_md.getDuration())
                duration = (last_end - first_md.start_timestamp).total_seconds()
        except Exception as exc:
            print(
                f"  ! overview_record {filename}: could not read duration "
                f"from sources_overview: {exc}"
            )

    pupitre_frames = []
    for pupitre_path in sources_pupitre or []:
        resolved_pupitre_path = _resolve_source_path(pupitre_path, housing)
        from python_magnetrun.magnetdata import load_magnetdata

        try:
            pupitre_frames.append(load_magnetdata(resolved_pupitre_path).Data)
        except Exception as exc:
            print(f"  ! overview_record {filename}: could not read {resolved_pupitre_path}: {exc}")

    teb = _mean_across_frames(pupitre_frames, "teb")
    bp = _mean_across_frames(pupitre_frames, "BP")

    con.execute(
        "UPDATE overview_records SET assembly_name = ?, housing = ?, t0 = ?, "
        "duration = ?, teb = ?, bp = ? WHERE filename = ?",
        [assembly_name, housing, t0_db, duration, teb, bp, filename],
    )
    if verbose:
        print(
            f"  ~ overview_record  {filename}  assembly_name → {assembly_name}  t0={t0_db}  "
            f"duration={duration:.1f}s  teb={teb:.2f}  bp={bp:.2f}"
        )
    _postprocess_overview_record(con, filename, verbose=verbose)
    return "resolved"


def _row_end(row: dict) -> Any:
    """The row's own ``t0 + duration``, or ``None`` if ``t0`` is missing."""
    if row.get("t0") is None:
        return None
    return row["t0"] + timedelta(seconds=float(row.get("duration") or 0.0))


def _merge_overview_rows(existing: dict, incoming: dict) -> dict:
    """Combine two overview_records rows that share a pupitre source file.

    The row with the earlier ``t0`` supplies identity fields (``filename``,
    ``assembly_name``, ``housing``, ``mode``, ``t0``); every ``sources_*``
    column is unioned and de-duplicated; ``duration`` is the span from the
    earlier row's ``t0`` to the true end of whichever constituent ends
    latest (falling back to the sum of the two rows' ``duration`` values
    when either ``t0`` is missing); ``teb`` and ``bp`` become
    duration-weighted averages (weighted by each row's own ``duration``,
    not the merged span); the JSON dict columns are shallow-merged, with
    the earlier row's keys winning on conflict.

    Parameters
    ----------
    existing : dict
        One of the two rows being merged.
    incoming : dict
        The other row being merged.

    Returns
    -------
    dict
        The merged row, keyed like *existing*/*incoming*. ``merged["filename"]``
        is always one of the two input filenames (whichever has the lower
        ``t0``) — the survivor to update in place.
    """
    lower, higher = (
        (existing, incoming)
        if str(existing.get("t0") or "") <= str(incoming.get("t0") or "")
        else (incoming, existing)
    )
    merged = {
        "filename": lower["filename"],
        "assembly_name": lower["assembly_name"],
        "housing": lower["housing"],
        "mode": lower["mode"],
        "t0": lower["t0"],
    }
    for col in _OVERVIEW_SOURCE_LIST_COLUMNS:
        merged[col] = sorted(set(lower.get(col) or []) | set(higher.get(col) or []))

    d_lower = float(lower.get("duration") or 0.0)
    d_higher = float(higher.get("duration") or 0.0)
    total = d_lower + d_higher
    if total > 0:
        merged["teb"] = (
            float(lower.get("teb") or 0.0) * d_lower
            + float(higher.get("teb") or 0.0) * d_higher
        ) / total
        merged["bp"] = (
            float(lower.get("bp") or 0.0) * d_lower
            + float(higher.get("bp") or 0.0) * d_higher
        ) / total
    else:
        merged["teb"] = lower.get("teb")
        merged["bp"] = lower.get("bp")

    for col in _OVERVIEW_JSON_COLUMNS:
        merged[col] = {**(higher.get(col) or {}), **(lower.get(col) or {})}

    # Real end of the latest-in-time constituent absorbed so far — used both
    # to derive `duration` below and for adjacency checks against the next
    # candidate. Not itself a DB column (never persisted).
    ends = [
        e for e in (lower.get("_last_end") or _row_end(lower), higher.get("_last_end") or _row_end(higher))
        if e is not None
    ]
    merged["_last_end"] = max(ends) if ends else None

    first_t0 = lower.get("t0")
    if first_t0 is not None and merged["_last_end"] is not None:
        merged["duration"] = (merged["_last_end"] - first_t0).total_seconds()
    else:
        merged["duration"] = total

    return merged


def _overview_gap_seconds(row_a: dict, row_b: dict) -> float | None:
    """Seconds between the earlier row's real end and the later row's ``t0``.

    *row_a*/*row_b* are sorted by ``t0`` internally, so argument order does
    not matter. A negative result means the windows overlap. The earlier
    row's end is read from its ``_last_end`` key if present (set by
    :func:`_merge_overview_rows` for an already-merged composite, so a
    multi-hop chain compares against the true end of its latest constituent
    rather than a sum of durations that would silently swallow the small
    real dead-time gaps between them) — falling back to its own
    ``t0 + duration`` otherwise.

    Parameters
    ----------
    row_a : dict
        One of the two rows being compared.
    row_b : dict
        The other row being compared.

    Returns
    -------
    float or None
        The gap in seconds, or ``None`` if either row is missing ``t0``.
    """
    t0_a, t0_b = row_a.get("t0"), row_b.get("t0")
    if t0_a is None or t0_b is None:
        return None
    earlier, later = (row_a, row_b) if t0_a <= t0_b else (row_b, row_a)
    end_of_earlier = earlier.get("_last_end") or _row_end(earlier)
    return (later["t0"] - end_of_earlier).total_seconds()


def _find_pupitre_duplicate_pair(group: dict, max_gap_seconds: float) -> tuple[dict, dict] | None:
    """Return the first pair of rows in *group* sharing a pupitre source and time-adjacent.

    A pupitre source file can legitimately be referenced by many separate,
    unrelated Overview captures spanning hours (pupitre logs rotate on a
    much coarser cadence than pigbrother TDMS captures) — so sharing a
    ``sources_pupitre`` entry alone is not a reliable duplicate signal. A
    pair only counts as a duplicate if, in addition, the real gap between
    one row's end (``t0 + duration``) and the other's ``t0`` is within
    *max_gap_seconds* (see :func:`_overview_gap_seconds`) — consistent with
    two captures being one continuous session split across files, rather
    than two genuinely distinct experiments that happen to overlap the same
    pupitre log.

    Parameters
    ----------
    group : dict
        Maps ``filename`` to row dict, for rows already known to share the
        same ``(housing, assembly_name)``.
    max_gap_seconds : float
        Maximum real-time gap (seconds) between the two rows' windows for
        them to still count as adjacent.

    Returns
    -------
    tuple[dict, dict] or None
        The two matching rows, or ``None`` if no pair shares a
        ``sources_pupitre`` entry within *max_gap_seconds*.
    """
    filenames = list(group)
    for i, name_a in enumerate(filenames):
        row_a = group[name_a]
        pupitre_a = set(row_a.get("sources_pupitre") or [])
        if not pupitre_a:
            continue
        for name_b in filenames[i + 1:]:
            row_b = group[name_b]
            if not (pupitre_a & set(row_b.get("sources_pupitre") or [])):
                continue
            gap = _overview_gap_seconds(row_a, row_b)
            if gap is not None and gap <= max_gap_seconds:
                return row_a, row_b
    return None


def _apply_overview_record_merge_update(con, merged: dict) -> None:
    """UPDATE the surviving overview_records row in place with merged field values."""
    set_cols = [c for c in _OVERVIEW_RECORD_COLUMNS if c != "filename"]
    values = [
        json.dumps(merged[col]) if col in _OVERVIEW_JSON_COLUMNS else merged[col]
        for col in set_cols
    ]
    assignments = ", ".join(f"{col} = ?" for col in set_cols)
    con.execute(
        f"UPDATE overview_records SET {assignments} WHERE filename = ?",
        values + [merged["filename"]],
    )


def merge_duplicate_pupitre_records(
    con, verbose: bool = True, max_gap_seconds: float = 60.0
) -> dict:
    """Merge overview_records rows that share a pupitre source file and are time-adjacent.

    Table-wide sweep, intended to run from ``populate overview-records-infer``
    once ``housing``/``assembly_name``/``t0`` have been resolved for the rows
    involved — never at insert time, and never scoped by ``housing`` alone.

    A pupitre log can legitimately be referenced by several genuinely
    distinct Overview captures spanning hours (pupitre rotates on a much
    coarser cadence than pigbrother TDMS captures), so sharing a
    ``sources_pupitre`` entry alone does not mean two rows are duplicates —
    see :func:`_find_pupitre_duplicate_pair`, which additionally requires the
    real gap between the two rows' windows to be within *max_gap_seconds*.

    Live rows (``merged_into IS NULL``) are grouped by ``(housing, assembly_name)``;
    rows with ``assembly_name IS NULL`` form their own ``(housing, NULL)`` group
    and are only ever compared against each other, never against a row that
    already has a resolved ``assembly_name`` for that housing. Within each group,
    any qualifying pair is merged: the row with the lower ``t0`` is the
    survivor, updated in place (via :func:`_merge_overview_rows`); the other
    row is tombstoned — ``merged_into`` set to the survivor's filename —
    rather than deleted, so a later re-populate of its source file cannot
    resurrect and re-merge it. This repeats within each group until no more
    pairs are found, so chains (A–B share a file, B–C share a different
    file) all consolidate onto one survivor. If a row that other tombstoned
    rows already point ``merged_into`` at is itself absorbed into a new
    survivor, those pointers are flattened to the new survivor so
    ``merged_into`` is always exactly one hop from any tombstoned row to the
    current live row.

    Parameters
    ----------
    con:
        Open DuckDB connection.
    verbose : bool
        Print a status line per merge.
    max_gap_seconds : float
        Maximum real-time gap (seconds) between two pupitre-sharing rows'
        windows for them to still count as adjacent (default: 60.0).

    Returns
    -------
    dict
        ``{"groups_checked": int, "merges": int}``.
    """
    rows = con.execute(
        f"SELECT {', '.join(_OVERVIEW_RECORD_COLUMNS)} FROM overview_records "
        "WHERE merged_into IS NULL"
    ).fetchall()

    groups: dict[tuple, dict] = {}
    for values in rows:
        row = dict(zip(_OVERVIEW_RECORD_COLUMNS, values))
        for key in _OVERVIEW_JSON_COLUMNS:
            row[key] = json.loads(row[key]) if row[key] else {}
        groups.setdefault((row["housing"], row["assembly_name"]), {})[row["filename"]] = row

    n_merges = 0
    for group in groups.values():
        while True:
            pair = _find_pupitre_duplicate_pair(group, max_gap_seconds)
            if pair is None:
                break
            merged = _merge_overview_rows(*pair)
            survivor_filename = merged["filename"]
            absorbed_filename = next(
                f for f in (pair[0]["filename"], pair[1]["filename"]) if f != survivor_filename
            )

            _apply_overview_record_merge_update(con, merged)
            con.execute(
                "UPDATE overview_records SET merged_into = ? WHERE filename = ?",
                [survivor_filename, absorbed_filename],
            )
            con.execute(
                "UPDATE overview_records SET merged_into = ? WHERE merged_into = ?",
                [survivor_filename, absorbed_filename],
            )

            group.pop(absorbed_filename)
            group[survivor_filename] = merged
            n_merges += 1
            if verbose:
                print(
                    f"  ~ overview_record  {survivor_filename}  [{merged['housing']}]  "
                    f"merged with {absorbed_filename} (shared pupitre source), "
                    f"duration={merged['duration']:.1f}s"
                )

    if verbose:
        print(
            f"\noverview_records: {n_merges} pupitre-duplicate merge(s) "
            f"across {len(groups)} group(s)."
        )
    return {"groups_checked": len(groups), "merges": n_merges}


def update_assembly_magnet(con, assembly_name: str, magnet_name: str, **kwargs) -> None:
    """Update positional/temporal fields on an existing assembly_magnets row.

    Accepted kwargs: z_offset, r_offset, parallax, commissioned_at,
    decommissioned_at, metadata.  Only non-None values are updated.
    Raises ValueError if the (assembly_name, magnet_name) row does not exist.
    """
    updates = {k: v for k, v in kwargs.items() if k in _ASSEMBLY_MAGNET_FIELDS and v is not None}
    if not updates:
        print("Nothing to update.")
        return

    if not con.execute(
        "SELECT 1 FROM assembly_magnets WHERE assembly_name = ? AND magnet_name = ?",
        [assembly_name, magnet_name],
    ).fetchone():
        raise ValueError(f"No link between assembly '{assembly_name}' and magnet '{magnet_name}'.")

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

    values.extend([assembly_name, magnet_name])
    con.execute(
        f"UPDATE assembly_magnets SET {', '.join(set_clauses)} "
        "WHERE assembly_name = ? AND magnet_name = ?",
        values,
    )
    print(f"Updated assembly_magnets ({assembly_name}, {magnet_name}): {sorted(updates)}")
