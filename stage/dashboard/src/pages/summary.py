import dash
from dash import html, dcc, Output, Input, State, MATCH, ALL
import dash_bootstrap_components as dbc
import pandas as pd
import plotly.graph_objects as go
import magnetdb_analysis as db
from magnetdb_plot import create_plot 

# --- 1. ENREGISTREMENT DE LA PAGE ---
dash.register_page(
    __name__, 
    path='/summary', 
    name="Housing Summary",
    order=6
)

# --- 2. LAYOUT ---
layout = html.Div([
    html.H2("Housing Summary & Data Exploration", style={'fontWeight': 'bold', 'marginBottom': '10px'}),
    html.P("Select a Housing then a Pupitre. All associated files will automatically be displayed below.", style={'color': '#666', 'marginBottom': '30px'}),

    # --- PARTIE 1 : LES CONTRÔLES DE SÉLECTION  ---
    dbc.Card([
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    html.Label("1. Housing:", style={'fontWeight': 'bold'}),
                    dcc.Dropdown(id='summary-dd-housing', placeholder="Loading...")
                ], width=6),
                
                dbc.Col([
                    html.Label("2. Pupitre File:", style={'fontWeight': 'bold'}),
                    dcc.Dropdown(id='summary-dd-pupitre', placeholder="Select a pupitre...", disabled=True)
                ], width=6),
            ])
        ])
    ], style={'boxShadow': '0 2px 4px rgba(0,0,0,0.05)', 'borderRadius': '8px', 'marginBottom': '30px'}),

    # --- PARTIE 2 : LA ZONE DES GRAPHIQUES ---
    # Contiendra un gros bloc par fichier (Pupitre, Overview, Archive...)
    html.Div(id='summary-files-container')
])


# Callback 1 : Initialiser la liste des Housings au chargement
@dash.callback(
    Output('summary-dd-housing', 'options'),
    Input('summary-dd-housing', 'id')
)
def load_housings(_):
    try:
        housings = db.get_housings()
        return [{'label': str(h), 'value': str(h)} for h in housings]
    except Exception as e:
        print(f"[summary.py] Error get_housings: {e}")
        return []

# Callback 2 : Mettre à jour la liste des Pupitres selon le Housing
@dash.callback(
    Output('summary-dd-pupitre', 'options'),
    Output('summary-dd-pupitre', 'value'),
    Output('summary-dd-pupitre', 'disabled'),
    Input('summary-dd-housing', 'value')
)
def update_pupitres(selected_housing):
    if not selected_housing:
        return [], None, True
        
    try:
        pupitres = db.get_pupitres_for_housing(selected_housing)
        options = [{'label': p, 'value': p} for p in pupitres]
        return options, None, False
    except Exception as e:
        print(f"[summary.py] Error get_pupitres_for_housing: {e}")
        return [], None, True


# Callback 3 : Générer TOUS les fichiers d'un coup quand on choisit un Pupitre
@dash.callback(
    Output('summary-files-container', 'children'),
    Input('summary-dd-pupitre', 'value'),
    State('summary-dd-housing', 'value')
)
def generate_all_files_ui(selected_pupitre, housing):
    if not selected_pupitre or not housing:
        return []
        
    # 1. On prépare la liste de tous les fichiers à afficher
    files_to_load = [("Pupitre", selected_pupitre)]
    
    try:
        linked = db.get_linked_files(housing, selected_pupitre)
        if linked:
            if linked.get('pigbrother_file') and pd.notna(linked['pigbrother_file']) and linked['pigbrother_file'] != '':
                files_to_load.append(("Overview", linked['pigbrother_file']))
            if linked.get('archive_file') and pd.notna(linked['archive_file']) and linked['archive_file'] != '':
                files_to_load.append(("Archive", linked['archive_file']))
            if linked.get('default_file') and pd.notna(linked['default_file']) and linked['default_file'] != '':
                files_to_load.append(("Default", linked['default_file']))
    except Exception as e:
        print(f"[summary.py] Error retrieving linked files: {e}")

    all_files_html = []

    # 2. On boucle sur chaque fichier pour créer son interface
    for file_type, file_name in files_to_load:
        print(f"[summary.py] Automatic loading of {file_name} ({file_type})")
        
        try:
            mrun = db.load_mrun_object(file_name, housing)
            if mrun is None:
                all_files_html.append(html.Div(f"Unable to read data from {file_name}.", style={'color': 'orange', 'padding': '10px'}))
                continue
        except FileNotFoundError:
            msg = f"{file_type} '{file_name}' referenced in database, but physically missing."
            all_files_html.append(html.Div(msg, style={'color': 'red', 'padding': '15px', 'border': '1px solid red', 'borderRadius': '5px', 'margin': '10px 0'}))
            continue
        except Exception as e:
            all_files_html.append(html.Div(f"Error with {file_name}: {e}", style={'color': 'red', 'padding': '10px'}))
            continue

        menus_blocks = []
        
        # --- Création des accordéons pour CE fichier précis ---
        for group_name in mrun.MagnetData.list_groups():
            if group_name == 'Infos':
                continue

            sensors = [c for c in mrun.MagnetData.get_group_data(group_name).columns if c not in ('t', 'timestamp')]
            options = []
            for s in sensors:
                try:
                    symbol, unit = mrun.getUnit(s)
                except RuntimeError:
                    try:
                        symbol, unit = mrun.getUnit(f"{group_name}/{s}")
                    except RuntimeError:
                        symbol, unit = None, None

                label = f"{s} ({symbol} [{unit:~P}])" if symbol and unit is not None else (f"{s} ({symbol})" if symbol else s)
                options.append({'label': label, 'value': s})

            menus_blocks.append(
                html.Details([
                    html.Summary(f"📂 {group_name}", style={
                        'fontWeight': 'bold', 'cursor': 'pointer', 'padding': '8px 15px',
                        'backgroundColor': '#e9ecef', 'borderBottom': '1px solid #ddd', 'outline': 'none'
                    }),
                    html.Div([
                        html.Div([
                            dcc.Checklist(
                                id={'type': 'summary-checklist', 'file': file_name, 'group': group_name},
                                options=options,
                                value=[],
                                labelStyle={'display': 'block', 'marginLeft': '25px', 'marginBottom': '4px'} 
                            )
                        ], style={'width': '250px', 'flexShrink': 0, 'padding': '10px', 'borderRight': '1px solid #ddd', 'backgroundColor': '#ffffff'}),
                        
                        html.Div([
                            dcc.Graph(
                                id={'type': 'summary-graph', 'file': file_name, 'group': group_name},
                                style={'height': '350px'}
                            )
                        ], style={'flexGrow': 1, 'minWidth': '0', 'padding': '10px'})
                        
                    ], style={'display': 'flex', 'flexDirection': 'row', 'backgroundColor': '#f8f9fa'})
                ], open=False, style={'border': '1px solid #007bff', 'borderRadius': '8px', 'marginBottom': '10px', 'overflow': 'hidden'})
            )

        # On emballe tous les accordéons de ce fichier dans une belle carte
        file_card = dbc.Card([
            dbc.CardHeader(html.H5(f"{file_type} : {file_name}", className="mb-0", style={'fontWeight': 'bold', 'color': '#0d6efd'})),
            dbc.CardBody(menus_blocks)
        ], style={'marginBottom': '30px', 'boxShadow': '0 4px 8px rgba(0,0,0,0.1)'})

        all_files_html.append(file_card)
        
    return all_files_html


# Callback 4: Mettre à jour le graphique ciblé 
@dash.callback(
    Output({'type': 'summary-graph', 'file': MATCH, 'group': MATCH}, 'figure'),
    Input({'type': 'summary-checklist', 'file': MATCH, 'group': MATCH}, 'value'),
    State('summary-dd-housing', 'value'),
    State({'type': 'summary-checklist', 'file': MATCH, 'group': MATCH}, 'id')
)
def update_summary_graph(selected_sensors, housing, element_id):
    file_name = element_id['file']
    group_name = element_id['group']

    if not selected_sensors or not housing:
        return go.Figure()
        
    df = db.get_group_dataframe(file_name, housing, group_name)
    
    if df is None or df.empty:
        return go.Figure()

    fig = create_plot(df, x_col='t', y_cols=selected_sensors, method='LTTB', filename=file_name)
    return fig