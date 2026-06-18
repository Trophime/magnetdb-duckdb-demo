import duckdb
import pandas as pd

DB_PATH = "/workspaces/2026-m1-hifimagnet/to_duckdb/magnetdb.duckdb"

def get_all_tables():
    """Get all table names from the DuckDB database."""
    with duckdb.connect(DB_PATH) as conn:
        query = "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        return conn.execute(query).df()['table_name'].tolist()

def get_row_dropdown_data(selected_table):
    """Generate the options and placeholder text for the second dropdown."""
    if not selected_table:
        return [], "Select a table first..."
    
    with duckdb.connect(DB_PATH) as conn:
        columns = conn.execute(f"PRAGMA table_info('{selected_table}')").df()['name'].tolist()
        
        # Trouver la meilleure colonne pour le nommage
        candidate_cols = ['file', 'filename', 'description', 'site', 'id']
        display_col = next((c for c in candidate_cols if c in columns), columns[0])
        
        # Récupérer les valeurs
        df_options = conn.execute(f"SELECT DISTINCT {display_col} FROM {selected_table} WHERE {display_col} IS NOT NULL").df()
        
        options = [{'label': str(val), 'value': str(val)} for val in df_options[display_col]]
        placeholder = f"Choose an item from {selected_table} (based on {display_col})..."
        
        return options, placeholder
def get_table_data(selected_table, selected_value):
    """Get the columns and filtered data for the final table."""
    if not selected_value or not selected_table:
        return [], []
    
    try:
        with duckdb.connect(DB_PATH) as conn:
            # 1. Retrouver la colonne qui a servi de filtre
            columns = conn.execute(f"PRAGMA table_info('{selected_table}')").df()['name'].tolist()
            candidate_cols = ['file', 'name', 'description', 'site_name', 'id', 'experiment_id', 'materials', 'part_name', 'status', 'type', 'rank', 'site_name', 'geometry']
            display_col = next((c for c in candidate_cols if c in columns), columns[0])
            
            # --- DEBUG --- (Ceci s'affichera dans votre terminal VS Code)
            print(f"DEBUG: Research in table '{selected_table}' where '{display_col}' = {selected_value}")
            
            # 2. Requête SQL
            query = f"SELECT * FROM {selected_table} WHERE {display_col} = ?"
            df_result = conn.execute(query, [selected_value]).df()
            
            print(f"DEBUG: {len(df_result)} line(s) found.")
            
            # 3. CONVERSION OBLIGATOIRE POUR DASH
            # Convertit toutes les colonnes en chaînes de caractères (texte)
            # Cela empêche Dash de planter sur des dates, des tableaux ou des BLOBs
            df_result = df_result.astype(str)
            
            # 4. Préparation des données
            cols = [{"name": i, "id": i} for i in df_result.columns]
            data = df_result.to_dict('records')
            
            return cols, data
            
    except Exception as e:
        # S'il y a une erreur SQL, on l'affiche dans le terminal au lieu qu'elle soit invisible
        print(f"ERROR IN GET_TABLE_DATA : {e}")
        return [{"name": "Error", "id": "Error"}], [{"Error": str(e)}]