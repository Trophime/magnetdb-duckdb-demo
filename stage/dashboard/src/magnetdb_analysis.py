import duckdb
import os
import glob
import functools
from python_magnetrun.MagnetRun import load_mrun
from python_magnetrun.field_defs import match_channels_across_formats
import re
from datetime import datetime
import numpy as np
import json
import time
from functools import wraps
import pandas as pd
import scipy.signal as sg

# Chemin absolu vers la base DuckDB (surchargable via variable d'environnement)
DB_PATH = os.environ.get(
    "MAGNETDB_DB_PATH", "/workspaces/2026-m1-hifimagnet/to_duckdb/magnetdb.duckdb"
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


_SITE_DATE_RE = re.compile(r"_A(\d{6})_\d{2}$")


def _site_sort_key(site_name):
    """Sort key extracting the YYMMDD date from a ``housing_AYYMMDD_NN`` site name."""
    match = _SITE_DATE_RE.search(site_name)
    return match.group(1) if match else site_name


def get_all_sites(db_path=None):
    """Select the list of all sites for the first menu, sorted chronologically by their YYMMDD date."""
    with duckdb.connect(db_path or DB_PATH, read_only=True) as conn:
        sites = (
            conn.execute(
                "SELECT DISTINCT site_name FROM experiments WHERE site_name IS NOT NULL"
            )
            .df()["site_name"]
            .tolist()
        )
    return sorted(sites, key=_site_sort_key)


def get_magnet_types_for_site(site_name, db_path=None):
    """Return the distinct magnet types (e.g. 'insert', 'bitters') defined for a site."""
    with duckdb.connect(db_path or DB_PATH, read_only=True) as conn:
        query = """
            SELECT DISTINCT m.type
            FROM site_magnets sm
            JOIN magnets m ON m.name = sm.magnet_name
            WHERE sm.site_name = ? AND m.type IS NOT NULL
        """
        return conn.execute(query, [site_name]).df()["type"].tolist()


def get_files_for_site(site_name, table_name, db_path=None):
    """
    Interroge la table choisie pour sortir tous les fichiers du site.
    C'est ta nouvelle requête SQL clé.
    """
    with duckdb.connect(db_path or DB_PATH, read_only=True) as conn:
        query = f"SELECT DISTINCT file FROM {table_name} WHERE site_name = ? AND file IS NOT NULL"
        df = conn.execute(query, [site_name]).df()
        return df["file"].tolist()


def get_overview_records_for_site(site_name, db_path=None):
    """Return overview_records rows for a site, ordered chronologically.

    Unlike operationaldata, overview_records keys its files under
    ``filename`` (not ``file``) and each row is already a fully processed
    summary, so there is no pupitre/pigbrother pairing to do here.
    """
    with duckdb.connect(db_path or DB_PATH, read_only=True) as conn:
        query = """
            SELECT filename, housing, mode, t0
            FROM overview_records
            WHERE site_name = ?
            ORDER BY t0 NULLS LAST, filename
        """
        return conn.execute(query, [site_name]).df().to_dict("records")


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
    Extrait et convertit la date et l'heure d'un nom de fichier en objet datetime (sans les secondes).
    Supporte les formats Pupitre (.txt) et PigBrother (.tdms).
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
        # CORRECTION : Ajout des parenthèses autour du 3ème \d{2} pour capturer le jour !
        match = re.search(r"(\d{2})(\d{2})(\d{2})-(\d{2})(\d{2})", filename)
        if match:
            year_short, month, day, hour, minute = match.groups()
            # On reconstruit l'année complète (ex: 25 -> 2025)
            year = 2000 + int(year_short)
            return datetime(year, int(month), int(day), int(hour), int(minute))

    return None


def check_same_date(file_pupitre, file_pigbrother):
    """
    Vérifie si un fichier Pupitre et un fichier PigBrother proviennent du même run (même minute).
    """
    dt_pupitre = parse_magnet_filename(file_pupitre)
    dt_pigbrother = parse_magnet_filename(file_pigbrother)

    if dt_pupitre is None or dt_pigbrother is None:
        return False

    # Comparaison directe des objets datetime (Année, Mois, Jour, Heure, Minute)
    return dt_pupitre == dt_pigbrother


def load_json_config(filepath):
    """Charge un fichier JSON de configuration de manière sécurisée."""
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Erreur lors de la lecture du fichier JSON {filepath}: {e}")
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


def chrono_callback(func):
    """Décorateur pour mesurer le temps d'exécution d'une fonction."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        temps_ms = (end_time - start_time) * 1000
        print(f"Callback '{func.__name__}' exécuté en {temps_ms:.2f} ms")
        return result

    return wrapper
