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

from crud import load_geometry_json
from enums import AssemblyStatus, LifecycleStatus, MagnetType, PartType
from populate import _RECORDS_BASE as _DEFAULT_RECORDS_BASE
from populate import _SRV_SUBDIR as _DEFAULT_SRV_SUBDIR
from populate import resolve_operationaldata_path

_VALID_MAGNET_TYPES = {t.value for t in MagnetType}
_VALID_LIFECYCLE_STATUSES = {s.value for s in LifecycleStatus}
_VALID_ASSEMBLY_STATUSES = {s.value for s in AssemblyStatus}


# ---------------------------------------------------------------------------
# part
# ---------------------------------------------------------------------------


def check_parts(con, name: str | None = None, fix: bool = False) -> list[dict]:
    """Check that every part has ``geometry``/``geometry_data`` set and a valid status.

    With ``fix=True``, a part that has a ``geometry`` file path but no cached
    ``geometry_data`` has it loaded via :func:`crud.load_geometry_json` and
    written back to the DB. A part with no ``geometry`` path, or whose file
    fails to load, cannot be auto-fixed and is reported as an ordinary
    problem instead.
    """
    query = "SELECT name, geometry, geometry_data, status FROM parts"
    params: list = []
    if name:
        query += " WHERE name = ?"
        params.append(name)
    query += " ORDER BY name"

    results = []
    for part_name, geometry, geometry_data, status in con.execute(query, params).fetchall():
        problems = []
        if geometry is None:
            problems.append("geometry is not set")
        if geometry_data is None:
            if geometry is None:
                problems.append("geometry_data is not set (no geometry path — cannot auto-fix)")
            elif fix:
                loaded = load_geometry_json(geometry)
                if loaded is not None:
                    con.execute(
                        "UPDATE parts SET geometry_data = ? WHERE name = ?",
                        [loaded, part_name],
                    )
                    print(f"  + part {part_name}: geometry_data loaded from '{geometry}'")
                else:
                    problems.append(
                        f"geometry_data is not set and could not be auto-fixed "
                        f"(failed to load '{geometry}')"
                    )
            else:
                problems.append("geometry_data is not set")
        if status is not None and status not in _VALID_LIFECYCLE_STATUSES:
            problems.append(
                f"status '{status}' is not a valid LifecycleStatus ({sorted(_VALID_LIFECYCLE_STATUSES)})"
            )
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
    from python_magnetgeo.deserialize import unserialize_object
    from python_magnetgeo.Insert import Insert
    from python_magnetgeo.Supras import Supras

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
    query = "SELECT name, type, geometry_data, status FROM magnets"
    params: list = []
    if name:
        query += " WHERE name = ?"
        params.append(name)
    query += " ORDER BY name"

    results = []
    for magnet_name, magnet_type, geometry_data, status in con.execute(query, params).fetchall():
        problems = []
        type_is_valid = magnet_type in _VALID_MAGNET_TYPES

        if not type_is_valid:
            problems.append(
                f"type '{magnet_type}' is not a valid MagnetType "
                f"({sorted(_VALID_MAGNET_TYPES)})"
            )

        if status is not None and status not in _VALID_LIFECYCLE_STATUSES:
            problems.append(
                f"status '{status}' is not a valid LifecycleStatus ({sorted(_VALID_LIFECYCLE_STATUSES)})"
            )
        if status == LifecycleStatus.DEAD.value:
            dead_part_count = con.execute(
                "SELECT COUNT(*) FROM magnet_parts mp JOIN parts p ON p.name = mp.part_name "
                "WHERE mp.magnet_name = ? AND p.status = ?",
                [magnet_name, LifecycleStatus.DEAD.value],
            ).fetchone()[0]
            if dead_part_count == 0:
                problems.append(
                    "status is 'dead' but no linked part has status 'dead' "
                    "(violates the dead-part invariant)"
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
# assembly
# ---------------------------------------------------------------------------


def check_assemblies(con, name: str | None = None) -> list[dict]:
    """Check assembly status/``decommissioned_at`` consistency and residual
    per-housing window overlaps.

    A non-``in_study`` assembly's ``status`` must match what's derived from
    ``decommissioned_at`` (``in_operation`` if unset, else ``disassembled``);
    overlaps are checked pairwise across all non-``in_study`` assemblies
    sharing a housing. Both should be impossible to introduce via
    ``insert_assembly``/``decommission_assembly`` — this audits for legacy or
    manually-edited data that predates those invariants.
    """
    query = "SELECT name, status, housing, commissioned_at, decommissioned_at FROM assemblies"
    params: list = []
    if name:
        query += " WHERE name = ?"
        params.append(name)
    query += " ORDER BY name"

    results = []
    for aname, status, housing, commissioned_at, decommissioned_at in con.execute(query, params).fetchall():
        problems = []
        if status is not None and status not in _VALID_ASSEMBLY_STATUSES:
            problems.append(
                f"status '{status}' is not a valid AssemblyStatus ({sorted(_VALID_ASSEMBLY_STATUSES)})"
            )
        elif status is not None and status != AssemblyStatus.IN_STUDY.value:
            expected = (
                AssemblyStatus.IN_OPERATION.value
                if decommissioned_at is None
                else AssemblyStatus.DISASSEMBLED.value
            )
            if status != expected:
                problems.append(
                    f"status '{status}' is inconsistent with decommissioned_at "
                    f"({decommissioned_at if decommissioned_at is not None else 'unset'}); "
                    f"expected '{expected}'"
                )
        results.append({"entity": "assembly", "name": aname, "ok": not problems, "problems": problems})

    overlap_query = """
        SELECT a.name, b.name
        FROM assemblies a
        JOIN assemblies b
          ON a.housing = b.housing AND a.name < b.name AND a.housing IS NOT NULL
        WHERE a.status != ? AND b.status != ?
          AND a.commissioned_at < COALESCE(b.decommissioned_at, TIMESTAMP '9999-12-31')
          AND COALESCE(a.decommissioned_at, TIMESTAMP '9999-12-31') > b.commissioned_at
    """
    overlap_params = [AssemblyStatus.IN_STUDY.value, AssemblyStatus.IN_STUDY.value]
    if name:
        overlap_query += " AND (a.name = ? OR b.name = ?)"
        overlap_params += [name, name]

    overlap_by_name: dict[str, list[str]] = {}
    for a_name, b_name in con.execute(overlap_query, overlap_params).fetchall():
        overlap_by_name.setdefault(a_name, []).append(b_name)
        overlap_by_name.setdefault(b_name, []).append(a_name)

    for r in results:
        others = overlap_by_name.get(r["name"])
        if others:
            r["problems"].append(f"window overlaps assembly(ies) {sorted(others)} on the same housing")
            r["ok"] = False

    return results


# ---------------------------------------------------------------------------
# experiment / operationaldata
# ---------------------------------------------------------------------------


def _check_file_table(con, query: str, params: list, entity: str, resolve) -> list[dict]:
    results = []
    for row_id, row_name, file, *extra in con.execute(query, params).fetchall():
        problems = []
        if not file:
            problems.append("file is not set")
        elif not resolve(file, *extra).exists():
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


def check_experiments(
    con,
    name: str | None = None,
    records_base: Path = _DEFAULT_RECORDS_BASE,
    srv_subdir: str = _DEFAULT_SRV_SUBDIR,
) -> list[dict]:
    """Check that every experiment's ``file`` is set and exists on disk.

    ``experiments.file`` stores a bare pupitre-TXT filename, so it is
    resolved as ``records_base / srv_subdir / housing / file`` (housing
    comes from the linked assembly) before checking existence. Already-
    absolute paths, and rows with no linked assembly, are checked as-is.
    """
    query = (
        "SELECT e.id, e.name, e.file, s.housing "
        "FROM experiments e LEFT JOIN assemblies s ON s.name = e.assembly_name"
    )
    params: list = []
    if name:
        query += " WHERE e.name = ?"
        params.append(name)
    query += " ORDER BY e.id"

    def resolve(file: str, housing: str | None) -> Path:
        p = Path(file)
        if p.is_absolute() or not housing:
            return p
        return records_base / srv_subdir / housing / file

    return _check_file_table(con, query, params, "experiment", resolve)


def check_operationaldata(
    con, name: str | None = None, records_base: Path = _DEFAULT_RECORDS_BASE
) -> list[dict]:
    """Check that every operationaldata row's ``file`` is set and exists on disk.

    ``operationaldata.file`` stores a path relative to *records_base*
    (see :func:`populate.resolve_operationaldata_path`); already-absolute
    legacy paths are checked as-is.
    """
    query = "SELECT id, name, file FROM operationaldata"
    params: list = []
    if name:
        query += " WHERE name = ?"
        params.append(name)
    query += " ORDER BY id"

    def resolve(file: str) -> Path:
        return resolve_operationaldata_path(file, records_base=records_base)

    return _check_file_table(con, query, params, "operationaldata", resolve)


# ---------------------------------------------------------------------------
# orchestration + reporting
# ---------------------------------------------------------------------------

_ENTITY_CHECKS = {
    "part": lambda con, name, fix: check_parts(con, name, fix=fix),
    "magnet": lambda con, name, fix: check_magnets(con, name, fix=fix),
    "assembly": lambda con, name, fix: check_assemblies(con, name),
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
