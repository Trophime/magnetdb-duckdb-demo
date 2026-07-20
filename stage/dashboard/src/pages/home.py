from dash import Dash, html, dcc, Input, Output, no_update, ALL, State, register_page
import dash
import plotly.express as px
from plotly import graph_objects as go
import magnetdb_analysis as db
import magnetdb_plot as plot
import os
import pandas as pd

dash.register_page(__name__, path='/')

layout = html.Div([
    html.Div([
        html.H2("Magnetdb Dashboard", style={'marginTop': '0px', 'marginBottom': '20px'}),
        html.Hr(),
        
        html.Label("1. Choose Site :", style={'fontWeight': 'bold'}),
        dcc.Dropdown(id='dd-site', options=db.get_all_sites(), placeholder="Choose a site..."),
        
        html.Br(),
        html.Label("2. Choose Table :", style={'fontWeight': 'bold'}),
        dcc.Dropdown(id='dd-table', options=['experiments', 'operationaldata'], value='experiments'),
        
        html.Br(),
        html.Label("3. Choose File :", style={'fontWeight': 'bold'}),
        dcc.Dropdown(id='dd-file', placeholder="Choose a file..."),

        html.Br(),
        html.Label("4. Choose X-axis :", style={'fontWeight': 'bold', 'color':'#007bff'}),
        dcc.Dropdown(
            id='dd-x-axis',
            options=[
                {'label': 'Real Time (timestamp)', 'value': 'timestamp'},
                {'label': 'Elapsed Time (t)', 'value': 't'}
            ],
            value='timestamp', 
            clearable=False    
        ),

        html.Br(),
        html.Label("5. Choose Sensors :", style={'fontWeight': 'bold'}),
        # C'est ce conteneur unique qui contiendra tout (Groupes + Checklist + Graphiques associés)
        html.Div(id='sensors-selectors-container', children=[], style={'marginTop': '10px'}),

        html.Br(),
        html.Label("7. Downsampling Method:", style={'fontWeight': 'bold'}),
        dcc.Dropdown(
            id='dropdown-downsampling',
            options=['raw data', 'lttb', 'minmax', 'm4', 'nan_m4', 'minmax_lttb', 'stride'],
            value='lttb',
            clearable=False
        )
        
    ], style={'padding': '20px', 'backgroundColor': '#f8f9fa', 'minHeight': '100vh'})
])

# CALLBACK 1 : Met à jour la liste des fichiers en fonction du Site ET de la Table
@dash.callback(
    Output('dd-file', 'options'),
    Input('dd-site', 'value'),
    Input('dd-table', 'value')
)
def update_file_dropdown(selected_site, selected_table):
    if not selected_site or not selected_table:
        return []
    files = db.get_files_for_site(selected_site, selected_table)
    return [{'label': f, 'value': f} for f in files]


@dash.callback(
    Output('sensors-selectors-container', 'children'), 
    Input('dd-file', 'value'), # Plus de dd-group ici !
    Input('dd-site', 'value'),
    State({'type': 'group-sensors-checklist', 'index': ALL}, 'value'),
    State({'type': 'group-sensors-checklist', 'index': ALL}, 'id')
)
def update_sensors_menus(selected_file, selected_site, current_sensor_values, current_sensor_ids):
    if not selected_file or not selected_site:
        return []
        
    housing = selected_site.split('_')[0] 
    mrun = db.load_mrun_object(selected_file, housing)
    
    if mrun is None:
        return []
    
    # Mémorisation des cases cochées
    saved_state_map = {}
    if current_sensor_ids and current_sensor_values:
        saved_state_map = {
            s_id['index']: s_vals 
            for s_id, s_vals in zip(current_sensor_ids, current_sensor_values)
            if s_vals is not None
        }
    
    menus_blocks = []
    
    # On boucle sur TOUS les groupes existants dans le fichier
    for group_name, sensors in mrun.MagnetData.Groups.items():
        if group_name == 'Infos':
            continue
            
        if isinstance(sensors, dict):
            options = [{'label': s, 'value': s} for s in sensors.keys()]
        else:
            options = [{'label': s, 'value': s} for s in sensors]
            
        saved_values_for_this_group = saved_state_map.get(group_name, [])
            
        # Création du menu Accordéon (Details/Summary)
        # Création du conteneur Flexbox pour mettre le menu et le graphe côte à côte
        menus_blocks.append(
            html.Div([
                
                # --- PARTIE GAUCHE : L'accordéon et les cases à cocher (Largeur fixe) ---
                html.Div([
                    html.Details([
                        html.Summary(f"📂 {group_name}", style={
                            'fontWeight': 'bold', 
                            'cursor': 'pointer',
                            'marginBottom': '5px',
                            'outline': 'none',
                            'fontSize': '16px'
                        }),
                        
                        html.Div([
                            dcc.Checklist(
                                id={'type': 'group-sensors-checklist', 'index': group_name},
                                options=options,
                                value=saved_values_for_this_group,
                                labelStyle={'display': 'block', 'marginLeft': '25px', 'marginBottom': '4px'} 
                            )
                        ], style={'marginBottom': '10px'})
                    ], open=True) # "open=True" ouvre l'accordéon par défaut, c'est plus pratique !
                ], style={
                    'width': '250px', # On fixe la largeur du menu à gauche (pas trop grand)
                    'flexShrink': 0,  # Empêche le menu de se faire écraser
                    'padding': '10px',
                    'borderRight': '1px solid #ddd', # Petite barre de séparation discrète
                    'backgroundColor': '#ffffff'
                }),
                
                # --- PARTIE DROITE : Le conteneur du Graphique (Prend tout le reste de la place) ---
                html.Div(
                    id={'type': 'group-graph-container', 'index': group_name}, 
                    children=[], 
                    style={
                        'flexGrow': 1, # Magie Flexbox : prend 100% de l'espace restant !
                        'minWidth': '0', # Force Plotly à s'adapter sans dépasser
                        'padding': '10px'
                    }
                )
                
            ], style={
                'display': 'flex', # C'est la commande magique pour mettre côte à côte
                'flexDirection': 'row',
                'border': '1px solid #007bff', # Un joli cadre bleu autour de tout le bloc du groupe
                'borderRadius': '8px',
                'marginBottom': '20px',
                'boxShadow': '0 2px 4px rgba(0,0,0,0.05)', # Petite ombre stylée
                'backgroundColor': '#f8f9fa'
            })
        )
        
    return menus_blocks

@dash.callback(
    # On cible l'ID dynamique de la boîte à graphique créée juste au-dessus
    Output({'type': 'group-graph-container', 'index': ALL}, 'children'),
    Input('dd-file', 'value'),
    Input('dd-site', 'value'),
    Input('dd-table', 'value'),
    Input('dd-x-axis', 'value'),
    Input({'type': 'group-sensors-checklist', 'index': ALL}, 'value'), 
    Input({'type': 'group-sensors-checklist', 'index': ALL}, 'id'), 
    Input('dropdown-downsampling', 'value')
)
def update_outputs(selected_file, selected_site, selected_table, selected_x, all_sensors_lists, all_sensors_ids, selected_algo):
    
    # Si aucun fichier n'est sélectionné, on renvoie une liste de composants vides pour chaque Checklist présente
    if not selected_file or not selected_site:
        return [[] for _ in all_sensors_ids]
    
    base_dir = "/mnt/LNCMIG-Data/records"
    filepath = os.path.join(base_dir, selected_file)
    housing = selected_site.split('_')[0] 
    
    mrun = db.load_mrun_object(selected_file, housing)
    if mrun is None:
        return [[] for _ in all_sensors_ids]

    # Cartographie des capteurs
    sensors_map = {
        sensor_id['index']: sensor_values 
        for sensor_id, sensor_values in zip(all_sensors_ids, all_sensors_lists)
        if sensor_values is not None
    }

    # Dash attend qu'on retourne une liste de réponses ordonnée de la même façon que all_sensors_ids
    outputs_blocks = []
    
    for sensor_id in all_sensors_ids:
        group_name = sensor_id['index']

        if group_name == 'Infos' or group_name not in mrun.MagnetData.Groups:
            outputs_blocks.append([])
            continue
        
        sensors_in_this_group = sensors_map.get(group_name, [])
        
        # S'il n'y a aucun capteur coché pour ce groupe, on laisse la boîte vide
        if not sensors_in_this_group:
            outputs_blocks.append([])
            continue
        
        # Extraction des données
        if isinstance(mrun.MagnetData.Data, pd.DataFrame):
            df = mrun.MagnetData.Data
        elif isinstance(mrun.MagnetData.Data, dict) and group_name in mrun.MagnetData.Data:
            df = mrun.MagnetData.Data[group_name]
        else:
            try:
                df = mrun.getDataFrame()
            except:
                outputs_blocks.append([])
                continue
                
        if not isinstance(df, pd.DataFrame):
            outputs_blocks.append([])
            continue 
            
        # Création du plot
        fig = plot.create_plot(df, selected_x, sensors_in_this_group, selected_algo, filename=f"{selected_file} - {group_name}", mrun=mrun, group_name=group_name)
        
        # On ajoute le graphique à notre liste de composants pour ce groupe
        outputs_blocks.append(
            dcc.Graph(
                id={'type': 'dynamic-graph', 'index': group_name},
                figure=fig
            )
        )
        
    return outputs_blocks

@dash.callback(
    Output({'type': 'group-sensors-checklist', 'index': ALL}, 'value'),
    Input('dd-file', 'value'), # Dès que le fichier change
    prevent_initial_call=True
)
def reset_checklists(selected_file):
    # On renvoie une liste vide pour chaque checklist existante
    # Dash va automatiquement décocher toutes les cases
    return []
