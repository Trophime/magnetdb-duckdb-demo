import duckdb
import pandas as pd
import os
import glob
import functools
from python_magnetrun.MagnetRun import load_mrun
import re
from datetime import datetime
import numpy as np
import json

# Chemin absolu vers la base DuckDB (surchargable via variable d'environnement)
DB_PATH = os.environ.get(
    "MAGNETDB_DB_PATH", "/workspaces/2026-m1-hifimagnet/to_duckdb/magnetdb.duckdb"
)
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


def get_all_sites(db_path=None):
    """Select the list of all sites for the first menu."""
    with duckdb.connect(db_path or DB_PATH, read_only=True) as conn:
        return (
            conn.execute(
                "SELECT DISTINCT site_name FROM experiments WHERE site_name IS NOT NULL"
            )
            .df()["site_name"]
            .tolist()
        )


def get_files_for_site(site_name, table_name, db_path=None):
    """
    Interroge la table choisie pour sortir tous les fichiers du site.
    C'est ta nouvelle requête SQL clé.
    """
    with duckdb.connect(db_path or DB_PATH, read_only=True) as conn:
        query = f"SELECT DISTINCT file FROM {table_name} WHERE site_name = ? AND file IS NOT NULL"
        df = conn.execute(query, [site_name]).df()
        return df["file"].tolist()


@functools.lru_cache(maxsize=2)
def load_mrun_object(filename, housing):
    """Charge et retourne l'objet MagnetRun complet."""
    filepath = os.path.join(RECORDS_DIR, filename)
    return load_mrun(filename=filepath, housing=housing)


@functools.lru_cache(maxsize=2)
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


import json


def get_comparable_groups(pigbrother_defs_path=PIGBROTHER_DEF):
    """Retourne uniquement la liste des groupes ayant au moins un alias vers Pupitre."""
    try:
        with open(pigbrother_defs_path, "r", encoding="utf-8") as f:
            pb_defs = json.load(f)

        groups = set()
        for key, info in pb_defs.items():
            if key.startswith("_"):
                continue

            # Si le canal possède un alias vers pupitre, son groupe est comparable
            if "aliases" in info and "pupitre" in info["aliases"]:
                group_name = key.split("/")[0]
                groups.add(group_name)

        return sorted(list(groups))
    except Exception as e:
        print(f"Erreur lors de la lecture des groupes comparables: {e}")
        return ["Courants_Alimentations", "Tensions_Aimant"]


import json

# Assure-toi que les constantes de chemin vers tes JSON sont définies
# Ex: PUPITRE_DEF = 'pupitre-defs.json'
#     PIGBROTHER_DEF = 'pigbrother-defs.json'


def get_comparable_pairs_for_group(
    group_name, pigbrother_defs_path=PIGBROTHER_DEF, pupitre_defs_path=PUPITRE_DEF
):
    """
    Lit pigbrother-defs.json et pupitre-defs.json pour retourner
    la liste des dictionnaire(s) des paires comparables pour un groupe donné.
    """
    try:
        with open(pigbrother_defs_path, "r", encoding="utf-8") as f:
            pb_defs = json.load(f)
        with open(pupitre_defs_path, "r", encoding="utf-8") as f:
            pup_defs = json.load(f)
    except Exception as e:
        print(f"Erreur de lecture des définitions JSON : {e}")
        return []

    pairs = []

    for pb_key, pb_info in pb_defs.items():
        if pb_key.startswith("_"):
            continue

        parts = pb_key.split("/")
        if len(parts) != 2:
            continue

        pb_group, pb_channel = parts[0], parts[1]

        # On extrait uniquement les capteurs du groupe sélectionné
        if pb_group == group_name:
            aliases = pb_info.get("aliases", {})
            pupitre_channel = aliases.get("pupitre")

            # S'il existe une correspondance (alias) vers un capteur Pupitre
            if pupitre_channel:
                pup_info = pup_defs.get(pupitre_channel, {})
                unit = pb_info.get("unit") or pup_info.get("unit") or ""
                unit_str = f" [{unit}]" if unit else ""

                # Ce dictionnaire contient exactement la clé 'id' attendue par comparison.py
                pairs.append(
                    {
                        "id": f"{pupitre_channel}_vs_{pb_channel}",
                        "label": f"{pb_info.get('label', pb_channel)}{unit_str}",
                        "pupitre": pupitre_channel,
                        "pigbrother": pb_channel,
                        "description": pb_info.get("description")
                        or pup_info.get("description", ""),
                    }
                )

    return pairs


import time
from functools import wraps


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
