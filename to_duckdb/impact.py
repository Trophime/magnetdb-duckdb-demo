"""
impact.py
=========
Impact of a change made by an ``update`` command on stored, derived results.

One dependency map (:data:`HOOP_STRESS_INPUTS`) lists the source columns the
hoop-stress computation reads; scope resolvers turn a changed row into the
assemblies — hence experiments — whose stored ``hoop_stress_*`` rows were
computed from it. The total field B couples every coil of an assembly, so a
change on one part affects the stresses of *all* parts of every assembly
containing it.

Stale results are **marked**, never deleted: ``hoop_stress_processed``
carries ``stale_since`` / ``stale_reason`` (an ``operation_log.id``), and
``hoop-stress compute`` recomputes marked experiments.

Kept free of heavy dependencies (pyarrow, magnettools, …) so ``crud.py`` can
import it.
"""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from populate import as_aware, parse_pupitre_file_ts

# Source columns read by the hoop-stress computation, per table. A change to
# any of them makes the stored hoop_stress_* rows of the affected assemblies
# stale. Materials: any property (not the free-text description), for now —
# only electrical_conductivity is read by the analytical model today;
# refinement is a follow-up.
HOOP_STRESS_INPUTS: dict[str, frozenset[str]] = {
    "materials": frozenset({
        "nuance", "t_ref", "volumic_mass", "specific_heat",
        "alpha", "electrical_conductivity", "thermal_conductivity",
        "magnet_permeability", "young", "poisson", "expansion_coefficient", "rpe",
    }),
    "parts": frozenset({"material_name", "geometry_data"}),
    "magnets": frozenset({"geometry_data"}),
    "assembly_magnets": frozenset({"z_offset", "commissioned_at"}),
}

_HOOP_STATS_TABLES = ("hoop_stress_bin_stats", "hoop_stress_fatigue", "hoop_stress_fatigue_bins")


def hoop_stress_inputs_changed(table: str, changed_fields) -> list[str]:
    """Return the changed fields of *table* that the hoop-stress computation reads.

    Parameters
    ----------
    table : str
        Source table name, e.g. ``"parts"``.
    changed_fields : iterable of str
        Columns whose value actually changed.

    Returns
    -------
    list of str
        Sorted subset of *changed_fields* listed in :data:`HOOP_STRESS_INPUTS`.
    """
    return sorted(set(changed_fields) & HOOP_STRESS_INPUTS.get(table, frozenset()))


def affected_assemblies(con, table: str, key) -> list[str]:
    """Return the assemblies whose hoop-stress results depend on one source row.

    Parameters
    ----------
    con : duckdb.DuckDBPyConnection
        Open connection.
    table : str
        ``"materials"``, ``"parts"``, ``"magnets"`` or ``"assembly_magnets"``.
    key : str or tuple of str
        Row key: the name, or ``(assembly_name, magnet_name)`` for
        ``assembly_magnets``.

    Returns
    -------
    list of str
        Sorted assembly names.

    Raises
    ------
    ValueError
        If *table* has no resolver.
    """
    if table == "assembly_magnets":
        return [key[0]]
    if table == "magnets":
        where, params = "am.magnet_name = ?", [key]
    elif table == "parts":
        where, params = "am.magnet_name IN (SELECT magnet_name FROM magnet_parts WHERE part_name = ?)", [key]
    elif table == "materials":
        where = (
            "am.magnet_name IN (SELECT mp.magnet_name FROM magnet_parts mp "
            "JOIN parts p ON p.name = mp.part_name WHERE p.material_name = ?)"
        )
        params = [key]
    else:
        raise ValueError(f"No impact resolver for table '{table}'.")
    rows = con.execute(
        f"SELECT DISTINCT am.assembly_name FROM assembly_magnets am WHERE {where} ORDER BY 1",
        params,
    ).fetchall()
    return [r[0] for r in rows]


def hoop_stress_impact(con, assemblies: list[str]) -> dict:
    """Describe the stored hoop-stress results of *assemblies*.

    Only experiments already present in ``hoop_stress_processed`` are
    listed: unprocessed ones have nothing to mark.

    Parameters
    ----------
    con : duckdb.DuckDBPyConnection
        Open connection.
    assemblies : list of str
        Assembly names.

    Returns
    -------
    dict
        ``{"assemblies": [...], "experiment_ids": [...], "rows": {table: count}}``.
    """
    impact = {"assemblies": list(assemblies), "experiment_ids": [], "rows": {}}
    if not assemblies:
        return impact
    marks = ", ".join("?" * len(assemblies))
    exp_ids = [
        r[0] for r in con.execute(
            f"SELECT DISTINCT e.id FROM experiments e "
            f"JOIN hoop_stress_processed h ON h.experiment_id = e.id "
            f"WHERE e.assembly_name IN ({marks}) ORDER BY 1",
            list(assemblies),
        ).fetchall()
    ]
    impact["experiment_ids"] = exp_ids
    if exp_ids:
        id_marks = ", ".join("?" * len(exp_ids))
        for table in _HOOP_STATS_TABLES:
            impact["rows"][table] = con.execute(
                f"SELECT COUNT(*) FROM {table} WHERE experiment_id IN ({id_marks})", exp_ids
            ).fetchone()[0]
    return impact


def find_hoop_stale_impact(con, table: str, key, changed_fields) -> dict | None:
    """Return what a change makes stale, or ``None`` if it touches no hoop-stress input.

    Parameters
    ----------
    con : duckdb.DuckDBPyConnection
        Open connection.
    table : str
        Source table of the change.
    key : str or tuple of str
        Row key (see :func:`affected_assemblies`).
    changed_fields : iterable of str
        Columns whose value actually changed.

    Returns
    -------
    dict or None
        :func:`hoop_stress_impact` result plus ``"inputs"`` (the changed
        hoop-stress inputs), or ``None``.
    """
    inputs = hoop_stress_inputs_changed(table, changed_fields)
    if not inputs:
        return None
    impact = hoop_stress_impact(con, affected_assemblies(con, table, key))
    impact["inputs"] = inputs
    return impact


def mark_hoop_stale(con, experiment_ids: list[int], op_id: int | None) -> int:
    """Mark the hoop-stress results of *experiment_ids* stale.

    An experiment already marked keeps its first ``stale_since`` /
    ``stale_reason``.

    Parameters
    ----------
    con : duckdb.DuckDBPyConnection
        Open connection.
    experiment_ids : list of int
        Experiments to mark.
    op_id : int or None
        ``operation_log.id`` of the change, stored as ``stale_reason``.

    Returns
    -------
    int
        Number of experiments newly marked.
    """
    if not experiment_ids:
        return 0
    marks = ", ".join("?" * len(experiment_ids))
    where = f"experiment_id IN ({marks}) AND stale_since IS NULL"
    n = con.execute(
        f"SELECT COUNT(DISTINCT experiment_id) FROM hoop_stress_processed WHERE {where}",
        list(experiment_ids),
    ).fetchone()[0]
    con.execute(
        f"UPDATE hoop_stress_processed SET stale_since = now(), stale_reason = ? WHERE {where}",
        [op_id, *experiment_ids],
    )
    return n


def stale_summary(impact: dict | None) -> dict | None:
    """Return the compact form of *impact* stored in ``operation_log.details``."""
    if not impact:
        return None
    return {
        "inputs": impact["inputs"],
        "assemblies": impact["assemblies"],
        "experiments": len(impact["experiment_ids"]),
        "rows": impact["rows"],
    }


def format_hoop_stale_report(impact: dict | None, dry_run: bool = False) -> str:
    """Return a human-readable report of *impact* (empty string if nothing is affected).

    Parameters
    ----------
    impact : dict or None
        Result of :func:`find_hoop_stale_impact`.
    dry_run : bool
        Phrase the report as "would be" instead of "now".

    Returns
    -------
    str
        Multi-line report, or ``""``.
    """
    if not impact or not impact["experiment_ids"]:
        return ""
    state = "would become stale" if dry_run else "now stale"
    lines = [
        f"  ! hoop-stress results {state} ({', '.join(impact['inputs'])} changed): "
        f"{len(impact['assemblies'])} assembl{'y' if len(impact['assemblies']) == 1 else 'ies'}, "
        f"{len(impact['experiment_ids'])} experiment(s)",
    ]
    for table, count in impact["rows"].items():
        lines.append(f"      {table}: {count} row(s)")
    assemblies = " ".join(f"--assembly {a}" for a in impact["assemblies"])
    lines.append(f"    recompute with: python magnetdb.py hoop-stress compute {assemblies}")
    return "\n".join(lines)


def decommission_report(
    con, assembly_name: str, decommissioned_at, db_tz: ZoneInfo = ZoneInfo("UTC")
) -> dict:
    """List records still assigned to *assembly_name* but dated after its end.

    ``populate`` never reassigns files, so records assigned while the
    assembly's window was open-ended stay attached after it is closed.

    Parameters
    ----------
    con : duckdb.DuckDBPyConnection
        Open connection.
    assembly_name : str
        Assembly name.
    decommissioned_at : datetime or str
        End of the assembly's window, naive in *db_tz*.
    db_tz : ZoneInfo, optional
        Timezone the DB timestamps are stored in (default UTC, as ``--db-tz``).

    Returns
    -------
    dict
        ``{"experiments": [...], "operationaldata": [...], "overview_records": [...]}``,
        each a sorted list of names.
    """
    if isinstance(decommissioned_at, str):
        decommissioned_at = datetime.fromisoformat(decommissioned_at)
    end_aware = as_aware(decommissioned_at, db_tz)

    def _after_end(table: str) -> list[str]:
        late = []
        for name, file in con.execute(
            f"SELECT name, file FROM {table} WHERE assembly_name = ?", [assembly_name]
        ).fetchall():
            ts = parse_pupitre_file_ts(Path(file).name if file else (name or ""))
            if ts is not None and ts > end_aware:
                late.append(name)
        return sorted(late)

    overview = [
        r[0] for r in con.execute(
            "SELECT filename FROM overview_records WHERE assembly_name = ? AND t0 > ? ORDER BY 1",
            [assembly_name, decommissioned_at],
        ).fetchall()
    ]
    return {
        "experiments": _after_end("experiments"),
        "operationaldata": _after_end("operationaldata"),
        "overview_records": overview,
    }
