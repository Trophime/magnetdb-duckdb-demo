import duckdb
import pandas as pd
import os
import glob
import functools
from python_magnetrun.MagnetRun import load_mrun
import re
from datetime import datetime

# Chemin absolu vers la base DuckDB (surchargable via variable d'environnement)
DB_PATH = os.environ.get("MAGNETDB_DB_PATH", "/workspaces/2026-m1-hifimagnet/to_duckdb/magnetdb.duckdb")
# Répertoire scanné pour lister les bases sélectionnables dans le dropdown
DB_DIR = os.environ.get("MAGNETDB_DB_DIR", os.path.dirname(DB_PATH))
RECORDS_DIR = os.environ.get("MAGNETDB_RECORDS_DIR", "/mnt/LNCMIG-Data/records")


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
    return [{'label': os.path.basename(p), 'value': p} for p in paths]


def get_all_tables(db_path=None):
    """Lists all the tables of the database."""
    with duckdb.connect(db_path or DB_PATH, read_only=True) as conn:
        return conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'").df()['table_name'].tolist()


def get_all_sites(db_path=None):
    """Select the list of all sites for the first menu."""
    with duckdb.connect(db_path or DB_PATH, read_only=True) as conn:
        return conn.execute("SELECT DISTINCT site_name FROM experiments WHERE site_name IS NOT NULL").df()['site_name'].tolist()

def get_files_for_site(site_name, table_name, db_path=None):
    """
    Interroge la table choisie pour sortir tous les fichiers du site.
    C'est ta nouvelle requête SQL clé.
    """
    with duckdb.connect(db_path or DB_PATH, read_only=True) as conn:
        query = f"SELECT DISTINCT file FROM {table_name} WHERE site_name = ? AND file IS NOT NULL"
        df = conn.execute(query, [site_name]).df()
        return df['file'].tolist()
    

@functools.lru_cache(maxsize=5)
def load_mrun_object(filename, housing):
    """Charge et retourne l'objet MagnetRun complet."""
    filepath = os.path.join(RECORDS_DIR, filename)
    return load_mrun(filename=filepath, housing=housing)

@functools.lru_cache(maxsize=5)
def load_data(filepath, site_name, housing):
    """Charge le fichier via load_mrun et retourne un DataFrame propre pour Dash."""
    if not os.path.exists(filepath):
        return pd.DataFrame() 

    try:
        mrun = load_mrun(filename=filepath, housing=housing, site=site_name)
        
        donnees = mrun.getDataFrame()
        
        # On renvoie le tableau (en gérant le cas des fichiers TDMS qui renvoient une liste)
        if isinstance(donnees, list):
            if len(donnees) > 0:
                return donnees[0] 
            else:
                return pd.DataFrame()
        else:
            return donnees
            
    except Exception as e:
        print(f"Error loading file: {e}")
        return pd.DataFrame()
    



def parse_magnet_filename(filename):
    """
    Extrait et convertit la date et l'heure d'un nom de fichier en objet datetime (sans les secondes).
    Supporte les formats Pupitre (.txt) et PigBrother (.tdms).
    Returns datetime object ou None si aucun format ne correspond.
    """
    # 1. Format Pupitre : "2025.01.24 - 10:30:29.txt"
    if filename.endswith('.txt'):
        # On cherche un pattern AAAA.MM.JJ - HH:MM:SS
        match = re.search(r'(\d{4})\.(\d{2})\.(\d{2})\s*-\s*(\d{2}):(\d{2})', filename)
        if match:
            year, month, day, hour, minute = match.groups()
            return datetime(int(year), int(month), int(day), int(hour), int(minute))

    # 2. Format PigBrother : "M9_Archive_251202-1430.tdms"
    elif filename.endswith('.tdms'):
        # CORRECTION : Ajout des parenthèses autour du 3ème \d{2} pour capturer le jour ! 
        match = re.search(r'(\d{2})(\d{2})(\d{2})-(\d{2})(\d{2})', filename)
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