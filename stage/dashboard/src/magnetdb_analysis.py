import duckdb
import pandas as pd
import os
import functools
from python_magnetrun.MagnetRun import load_mrun
import re
from datetime import datetime

# Chemin absolu vers la base DuckDB
DB_PATH = "/workspaces/2026-m1-hifimagnet/to_duckdb/magnetdb.duckdb"


def get_all_tables():
    """Lists all the tables of the database."""
    with duckdb.connect(DB_PATH, read_only=True) as conn:
        return conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'").df()['table_name'].tolist()


def get_all_sites():
    """Select the list of all sites for the first menu."""
    with duckdb.connect(DB_PATH, read_only=True) as conn:
        return conn.execute("SELECT DISTINCT site_name FROM experiments WHERE site_name IS NOT NULL").df()['site_name'].tolist()

def get_files_for_site(site_name, table_name):
    """
    Interroge la table choisie pour sortir tous les fichiers du site.
    C'est ta nouvelle requête SQL clé.
    """
    with duckdb.connect(DB_PATH, read_only=True) as conn:
        query = f"SELECT DISTINCT file FROM {table_name} WHERE site_name = ? AND file IS NOT NULL"
        df = conn.execute(query, [site_name]).df()
        return df['file'].tolist()
    

@functools.lru_cache(maxsize=5)
def load_mrun_object(filename, housing):
    """Charge et retourne l'objet MagnetRun complet."""
    # Attention : il faut que filename contienne le chemin complet
    # Vous pouvez réutiliser la logique de chemin que vous aviez dans votre app
    base_dir = "/mnt/LNCMIG-Data/records"
    filepath = os.path.join(base_dir, filename)
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