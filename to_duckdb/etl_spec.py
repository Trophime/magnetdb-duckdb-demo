"""
etl_spec.py
===========
Pupitre ETL spec of an assembly at a housing-config version, built from
DuckDB (PLAN_pupitre_etl_spec.md, step 5).

- The housing part comes from ``housing_config`` + ``housing_config_versions``
  resolved at the file start (``HousingConfig.at``), then the missing-type
  rule drops the electrical fields of a magnet type absent from the assembly.
- Magnet wirings come from ``pupitre_etl_magnet``, keyed by housing version
  (decision D1): a wiring change is declared once, as a housing version.
- Check rules come from ``check_rules`` (housing, assembly and magnet
  levels), merged into the spec; failed checks attach ``tags`` to the file
  in ``record_tags`` (PLAN_file_check_rules.md).
"""

import json
import re
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from crud import _housing_config_dict, _log_operation
from file_context import PUPITRE_TZ
from python_magnetrun.housing_config import HousingConfig
from python_magnetrun.runetl import PupitreEtlSpec, check_rule, save_pupitre_etl_spec

_IDCCT = re.compile(r"Idcct\d+")
_TAG_NAME = re.compile(r"[a-z]+:[a-z0-9_]+")
_TAG_COLOR = re.compile(r"#[0-9a-f]{6}")
CHANNEL_TAG = "check:channel_not_empty"
RESERVED_COLORS = {"#f8d7da": "geometry problems", "#fff3cd": "missing dates"}
RULE_SOURCES = ["pupitre"]
RULE_APPLIES_TO = "experiments"


def _housing_of(con, assembly: str) -> str:
    """Return the housing of *assembly*; ``ValueError`` if the assembly is unknown."""
    row = con.execute("SELECT housing FROM assemblies WHERE name = ?", [assembly]).fetchone()
    if row is None:
        raise ValueError(f"Unknown assembly {assembly!r}")
    return row[0]


def _assembly_window(con, assembly: str) -> tuple[datetime, datetime | None]:
    """Return the assembly's ``[commissioned_at, decommissioned_at)`` as Europe/Paris times."""
    start, end = con.execute(
        "SELECT commissioned_at, decommissioned_at FROM assemblies WHERE name = ?", [assembly]
    ).fetchone()
    return start.replace(tzinfo=PUPITRE_TZ), end.replace(tzinfo=PUPITRE_TZ) if end else None


def _version_windows(con, housing: str) -> list[tuple[str, datetime, datetime | None]]:
    """Return ``(name, valid_from, next valid_from)`` for each version of *housing*."""
    rows = con.execute(
        "SELECT name, valid_from FROM housing_config_versions WHERE housing = ? ORDER BY valid_from",
        [housing],
    ).fetchall()
    return [
        (name, start, rows[i + 1][1] if i + 1 < len(rows) else None)
        for i, (name, start) in enumerate(rows)
    ]


def _overlaps(v_start, v_end, a_start, a_end) -> bool:
    """True when ``[v_start, v_end)`` and ``[a_start, a_end)`` overlap (``None`` = open end)."""
    return (a_end is None or v_start < a_end) and (v_end is None or v_end > a_start)


def _apply_missing_types(housing: dict, cfg: HousingConfig, types: set[str]) -> None:
    """Drop the electrical fields of the group of a magnet type absent from the assembly.

    The group of ``insert`` is the one whose reference current is ``IH``,
    that of ``bitters`` the one with ``IB``; its current and voltage are not
    added, and the current, voltage, ``Ucoil`` channels and ``Idcct`` sources
    are removed. Hydraulics are kept.
    """
    groups = [
        (cfg.reference_gr1_current, cfg.reference_gr1_voltage, cfg.voltage_channels_gr1),
        (cfg.reference_gr2_current, cfg.reference_gr2_voltage, cfg.voltage_channels_gr2),
    ]
    for current, magnet_type in (("IH", "insert"), ("IB", "bitters")):
        if magnet_type in types:
            continue
        for ref_current, ref_voltage, channels in groups:
            if ref_current != current:
                continue
            formula = cfg.pupitre_formula_map.get(current, {}).get("formula", "")
            housing["add"].pop(current, None)
            housing["defaults"].pop(ref_voltage, None)
            housing["remove"] += [current, ref_voltage, *channels, *_IDCCT.findall(formula)]


def build_pupitre_etl_spec(con, assembly_name: str, at: datetime) -> dict:
    """Build the ETL spec of an assembly at a given time.

    Parameters
    ----------
    con : duckdb.DuckDBPyConnection
        Open DuckDB connection.
    assembly_name : str
        Assembly name.
    at : datetime
        Timezone-aware time (e.g. the file start) selecting the housing version.

    Returns
    -------
    dict
        Validated spec in its JSON form (:meth:`PupitreEtlSpec.to_dict`):
        housing part of that version with the missing-type rule applied, the
        magnet wirings stored for that version, and the check rules of the
        housing, the assembly and its magnets that apply to that version.

    Raises
    ------
    ValueError
        If the assembly is unknown or the spec is invalid (merge conflicts).
    """
    housing = _housing_of(con, assembly_name)
    cfg = HousingConfig.from_dict(_housing_config_dict(con, housing)).at(at)
    spec = PupitreEtlSpec.from_housing(cfg, assembly=assembly_name).to_dict()
    types = {
        row[0]
        for row in con.execute(
            "SELECT m.type FROM assembly_magnets am JOIN magnets m ON m.name = am.magnet_name "
            "WHERE am.assembly_name = ?",
            [assembly_name],
        ).fetchall()
    }
    _apply_missing_types(spec["housing"], cfg, types)
    rows = con.execute(
        "SELECT magnet_name, spec FROM pupitre_etl_magnet "
        "WHERE assembly_name = ? AND housing_version = ? ORDER BY magnet_name",
        [assembly_name, cfg.version],
    ).fetchall()
    spec["magnets"] = {magnet: json.loads(wiring) for magnet, wiring in rows}
    spec["rules"] = _merged_rules(con, housing, assembly_name, cfg.version)
    return PupitreEtlSpec.from_dict(spec).to_dict()


def set_magnet_wiring(
    con, assembly: str, magnet: str, housing_version: str, wiring: dict
) -> None:
    """Insert or replace the wiring of a magnet for one housing version.

    Parameters
    ----------
    con : duckdb.DuckDBPyConnection
        Open DuckDB connection (read-write).
    assembly : str
        Assembly name.
    magnet : str
        Magnet of the assembly (checked by the foreign key).
    housing_version : str
        Version of the assembly's housing (``housing_config_versions.name``).
    wiring : dict
        ``{"channels", "remove", "add"}`` (never ``rename``); checks are
        rules (:func:`add_rule`).

    Raises
    ------
    ValueError
        If the wiring is invalid, the version is unknown, belongs to another
        housing, or does not overlap the assembly's lifetime.
    duckdb.ConstraintException
        If the magnet is not part of the assembly.

    Notes
    -----
    Every call writes an ``operation_log`` row (``upsert``, status ``ok`` or
    ``error``), as the other mutating commands do.
    """
    record = f"{assembly}/{magnet}/{housing_version}"
    try:
        PupitreEtlSpec(assembly=assembly, housing={"name": "-"}, magnets={magnet: wiring})
        housing = _housing_of(con, assembly)
        windows = {name: (start, end) for name, start, end in _version_windows(con, housing)}
        if housing_version not in windows:
            other = con.execute(
                "SELECT housing FROM housing_config_versions WHERE name = ?", [housing_version]
            ).fetchone()
            if other:
                raise ValueError(
                    f"Housing version {housing_version!r} belongs to {other[0]!r}, "
                    f"not to {housing!r} (assembly {assembly!r})"
                )
            raise ValueError(f"Unknown housing version {housing_version!r} for {housing!r}")
        if not _overlaps(*windows[housing_version], *_assembly_window(con, assembly)):
            raise ValueError(
                f"Housing version {housing_version!r} does not overlap the lifetime of {assembly!r}"
            )
        con.execute(
            """
            INSERT INTO pupitre_etl_magnet (assembly_name, magnet_name, housing_version, spec)
            VALUES (?, ?, ?, ?)
            ON CONFLICT DO UPDATE SET spec = excluded.spec, updated_at = now()
            """,
            [assembly, magnet, housing_version, json.dumps(wiring)],
        )
        _log_operation(con, "upsert", "pupitre_etl_magnet", record)
    except Exception as exc:
        _log_operation(
            con, "upsert", "pupitre_etl_magnet", record, status="error",
            details={"error": str(exc)},
        )
        raise


def spec_time(con, assembly: str, version: str | None = None) -> datetime:
    """Return a time inside the assembly's lifetime for *version* (default: now or the assembly end).

    Raises ``ValueError`` if *version* does not overlap the assembly.
    """
    a_start, a_end = _assembly_window(con, assembly)
    if version is None:
        now = datetime.now(timezone.utc)
        return now if a_end is None or now < a_end else a_end - timedelta(seconds=1)
    for name, start, end in _version_windows(con, _housing_of(con, assembly)):
        if name == version and _overlaps(start, end, a_start, a_end):
            return max(start, a_start)
    raise ValueError(f"Housing version {version!r} does not overlap {assembly!r}")


def export_pupitre_etl_spec(
    con,
    assembly: str,
    output_dir: str | Path,
    version: str | None = None,
    at: datetime | None = None,
) -> list[Path]:
    """Write ``<assembly>.<housing version>.pupitre-etl.json`` file(s).

    Parameters
    ----------
    con : duckdb.DuckDBPyConnection
        Open DuckDB connection.
    assembly : str
        Assembly name.
    output_dir : str or :class:`~pathlib.Path`
        Destination directory (created if needed).
    version : str, optional
        Export only the spec of this housing version.
    at : datetime, optional
        Export only the spec in force at this timezone-aware time.

    Returns
    -------
    list[:class:`~pathlib.Path`]
        Written files: one per housing version overlapping the assembly when
        neither *version* nor *at* is given.

    Raises
    ------
    ValueError
        If no housing version overlaps the assembly (versions not loaded:
        run ``insert_housing_config_from_magnetrun``).
    """
    if at is not None:
        times = [at]
    elif version is not None:
        times = [spec_time(con, assembly, version)]
    else:
        a_start, a_end = _assembly_window(con, assembly)
        times = [
            max(start, a_start)
            for _, start, end in _version_windows(con, _housing_of(con, assembly))
            if _overlaps(start, end, a_start, a_end)
        ]
        if not times:
            raise ValueError(
                f"No housing version overlaps {assembly!r}: load them with "
                "insert_housing_config_from_magnetrun"
            )
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for when in times:
        spec = PupitreEtlSpec.from_dict(build_pupitre_etl_spec(con, assembly, when))
        path = output_dir / f"{assembly}.{spec.housing['version']}.pupitre-etl.json"
        save_pupitre_etl_spec(path, spec)
        paths.append(path)
    return paths


# ---------------------------------------------------------------------------
# Tags, check rules and record tags (PLAN_file_check_rules.md)
# ---------------------------------------------------------------------------

_SAME_RULE = (
    "name = ? AND housing IS NOT DISTINCT FROM ? AND assembly_name IS NOT DISTINCT FROM ? "
    "AND magnet_name IS NOT DISTINCT FROM ? AND housing_version IS NOT DISTINCT FROM ?"
)


@contextmanager
def _logged(con, operation: str, table: str, record: str):
    """Write an ``operation_log`` row: ``ok`` after the block, ``error`` (re-raised) on failure."""
    try:
        yield
    except Exception as exc:
        _log_operation(con, operation, table, record, status="error", details={"error": str(exc)})
        raise
    _log_operation(con, operation, table, record)


def _rows(cursor) -> list[dict]:
    """Return the rows of an executed DuckDB cursor as dicts."""
    columns = [d[0] for d in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _has_table(con, table: str) -> bool:
    """True when *table* exists (DBs built before PLAN_file_check_rules.md lack the new tables)."""
    return con.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_name = ?", [table]
    ).fetchone() is not None


def _check_color(con, name: str, color: str) -> str:
    """Return *color* in lowercase; ``ValueError`` if malformed, reserved or used by another tag."""
    color = color.lower()
    if not _TAG_COLOR.fullmatch(color):
        raise ValueError(f"Tag colour {color!r}: expected #rrggbb")
    if color in RESERVED_COLORS:
        raise ValueError(f"Tag colour {color} is reserved for {RESERVED_COLORS[color]}")
    other = con.execute("SELECT name FROM tags WHERE color = ? AND name <> ?", [color, name]).fetchone()
    if other:
        raise ValueError(f"Tag colour {color} is already used by {other[0]!r}")
    return color


def _tag_exists(con, name: str) -> bool:
    """True when *name* is in ``tags``."""
    return con.execute("SELECT 1 FROM tags WHERE name = ?", [name]).fetchone() is not None


def add_tag(con, name: str, color: str, severity: int = 1, description: str | None = None) -> None:
    """Define a new tag.

    Parameters
    ----------
    con : duckdb.DuckDBPyConnection
        Open DuckDB connection (read-write).
    name : str
        ``<category>:<name>``, lowercase letters, digits and ``_``
        (e.g. ``"check:current_mismatch"``).
    color : str
        ``#rrggbb``; not ``#f8d7da`` (geometry problems), ``#fff3cd``
        (missing dates) or a colour another tag uses.
    severity : int, optional
        Higher is more severe; the most severe tag of a file sets its colour.
    description : str, optional
        Shown in the dashboard tooltips.

    Raises
    ------
    ValueError
        If the name is malformed or already defined, or the colour is refused.
    """
    with _logged(con, "add", "tags", name):
        if not _TAG_NAME.fullmatch(name):
            raise ValueError(
                f"Tag name {name!r}: expected <category>:<name> (lowercase letters, digits, '_')"
            )
        if _tag_exists(con, name):
            raise ValueError(f"Tag {name!r} already exists (use tag update)")
        color = _check_color(con, name, color)
        con.execute(
            "INSERT INTO tags (name, color, severity, description) VALUES (?, ?, ?, ?)",
            [name, color, int(severity), description],
        )


def update_tag(
    con,
    name: str,
    color: str | None = None,
    severity: int | None = None,
    description: str | None = None,
) -> None:
    """Change the colour, severity or description of a tag.

    Parameters
    ----------
    con : duckdb.DuckDBPyConnection
        Open DuckDB connection (read-write).
    name : str
        Existing tag.
    color : str, optional
        New ``#rrggbb`` colour, checked as in :func:`add_tag`.
    severity : int, optional
        New severity.
    description : str, optional
        New description.

    Raises
    ------
    ValueError
        If the tag is unknown or the colour is refused.
    """
    with _logged(con, "update", "tags", name):
        if not _tag_exists(con, name):
            raise ValueError(f"Unknown tag {name!r}")
        changes = {}
        if color is not None:
            changes["color"] = _check_color(con, name, color)
        if severity is not None:
            changes["severity"] = int(severity)
        if description is not None:
            changes["description"] = description
        if changes:
            assignments = ", ".join(f"{column} = ?" for column in changes)
            con.execute(f"UPDATE tags SET {assignments} WHERE name = ?", [*changes.values(), name])


def remove_tag(con, name: str) -> None:
    """Delete a tag that no rule and no record uses.

    Parameters
    ----------
    con : duckdb.DuckDBPyConnection
        Open DuckDB connection (read-write).
    name : str
        Tag to delete; never :data:`CHANNEL_TAG`.

    Raises
    ------
    ValueError
        If the tag is unknown, is :data:`CHANNEL_TAG`, or is still used.
    """
    with _logged(con, "delete", "tags", name):
        if name == CHANNEL_TAG:
            raise ValueError(f"Tag {name!r} is used by the built-in channel check")
        if not _tag_exists(con, name):
            raise ValueError(f"Unknown tag {name!r}")
        rules = con.execute("SELECT count(*) FROM check_rules WHERE tag = ?", [name]).fetchone()[0]
        if rules:
            raise ValueError(f"Tag {name!r} is used by {rules} rule(s)")
        records = con.execute("SELECT count(*) FROM record_tags WHERE tag = ?", [name]).fetchone()[0]
        if records:
            raise ValueError(f"Tag {name!r} is attached to {records} record(s): re-check them first")
        con.execute("DELETE FROM tags WHERE name = ?", [name])


def list_tags(con) -> list[dict]:
    """Return all tags, by name.

    Parameters
    ----------
    con : duckdb.DuckDBPyConnection
        Open DuckDB connection.

    Returns
    -------
    list[dict]
        ``{"name", "color", "severity", "description"}`` per tag.
    """
    if not _has_table(con, "tags"):
        return []
    return _rows(con.execute("SELECT name, color, severity, description FROM tags ORDER BY name"))


def _rule_record(name, housing, assembly, magnet, version) -> str:
    """``operation_log`` record name of a rule: ``<housing|assembly>[/magnet][@version]:<name>``."""
    where = housing or assembly or "-"
    if magnet:
        where += f"/{magnet}"
    if version:
        where += f"@{version}"
    return f"{where}:{name}"


def add_rule(
    con,
    name: str,
    expr: str,
    stat: str,
    tol: float,
    *,
    housing: str | None = None,
    assembly: str | None = None,
    magnet: str | None = None,
    version: str | None = None,
    unit: str | None = None,
    tag: str | None = None,
    sources: list[str] | None = None,
    applies_to: str = RULE_APPLIES_TO,
    description: str | None = None,
) -> None:
    """Insert or replace a check rule at housing, assembly or magnet level.

    Parameters
    ----------
    con : duckdb.DuckDBPyConnection
        Open DuckDB connection (read-write).
    name : str
        Rule name (letters, digits, ``_``); a rule of the same name at a
        narrower level overrides it.
    expr : str
        Expression on the file's columns after rename and add, e.g.
        ``"IH - Icoil2"`` (see :func:`~python_magnetrun.runetl.check_rule`).
    stat : str
        ``max_abs``, ``p99_abs`` or ``mean_abs`` of the expression's values.
    tol : float
        The check passes when the statistic is ≤ *tol*, in *unit*.
    housing : str, optional
        Housing of a housing rule.
    assembly : str, optional
        Assembly of an assembly or magnet rule (exclusive with *housing*).
    magnet : str, optional
        Magnet of *assembly*, for a magnet rule.
    version : str, optional
        Restrict the rule to this housing version; default: all versions.
    unit : str, optional
        Unit of the expression and *tol*, e.g. ``"A"``.
    tag : str, optional
        Existing tag attached to the file when the rule fails; without it
        the result is only stored in ``etl_checks``.
    sources : list[str], optional
        Data sources; only ``["pupitre"]`` (the default) for now.
    applies_to : str, optional
        Checked records; only ``"experiments"`` for now.
    description : str, optional
        Free text.

    Raises
    ------
    ValueError
        On an invalid rule or scope, an unknown housing, assembly, magnet,
        version or tag, or a rule name already used by another magnet of the
        assembly.
    """
    record = _rule_record(name, housing, assembly, magnet, version)
    with _logged(con, "upsert", "check_rules", record):
        if magnet is not None and assembly is None:
            raise ValueError("A magnet rule needs its assembly")
        if (housing is None) == (assembly is None):
            raise ValueError("Give a housing or an assembly (not both)")
        sources = list(sources or RULE_SOURCES)
        if sources != RULE_SOURCES:
            raise ValueError(f"Rule sources {sources}: only {RULE_SOURCES} is supported for now")
        if applies_to != RULE_APPLIES_TO:
            raise ValueError(
                f"Rule applies_to {applies_to!r}: only {RULE_APPLIES_TO!r} is supported for now"
            )
        rule = {"name": name, "expr": expr, "stat": stat, "tol": tol}
        rule.update({k: v for k, v in (("unit", unit), ("tag", tag)) if v is not None})
        check_rule(rule)
        if housing is not None:
            if not con.execute("SELECT 1 FROM housing_config WHERE name = ?", [housing]).fetchone():
                raise ValueError(f"Unknown housing {housing!r}")
            rule_housing = housing
        else:
            rule_housing = _housing_of(con, assembly)
        if magnet is not None and not con.execute(
            "SELECT 1 FROM assembly_magnets WHERE assembly_name = ? AND magnet_name = ?",
            [assembly, magnet],
        ).fetchone():
            raise ValueError(f"Magnet {magnet!r} is not part of {assembly!r}")
        if version is not None:
            row = con.execute(
                "SELECT housing FROM housing_config_versions WHERE name = ?", [version]
            ).fetchone()
            if row is None:
                raise ValueError(f"Unknown housing version {version!r}")
            if row[0] != rule_housing:
                raise ValueError(
                    f"Housing version {version!r} belongs to {row[0]!r}, not to {rule_housing!r}"
                )
        if tag is not None and not _tag_exists(con, tag):
            raise ValueError(f"Unknown tag {tag!r} (define it with tag add)")
        if magnet is not None:
            other = con.execute(
                "SELECT magnet_name FROM check_rules WHERE assembly_name = ? AND name = ? "
                "AND magnet_name IS NOT NULL AND magnet_name <> ?",
                [assembly, name, magnet],
            ).fetchone()
            if other:
                raise ValueError(
                    f"Rule {name!r} already exists for magnet {other[0]!r} of {assembly!r}; "
                    "two magnets of one assembly cannot share a rule name"
                )
        con.execute(f"DELETE FROM check_rules WHERE {_SAME_RULE}", [name, housing, assembly, magnet, version])
        con.execute(
            """
            INSERT INTO check_rules (name, housing, assembly_name, magnet_name, housing_version,
                                     expr, stat, tol, unit, tag, sources, applies_to, description)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [name, housing, assembly, magnet, version, expr, stat, float(tol), unit, tag,
             sources, applies_to, description],
        )


def remove_rule(
    con,
    name: str,
    *,
    housing: str | None = None,
    assembly: str | None = None,
    magnet: str | None = None,
    version: str | None = None,
) -> None:
    """Delete one check rule, identified by its name and exact scope.

    Parameters
    ----------
    con : duckdb.DuckDBPyConnection
        Open DuckDB connection (read-write).
    name : str
        Rule name.
    housing, assembly, magnet, version : str, optional
        Scope, as given to :func:`add_rule`.

    Raises
    ------
    ValueError
        If no rule has that name and scope.
    """
    record = _rule_record(name, housing, assembly, magnet, version)
    with _logged(con, "delete", "check_rules", record):
        params = [name, housing, assembly, magnet, version]
        if not con.execute(f"SELECT 1 FROM check_rules WHERE {_SAME_RULE}", params).fetchone():
            raise ValueError(f"There is no rule {record!r}")
        con.execute(f"DELETE FROM check_rules WHERE {_SAME_RULE}", params)


def list_rules(con, housing: str | None = None, assembly: str | None = None) -> list[dict]:
    """Return the check rules, optionally those that can apply to a housing or an assembly.

    Parameters
    ----------
    con : duckdb.DuckDBPyConnection
        Open DuckDB connection.
    housing : str, optional
        Rules of this housing and of its assemblies and magnets.
    assembly : str, optional
        Rules of this assembly, of its magnets and of its housing.

    Returns
    -------
    list[dict]
        One dict per ``check_rules`` row (without ``id``), plus
        ``rule_housing``; sorted by housing, assembly, magnet, name, version.
    """
    if not _has_table(con, "check_rules"):
        return []
    return _rows(con.execute(
        """
        SELECT r.name, r.housing, r.assembly_name, r.magnet_name, r.housing_version, r.expr,
               r.stat, r.tol, r.unit, r.tag, r.sources, r.applies_to, r.description,
               COALESCE(r.housing, a.housing) AS rule_housing
        FROM check_rules r LEFT JOIN assemblies a ON a.name = r.assembly_name
        WHERE (? IS NULL OR COALESCE(r.housing, a.housing) = ?)
          AND (? IS NULL OR r.assembly_name = ?
               OR r.housing = (SELECT housing FROM assemblies WHERE name = ?))
        ORDER BY rule_housing, r.assembly_name NULLS FIRST, r.magnet_name NULLS FIRST,
                 r.name, r.housing_version NULLS FIRST
        """,
        [housing, housing, assembly, assembly, assembly],
    ))


def _merged_rules(con, housing: str, assembly: str, version: str) -> list[dict]:
    """Rules of *housing*, *assembly* and its magnets at *version*: magnet > assembly > housing, version-specific > all."""
    if not _has_table(con, "check_rules"):
        return []
    rows = con.execute(
        """
        SELECT name, expr, stat, tol, unit, tag, assembly_name, magnet_name, housing_version
        FROM check_rules
        WHERE applies_to = ? AND (housing_version IS NULL OR housing_version = ?)
          AND (housing = ? OR assembly_name = ?)
        """,
        [RULE_APPLIES_TO, version, housing, assembly],
    ).fetchall()
    ranked = []
    for name, expr, stat, tol, unit, tag, rule_assembly, magnet, rule_version in rows:
        rule = {"name": name, "expr": expr, "stat": stat, "tol": tol}
        rule.update({k: v for k, v in (("unit", unit), ("tag", tag)) if v is not None})
        rule["scope"] = f"magnet:{magnet}" if magnet else "assembly" if rule_assembly else "housing"
        level = 2 if magnet else 1 if rule_assembly else 0
        ranked.append(((level, rule_version is not None), rule))
    merged = {}
    for _, rule in sorted(ranked, key=lambda item: item[0]):
        merged[rule["name"]] = rule
    return [merged[name] for name in sorted(merged)]


def replace_record_tags(con, record_table: str, record_key: str, checks: list[dict]) -> None:
    """Replace the tags of one record by those of its failed checks.

    A failed rule with a ``tag`` gives one row (``rule`` = rule name,
    ``value``, ``tolerance`` = ``tol``); a failed channel check gives one
    :data:`CHANNEL_TAG` row (``rule`` = ``ch<n>``, ``value`` = its largest
    non-zero field, ``tolerance`` = 0). Other results attach no tag.

    Parameters
    ----------
    con : duckdb.DuckDBPyConnection
        Open DuckDB connection (read-write).
    record_table : str
        ``"experiments"``.
    record_key : str
        Record key as text (``experiments.id``).
    checks : list[dict]
        Results of :func:`~python_magnetrun.runetl.prepare_pupitre`.
    """
    con.execute(
        "DELETE FROM record_tags WHERE record_table = ? AND record_key = ?", [record_table, record_key]
    )
    for check in checks:
        if check.get("ok") is not False:
            continue
        if check["kind"] == "rule" and check.get("tag"):
            row = (check["tag"], check["name"], check["value"], check["tol"])
        elif check["kind"] == "channel":
            row = (CHANNEL_TAG, f"ch{check['channel']}", max(check["fields"].values()), 0.0)
        else:
            continue
        con.execute(
            "INSERT INTO record_tags (record_table, record_key, tag, rule, value, tolerance) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [record_table, record_key, *row],
        )
