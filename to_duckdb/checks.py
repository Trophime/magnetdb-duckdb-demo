"""
checks.py
=========
Data-validity checks for the student magnetdb DuckDB, used by
``magnetdb.py check``.

Each ``check_*`` function returns a list of result dicts:
    {"entity": str, "name": str, "ok": bool, "problems": list[str]}

Kept free of ``stress_map.py``'s heavy plotting/analysis dependencies
(matplotlib, pandas, magnettools, python_magnetsetup, ...) so a plain
validity pass stays cheap to import.
"""

import copy
import json
from pathlib import Path

from enums import MagnetType, PartType

_VALID_MAGNET_TYPES = {t.value for t in MagnetType}


# ---------------------------------------------------------------------------
# part
# ---------------------------------------------------------------------------


def check_parts(con, name: str | None = None) -> list[dict]:
    """Check that every part has both ``geometry`` and ``geometry_data`` set."""
    query = "SELECT name, geometry, geometry_data FROM parts"
    params: list = []
    if name:
        query += " WHERE name = ?"
        params.append(name)
    query += " ORDER BY name"

    results = []
    for part_name, geometry, geometry_data in con.execute(query, params).fetchall():
        problems = []
        if geometry is None:
            problems.append("geometry is not set")
        if geometry_data is None:
            problems.append("geometry_data is not set")
        results.append(
            {"entity": "part", "name": part_name, "ok": not problems, "problems": problems}
        )
    return results


# ---------------------------------------------------------------------------
# magnet
# ---------------------------------------------------------------------------


def _rebuild_magnet_assembly(con, magnet_name: str, magnet_type: str):
    """Reconstruct the python_magnetgeo assembly object for *magnet_name* from
    its parts' ``geometry_data``.

    Mirrors the per-type reconstruction in ``stress_map.magnet_geometry_config_to_yaml``
    (which mirrors ``Magnet.geometry_config_to_yaml()`` from the Django ORM
    version), stopping short of YAML so the caller can serialise to JSON for
    storage in ``magnets.geometry_data``.

    Raises
    ------
    ValueError
        If parts are missing, a part lacks ``geometry_data``, a part's type is
        not valid for *magnet_type*, or *magnet_type* is not a reconstructable
        ``MagnetType`` (e.g. legacy ``'hybrid'`` data).
    """
    from python_magnetgeo.Bitters import Bitters
    from python_magnetgeo.Insert import Insert
    from python_magnetgeo.Supras import Supras
    from python_magnetgeo.deserialize import unserialize_object

    if magnet_type not in _VALID_MAGNET_TYPES:
        raise ValueError(
            f"Magnet '{magnet_name}' has type '{magnet_type}', which is not a "
            f"valid MagnetType ({sorted(_VALID_MAGNET_TYPES)}). This indicates "
            "a data inconsistency (e.g. legacy 'hybrid' data) that must be "
            "corrected manually before geometry_data can be reconstructed."
        )

    parts_rows = con.execute(
        """
        SELECT p.name, p.type, p.geometry_data
        FROM magnet_parts mp
        JOIN parts p ON p.name = mp.part_name
        WHERE mp.magnet_name = ?
        ORDER BY mp.rank
        """,
        [magnet_name],
    ).fetchall()
    if not parts_rows:
        raise ValueError(f"Magnet '{magnet_name}' has no parts in DB.")

    missing = [pn for pn, _, gd in parts_rows if not gd]
    if missing:
        raise ValueError(
            f"Magnet '{magnet_name}': part(s) {missing} have no geometry_data — "
            "re-import with 'magnetdb.py magnet add --geometry' or fix the parts first."
        )

    def _obj(part_name: str, geometry_data: str):
        config = copy.deepcopy(json.loads(geometry_data))
        config["name"] = part_name
        return unserialize_object(config)

    if magnet_type == MagnetType.INSERT.value:
        helices, rings, currentleads = [], [], []
        for part_name, part_type, geometry_data in parts_rows:
            obj = _obj(part_name, geometry_data)
            if part_type == PartType.HELIX.value:
                helices.append(obj)
            elif part_type == PartType.RING.value:
                rings.append(obj)
            elif part_type == PartType.LEAD.value:
                currentleads.append(obj)
            else:
                raise ValueError(
                    f"Unsupported part type '{part_type}' for '{part_name}' in "
                    f"INSERT magnet '{magnet_name}'. Expected HELIX, RING, or LEAD."
                )
        return Insert(
            name=magnet_name,
            helices=helices,
            rings=rings,
            currentleads=currentleads,
            hangles=[0] * len(helices),
            rangles=[0] * len(rings),
            innerbore=0,
            outerbore=0,
        )

    if magnet_type == MagnetType.BITTERS.value:
        magnets, currentleads = [], []
        for part_name, part_type, geometry_data in parts_rows:
            obj = _obj(part_name, geometry_data)
            if part_type == PartType.BITTER.value:
                magnets.append(obj)
            elif part_type == PartType.LEAD.value:
                currentleads.append(obj)
            else:
                raise ValueError(
                    f"Unsupported part type '{part_type}' for '{part_name}' in "
                    f"BITTERS magnet '{magnet_name}'. Expected BITTER or LEAD."
                )
        return Bitters(name=magnet_name, magnets=magnets, innerbore=0, outerbore=0)

    magnets, currentleads = [], []
    for part_name, part_type, geometry_data in parts_rows:
        obj = _obj(part_name, geometry_data)
        if part_type == PartType.SUPRA.value:
            magnets.append(obj)
        elif part_type == PartType.LEAD.value:
            currentleads.append(obj)
        else:
            raise ValueError(
                f"Unsupported part type '{part_type}' for '{part_name}' in "
                f"SUPRAS magnet '{magnet_name}'. Expected SUPRA or LEAD."
            )
    return Supras(name=magnet_name, magnets=magnets, innerbore=0, outerbore=0)


def check_magnets(con, name: str | None = None, fix: bool = False) -> list[dict]:
    """Check magnet type validity, part/type consistency, and geometry_data coverage.

    With ``fix=True``, a magnet with a valid ``MagnetType`` but missing
    ``geometry_data`` has it reconstructed from its parts' ``geometry_data``
    and written back to the DB. A magnet whose ``type`` is not a valid
    ``MagnetType`` (e.g. legacy ``'hybrid'`` data) cannot be auto-fixed —
    this raises ``ValueError`` immediately rather than reporting it as an
    ordinary problem, since such a magnet should not exist under the current
    schema.
    """
    query = "SELECT name, type, geometry_data FROM magnets"
    params: list = []
    if name:
        query += " WHERE name = ?"
        params.append(name)
    query += " ORDER BY name"

    results = []
    for magnet_name, magnet_type, geometry_data in con.execute(query, params).fetchall():
        problems = []
        type_is_valid = magnet_type in _VALID_MAGNET_TYPES

        if not type_is_valid:
            problems.append(
                f"type '{magnet_type}' is not a valid MagnetType "
                f"({sorted(_VALID_MAGNET_TYPES)})"
            )

        if geometry_data is None:
            if not type_is_valid:
                if fix:
                    raise ValueError(
                        f"Magnet '{magnet_name}' has invalid type '{magnet_type}' "
                        "and is missing geometry_data — cannot --fix. Correct "
                        "magnets.type manually first (hybrid magnets are not "
                        "supported by the current schema)."
                    )
                problems.append("geometry_data is not set (and type is invalid — cannot auto-fix)")
            elif fix:
                try:
                    assembly = _rebuild_magnet_assembly(con, magnet_name, magnet_type)
                    from python_magnetgeo.deserialize import serialize_instance
                    new_geometry_data = json.dumps(assembly, default=serialize_instance)
                    con.execute(
                        "UPDATE magnets SET geometry_data = ? WHERE name = ?",
                        [new_geometry_data, magnet_name],
                    )
                    print(f"  + magnet {magnet_name}: geometry_data reconstructed from parts")
                except ValueError as exc:
                    problems.append(f"geometry_data is not set and could not be auto-fixed: {exc}")
            else:
                problems.append("geometry_data is not set")

        if type_is_valid:
            expected = {pt.value for pt in MagnetType(magnet_type).supported_part_types}
            part_rows = con.execute(
                """
                SELECT p.name, p.type
                FROM magnet_parts mp
                JOIN parts p ON p.name = mp.part_name
                WHERE mp.magnet_name = ?
                """,
                [magnet_name],
            ).fetchall()
            for part_name, part_type in part_rows:
                if part_type not in expected:
                    problems.append(
                        f"part '{part_name}' has type '{part_type}', not valid for a "
                        f"{magnet_type} magnet (expected one of {sorted(expected)})"
                    )

        results.append(
            {"entity": "magnet", "name": magnet_name, "ok": not problems, "problems": problems}
        )
    return results


# ---------------------------------------------------------------------------
# experiment / operationaldata
# ---------------------------------------------------------------------------


def _check_file_table(con, table: str, entity: str, name: str | None) -> list[dict]:
    query = f"SELECT id, name, file FROM {table}"
    params: list = []
    if name:
        query += " WHERE name = ?"
        params.append(name)
    query += " ORDER BY id"

    results = []
    for row_id, row_name, file in con.execute(query, params).fetchall():
        problems = []
        if not file:
            problems.append("file is not set")
        elif not Path(file).exists():
            problems.append(f"file '{file}' does not exist on disk")
        results.append(
            {
                "entity": entity,
                "name": f"{row_name or '?'} (id={row_id})",
                "ok": not problems,
                "problems": problems,
            }
        )
    return results


def check_experiments(con, name: str | None = None) -> list[dict]:
    """Check that every experiment's ``file`` is set and exists on disk."""
    return _check_file_table(con, "experiments", "experiment", name)


def check_operationaldata(con, name: str | None = None) -> list[dict]:
    """Check that every operationaldata row's ``file`` is set and exists on disk."""
    return _check_file_table(con, "operationaldata", "operationaldata", name)


# ---------------------------------------------------------------------------
# orchestration + reporting
# ---------------------------------------------------------------------------

_ENTITY_CHECKS = {
    "part": lambda con, name, fix: check_parts(con, name),
    "magnet": lambda con, name, fix: check_magnets(con, name, fix=fix),
    "experiment": lambda con, name, fix: check_experiments(con, name),
    "operationaldata": lambda con, name, fix: check_operationaldata(con, name),
}


def run_checks(con, entity: str = "all", name: str | None = None, fix: bool = False) -> list[dict]:
    """Run the requested entity check(s) and return the combined results list.

    Raises
    ------
    ValueError
        If *entity* is unknown, if *name* is given together with
        ``entity="all"``, or if ``fix`` uncovers an unfixable magnet
        (see ``check_magnets``).
    """
    if entity == "all":
        if name is not None:
            raise ValueError("--name requires a specific --entity, not 'all'.")
        results = []
        for check_fn in _ENTITY_CHECKS.values():
            results.extend(check_fn(con, None, fix))
        return results

    check_fn = _ENTITY_CHECKS.get(entity)
    if check_fn is None:
        raise ValueError(
            f"Unknown entity '{entity}'. Expected one of: all, {', '.join(_ENTITY_CHECKS)}."
        )
    return check_fn(con, name, fix)


def print_check_report(results: list[dict]) -> bool:
    """Print a human-readable validity report.

    Returns ``True`` if every checked object is OK, ``False`` otherwise.
    """
    if not results:
        print("Nothing to check.")
        return True

    n_ok = 0
    for r in results:
        if r["ok"]:
            n_ok += 1
            print(f"[OK]      {r['entity']:<15} {r['name']}")
        else:
            print(f"[PROBLEM] {r['entity']:<15} {r['name']}")
            for p in r["problems"]:
                print(f"            • {p}")

    n_problem = len(results) - n_ok
    print(f"\n{n_ok} OK, {n_problem} problem(s) out of {len(results)} checked.")
    return n_problem == 0
