import dash
from dash import html, dcc, dash_table, Input, Output
import dash_bootstrap_components as dbc
import duckdb
import pandas as pd
import numpy as np

DB_PATH = "/workspaces/2026-m1-hifimagnet/to_duckdb/magnetdb.duckdb"

# Initialisation de l'application avec un thème sympa
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])

# 1. Récupération dynamique de la liste des tables
# On se connecte juste un instant pour voir ce qu'il y a dans la base
try:
    conn = duckdb.connect(DB_PATH, read_only=True)
    tables_df = conn.execute("SHOW TABLES").fetchdf()
    table_names = tables_df['name'].tolist()
    conn.close()
except Exception as e:
    print(f"Erreur de connexion à la base: {e}")
    table_names = []

# 2. Le Layout (L'interface visuelle)
app.layout = dbc.Container([
    html.H2("Explorateur Rapide DuckDB 🦆", className="my-4 text-center"),
    
    dbc.Row([
        dbc.Col([
            html.Label("Choisissez une table à explorer :", className="fw-bold"),
            dcc.Dropdown(
                id='table-selector',
                options=[{'label': t, 'value': t} for t in table_names],
                placeholder="Sélectionnez une table...",
                className="mb-4"
            )
        ], width=6)
    ], className="justify-content-center"),
    
    dbc.Row([
        dbc.Col([
            # Le composant tableau interactif
            dash_table.DataTable(
                id='data-table',
                page_size=15, # Affiche 15 lignes par page
                style_table={'overflowX': 'auto'}, # Permet de scroller horizontalement
                style_cell={'textAlign': 'left', 'padding': '10px'},
                style_header={'backgroundColor': '#f8f9fa', 'fontWeight': 'bold'},
                filter_action="native", # Permet de filtrer les colonnes
                sort_action="native",   # Permet de trier les colonnes
            )
        ])
    ])
], fluid=True)

# 3. Le Callback (La logique interactive)
@app.callback(
    Output('data-table', 'data'),
    Output('data-table', 'columns'),
    Input('table-selector', 'value')
)
def update_table(selected_table):
    if not selected_table:
        return [], []

    try:
        # 1. Connexion sécurisée
        with duckdb.connect(DB_PATH, read_only=True) as conn:
            query = f'SELECT * FROM "{selected_table}" LIMIT 1000'
            df = conn.execute(query).fetchdf()

        if df.empty:
            return [], []

        # 2. Conversion complète : inclut les tableaux NumPy (np.ndarray), listes, dicts, etc.
        for col in df.columns:
            df[col] = df[col].apply(
                lambda x: str(x.tolist()) if isinstance(x, np.ndarray) 
                else (str(x) if isinstance(x, (list, dict, tuple, set)) else x)
            )

        # 3. Formatage pour la DataTable
        columns = [{"name": col, "id": col} for col in df.columns]
        data = df.to_dict('records')

        return data, columns

    except Exception as e:
        print(f"Erreur lors de la lecture de la table '{selected_table}': {e}")
        return [], []

# Lancement du serveur
if __name__ == '__main__':
    # host='0.0.0.0' est crucial si vous êtes dans un Dev Container / Codespace
    app.run(debug=True, host='0.0.0.0', port=8052)