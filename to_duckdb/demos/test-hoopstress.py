import os
import sys
import duckdb
import pandas as pd

# 1. Base du projet
base_dir = os.getcwd()  # "/workspaces/2026-m1-hifimagnet"
print(f"Base du projet : {base_dir}")
# sys.path.insert(0, os.path.join(base_dir, "to_duckdb"))

from compute_hoop_stats import compute_hoop_stress_history
from stress_map import magnet_geometry_config_to_yaml


def print_magnet_geometry_fields(db_path, site_name):
    """Affiche les champs geometry / geometry_data des magnets rattachés à un site.

    Si geometry_data est absent en base pour un magnet, tente de le reconstruire
    à la volée à partir des parts via magnet_geometry_config_to_yaml().
    """
    conn = duckdb.connect(db_path, read_only=True)
    try:
        rows = conn.execute(
            """
            SELECT m.name, m.type, m.geometry, m.geometry_data
            FROM site_magnets sm
            JOIN magnets m ON m.name = sm.magnet_name
            WHERE sm.site_name = ?
            ORDER BY sm.commissioned_at DESC NULLS LAST
            """,
            [site_name],
        ).fetchall()
    finally:
        conn.close()

    print(f"  Magnets rattachés à {site_name} :")
    for name, magnet_type, geometry, geometry_data in rows:
        geometry_status = geometry if geometry else "None"
        if geometry_data:
            geometry_data_status = f"present ({len(geometry_data)} caractères)"
        else:
            try:
                built_yaml = magnet_geometry_config_to_yaml(name, db_path)
                geometry_data_status = (
                    f"MANQUANT en base, reconstruit depuis les parts "
                    f"({len(built_yaml)} caractères)"
                )
            except Exception as exc:
                geometry_data_status = f"MANQUANT et impossible à reconstruire : {exc}"
        print(
            f"    - {name} [{magnet_type}] : geometry={geometry_status}, "
            f"geometry_data={geometry_data_status}"
        )


def compute_and_export_m9_hoop_stress():
    # Chemins des fichiers physiques
    db_file = os.path.join(base_dir, "to_duckdb", "magnetdb.duckdb")
    output_csv = os.path.join(base_dir, "stage", "m9_hoop_stress_results.csv")

    if not os.path.exists(db_file):
        print(f"Erreur : La base de données '{db_file}' est introuvable.")
        return

    print(f"Récupération des sites depuis : {db_file}...")

    # 2. Lecture de la liste des sites
    conn = duckdb.connect(db_file)
    try:
        query = (
            "SELECT DISTINCT site_name FROM experiments WHERE site_name LIKE" " 'M9_%';"
        )
        df_sites = conn.execute(query).fetchdf()
    except Exception as e:
        print(f"Impossible de lire la table experiments : {e}")
        return
    finally:
        conn.close()  # Libère complètement la base pour la suite !

    list_sites = df_sites["site_name"].tolist()

    if not list_sites:
        print("Aucun site M9 trouvé.")
        return

    print(f"{len(list_sites)} sites M9 trouvés. Lancement des calculs...")
    print(f"Liste des sites : {list_sites}")
    results = []


    # 3. Boucle de calcul sur les sites
    for site in list_sites:
        print(f"\nCalcul du hoop stress pour : {site}...")
        print_magnet_geometry_fields(db_file, site)

        try:
            summary = compute_hoop_stress_history(
                site_name=site,
                db_path=db_file,
                pupitre_datadir="/mnt/LNCMIG-Data/records/srv-data-install",
                verbose=True,
            )

            print(f"Terminé pour {site}")
            results.append(
                {
                    "site": site,
                    "status": "Success",
                    "log": (
                        f"Calcul effectué ({summary['new']} traités, {summary['skipped']}"
                        " ignorés)"
                    ),
                }
            )

        except Exception as e:
            print(f"Erreur pour le site {site}: {e}")
            results.append({"site": site, "status": "Failed", "log": str(e)})

    # 4. Sauvegarde du fichier CSV
    df_results = pd.DataFrame(results)
    df_results.to_csv(output_csv, index=False, encoding="utf-8")
    print(f"\nRésumé de l'opération sauvegardé dans : {output_csv}")


if __name__ == "__main__":
    compute_and_export_m9_hoop_stress()
