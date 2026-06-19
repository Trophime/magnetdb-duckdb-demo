import duckdb
import pandas as pd
import os
from python_magnetrun.MagnetRun import MagnetRun
from python_magnetrun.magnetdata import MagnetData

# Chemin absolu vers la base DuckDB
DB_PATH = "/workspaces/2026-m1-hifimagnet/to_duckdb/magnetdb.duckdb"

# --- UTILITAIRES DE BASE ---
def get_all_tables():
    """Liste toutes les tables de la base."""
    with duckdb.connect(DB_PATH, read_only=True) as conn:
        return conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'").df()['table_name'].tolist()


def get_all_sites():
    """Récupère la liste de tous les sites pour le premier menu."""
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

# --- CHARGEMENT DES DONNÉES ---
def load_data(filepath, site_name):
    """Charge et nettoie le fichier avec MagnetRun."""
    if not os.path.exists(filepath):
        print(f"File not found : {filepath}")
        return pd.DataFrame()

    try:
        filename = os.path.basename(filepath)
        housing = os.path.basename(os.path.dirname(filepath))
        
        print(f"Loading {filename}...")
        mrun = MagnetRun.fromtxt(housing, site_name, filepath)
        
        if hasattr(mrun, 'MagnetData') and mrun.MagnetData:
            return mrun.MagnetData.Data
        return pd.DataFrame()
        
    except Exception as e:
        print(f"Error loading file : {e}")
        return pd.DataFrame()