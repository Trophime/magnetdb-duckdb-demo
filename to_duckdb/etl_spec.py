"""
etl_spec.py
===========
Pupitre ETL spec of an assembly at a housing-config version, built from
DuckDB (PLAN_pupitre_etl_spec.md, step 5).

- The housing part comes from ``housing_config`` + ``housing_config_versions``
  resolved at the file start (``HousingConfig.at``), then the missing-type
  rule drops the electrical fields of a magnet type absent from the assembly.
- Magnet parts come from ``pupitre_etl_magnet``, keyed by housing version
  (decision D1): a wiring change is declared once, as a housing version.
"""

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from crud import _housing_config_dict, _log_operation
from file_context import PUPITRE_TZ
from python_magnetrun.housing_config import HousingConfig
from python_magnetrun.runetl import PupitreEtlSpec, save_pupitre_etl_spec

_IDCCT = re.compile(r"Idcct\d+")


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
        housing part of that version with the missing-type rule applied, and
        the magnet parts stored for that version.

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
    spec["magnets"] = {magnet: json.loads(part) for magnet, part in rows}
    return PupitreEtlSpec.from_dict(spec).to_dict()


def set_magnet_part(con, assembly: str, magnet: str, housing_version: str, part: dict) -> None:
    """Insert or replace the ETL part of a magnet for one housing version.

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
    part : dict
        ``{"channels", "remove", "add", "current"}`` (never ``rename``).

    Raises
    ------
    ValueError
        If the part is invalid, the version is unknown, belongs to another
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
        PupitreEtlSpec(assembly=assembly, housing={"name": "-"}, magnets={magnet: part})
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
            [assembly, magnet, housing_version, json.dumps(part)],
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
