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

from pathlib import Path

from crud import load_geometry_json, update_part_from_json
from enums import AssemblyStatus, LifecycleStatus, MagnetType
from magnet_geometry import geometry_problem, refresh_geometry_problem
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
    written back through :func:`crud.update_part_from_json`: logged in
    ``operation_log``, hoop-stress results of the assemblies holding the part
    marked stale, and its magnets' ``geometry_problem`` refreshed. A part
    with no ``geometry`` path, or whose file fails to load, cannot be
    auto-fixed and is reported as an ordinary problem instead.
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
                    update_part_from_json(con, {"name": part_name, "geometry_data": loaded}, verbose=False)
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


def _has_geometry_problem_column(con) -> bool:
    """Whether ``magnets.geometry_problem`` exists (DBs from before it do not)."""
    return con.execute(
        "SELECT COUNT(*) FROM information_schema.columns "
        "WHERE table_name = 'magnets' AND column_name = 'geometry_problem'"
    ).fetchone()[0] > 0


def check_magnets(con, name: str | None = None, fix: bool = False) -> list[dict]:
    """Check magnet type, status, part/type consistency and that the geometry can be rebuilt.

    ``magnets.geometry_data`` is not checked: it stays unset by design, the
    geometry being rebuilt from the parts (see :mod:`magnet_geometry`).
    The rebuild is run and a failure reported as a problem; the stored
    ``magnets.geometry_problem`` is compared with it (when the column
    exists) and reported when out of date.

    Parameters
    ----------
    con : duckdb.DuckDBPyConnection
        Open DuckDB connection (read-write when *fix* is set).
    name : str, optional
        Check only this magnet.
    fix : bool, optional
        Refresh an out-of-date ``magnets.geometry_problem``. Nothing else is
        written.

    Returns
    -------
    list of dict
        One ``{"entity", "name", "ok", "problems"}`` dict per magnet.
    """
    has_stored = _has_geometry_problem_column(con)
    stored_col = "geometry_problem" if has_stored else "NULL"
    query = f"SELECT name, type, status, {stored_col} FROM magnets"
    params: list = []
    if name:
        query += " WHERE name = ?"
        params.append(name)
    query += " ORDER BY name"

    results = []
    for magnet_name, magnet_type, status, stored in con.execute(query, params).fetchall():
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

        problem = geometry_problem(con, magnet_name)
        if problem:
            problems.append(f"geometry cannot be rebuilt from parts: {problem}")
        if has_stored and stored != problem:
            if fix:
                refresh_geometry_problem(con, magnet_name)
                print(f"  + magnet {magnet_name}: geometry_problem refreshed")
            else:
                problems.append("stored geometry_problem is out of date (run 'check --fix')")

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
# dates
# ---------------------------------------------------------------------------


def _first_commissioned(con, query: str, name: str) -> str:
    """Return the ``"first assembly <name> commissioned <date>"`` hint for *query*'s first row."""
    row = con.execute(query, [name]).fetchone()
    if row is None:
        return "not in any commissioned assembly"
    return f"first assembly {row[0]} commissioned {row[1]:%Y-%m-%d}"


def _date_results(entity: str, column: str, n_checked: int, problems: list[dict]) -> list[dict]:
    """Return *problems* plus one OK summary row for the dated rows of *column*."""
    n_dated = n_checked - len(problems)
    summary = [{"entity": entity, "name": f"{column}: {n_dated} row(s) dated", "ok": True, "problems": []}]
    return problems + (summary if n_dated else [])


def _problem(entity: str, name: str, message: str) -> dict:
    return {"entity": entity, "name": name, "ok": False, "problems": [message]}


def check_dates(con, name: str | None = None) -> list[dict]:
    """Report rows whose date is missing or unparseable; never writes.

    Checks ``magnets.assembled_at``, ``parts.manufactured_at``,
    ``overview_records.t0`` (live rows only), ``assemblies.commissioned_at``
    (``in_study`` assemblies exempt) and the timestamp parsed from
    ``experiments.file`` (rows without a file are left to
    :func:`check_experiments`). Each undated row gets one problem with a
    hint on how to fix it; each date column with dated rows gets one OK
    summary row instead of one row per object.

    Parameters
    ----------
    con : duckdb.DuckDBPyConnection
        Open connection; only read.
    name : str, optional
        Restrict every check to the row with this name (magnet, part,
        overview-record filename, assembly or experiment name).

    Returns
    -------
    list[dict]
        Result dicts ``{"entity", "name", "ok", "problems"}``.
    """
    from crud import _parse_overview_filename
    from python_magnetrun.utils.timestamps import parse_filename_timestamp

    def rows(query: str, name_column: str) -> list[tuple]:
        if name:
            query += f" AND {name_column} = ?"
        return con.execute(query + f" ORDER BY {name_column}", [name] if name else []).fetchall()

    results: list[dict] = []

    magnets = rows("SELECT name, assembled_at FROM magnets WHERE TRUE", "name")
    problems = [
        _problem(
            "magnet", magnet,
            "assembled_at is not set ("
            + _first_commissioned(
                con,
                "SELECT s.name, s.commissioned_at FROM assembly_magnets am "
                "JOIN assemblies s ON s.name = am.assembly_name "
                "WHERE am.magnet_name = ? AND s.commissioned_at IS NOT NULL "
                "ORDER BY s.commissioned_at LIMIT 1",
                magnet,
            )
            + "; set it with 'magnet update')",
        )
        for magnet, assembled_at in magnets
        if assembled_at is None
    ]
    results += _date_results("magnet", "assembled_at", len(magnets), problems)

    parts = rows("SELECT name, manufactured_at FROM parts WHERE TRUE", "name")
    problems = [
        _problem(
            "part", part,
            "manufactured_at is not set ("
            + _first_commissioned(
                con,
                "SELECT s.name, s.commissioned_at FROM magnet_parts mp "
                "JOIN assembly_magnets am ON am.magnet_name = mp.magnet_name "
                "JOIN assemblies s ON s.name = am.assembly_name "
                "WHERE mp.part_name = ? AND s.commissioned_at IS NOT NULL "
                "ORDER BY s.commissioned_at LIMIT 1",
                part,
            )
            + "; set it with 'part update')",
        )
        for part, manufactured_at in parts
        if manufactured_at is None
    ]
    results += _date_results("part", "manufactured_at", len(parts), problems)

    records = rows(
        "SELECT filename, t0 FROM overview_records WHERE merged_into IS NULL", "filename"
    )
    problems = []
    for filename, t0 in records:
        if t0 is not None:
            continue
        _, suggested = _parse_overview_filename(filename)
        hint = f"suggested: {suggested:%Y-%m-%d %H:%M} from filename; " if suggested else ""
        problems.append(
            _problem(
                "overview_record", filename,
                f"t0 is not set ({hint}run 'magnetdb.py populate overview-records-infer')",
            )
        )
    results += _date_results("overview_record", "t0", len(records), problems)

    assemblies = rows(
        "SELECT name, commissioned_at FROM assemblies WHERE status != 'in_study'", "name"
    )
    problems = []
    for assembly, commissioned_at in assemblies:
        if commissioned_at is not None:
            continue
        stamps = [
            ts
            for (file,) in con.execute(
                "SELECT file FROM experiments WHERE assembly_name = ? AND file IS NOT NULL",
                [assembly],
            ).fetchall()
            if (ts := parse_filename_timestamp(Path(file).name)) is not None
        ]
        hint = f"earliest experiment: {min(stamps):%Y-%m-%d}" if stamps else "no dated experiment"
        problems.append(
            _problem(
                "assembly", assembly,
                f"commissioned_at is not set ({hint}; set it with 'assembly update')",
            )
        )
    results += _date_results("assembly", "commissioned_at", len(assemblies), problems)

    experiments = rows(
        "SELECT name, id, file FROM experiments WHERE file IS NOT NULL", "name"
    )
    problems = [
        _problem(
            "experiment", f"{exp_name or '?'} (id={exp_id})",
            f"no timestamp can be parsed from file '{file}'",
        )
        for exp_name, exp_id, file in experiments
        if parse_filename_timestamp(Path(file).name) is None
    ]
    results += _date_results("experiment", "file timestamp", len(experiments), problems)

    return results


# ---------------------------------------------------------------------------
# orchestration + reporting
# ---------------------------------------------------------------------------

_ENTITY_CHECKS = {
    "part": lambda con, name, fix: check_parts(con, name, fix=fix),
    "magnet": lambda con, name, fix: check_magnets(con, name, fix=fix),
    "assembly": lambda con, name, fix: check_assemblies(con, name),
    "experiment": lambda con, name, fix: check_experiments(con, name),
    "operationaldata": lambda con, name, fix: check_operationaldata(con, name),
    "dates": lambda con, name, fix: check_dates(con, name),
}

# Run only when asked for by name, not by ``entity="all"``.
_EXPLICIT_ONLY_CHECKS = {"dates"}


def run_checks(con, entity: str = "all", name: str | None = None, fix: bool = False) -> list[dict]:
    """Run the requested entity check(s) and return the combined results list.

    ``entity="all"`` runs every check except ``"dates"``, which runs only
    when named. ``fix`` has no effect on ``"dates"`` (report-only).

    Raises
    ------
    ValueError
        If *entity* is unknown, or if *name* is given together with
        ``entity="all"``.
    """
    if entity == "all":
        if name is not None:
            raise ValueError("--name requires a specific --entity, not 'all'.")
        results = []
        for key, check_fn in _ENTITY_CHECKS.items():
            if key not in _EXPLICIT_ONLY_CHECKS:
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
