import duckdb
import os
import glob
import functools
from python_magnetrun.MagnetRun import load_mrun
from python_magnetrun.field_defs import match_channels_across_formats
import re
from datetime import datetime, timedelta
import numpy as np
import json
import time
from functools import wraps
import pandas as pd
import scipy.signal as sg

# Chemin absolu vers la base DuckDB (surchargable via variable d'environnement)
DB_PATH = os.environ.get(
    "MAGNETDB_DB_PATH", "/workspaces/2026-m1-hifimagnet/to_duckdb/test-magnetdb.duckdb"
)
# Répertoire scanné pour lister les bases sélectionnables dans le dropdown
DB_DIR = os.environ.get("MAGNETDB_DB_DIR", os.path.dirname(DB_PATH))

print(f"Using DuckDB database: {DB_PATH}")

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
    """Select the list of all assemblies for the first menu, sorted by ascending commissioning date."""
    with duckdb.connect(db_path or DB_PATH, read_only=True) as conn:
        query = """
            SELECT DISTINCT e.assembly_name
            FROM experiments AS e
            JOIN assemblies AS s ON s.name = e.assembly_name
            WHERE e.assembly_name IS NOT NULL
            ORDER BY s.commissioned_at ASC
        """
        return conn.execute(query).df()["assembly_name"].tolist()


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


def get_files_for_assembly(assembly_name, table_name, db_path=None):
    """
    Interroge la table choisie pour sortir tous les fichiers du assembly.
    C'est ta nouvelle requête SQL clé.
    """
    with duckdb.connect(db_path or DB_PATH, read_only=True) as conn:
        query = f"SELECT DISTINCT file FROM {table_name} WHERE assembly_name = ? AND file IS NOT NULL"
        df = conn.execute(query, [assembly_name]).df()
        return df["file"].tolist()


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
        return conn.execute(query, [assembly_name]).df().to_dict("records")


@functools.lru_cache(maxsize=16)
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


def get_common_groups(selected_files, housing):
    """Groups present (per list_groups()) in every selected file.

    A group must exist in all selected files to be offered — files that fail
    to load are skipped rather than collapsing the intersection to empty.
    """
    groups = None
    for filename in selected_files or []:
        mrun = load_mrun_object(filename, housing)
        if mrun is None:
            continue
        file_groups = {g for g in mrun.MagnetData.list_groups() if g != "Infos"}
        groups = file_groups if groups is None else groups & file_groups
    return sorted(groups) if groups else []


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
    """Return the list of distinct housings defined in ``housing_config``.

    Parameters
    ----------
    db_path : str or :class:`~pathlib.Path`, optional
        Path to the DuckDB database. Defaults to `DB_PATH`.

    Returns
    -------
    list of str
        Housing names (e.g. ``"M9"``, ``"M10"``).
    """
    with duckdb.connect(db_path or DB_PATH, read_only=True) as conn:
        query = "SELECT DISTINCT name FROM housing_config WHERE name IS NOT NULL"
        return conn.execute(query).df()["name"].tolist()


def get_pupitres_for_housing(housing, db_path=None):
    """Return the list of Pupitre files recorded for a given housing.

    Parameters
    ----------
    housing : str
        Housing name (e.g. ``"M9"``).
    db_path : str or :class:`~pathlib.Path`, optional
        Path to the DuckDB database. Defaults to `DB_PATH`.

    Returns
    -------
    list of str
        Pupitre filenames for *housing*.
    """
    with duckdb.connect(db_path or DB_PATH, read_only=True) as conn:
        query = "SELECT pupitre FROM housing_summary WHERE housing = ? AND pupitre <> ''"
        return conn.execute(query, [housing]).df()["pupitre"].tolist()


def get_linked_files(housing, pupitre_filename, db_path=None):
    """Return the Overview, Archive and Default files linked to a Pupitre file.

    Parameters
    ----------
    housing : str
        Housing name (e.g. ``"M9"``).
    pupitre_filename : str
        Pupitre filename to look up in ``housing_summary``.
    db_path : str or :class:`~pathlib.Path`, optional
        Path to the DuckDB database. Defaults to `DB_PATH`.

    Returns
    -------
    dict or None
        Dict with ``pigbrother_file``, ``archive_file`` and ``default_file``
        keys, or ``None`` if *pupitre_filename* has no matching row.
    """
    with duckdb.connect(db_path or DB_PATH, read_only=True) as conn:
        query = """
            SELECT
                overview as pigbrother_file,
                archive as archive_file,
                "default" as default_file
            FROM housing_summary
            WHERE housing = ? AND pupitre = ?
        """
        result = conn.execute(query, [housing, pupitre_filename]).df().to_dict("records")
    return result[0] if result else None


def get_research_area_stats(housing=None, year=None, db_path=None):
    """Return per-research-area usage statistics from the ``users`` table.

    Parameters
    ----------
    housing : str, optional
        Restrict to sessions on this housing (e.g. ``"M9"``). ``None``
        includes all housings.
    year : str or int, optional
        Restrict to sessions whose ``hstart`` falls in this year. ``None``
        includes all years.
    db_path : str or :class:`~pathlib.Path`, optional
        Path to the DuckDB database. Defaults to `DB_PATH`.

    Returns
    -------
    :class:`~pandas.DataFrame`
        One row per research area, with columns ``research_area``,
        ``n_experiments`` (distinct experiments), ``n_users`` (distinct
        acronyms) and ``total_field_time_s`` (summed
        ``overview_records.duration`` [s]).
    """
    with duckdb.connect(db_path or DB_PATH, read_only=True) as conn:
        query = """
            WITH filtered_users AS (
                SELECT *
                FROM users
                WHERE research_area IS NOT NULL
                    AND (? IS NULL OR housing = ?)
                    AND (? IS NULL OR EXTRACT(YEAR FROM hstart) = ?)
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
                SELECT fu.research_area, SUM(o.duration) AS total_field_time_s
                FROM filtered_users AS fu, UNNEST(fu.overview_records_ids) AS t(ovid)
                JOIN overview_records AS o ON o.filename = t.ovid AND o.merged_into IS NULL
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
        params = [housing, housing, year, year]
        return conn.execute(query, params).df()


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
