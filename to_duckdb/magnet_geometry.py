"""
magnet_geometry.py
==================
Rebuild a magnet's python_magnetgeo geometry from its parts.

``parts.geometry_data`` is the only geometry stored: a magnet's geometry is
always rebuilt from its parts (an assembly's from its magnets plus the
``assembly_magnets`` offsets, see ``stress_map.py``), and
``magnets.geometry_data`` stays unset. Whether the rebuild works is stored
in ``magnets.geometry_problem`` (NULL = OK, else the error), so readers such
as the dashboard need not rebuild it themselves.
"""

import copy
import json
import logging
from contextlib import contextmanager

from crud import _log_operation
from enums import MagnetType, PartType

_VALID_MAGNET_TYPES = {t.value for t in MagnetType}


@contextmanager
def _quiet_magnetgeo():
    """Silence python_magnetgeo's import INFO lines and bore warnings."""
    previous = logging.root.manager.disable
    logging.disable(logging.WARNING)
    try:
        yield
    finally:
        logging.disable(previous)


def rebuild_magnet_geometry(con, magnet_name: str, magnet_type: str):
    """Rebuild the python_magnetgeo object of a magnet from its parts.

    Mirrors the per-type reconstruction in
    ``stress_map.magnet_geometry_config_to_yaml`` (itself mirroring
    ``Magnet.geometry_config_to_yaml()`` of the Django version), stopping
    short of YAML.

    Parameters
    ----------
    con : duckdb.DuckDBPyConnection
        Open DuckDB connection.
    magnet_name : str
        Magnet to rebuild.
    magnet_type : str
        ``magnets.type`` of that magnet (a :class:`~enums.MagnetType` value).

    Returns
    -------
    python_magnetgeo.Insert.Insert or python_magnetgeo.Bitters.Bitters or python_magnetgeo.Supras.Supras
        The rebuilt magnet.

    Raises
    ------
    ValueError
        If parts are missing, a part lacks ``geometry_data``, a part's type is
        not valid for *magnet_type*, or *magnet_type* is not a
        ``MagnetType`` (e.g. legacy ``'hybrid'`` data). python_magnetgeo may
        raise other exceptions for a part geometry it cannot build.
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
            "corrected manually before its geometry can be rebuilt."
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
            "fix the parts first ('magnetdb.py part update' or 'check --entity part --fix')."
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


def geometry_problem(con, magnet_name: str) -> str | None:
    """Return why a magnet's geometry cannot be rebuilt from its parts.

    Parameters
    ----------
    con : duckdb.DuckDBPyConnection
        Open DuckDB connection.
    magnet_name : str
        Magnet to rebuild.

    Returns
    -------
    str or None
        ``None`` if the rebuild works, else the error message.
    """
    magnet_type = con.execute("SELECT type FROM magnets WHERE name = ?", [magnet_name]).fetchone()[0]
    try:
        with _quiet_magnetgeo():
            rebuild_magnet_geometry(con, magnet_name, magnet_type)
    except Exception as exc:  # python_magnetgeo raises more than ValueError
        return str(exc) or type(exc).__name__
    return None


def refresh_geometry_problem(con, magnet_name: str) -> str | None:
    """Rebuild a magnet's geometry and store the outcome in ``magnets.geometry_problem``.

    When the stored value changes, an ``update`` row with
    ``{"geometry_problem": [old, new]}`` is appended to ``operation_log``.

    Parameters
    ----------
    con : duckdb.DuckDBPyConnection
        Open read-write DuckDB connection.
    magnet_name : str
        Magnet to rebuild.

    Returns
    -------
    str or None
        ``None`` if the rebuild works, else the error message (now stored).
    """
    problem = geometry_problem(con, magnet_name)
    stored = con.execute("SELECT geometry_problem FROM magnets WHERE name = ?", [magnet_name]).fetchone()[0]
    if stored != problem:
        con.execute("UPDATE magnets SET geometry_problem = ? WHERE name = ?", [problem, magnet_name])
        _log_operation(con, "update", "magnets", magnet_name, details={"geometry_problem": [stored, problem]})
    return problem
