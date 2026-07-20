import dash
from dash import html, dcc, Output, Input, no_update
from dash.exceptions import PreventUpdate
import magnetdb_analysis as db
import plotly.graph_objects as go
import dash_bootstrap_components as dbc
from magnetdb_plot import create_plot
import pandas as pd

target_table = 'operationaldata'

# Enregistrement de la page auprès de Dash
# On ajoute suppress_callback_exceptions=True pour autoriser les composants dynamiques 
dash.register_page(
    __name__, 
    path='/comparison', 
    name="Comparaison Multi-fichiers"
)

# Le Layout obligatoire corrig0 échecklist et aligné 
layout = html.Div([
    html.H2("Visualisation et Comparaison Multi-fichiers"),
    html.P("Superposez les courants électriques de plusieurs fichiers (Pupitre et PigBrother)."),
    
    # --- SECTION SÉLECTION ET VISUALISATION ---
    dbc.Row([
        # Colonne de gauche : Contrôles globaux (Largeur 3/12)
        dbc.Col([
            html.Div([
                html.Hr(),
                html.Label("1. Choose Site :", style={'fontWeight': 'bold'}),
                dcc.Dropdown(id='dd-site', options=db.get_all_sites(), placeholder="Choose a site..."),
            ], style={"padding": "10px"}),

            html.Div([
                html.Label("2. Choose Files to Compare :", style={'fontWeight': 'bold', 'marginTop': '15px', 'display': 'block'}),
                dcc.Dropdown(
                    id='dd-files-compare',
                    options=[],
                    multi=True,
                    placeholder="Select files..."
                ),
            ], style={"padding": "10px"}),

            html.Div([
                html.Label("3. X-Axis Type :", style={'fontWeight': 'bold', 'marginTop': '15px', 'display': 'block'}),
                dcc.RadioItems(
                    id='comp-xaxis-selector',
                    options=[{'label': 'Temps (t)', 'value': 't'}, {'label': 'Timestamp', 'value': 'timestamp'}],
                    value='t',
                    inline=True
                ),
            ], style={"padding": "10px"}),
        ], width=3),

        # Colonne de droite : Capteurs + Graphique côte à côte (Largeur 9/12)
        dbc.Col([
            dbc.Row([
                # Sous-colonne gauche : liste des capteurs (Largeur 3/12 de la zone droite)
                dbc.Col([
                    html.H5("Capteurs (Courants_Alimentations)"),
                    html.Div(id='sensors-message', children="Sélectionnez vos fichiers pour charger les capteurs."),

                    dcc.Checklist(
                        id='checklist-sensors',
                        options=[], # Vide au départ
                        value=[],   # Vide au départ
                        labelStyle={'display': 'block', 'marginBottom': '5px'}
                    )
                ], width=3),

                # Sous-colonne droite : graphique principal (Largeur 9/12 de la zone droite)
                dbc.Col([
                    dcc.Graph(
                        id='comparison-main-graph',
                        style={'height': '70vh'}
                    )
                ], width=9)
            ])
        ], width=9)
        
    ], className="g-4") # Fin de la ligne principale
])

@dash.callback(
    Output('dd-files-compare', 'options'),
    Input('dd-site', 'value')
)
def update_file_dropdown(selected_site, target_table='operationaldata'):
    if not selected_site:
        return []

    files = db.get_files_for_site(selected_site, target_table)
    
    pupitre_files = [f for f in files if f.endswith('.txt')]
    pigbrother_files = [f for f in files if f.endswith('.tdms')]
    
    options = []
    
    for p_file in pupitre_files:
        matched_pb_file = None
        for pb_file in pigbrother_files:
            if db.check_same_date(p_file, pb_file):
                matched_pb_file = pb_file
                break
        
        if matched_pb_file:
            options.append({'label': f"Pupitre: {p_file} ", 'value': p_file})
            options.append({'label': f"PigBrother: {matched_pb_file}", 'value': matched_pb_file})
            pigbrother_files.remove(matched_pb_file)
        
    return options

@dash.callback(
    Output('dd-files-compare', 'value'),
    Input('dd-files-compare', 'value')
)
def limit_selection(selected_values):
    if selected_values and len(selected_values) > 2:
        return selected_values[:2] # On garde seulement les 2 premiers
    return selected_values


 

@dash.callback(
    Output('checklist-sensors', 'options'),
    Output('checklist-sensors', 'value'),
    Output('sensors-message', 'children'), # Pour effacer ou afficher le message
    Input('dd-files-compare', 'value'),
    Input('dd-site', 'value')
)
def update_comparison_sensors(selected_files, selected_site):
    if not selected_files or not selected_site:
        return [], [], "Sélectionnez vos fichiers pour charger les capteurs."
    
    housing = selected_site.split('_')[0]
    group_name = 'Courants_Alimentations'
    
    # Utilisation d'un set pour stocker les capteurs afin d'éviter naturellement les doublons
    all_unique_sensors = set()
    
    for file_path in selected_files:
        try:
            mrun = db.load_mrun_object(file_path, housing)
            
            # 1. Cas : Fichier Pupitre (avec groupes)
            if hasattr(mrun.MagnetData, 'Groups') and group_name in mrun.MagnetData.Groups:
                sensors = mrun.MagnetData.Groups[group_name]
                if isinstance(sensors, dict):
                    all_unique_sensors.update(sensors.keys())
                else:
                    all_unique_sensors.update(sensors)
            
            # 2. Cas : Fichier PigBrother (DataFrame plat)
            elif hasattr(mrun.MagnetData, 'Data') and isinstance(mrun.MagnetData.Data, pd.DataFrame):
                df = mrun.MagnetData.Data
                # Filtre tes colonnes ici
                found = [col for col in df.columns if 'I' in col]
                all_unique_sensors.update(found)
                
        except Exception as e:
            print(f"Erreur lors du traitement du fichier {file_path}: {e}")
            continue

    # Conversion en liste triée pour l'affichage
    sensors_list = sorted(list(all_unique_sensors))
    
    if not sensors_list:
        return [], [], "Aucun capteur correspondant trouvé."

    options = [{'label': s, 'value': s} for s in sensors_list]
    value = [sensors_list[0]] 

    # options remplies, 1ère valeur cochée, et on vide le message textuel !
    return options, value, ""


# Variables globales pour maintenir la limite (ou utilisez dcc.Store pour une approche stateless)
current_mruns = {} # Dictionnaire {filename: mrun_object}

@dash.callback(
    Output('comparison-main-graph', 'figure'),
    [Input('dd-files-compare', 'value'),
     Input('checklist-sensors', 'value'),
     Input('comp-xaxis-selector', 'value'),
     Input('dd-site', 'value')]
)
def update_graph(selected_files, selected_sensors, xaxis_type, selected_site):
    if selected_sensors is None or selected_files is None:
        raise PreventUpdate

    fig = go.Figure()
    housing = selected_site.split('_')[0]
    for file in selected_files:
        # 1. Chargement spécifique pour ce fichier
        mrun = db.load_mrun_object(file, housing) 
        df = db.load_data(file, selected_site, housing) 
        
        # 2. Utilisation de votre fonction existante
        # Dans ton callback update_graph de comparison.py
        sub_fig = create_plot(
        df=df, 
        x_col=xaxis_type, 
        y_cols=selected_sensors, 
        method='m4', # Tu peux laisser 'lttb' en dur, ou ajouter un dcc.Dropdown dans ton layout pour que l'utilisateur choisisse !
        filename=file,
        mrun=mrun,
        group_name='Courants_Alimentations' # Ajoute bien le groupe pour que ton extraction d'unité PigBrother fonctionne !
        )
        
        # 3. Intégration
        for trace in sub_fig.data:
            trace.name = f"{file} - {trace.name}"
            fig.add_trace(trace)
            
        # 4. Suppression explicite de l'objet si nécessaire
        del mrun
        del df

    return fig