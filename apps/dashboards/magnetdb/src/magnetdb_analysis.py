import functools
import glob
import json
import os
import re
import time
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

import duckdb
import magnetdb_plot as plot
import numpy as np
import pandas as pd
import scipy.signal as sg
from natsort import natsorted
from python_magnetrun.field_defs import (
    load_defs,
    match_channels_across_formats,
    resolve_defs_file,
)
from python_magnetrun.magnetdata_base import DataType
from python_magnetrun.MagnetRun import load_mrun

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef]

# Chemin absolu vers la base DuckDB (surchargable via variable d'environnement)
DB_PATH = os.environ.get(
    "MAGNETDB_DB_PATH", "/workspaces/magnetdb-duckdb-demo/to_duckdb/test-magnetdb.duckdb"
)
# Répertoire scanné pour lister les bases sélectionnables dans le dropdown
DB_DIR = os.environ.get("MAGNETDB_DB_DIR", os.path.dirname(DB_PATH))

# Timestamps are stored in the database as naive UTC (see to_duckdb/populate.py's
# --db-tz, defaulting to UTC). DISPLAY_TZ is the timezone they are converted to
# for display in the dashboard; override via MAGNETDB_DISPLAY_TZ for deployments
# outside France.
UTC_TZ = ZoneInfo("UTC")
DISPLAY_TZ = ZoneInfo(os.environ.get("MAGNETDB_DISPLAY_TZ", "Europe/Paris"))

print(f"Using DuckDB database: {DB_PATH}")


def to_display_tz(value):
    """Convert a naive UTC timestamp (as stored in the database) to naive `DISPLAY_TZ` local time.

    Parameters
    ----------
    value : datetime, :class:`~pandas.Timestamp`, or :class:`~pandas.Series`
        Naive UTC timestamp(s). ``None``/``NaT`` values pass through
        unchanged.

    Returns
    -------
    same type as *value*
        Naive `DISPLAY_TZ` local time (tzinfo stripped after conversion, so
        it renders the same way as other timestamps in the dashboard).
    """
    if isinstance(value, pd.Series):
        return value.dt.tz_localize(UTC_TZ).dt.tz_convert(DISPLAY_TZ).dt.tz_localize(None)
    if value is None or pd.isna(value):
        return value
    return pd.Timestamp(value).tz_localize(UTC_TZ).tz_convert(DISPLAY_TZ).tz_localize(None)


def get_available_databases(db_dir=None):
    """List the DuckDB database files selectable in the database dropdown.

    Parameters
    ----------
    db_dir : str or :class:`~pathlib.Path`, optional
        Directory to scan for ``*.duckdb`` files. Defaults to `DB_DIR`.

    Returns
    -------
    list of dict
        Each item has ``label`` (filename) and ``value`` (absolute path),
        suitable for a Dash ``dcc.Dropdown`` ``options`` argument.
    """
    directory = db_dir or DB_DIR
    if not os.path.isdir(directory):
        return []
    paths = sorted(glob.glob(os.path.join(directory, "*.duckdb")))
    return [{"label": os.path.basename(p), "value": p} for p in paths]


def get_all_tables(db_path=None):
    """Lists all the tables of the database."""
    with duckdb.connect(db_path or DB_PATH, read_only=True) as conn:
        return (
            conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
            )
            .df()["table_name"]
            .tolist()
        )


_ASSEMBLY_DATE_RE = re.compile(r"_A(\d{6})_\d{2}$")


def _assembly_sort_key(assembly_name):
    """Sort key extracting the YYMMDD date from a ``housing_AYYMMDD_NN`` assembly name."""
    match = _ASSEMBLY_DATE_RE.search(assembly_name)
    return match.group(1) if match else assembly_name


def get_all_assemblies(db_path=None):
    """Select the list of all assemblies, sorted by ascending commissioning date.

    Parameters
    ----------
    db_path : str or :class:`~pathlib.Path`, optional
        Path to the DuckDB database. Defaults to `DB_PATH`.

    Returns
    -------
    list of str
        Assembly names (``assemblies.name``).
    """
    with duckdb.connect(db_path or DB_PATH, read_only=True) as conn:
        query = """
            SELECT name
            FROM assemblies
            ORDER BY commissioned_at ASC
        """
        return conn.execute(query).df()["name"].tolist()


def get_all_parts(db_path=None):
    """Select the list of all parts, sorted by ascending manufacturing date.

    Parameters
    ----------
    db_path : str or :class:`~pathlib.Path`, optional
        Path to the DuckDB database. Defaults to `DB_PATH`.

    Returns
    -------
    list of str
        Part names (``parts.name``).
    """
    with duckdb.connect(db_path or DB_PATH, read_only=True) as conn:
        query = """
            SELECT name
            FROM parts
            ORDER BY manufactured_at ASC
        """
        return conn.execute(query).df()["name"].tolist()


def get_all_magnets(db_path=None):
    """Select the list of all magnets, sorted by ascending assembly date.

    Parameters
    ----------
    db_path : str or :class:`~pathlib.Path`, optional
        Path to the DuckDB database. Defaults to `DB_PATH`.

    Returns
    -------
    list of str
        Magnet names (``magnets.name``).
    """
    with duckdb.connect(db_path or DB_PATH, read_only=True) as conn:
        query = """
            SELECT name
            FROM magnets
            ORDER BY assembled_at ASC
        """
        return conn.execute(query).df()["name"].tolist()


def get_all_experiments(db_path=None):
    """Select the list of all experiments, sorted by the timestamp in their attached filename.

    ``experiments`` has no timestamp column of its own; the ordering is
    derived from the datetime embedded in each row's ``file`` name via
    :func:`parse_magnet_filename`.

    Parameters
    ----------
    db_path : str or :class:`~pathlib.Path`, optional
        Path to the DuckDB database. Defaults to `DB_PATH`.

    Returns
    -------
    list of str
        Experiment names (``experiments.name``).
    """
    with duckdb.connect(db_path or DB_PATH, read_only=True) as conn:
        rows = conn.execute("SELECT name, file FROM experiments").df().to_dict("records")
    rows.sort(key=lambda r: parse_magnet_filename(r["file"]) or datetime.min)
    return [r["name"] for r in rows]


def get_magnet_types_for_assembly(assembly_name, db_path=None):
    """Return the distinct magnet types (e.g. 'insert', 'bitters') defined for an assembly."""
    with duckdb.connect(db_path or DB_PATH, read_only=True) as conn:
        query = """
            SELECT DISTINCT m.type
            FROM assembly_magnets sm
            JOIN magnets m ON m.name = sm.magnet_name
            WHERE sm.assembly_name = ? AND m.type IS NOT NULL
        """
        return conn.execute(query, [assembly_name]).df()["type"].tolist()


def get_magnets_for_assembly(assembly_name, db_path=None):
    """Return the magnets composing an assembly.

    Parameters
    ----------
    assembly_name : str
        ``assemblies.name`` to look up.
    db_path : str, optional
        Path to the DuckDB database. Defaults to `DB_PATH`.

    Returns
    -------
    list of dict
        One entry per magnet, with ``name``, ``type``, ``status``, and
        ``assembled_at``, ordered by name.
    """
    with duckdb.connect(db_path or DB_PATH, read_only=True) as conn:
        query = """
            SELECT m.name, m.type, m.status, m.assembled_at
            FROM assembly_magnets AS sm
            JOIN magnets AS m ON m.name = sm.magnet_name
            WHERE sm.assembly_name = ?
            ORDER BY m.name
        """
        df = conn.execute(query, [assembly_name]).df()
    df["assembled_at"] = to_display_tz(df["assembled_at"])
    return df.to_dict("records")


def get_parts_for_magnet(magnet_name, db_path=None):
    """Return the parts composing a magnet, in physical stacking order.

    Parameters
    ----------
    magnet_name : str
        ``magnets.name`` to look up.
    db_path : str, optional
        Path to the DuckDB database. Defaults to `DB_PATH`.

    Returns
    -------
    list of dict
        One entry per part, with ``name``, ``type``, ``status``,
        ``material_name``, and ``manufactured_at``, ordered by
        ``magnet_parts.rank`` (the part's stacking position in the magnet).
    """
    with duckdb.connect(db_path or DB_PATH, read_only=True) as conn:
        query = """
            SELECT p.name, p.type, p.status, p.material_name, p.manufactured_at
            FROM magnet_parts AS mp
            JOIN parts AS p ON p.name = mp.part_name
            WHERE mp.magnet_name = ?
            ORDER BY mp.rank NULLS LAST, mp.part_name
        """
        df = conn.execute(query, [magnet_name]).df()
    df["manufactured_at"] = to_display_tz(df["manufactured_at"])
    return df.to_dict("records")


def get_files_for_assembly(assembly_name, table_name, db_path=None):
    """
    Interroge la table choisie pour sortir tous les fichiers du assembly.
    C'est ta nouvelle requête SQL clé.
    """
    with duckdb.connect(db_path or DB_PATH, read_only=True) as conn:
        query = f"SELECT DISTINCT file FROM {table_name} WHERE assembly_name = ? AND file IS NOT NULL"
        df = conn.execute(query, [assembly_name]).df()
        return df["file"].tolist()


def get_distinct_statuses(table_name, db_path=None):
    """Return the distinct lifecycle statuses present in *table_name*.

    Parameters
    ----------
    table_name : str
        Either ``"magnets"`` or ``"parts"`` -- both share the same
        lifecycle-status vocabulary (``in_operation``, ``in_stock``,
        ``in_study``, ``retired``, ``dead``).
    db_path : str, optional
        Path to the DuckDB database. Defaults to `DB_PATH`.

    Returns
    -------
    list of str
        Distinct non-null ``status`` values, sorted alphabetically.
    """
    with duckdb.connect(db_path or DB_PATH, read_only=True) as conn:
        query = f"SELECT DISTINCT status FROM {table_name} WHERE status IS NOT NULL ORDER BY status"
        return conn.execute(query).df()["status"].tolist()


def get_names_with_status(table_name, status, db_path=None):
    """Return the names of *table_name* rows matching *status*.

    Parameters
    ----------
    table_name : str
        Either ``"magnets"`` or ``"parts"``.
    status : str
        Lifecycle status to match.
    db_path : str, optional
        Path to the DuckDB database. Defaults to `DB_PATH`.

    Returns
    -------
    list of str
        ``name`` values whose ``status`` equals *status*.
    """
    with duckdb.connect(db_path or DB_PATH, read_only=True) as conn:
        query = f"SELECT name FROM {table_name} WHERE status = ?"
        return conn.execute(query, [status]).df()["name"].tolist()


def get_assembly_names_for_magnets(magnet_names, db_path=None):
    """Return the assembly names linked to any of *magnet_names*.

    Parameters
    ----------
    magnet_names : list of str
        ``magnets.name`` values to look up.
    db_path : str, optional
        Path to the DuckDB database. Defaults to `DB_PATH`.

    Returns
    -------
    list of str
        Distinct ``assembly_magnets.assembly_name`` values.
    """
    if not magnet_names:
        return []
    with duckdb.connect(db_path or DB_PATH, read_only=True) as conn:
        query = "SELECT DISTINCT assembly_name FROM assembly_magnets WHERE magnet_name = ANY(?)"
        return conn.execute(query, [list(magnet_names)]).df()["assembly_name"].tolist()


def get_assembly_names_for_parts(part_names, db_path=None):
    """Return the assembly names linked to any of *part_names* via their magnets.

    Parameters
    ----------
    part_names : list of str
        ``parts.name`` values to look up.
    db_path : str, optional
        Path to the DuckDB database. Defaults to `DB_PATH`.

    Returns
    -------
    list of str
        Distinct ``assembly_magnets.assembly_name`` values.
    """
    if not part_names:
        return []
    with duckdb.connect(db_path or DB_PATH, read_only=True) as conn:
        query = """
            SELECT DISTINCT sm.assembly_name
            FROM assembly_magnets AS sm
            JOIN magnet_parts AS mp ON mp.magnet_name = sm.magnet_name
            WHERE mp.part_name = ANY(?)
        """
        return conn.execute(query, [list(part_names)]).df()["assembly_name"].tolist()


def get_overview_records_for_assembly(assembly_name, db_path=None):
    """Return overview_records rows for an assembly, ordered chronologically.

    Unlike operationaldata, overview_records keys its files under
    ``filename`` (not ``file``) and each row is already a fully processed
    summary, so there is no pupitre/pigbrother pairing to do here.
    """
    with duckdb.connect(db_path or DB_PATH, read_only=True) as conn:
        query = """
            SELECT filename, housing, mode, t0
            FROM overview_records
            WHERE assembly_name = ? AND merged_into IS NULL
            ORDER BY t0 NULLS LAST, filename
        """
        df = conn.execute(query, [assembly_name]).df()
    df["t0"] = to_display_tz(df["t0"])
    return df.to_dict("records")


def get_assembly_history_for_magnet(magnet_name, db_path=None):
    """Return every assembly a magnet has been linked to, ordered by commissioning date.

    Parameters
    ----------
    magnet_name : str
        ``magnets.name`` to look up.
    db_path : str, optional
        Path to the DuckDB database. Defaults to `DB_PATH`.

    Returns
    -------
    list of dict
        One entry per linked assembly, ascending by ``commissioned_at``
        (NULLs last), with ``assembly_name``, ``housing``, ``status``,
        ``commissioned_at``, ``decommissioned_at``.
    """
    with duckdb.connect(db_path or DB_PATH, read_only=True) as conn:
        query = """
            SELECT a.name AS assembly_name, a.housing, a.status,
                   a.commissioned_at, a.decommissioned_at
            FROM assembly_magnets AS sm
            JOIN assemblies AS a ON a.name = sm.assembly_name
            WHERE sm.magnet_name = ?
            ORDER BY a.commissioned_at NULLS LAST
        """
        df = conn.execute(query, [magnet_name]).df()
    df["commissioned_at"] = to_display_tz(df["commissioned_at"])
    df["decommissioned_at"] = to_display_tz(df["decommissioned_at"])
    return df.to_dict("records")


def get_magnet_history_for_part(part_name, db_path=None):
    """Return every magnet a part has been linked to, ordered by assembly date.

    Parameters
    ----------
    part_name : str
        ``parts.name`` to look up.
    db_path : str, optional
        Path to the DuckDB database. Defaults to `DB_PATH`.

    Returns
    -------
    list of dict
        One entry per linked magnet, ascending by ``magnets.assembled_at``
        (NULLs last), with ``magnet_name``, ``type``, ``status``,
        ``assembled_at``, ``rank``, ``coil_index``.
    """
    with duckdb.connect(db_path or DB_PATH, read_only=True) as conn:
        query = """
            SELECT m.name AS magnet_name, m.type, m.status, m.assembled_at,
                   mp.rank, mp.coil_index
            FROM magnet_parts AS mp
            JOIN magnets AS m ON m.name = mp.magnet_name
            WHERE mp.part_name = ?
            ORDER BY m.assembled_at NULLS LAST
        """
        df = conn.execute(query, [part_name]).df()
    df["assembled_at"] = to_display_tz(df["assembled_at"])
    return df.to_dict("records")


def get_assembly_history_for_part(part_name, db_path=None):
    """Return every assembly a part's magnet has been linked to, ordered by commissioning date.

    Traverses part -> magnet (via ``magnet_parts``) -> assembly (via
    ``assembly_magnets``), same shape as :func:`get_assembly_history_for_magnet`.

    Parameters
    ----------
    part_name : str
        ``parts.name`` to look up.
    db_path : str, optional
        Path to the DuckDB database. Defaults to `DB_PATH`.

    Returns
    -------
    list of dict
        One entry per linked assembly, ascending by ``commissioned_at``
        (NULLs last), with ``assembly_name``, ``housing``, ``status``,
        ``commissioned_at``, ``decommissioned_at``.
    """
    with duckdb.connect(db_path or DB_PATH, read_only=True) as conn:
        query = """
            SELECT a.name AS assembly_name, a.housing, a.status,
                   a.commissioned_at, a.decommissioned_at
            FROM magnet_parts AS mp
            JOIN assembly_magnets AS sm ON sm.magnet_name = mp.magnet_name
            JOIN assemblies AS a ON a.name = sm.assembly_name
            WHERE mp.part_name = ?
            ORDER BY a.commissioned_at NULLS LAST
        """
        df = conn.execute(query, [part_name]).df()
    df["commissioned_at"] = to_display_tz(df["commissioned_at"])
    df["decommissioned_at"] = to_display_tz(df["decommissioned_at"])
    return df.to_dict("records")


def get_hoop_stress_summary_for_part(part_name, db_path=None):
    """Aggregate a part's hoop-stress bin-stats and fatigue proxy across every experiment.

    Parameters
    ----------
    part_name : str
        ``parts.name`` to look up.
    db_path : str, optional
        Path to the DuckDB database. Defaults to `DB_PATH`.

    Returns
    -------
    dict
        ``n_experiments``, ``n_samples``, ``mean_MPa`` (time-weighted),
        ``stddev_MPa`` (time-weighted), ``peak_MPa``, ``n_cycles``,
        ``sum_range3`` [MPa^3]. Zeroed/``None`` if the part has no recorded
        hoop-stress data.
    """
    with duckdb.connect(db_path or DB_PATH, read_only=True) as conn:
        n_experiments, n_samples, sum_dt, sum_x_dt, sum_x2_dt, peak_MPa = conn.execute(
            """
            SELECT COUNT(DISTINCT experiment_id) AS n_experiments,
                   SUM(n_samples)  AS n_samples,
                   SUM(sum_dt)     AS sum_dt,
                   SUM(sum_x_dt)   AS sum_x_dt,
                   SUM(sum_x2_dt)  AS sum_x2_dt,
                   MAX(max_x)      AS peak_MPa
            FROM hoop_stress_bin_stats
            WHERE part_name = ?
            """,
            [part_name],
        ).fetchone()
        fatigue_row = conn.execute(
            "SELECT SUM(n_cycles), SUM(sum_range3) FROM hoop_stress_fatigue WHERE part_name = ?",
            [part_name],
        ).fetchone()

    mean_MPa = sum_x_dt / sum_dt if sum_dt else None
    stddev_MPa = None
    if sum_dt and mean_MPa is not None:
        variance = sum_x2_dt / sum_dt - mean_MPa**2
        stddev_MPa = variance**0.5 if variance > 0 else 0.0

    return {
        "n_experiments": n_experiments or 0,
        "n_samples": int(n_samples) if n_samples is not None else 0,
        "mean_MPa": mean_MPa,
        "stddev_MPa": stddev_MPa,
        "peak_MPa": peak_MPa,
        "n_cycles": fatigue_row[0] if fatigue_row and fatigue_row[0] is not None else 0.0,
        "sum_range3": fatigue_row[1] if fatigue_row and fatigue_row[1] is not None else 0.0,
    }


def get_hoop_stress_bin_stats_for_part(part_name, db_path=None):
    """Per-bin hoop-stress sample counts for a part, summed across every experiment.

    Parameters
    ----------
    part_name : str
        ``parts.name`` to look up.
    db_path : str, optional
        Path to the DuckDB database. Defaults to `DB_PATH`.

    Returns
    -------
    :class:`~pandas.DataFrame`
        One row per stress bin, with ``stress_bin_low``, ``stress_bin_high``
        [MPa], ``n_samples``, and ``sum_dt`` [s] (time spent at that stress
        level; divide by 3600 for hours), ascending by ``stress_bin_low``.
        Empty if the part has no recorded hoop-stress data.
    """
    with duckdb.connect(db_path or DB_PATH, read_only=True) as conn:
        return conn.execute(
            """
            SELECT stress_bin_low, stress_bin_high,
                   SUM(n_samples) AS n_samples, SUM(sum_dt) AS sum_dt
            FROM hoop_stress_bin_stats
            WHERE part_name = ?
            GROUP BY stress_bin_low, stress_bin_high
            ORDER BY stress_bin_low
            """,
            [part_name],
        ).df()


def get_hoop_stress_fatigue_for_part(part_name, db_path=None):
    """Per-experiment rainflow fatigue results for a part.

    Parameters
    ----------
    part_name : str
        ``parts.name`` to look up.
    db_path : str, optional
        Path to the DuckDB database. Defaults to `DB_PATH`.

    Returns
    -------
    :class:`~pandas.DataFrame`
        One row per contributing experiment, with ``ID``, ``Experiment``
        (:class:`~pandas.Timestamp`), ``Assembly``, ``File``, ``Cycles``
        (``n_cycles``), and ``Fatigue proxy (MPa^3)`` (``sum_range3``),
        ascending by ``Experiment``. Column names match the page's main
        experiments table so :func:`experiment_links.experiment_link` can be
        reused as-is. Empty if the part has no recorded fatigue data.
    """
    with duckdb.connect(db_path or DB_PATH, read_only=True) as conn:
        df = conn.execute(
            """
            SELECT f.experiment_id AS ID, e.name AS Experiment,
                   e.assembly_name AS Assembly, e.file AS File,
                   f.n_cycles AS Cycles, f.sum_range3 AS "Fatigue proxy (MPa^3)"
            FROM hoop_stress_fatigue AS f
            JOIN experiments AS e ON e.id = f.experiment_id
            WHERE f.part_name = ?
            ORDER BY e.name
            """,
            [part_name],
        ).df()
    df["Experiment"] = pd.to_datetime(df["Experiment"])
    return df


def load_hoop_stress_history_for_part(part_name, db_path=None):
    """Load a part's chronologically-concatenated raw hoop-stress series.

    Reads the Parquet file written by ``magnetdb.py hoop-stress
    part-history`` (``<db_path's directory>/hoop_parquet/parts/<part_name>.parquet``);
    does not compute it if missing.

    Parameters
    ----------
    part_name : str
        ``parts.name`` to look up.
    db_path : str, optional
        Path to the DuckDB database. Defaults to `DB_PATH`.

    Returns
    -------
    :class:`~pandas.DataFrame` or None
        Columns ``timestamp``, ``hoop_stress_MPa``, ``experiment_id``,
        ``assembly_name``, or ``None`` if the file doesn't exist yet.
    """
    path = Path(db_path or DB_PATH).parent / "hoop_parquet" / "parts" / f"{part_name}.parquet"
    return pd.read_parquet(path) if path.exists() else None


@functools.lru_cache(maxsize=128)
def get_overview_record_sources(filename, db_path=None):
    """Fetch one overview_records row's housing, assembly, and source-file lists.

    Parameters
    ----------
    filename : str
        ``overview_records.filename`` primary key.
    db_path : str, optional
        Path to the DuckDB database. Defaults to `DB_PATH`.

    Returns
    -------
    dict or None
        Keys ``housing``, ``assembly_name``, ``sources_overview``,
        ``sources_archive``, ``sources_pupitre``, ``sources_default``,
        ``sources_spike``. ``None`` if *filename* has no matching row.
    """
    with duckdb.connect(db_path or DB_PATH, read_only=True) as conn:
        query = """
            SELECT housing, assembly_name, sources_overview, sources_archive,
                   sources_pupitre, sources_default, sources_spike
            FROM overview_records
            WHERE filename = ?
        """
        result = conn.execute(query, [filename]).df().to_dict("records")
    return result[0] if result else None


def get_db_counts(db_path=None):
    """Return row counts for the main DB-wide entity tables.

    Parameters
    ----------
    db_path : str, optional
        Path to the DuckDB database. Defaults to `DB_PATH`.

    Returns
    -------
    dict
        Keys ``housings``, ``assemblies``, ``magnets``, ``parts``,
        ``experiments``, ``overview_records`` (live rows only, i.e.
        ``merged_into IS NULL``), values are row counts.
    """
    with duckdb.connect(db_path or DB_PATH, read_only=True) as conn:
        query = """
            SELECT
                (SELECT COUNT(*) FROM housing_config) AS housings,
                (SELECT COUNT(*) FROM assemblies) AS assemblies,
                (SELECT COUNT(*) FROM magnets) AS magnets,
                (SELECT COUNT(*) FROM parts) AS parts,
                (SELECT COUNT(*) FROM experiments) AS experiments,
                (SELECT COUNT(*) FROM overview_records WHERE merged_into IS NULL) AS overview_records
        """
        row = conn.execute(query).fetchone()
        columns = [d[0] for d in conn.description]
    return dict(zip(columns, row))


@functools.lru_cache(maxsize=64)
def load_mrun_object(filename, housing):
    """Charge et retourne l'objet MagnetRun complet."""
    return load_mrun(filename=os.path.basename(filename), housing=housing)


@functools.lru_cache(maxsize=64)
def get_group_dataframe(filename, housing, group_name):
    """Return get_group_data(group_name) for filename, cached per (filename, housing, group_name).

    get_group_data() re-slices/rebuilds a DataFrame on every call (for TDMS,
    via getTdmsData) — it isn't free even when load_mrun_object is a cache
    hit. Comparison-page callers all request the same group for the same
    files repeatedly (once per pair-graph), so this is cached separately.
    """
    mrun = load_mrun_object(filename, housing)
    return mrun.MagnetData.get_group_data(group_name)


def parse_magnet_filename(filename):
    """
    Extracts the datetime from a Pupitre or PigBrother filename.
    Returns datetime object ou None si aucun format ne correspond.
    """
    # 1. Format Pupitre : "2025.01.24 - 10:30:29.txt"
    if filename.endswith(".txt"):
        # On cherche un pattern AAAA.MM.JJ - HH:MM:SS
        match = re.search(r"(\d{4})\.(\d{2})\.(\d{2})\s*-\s*(\d{2}):(\d{2})", filename)
        if match:
            year, month, day, hour, minute = match.groups()
            return datetime(int(year), int(month), int(day), int(hour), int(minute))

    # 2. Format PigBrother : "M9_Archive_251202-1430.tdms"
    elif filename.endswith(".tdms"):
        match = re.search(r"(\d{2})(\d{2})(\d{2})-(\d{2})(\d{2})", filename)
        if match:
            year_short, month, day, hour, minute = match.groups()
            # On reconstruit l'année complète (ex: 25 -> 2025)
            year = 2000 + int(year_short)
            return datetime(year, int(month), int(day), int(hour), int(minute))

    return None


def check_same_date(file_pupitre, file_pigbrother, tol=5):
    """
    Check if the Pupitre and PigBrother files are within a certain tolerance in minutes.
    """
    dt_pupitre = parse_magnet_filename(file_pupitre)
    dt_pigbrother = parse_magnet_filename(file_pigbrother)

    if dt_pupitre is None or dt_pigbrother is None:
        return False

    time_lag = abs(dt_pupitre - dt_pigbrother)

    tol_limit = timedelta(minutes=tol)
    
    # Comparaison directe des objets datetime (Année, Mois, Jour, Heure, Minute)
    return time_lag <= tol_limit


def load_json_config(filepath):
    """Load a JSON configuration file and return its content as a dictionary."""
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading JSON config {filepath}: {e}")
    return {}


_PUPITRE_DEFS = load_defs(resolve_defs_file("pupitre-defs.json"))

_DEFS_FORMAT_BY_DATATYPE = {
    DataType.PUPITRE: "pupitre",
    DataType.ENSIGHT: "pupitre",
    DataType.TDMS: "pigbrother",
}

# Channels with a defs.json alias to a tdms channel that isn't actually wired
# for this housing/magnet type — kept in the schema for other magnets, but
# not meaningful to display here.
_GROUP_CHANNEL_EXCLUSIONS = {
    "Tensions_Aimant": {"Ucoil2", "Ucoil3", "Ucoil4"},
}


def get_overview_group_entries(regular_files, housing):
    """Build per-group checklist entries for the overview-records page.

    Groups are keyed on pupitre's group vocabulary first. A pupitre channel
    with a ``pigbrother`` alias whose target ``Group/Channel`` is actually
    present among the tdms (overview/archive) files is folded into one
    matched entry spanning both files' channel names — this is what pulls a
    channel like ``Champ_magn`` into the ``Magnetic_Field`` block instead of
    its native ``Courants_Alimentations`` tdms group, since the alias
    target's own group is resolved explicitly rather than assumed equal to
    the pupitre group. Channels with no match (no alias, or the aliased tdms
    channel isn't present in this record) stay standalone. Leftover tdms
    channels not consumed by any match are appended as their own entries,
    under a block keyed by their tdms group name (merged into a same-named
    pupitre block when one already exists).

    Parameters
    ----------
    regular_files : list of str
        Overview + archive + pupitre source filenames for one overview record.
    housing : str
        Housing identifier, forwarded to :func:`load_mrun_object`.

    Returns
    -------
    dict
        ``{group_name: [{"label": str, "value": str, "channels": {fmt:
        name}}]}``, pupitre groups first (alphabetical), then leftover
        tdms-only groups (alphabetical). Groups left empty by exclusions are
        dropped.
    """
    pupitre_columns = {}
    tdms_columns = {}
    pupitre_mrun_by_channel = {}
    tdms_mrun_by_channel = {}

    for filename in regular_files or []:
        mrun = load_mrun_object(filename, housing)
        if mrun is None:
            continue
        fmt = _DEFS_FORMAT_BY_DATATYPE.get(mrun.MagnetData.Type)
        if fmt is None:
            continue
        target = pupitre_columns if fmt == "pupitre" else tdms_columns
        for group_name in mrun.MagnetData.list_groups():
            if group_name == "Infos":
                continue
            columns = [
                c for c in get_group_dataframe(filename, housing, group_name).columns
                if c not in ("t", "timestamp")
            ]
            target.setdefault(group_name, set()).update(columns)
            if fmt == "pupitre":
                for c in columns:
                    pupitre_mrun_by_channel.setdefault(c, mrun)
            else:
                for c in columns:
                    tdms_mrun_by_channel.setdefault((group_name, c), mrun)

    entries = {}
    consumed_tdms = set()

    for group_name in sorted(pupitre_columns):
        excluded = _GROUP_CHANNEL_EXCLUSIONS.get(group_name, set())
        group_entries = []
        for channel in sorted(pupitre_columns[group_name]):
            if channel in excluded:
                continue
            symbol, unit = plot.group_display_unit(
                pupitre_mrun_by_channel[channel], group_name, channel
            )
            alias = _PUPITRE_DEFS.get(channel, {}).get("aliases", {}).get("pigbrother")
            matched = None
            if alias and "/" in alias:
                tgroup, tchan = alias.split("/", 1)
                if tchan in tdms_columns.get(tgroup, set()):
                    matched = (tgroup, tchan)
            if matched:
                tgroup, tchan = matched
                consumed_tdms.add(matched)
                group_entries.append({
                    "label": plot.format_sensor_label(f"{channel} / {tchan}", symbol, unit),
                    "value": f"{group_name}::{channel}::pigbrother::{tchan}",
                    "channels": {"pupitre": channel, "pigbrother": tchan},
                })
            else:
                group_entries.append({
                    "label": plot.format_sensor_label(channel, symbol, unit),
                    "value": f"{group_name}::{channel}",
                    "channels": {"pupitre": channel},
                })
        entries[group_name] = group_entries

    for tgroup in sorted(tdms_columns):
        leftover = sorted(
            c for c in tdms_columns[tgroup] if (tgroup, c) not in consumed_tdms
        )
        if not leftover:
            continue
        group_entries = entries.setdefault(tgroup, [])
        for channel in leftover:
            symbol, unit = plot.group_display_unit(
                tdms_mrun_by_channel[(tgroup, channel)], tgroup, channel
            )
            group_entries.append({
                "label": plot.format_sensor_label(channel, symbol, unit),
                "value": f"{tgroup}::pigbrother::{channel}",
                "channels": {"pigbrother": channel},
            })

    return {g: e for g, e in entries.items() if e}


def get_comparable_pairs_for_group(group_name, selected_files, housing):
    """Build one entry per comparable channel in *group_name* for the selected files.

    Delegates the cross-format alias matching to
    ``python_magnetrun.field_defs.match_channels_across_formats``.
    """
    channels_by_type = {}
    for filename in selected_files or []:
        mrun = load_mrun_object(filename, housing)
        if mrun is None or group_name not in mrun.MagnetData.list_groups():
            continue
        columns = get_group_dataframe(filename, housing, group_name).columns
        channels_by_type.setdefault(mrun.MagnetData.Type, set()).update(
            c for c in columns if c not in ("t", "timestamp")
        )
    return match_channels_across_formats(channels_by_type, group_name)



def get_lag(df_pupitre, df_pb, column_current_pupitre='Idcct1', column_current_pigbrother='Courant_A1'):
    """
    Calculate the time lag with high precision using FFT on normalized derivatives.
    """

    # 1.Convert timestamps to seconds and extract current values
    t_pupitre = df_pupitre['timestamp'].astype('int64') / 10**9
    t_pb = df_pb['timestamp'].astype('int64') / 10**9

    y_pupitre = df_pupitre[column_current_pupitre].values
    y_pb = df_pb[column_current_pigbrother].values

    # 2. Identify the TRUE overlap zone (INTERSECTION, not union)
    t_min = max(t_pupitre.min(), t_pb.min())  
    t_max = min(t_pupitre.max(), t_pb.max())  

    if t_max - t_min < 10.0:
        return 0.0

    # 3. Create a common time vector with a fixed step (dt) for interpolation
    dt = 0.05  
    t_commun = np.arange(t_min, t_max, dt)

    # 4. Linear interpolation of both signals onto the common time vector
    y_pupitre_interp = np.interp(t_commun, t_pupitre, y_pupitre)
    y_pb_interp = np.interp(t_commun, t_pb, y_pb)

    # 5. Normalization of both signals
    y_pup_norm = (y_pupitre_interp - np.mean(y_pupitre_interp)) / (np.std(y_pupitre_interp) + 1e-9)
    y_pb_norm = (y_pb_interp - np.mean(y_pb_interp)) / (np.std(y_pb_interp) + 1e-9)

    # 6. Compute the derivatives of the normalized signals
    dy_pupitre = np.gradient(y_pup_norm)
    dy_pb = np.gradient(y_pb_norm)

    # 7. Correlation using FFT 
    correlation = sg.correlate(dy_pupitre, dy_pb, mode='full', method='fft')
    lags = sg.correlation_lags(len(dy_pupitre), len(dy_pb), mode='full')

    # 8. Extract best shift (lag) in seconds
    index_max = np.argmax(correlation)
    best_lag_indices = lags[index_max]

    # Convert in seconds
    lag_seconds = float(best_lag_indices * dt)

    return lag_seconds


def get_housings(db_path=None):
    """Return the list of distinct housings defined in ``housing_config``, naturally sorted.

    Parameters
    ----------
    db_path : str or :class:`~pathlib.Path`, optional
        Path to the DuckDB database. Defaults to `DB_PATH`.

    Returns
    -------
    list of str
        Housing names (e.g. ``"M9"``, ``"M10"``), ordered with
        :func:`natsort.natsorted` so ``"M10"`` follows ``"M9"`` instead of
        preceding it lexicographically.
    """
    with duckdb.connect(db_path or DB_PATH, read_only=True) as conn:
        query = "SELECT DISTINCT name FROM housing_config WHERE name IS NOT NULL"
        names = conn.execute(query).df()["name"].tolist()
    return natsorted(names)


def get_housing_file_summary(db_path=None):
    """Return per-housing experiment/overview-record counts and time ranges.

    Parameters
    ----------
    db_path : str or :class:`~pathlib.Path`, optional
        Path to the DuckDB database. Defaults to `DB_PATH`.

    Returns
    -------
    :class:`~pandas.DataFrame`
        One row per housing (naturally sorted, from :func:`get_housings`),
        with columns ``housing``, ``n_experiments``, ``experiments_start``,
        ``experiments_end`` (parsed from ``experiments.name``, ``NaT`` if
        unparseable or none) and ``n_overview_records``,
        ``overview_records_start``, ``overview_records_end`` (from live
        ``overview_records.t0``, i.e. ``merged_into IS NULL``).
    """
    with duckdb.connect(db_path or DB_PATH, read_only=True) as conn:
        experiments_df = conn.execute(
            """
                SELECT a.housing AS housing, e.name AS experiment
                FROM experiments AS e
                JOIN assemblies AS a ON a.name = e.assembly_name
            """
        ).df()
        overview_df = conn.execute(
            "SELECT housing, t0 FROM overview_records WHERE merged_into IS NULL"
        ).df()

    experiments_df["experiment"] = pd.to_datetime(experiments_df["experiment"], errors="coerce")
    exp_summary = experiments_df.groupby("housing").agg(
        n_experiments=("housing", "size"),
        experiments_start=("experiment", "min"),
        experiments_end=("experiment", "max"),
    ).reset_index()

    overview_df["t0"] = pd.to_datetime(overview_df["t0"], errors="coerce")
    ov_summary = overview_df.groupby("housing").agg(
        n_overview_records=("housing", "size"),
        overview_records_start=("t0", "min"),
        overview_records_end=("t0", "max"),
    ).reset_index()

    summary = pd.DataFrame({"housing": get_housings(db_path)})
    summary = summary.merge(exp_summary, on="housing", how="left")
    summary = summary.merge(ov_summary, on="housing", how="left")
    summary["n_experiments"] = summary["n_experiments"].fillna(0).astype(int)
    summary["n_overview_records"] = summary["n_overview_records"].fillna(0).astype(int)
    return summary


def load_assemblies_meta(db_path=None):
    """Load every assembly's name, housing, and commissioning window.

    Parameters
    ----------
    db_path : str, optional
        Path to the DuckDB database. Defaults to `DB_PATH`.

    Returns
    -------
    :class:`~pandas.DataFrame`
        One row per assembly (DB-wide, regardless of whether it has any
        experiments), with ``Assembly``, ``Housing``, ``Commissioned``, and
        ``Decommissioned`` columns. ``Decommissioned`` is ``NaT`` for
        assemblies still in operation.
    """
    with duckdb.connect(db_path or DB_PATH, read_only=True) as conn:
        return conn.execute("""
            SELECT
                name AS Assembly,
                housing AS Housing,
                commissioned_at AS Commissioned,
                decommissioned_at AS Decommissioned
            FROM assemblies
        """).df()


def assemblies_active_in_year(assemblies_meta, year):
    """Return assembly names whose commissioning window overlaps *year*.

    Parameters
    ----------
    assemblies_meta : :class:`~pandas.DataFrame`
        Must have ``Assembly``, ``Commissioned``, ``Decommissioned``
        columns, as returned by :func:`load_assemblies_meta`.
    year : int
        Calendar year to test for overlap.

    Returns
    -------
    set of str
        Assembly names commissioned on or before *year*, and either still
        in operation (``Decommissioned`` is ``NaT``) or decommissioned on
        or after *year*.
    """
    overlap = (assemblies_meta["Commissioned"].dt.year <= year) & (
        assemblies_meta["Decommissioned"].isna() | (assemblies_meta["Decommissioned"].dt.year >= year)
    )
    return set(assemblies_meta.loc[overlap, "Assembly"])


def assemblies_year_range(assemblies_meta):
    """Return the inclusive calendar-year span covered by *assemblies_meta*.

    Parameters
    ----------
    assemblies_meta : :class:`~pandas.DataFrame`
        Must have ``Commissioned``, ``Decommissioned`` columns, as returned
        by :func:`load_assemblies_meta`.

    Returns
    -------
    tuple of int, optional
        ``(min_year, max_year)`` spanning every assembly's commissioned
        year through its decommissioned year (or the current year, for
        assemblies still in operation). ``None`` if there are no assemblies
        with a commissioning date.
    """
    span = pd.concat(
        [assemblies_meta["Commissioned"], assemblies_meta["Decommissioned"].fillna(pd.Timestamp.now())]
    ).dropna()
    if span.empty:
        return None
    return int(span.dt.year.min()), int(span.dt.year.max())


def get_pupitres_for_housing(housing, db_path=None):
    """Return the list of Pupitre files recorded for a given housing.

    Merges two independent sources: ``overview_records.sources_pupitre`` and
    ``experiments.file`` (joined through ``assemblies`` for the housing
    filter, since ``experiments`` has no ``housing`` column). Filenames
    present in ``experiments`` but missing from ``overview_records`` are
    printed as a diagnostic.

    Parameters
    ----------
    housing : str
        Housing name (e.g. ``"M9"``).
    db_path : str or :class:`~pathlib.Path`, optional
        Path to the DuckDB database. Defaults to `DB_PATH`.

    Returns
    -------
    list of str
        Deduplicated Pupitre filenames for *housing*.
    """
    with duckdb.connect(db_path or DB_PATH, read_only=True) as conn:
        overview_pupitres = set(
            conn.execute(
                """
                    SELECT DISTINCT pupitre
                    FROM overview_records, UNNEST(sources_pupitre) AS t(pupitre)
                    WHERE housing = ?
                """,
                [housing],
            ).df()["pupitre"]
        )
        experiment_pupitres = set(
            conn.execute(
                """
                    SELECT DISTINCT e.file AS pupitre
                    FROM experiments AS e
                    JOIN assemblies AS a ON a.name = e.assembly_name
                    WHERE a.housing = ?
                """,
                [housing],
            ).df()["pupitre"]
        )

    missing_from_overview = sorted(experiment_pupitres - overview_pupitres)
    if missing_from_overview:
        print(
            f"[get_pupitres_for_housing] {len(missing_from_overview)} file(s) found in "
            f"experiments but not in overview_records for housing {housing!r}: "
            f"{missing_from_overview}"
        )

    return sorted(overview_pupitres | experiment_pupitres)


def get_linked_files(housing, pupitre_filename, db_path=None):
    """Return the Overview, Archive and Default files linked to a Pupitre file.

    Parameters
    ----------
    housing : str
        Housing name (e.g. ``"M9"``).
    pupitre_filename : str
        Pupitre filename to look up in ``overview_records.sources_pupitre``.
    db_path : str or :class:`~pathlib.Path`, optional
        Path to the DuckDB database. Defaults to `DB_PATH`.

    Returns
    -------
    dict or None
        Dict with ``pigbrother_file`` (str), ``archive_file`` (list of str)
        and ``default_file`` (list of str) keys, or ``None`` if
        *pupitre_filename* has no matching row.
    """
    with duckdb.connect(db_path or DB_PATH, read_only=True) as conn:
        query = """
            SELECT
                sources_overview[1] AS pigbrother_file,
                sources_archive AS archive_file,
                sources_default AS default_file
            FROM overview_records
            WHERE housing = ? AND list_contains(sources_pupitre, ?)
        """
        result = conn.execute(query, [housing, pupitre_filename]).df().to_dict("records")
    return result[0] if result else None


def get_research_areas(db_path=None):
    """Return the list of distinct research areas defined in ``users``, sorted.

    Rows with a ``NULL`` research area are reported as ``"NA"``.

    Parameters
    ----------
    db_path : str or :class:`~pathlib.Path`, optional
        Path to the DuckDB database. Defaults to `DB_PATH`.

    Returns
    -------
    list of str
        Research area names.
    """
    with duckdb.connect(db_path or DB_PATH, read_only=True) as conn:
        query = "SELECT DISTINCT COALESCE(research_area, 'NA') AS research_area FROM users"
        names = conn.execute(query).df()["research_area"].tolist()
    return sorted(names)


def get_users(db_path=None):
    """Return the list of distinct user acronyms defined in ``users``, sorted.

    Duplicate acronyms (rows sharing the same acronym) are collapsed to a
    single entry; any found are printed as a diagnostic.

    Parameters
    ----------
    db_path : str or :class:`~pathlib.Path`, optional
        Path to the DuckDB database. Defaults to `DB_PATH`.

    Returns
    -------
    list of str
        Distinct, sorted user acronyms.
    """
    with duckdb.connect(db_path or DB_PATH, read_only=True) as conn:
        acronyms = conn.execute(
            "SELECT acronym FROM users WHERE acronym IS NOT NULL"
        ).df()["acronym"]

    counts = acronyms.value_counts()
    duplicates = sorted(counts[counts > 1].index)
    if duplicates:
        print(f"[get_users] duplicate acronym(s) found: {duplicates}")

    return sorted(counts.index)


def get_research_area_stats(housing=None, year=None, research_area=None, user=None, db_path=None):
    """Return per-research-area usage statistics from the ``users`` table.

    Parameters
    ----------
    housing : str, optional
        Restrict to sessions on this housing (e.g. ``"M9"``). ``None``
        includes all housings.
    year : str or int, optional
        Restrict to sessions whose ``hstart`` falls in this year. ``None``
        includes all years.
    research_area : str, optional
        Restrict to sessions with this research area (``"NA"`` for sessions
        with no research area recorded). ``None`` includes all research
        areas.
    user : str, optional
        Restrict to sessions with this user acronym. ``None`` includes all
        users.
    db_path : str or :class:`~pathlib.Path`, optional
        Path to the DuckDB database. Defaults to `DB_PATH`.

    Returns
    -------
    :class:`~pandas.DataFrame`
        One row per research area, with columns ``research_area`` (``"NA"``
        for sessions with no research area recorded), ``n_experiments``
        (distinct experiments), ``n_users`` (distinct acronyms) and
        ``total_field_time_s`` (summed ``exp_run_scalars.value`` where
        ``channel = 'duration_field_on_s'`` [s]).
    """
    with duckdb.connect(db_path or DB_PATH, read_only=True) as conn:
        query = """
            WITH filtered_users AS (
                SELECT * EXCLUDE (research_area), COALESCE(research_area, 'NA') AS research_area
                FROM users
                WHERE (? IS NULL OR housing = ?)
                    AND (? IS NULL OR EXTRACT(YEAR FROM hstart) = ?)
                    AND (? IS NULL OR COALESCE(research_area, 'NA') = ?)
                    AND (? IS NULL OR acronym = ?)
            ),
            exp_counts AS (
                SELECT research_area, COUNT(DISTINCT eid) AS n_experiments
                FROM filtered_users, UNNEST(experiments_ids) AS t(eid)
                GROUP BY research_area
            ),
            user_counts AS (
                SELECT research_area, COUNT(DISTINCT acronym) AS n_users
                FROM filtered_users
                GROUP BY research_area
            ),
            field_time AS (
                SELECT fu.research_area, SUM(s.value) AS total_field_time_s
                FROM filtered_users AS fu, UNNEST(fu.experiments_ids) AS t(eid)
                JOIN exp_run_scalars AS s ON s.experiment_id = t.eid AND s.channel = 'duration_field_on_s'
                GROUP BY fu.research_area
            )
            SELECT
                u.research_area,
                COALESCE(e.n_experiments, 0) AS n_experiments,
                u.n_users,
                COALESCE(f.total_field_time_s, 0.0) AS total_field_time_s
            FROM user_counts AS u
            LEFT JOIN exp_counts AS e ON e.research_area = u.research_area
            LEFT JOIN field_time AS f ON f.research_area = u.research_area
            ORDER BY u.research_area
        """
        year = None if year is None else int(year)
        params = [housing, housing, year, year, research_area, research_area, user, user]
        return conn.execute(query, params).df()


def get_research_area_stats_by_year(housing=None, year=None, research_area=None, user=None, db_path=None):
    """Return per-(research-area, year) usage statistics from the ``users`` table.

    Same semantics as :func:`get_research_area_stats`, but broken out by
    the ``users.hstart`` session year instead of aggregated across all
    years.

    Parameters
    ----------
    housing : str, optional
        Restrict to sessions on this housing (e.g. ``"M9"``). ``None``
        includes all housings.
    year : str or int, optional
        Restrict to sessions whose ``hstart`` falls in this year. ``None``
        includes all years.
    research_area : str, optional
        Restrict to sessions with this research area (``"NA"`` for sessions
        with no research area recorded). ``None`` includes all research
        areas.
    user : str, optional
        Restrict to sessions with this user acronym. ``None`` includes all
        users.
    db_path : str or :class:`~pathlib.Path`, optional
        Path to the DuckDB database. Defaults to `DB_PATH`.

    Returns
    -------
    :class:`~pandas.DataFrame`
        One row per ``(research_area, year)`` combination present in the
        matching sessions, with columns ``research_area`` (``"NA"`` for
        sessions with no research area recorded), ``year`` (extracted from
        ``users.hstart``), ``n_experiments`` (distinct experiments),
        ``n_users`` (distinct acronyms) and ``total_field_time_s`` (summed
        ``exp_run_scalars.value`` where ``channel = 'duration_field_on_s'``
        [s]).
    """
    with duckdb.connect(db_path or DB_PATH, read_only=True) as conn:
        query = """
            WITH filtered_users AS (
                SELECT * EXCLUDE (research_area), COALESCE(research_area, 'NA') AS research_area,
                    EXTRACT(YEAR FROM hstart) AS session_year
                FROM users
                WHERE (? IS NULL OR housing = ?)
                    AND (? IS NULL OR EXTRACT(YEAR FROM hstart) = ?)
                    AND (? IS NULL OR COALESCE(research_area, 'NA') = ?)
                    AND (? IS NULL OR acronym = ?)
            ),
            exp_counts AS (
                SELECT research_area, session_year, COUNT(DISTINCT eid) AS n_experiments
                FROM filtered_users, UNNEST(experiments_ids) AS t(eid)
                GROUP BY research_area, session_year
            ),
            user_counts AS (
                SELECT research_area, session_year, COUNT(DISTINCT acronym) AS n_users
                FROM filtered_users
                GROUP BY research_area, session_year
            ),
            field_time AS (
                SELECT fu.research_area, fu.session_year, SUM(s.value) AS total_field_time_s
                FROM filtered_users AS fu, UNNEST(fu.experiments_ids) AS t(eid)
                JOIN exp_run_scalars AS s ON s.experiment_id = t.eid AND s.channel = 'duration_field_on_s'
                GROUP BY fu.research_area, fu.session_year
            )
            SELECT
                u.research_area,
                u.session_year AS year,
                COALESCE(e.n_experiments, 0) AS n_experiments,
                u.n_users,
                COALESCE(f.total_field_time_s, 0.0) AS total_field_time_s
            FROM user_counts AS u
            LEFT JOIN exp_counts AS e ON e.research_area = u.research_area AND e.session_year = u.session_year
            LEFT JOIN field_time AS f ON f.research_area = u.research_area AND f.session_year = u.session_year
            ORDER BY u.research_area, u.session_year
        """
        year = None if year is None else int(year)
        params = [housing, housing, year, year, research_area, research_area, user, user]
        return conn.execute(query, params).df()


def get_experiments_for_filters(housing=None, year=None, research_area=None, user=None, db_path=None):
    """Return experiments linked to users matching the given filters.

    Parameters
    ----------
    housing : str, optional
        Restrict to sessions on this housing (e.g. ``"M9"``). ``None``
        includes all housings.
    year : str or int, optional
        Restrict to sessions whose ``hstart`` falls in this year. ``None``
        includes all years.
    research_area : str, optional
        Restrict to sessions with this research area (``"NA"`` for sessions
        with no research area recorded). ``None`` includes all research
        areas.
    user : str, optional
        Restrict to sessions with this user acronym. ``None`` includes all
        users.
    db_path : str or :class:`~pathlib.Path`, optional
        Path to the DuckDB database. Defaults to `DB_PATH`.

    Returns
    -------
    :class:`~pandas.DataFrame`
        One row per distinct experiment linked to a matching ``users``
        session, with columns ``id``, ``name``, ``description``, ``file``,
        ``assembly_name`` and ``status``.
    """
    with duckdb.connect(db_path or DB_PATH, read_only=True) as conn:
        query = """
            WITH filtered_users AS (
                SELECT *
                FROM users
                WHERE (? IS NULL OR housing = ?)
                    AND (? IS NULL OR EXTRACT(YEAR FROM hstart) = ?)
                    AND (? IS NULL OR COALESCE(research_area, 'NA') = ?)
                    AND (? IS NULL OR acronym = ?)
            )
            SELECT DISTINCT e.id, e.name, e.description, e.file, e.assembly_name, e.status
            FROM filtered_users AS u, UNNEST(u.experiments_ids) AS t(eid)
            JOIN experiments AS e ON e.id = t.eid
            ORDER BY e.name
        """
        year = None if year is None else int(year)
        params = [housing, housing, year, year, research_area, research_area, user, user]
        return conn.execute(query, params).df()


def get_overview_records_for_filters(housing=None, year=None, research_area=None, user=None, db_path=None):
    """Return overview records linked to users matching the given filters.

    Parameters
    ----------
    housing : str, optional
        Restrict to sessions on this housing (e.g. ``"M9"``). ``None``
        includes all housings.
    year : str or int, optional
        Restrict to sessions whose ``hstart`` falls in this year. ``None``
        includes all years.
    research_area : str, optional
        Restrict to sessions with this research area (``"NA"`` for sessions
        with no research area recorded). ``None`` includes all research
        areas.
    user : str, optional
        Restrict to sessions with this user acronym. ``None`` includes all
        users.
    db_path : str or :class:`~pathlib.Path`, optional
        Path to the DuckDB database. Defaults to `DB_PATH`.

    Returns
    -------
    :class:`~pandas.DataFrame`
        One row per distinct live (``merged_into IS NULL``) overview record
        linked to a matching ``users`` session, with columns ``filename``,
        ``assembly_name``, ``housing``, ``mode``, ``t0`` and ``duration``
        [s].
    """
    with duckdb.connect(db_path or DB_PATH, read_only=True) as conn:
        query = """
            WITH filtered_users AS (
                SELECT *
                FROM users
                WHERE (? IS NULL OR housing = ?)
                    AND (? IS NULL OR EXTRACT(YEAR FROM hstart) = ?)
                    AND (? IS NULL OR COALESCE(research_area, 'NA') = ?)
                    AND (? IS NULL OR acronym = ?)
            )
            SELECT DISTINCT o.filename, o.assembly_name, o.housing, o.mode, o.t0, o.duration
            FROM filtered_users AS u, UNNEST(u.overview_records_ids) AS t(ovid)
            JOIN overview_records AS o ON o.filename = t.ovid AND o.merged_into IS NULL
            ORDER BY o.t0
        """
        year = None if year is None else int(year)
        params = [housing, housing, year, year, research_area, research_area, user, user]
        return conn.execute(query, params).df()


def get_field_bin_history(housing, db_path=None, assembly_names=None, year=None):
    """Return per-period activity for a housing, for a commissioning-timeline strip.

    Granularity is monthly by default, spanning the housing's earliest
    assembly commissioning date through today. When *year* is given,
    granularity switches to weekly, spanning that full calendar year
    (``year-01-01`` to ``year-12-31``). A period has activity if any
    experiment (:pyattr:`experiments.name`, parsed in pandas since the
    stored format like ``"2018.02.21 - 10:18:54"`` isn't directly castable
    by DuckDB's ``TIMESTAMP`` cast) or any live ``overview_records`` row
    (``t0``, ``merged_into IS NULL``) falls in it. ``t0`` and
    ``commissioned_at`` are stored in UTC and converted to `DISPLAY_TZ`
    before binning, so periods align with local calendar boundaries;
    ``experiments.name`` is already local and is binned as-is.

    Parameters
    ----------
    housing : str
        Housing name (e.g. ``"M9"``).
    db_path : str, optional
        Path to the DuckDB database. Defaults to `DB_PATH`.
    assembly_names : collection of str, optional
        Restrict to these assemblies only. Defaults to all assemblies in
        *housing*.
    year : int, optional
        If given, switch to weekly granularity bounded to that calendar
        year. Defaults to ``None`` (monthly, from earliest commissioning
        through today).

    Returns
    -------
    list of dict
        One entry per period, ordered chronologically, with ``period_start``
        and ``period_end`` (:class:`~datetime.date`), ``has_activity``
        (bool) and ``commissioned`` (list of str — assembly names
        commissioned during that period).
    """
    with duckdb.connect(db_path or DB_PATH, read_only=True) as conn:
        params = [housing]
        assembly_filter = ""
        if assembly_names is not None:
            assembly_filter = " AND name = ANY(?)"
            params.append(list(assembly_names))
        commissioned_df = conn.execute(
            f"""
            SELECT name AS assembly_name, commissioned_at
            FROM assemblies
            WHERE housing = ? AND commissioned_at IS NOT NULL{assembly_filter}
            """,
            params,
        ).df()

        exp_params = [housing] + ([list(assembly_names)] if assembly_names is not None else [])
        exp_filter = " AND a.name = ANY(?)" if assembly_names is not None else ""
        experiments_df = conn.execute(
            f"""
            SELECT e.name AS experiment
            FROM experiments AS e
            JOIN assemblies AS a ON a.name = e.assembly_name
            WHERE a.housing = ?{exp_filter}
            """,
            exp_params,
        ).df()

        ov_params = [housing] + ([list(assembly_names)] if assembly_names is not None else [])
        ov_filter = " AND assembly_name = ANY(?)" if assembly_names is not None else ""
        overview_df = conn.execute(
            f"""
            SELECT t0
            FROM overview_records
            WHERE housing = ? AND merged_into IS NULL{ov_filter}
            """,
            ov_params,
        ).df()

    freq = "W" if year is not None else "M"

    activity_periods = set(pd.to_datetime(experiments_df["experiment"], errors="coerce").dropna().dt.to_period(freq))
    overview_t0_local = to_display_tz(pd.to_datetime(overview_df["t0"], errors="coerce"))
    activity_periods |= set(overview_t0_local.dropna().dt.to_period(freq))

    commissioned_df["commissioned_at"] = to_display_tz(pd.to_datetime(commissioned_df["commissioned_at"]))
    commissioned_by_period = commissioned_df.groupby(commissioned_df["commissioned_at"].dt.to_period(freq))[
        "assembly_name"
    ].apply(list)

    if year is not None:
        periods = pd.period_range(start=f"{year}-01-01", end=f"{year}-12-31", freq=freq)
    else:
        if commissioned_df.empty:
            return []
        periods = pd.period_range(start=commissioned_df["commissioned_at"].min(), end=pd.Timestamp.now(), freq=freq)

    return [
        {
            "period_start": p.start_time.date(),
            "period_end": p.end_time.date(),
            "has_activity": p in activity_periods,
            "commissioned": commissioned_by_period.get(p, []),
        }
        for p in periods
    ]


def chrono_callback(func):
    """Decorator to measure the execution time of a function."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        temps_ms = (end_time - start_time) * 1000
        print(f"Callback '{func.__name__}' executed in {temps_ms:.2f} ms")
        return result

    return wrapper
