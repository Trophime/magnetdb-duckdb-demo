"""
file_context.py
===============
Resolve the context of a pupitre file before it is interpreted: experiment,
assembly, housing and the housing-config version in force at the file start.

Shared by the spec-driven Pupitre ETL (PLAN_pupitre_etl_spec.md, "Assembly
resolution") and the digital twin's header readers (PLAN_digital_twin_schema.md,
L2 "Resolution order"):

1. file → experiment (``experiments.file``: absolute path, or file name in the
   housing's directory);
2. not registered → the assembly of the housing whose
   ``[commissioned_at, decommissioned_at)`` window covers the file start;
3. no assembly → ``assembly = None`` (open question #28);

then the housing version at the file start (first ``Date``/``Time`` row,
Europe/Paris time; the file name when the rows cannot be read).
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from crud import _housing_config_dict, exists
from python_magnetrun.housing_config import HousingConfig
from python_magnetrun.utils.timestamps import parse_txt_filename

PUPITRE_TZ = ZoneInfo("Europe/Paris")


@dataclass(frozen=True)
class FileContext:
    """Context of a pupitre file.

    Attributes
    ----------
    experiment_id : int or None
        ``experiments.id`` when the file is registered.
    assembly : str or None
        Assembly the file belongs to; ``None`` when none covers it.
    housing : str or None
        Housing name (``None`` when unknown).
    housing_version : str
        Housing-config version in force at *t0* (``""`` = base wiring).
    t0 : datetime or None
        File start, timezone-aware (Europe/Paris).
    """

    experiment_id: int | None
    assembly: str | None
    housing: str | None
    housing_version: str
    t0: datetime | None


def file_start(path: Path) -> datetime | None:
    """Return the start of a pupitre file (first data row, else file name), Europe/Paris time."""
    try:
        row = pd.read_csv(path, sep=r"\s+", engine="python", skiprows=1, nrows=1)
        naive = datetime.strptime(
            f"{row['Date'].iloc[0]} {row['Time'].iloc[0]}", "%Y.%m.%d %H:%M:%S"
        )
    except (OSError, KeyError, IndexError, ValueError, pd.errors.ParserError):
        naive = parse_txt_filename(str(path))
    return naive.replace(tzinfo=PUPITRE_TZ) if naive else None


def housing_version_at(con, housing: str, at: datetime | None) -> str:
    """Return the name of the housing-config version of *housing* in force at *at* (``""`` = base)."""
    cfg = HousingConfig.from_dict(_housing_config_dict(con, housing))
    return cfg.at(at).version if at else ""


def resolve_file_context(con, path: str | Path, housing: str | None = None) -> FileContext:
    """Resolve the experiment, assembly, housing and housing version of a pupitre file.

    Parameters
    ----------
    con : duckdb.DuckDBPyConnection
        Open DuckDB connection.
    path : str or :class:`~pathlib.Path`
        Pupitre ``.txt`` file.
    housing : str, optional
        Housing name; by default the name of the file's directory
        (``srv-data-install/<housing>/<file>``).

    Returns
    -------
    FileContext
        The resolved context; ``assembly`` is ``None`` when no assembly of
        the housing covers the file start.
    """
    path = Path(path)
    housing = housing or path.parent.name
    t0 = file_start(path)

    row = con.execute(
        """
        SELECT e.id, e.assembly_name, a.housing
        FROM experiments e JOIN assemblies a ON a.name = e.assembly_name
        WHERE e.file = ? OR (e.file = ? AND a.housing = ?)
        ORDER BY e.id
        LIMIT 1
        """,
        [str(path), path.name, housing],
    ).fetchone()
    if row is not None:
        experiment_id, assembly, housing = row
    else:
        experiment_id, assembly = None, None
        if t0 is not None:
            local = t0.replace(tzinfo=None)  # assemblies store naive local times
            found = con.execute(
                """
                SELECT name FROM assemblies
                WHERE housing = ? AND commissioned_at <= ?
                  AND (decommissioned_at IS NULL OR decommissioned_at > ?)
                ORDER BY commissioned_at DESC
                LIMIT 1
                """,
                [housing, local, local],
            ).fetchone()
            assembly = found[0] if found else None

    if not exists(con, "housing_config", housing):
        return FileContext(experiment_id, assembly, None, "", t0)
    return FileContext(experiment_id, assembly, housing, housing_version_at(con, housing, t0), t0)
