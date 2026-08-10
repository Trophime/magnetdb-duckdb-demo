import os
import dash
from dash import html, dcc, Output, Input, State, MATCH, ALL, Patch, ctx
from dash.exceptions import PreventUpdate
import dash.bootstrap_components as dbc
import plotly.graph_objects as go
import magnetdb_analysis as db
from magnetdb_plot import create_plot, create_comparison_plot
import pandas as pd
from plotly.subplots import make_subplots
from metrics import evaluate_metrics, generate_metrics_report
from python_magnetrun.utils.files import classify_pigbrother_file
import numpy as np


TARGET_TABLE = 'operationaldata'

# --- 1. ENREGISTREMENT ET LAYOUT DASH ---
dash.register_page(
    __name__, 
    path='/comparison', 
    name="Multi-file comparison",
    order=5
)

layout = html.Div([
    html.H2("Visualization and Multi-file Comparison"),
    html.P("Overlay and compare equivalent sensors across multiple files (Pupitre and PigBrother)."),

    dcc.Store(id='zoom-state', data=None),

    dbc.Row([
        # Colonne de gauche : Selecteurs principaux
        dbc.Col([
            html.Div([
                html.Hr(),
                html.Label("1. Choose Site :", style={'fontWeight': 'bold'}),
                dcc.Dropdown(id='dd-site-compare', options=[], placeholder="Choose a site..."),
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
                html.Label("3. Choose Group :", style={'fontWeight': 'bold', 'marginTop': '15px', 'display': 'block'}),
                dcc.Dropdown(
                    id='dd-group',
                    options=['Courants_Alimentations', 'Tensions_Aimant'],
                    value='Courants_Alimentations',
                    clearable=False
                ),
            ], style={"padding": "10px"}),

            html.Div([
                html.Label("4. X-Axis Type :", style={'fontWeight': 'bold', 'marginTop': '15px', 'display': 'block'}),
                dcc.RadioItems(
                    id='comp-xaxis-selector',
                    options=[{'label': 'Temps (t)', 'value': 't'}, {'label': 'Timestamp', 'value': 'timestamp'}],
                    value='t',
                    inline=True
                ),
            ], style={"padding": "10px"}),
            
            html.Div([
                html.Label("5. Downsampling Method :", style={'fontWeight': 'bold', 'marginTop': '15px', 'display': 'block'}),
                dcc.Dropdown(
                    id='comp-method-selector',
                    options=['raw data', 'LTTB', 'minmax', 'M4', 'naive'],
                    value='LTTB',
                    clearable=False
                ),
            ], style={"padding": "10px"}),

            dcc.Store(id='sync-offsets-store', data={}),
            html.Div(id='sync-offsets-display', style={
                'padding': '15px', 
                'marginTop': '20px', 
                'backgroundColor': '#e9ecef', 
                'borderRadius': '8px',
                'borderLeft': '4px solid #007bff'
            }),
            
        ], width=3),

        # Colonne de droite : Zone des blocs cote a cote
        dbc.Col([
            html.H5("Comparison of sensor pairs"),
            html.Div(id='sensors-message', children="Select your files and a group."),
            
            # Conteneur dynamique
            html.Div(id='accordion-container')
        ], width=9)
        
    ], className="g-4")
])


# Chargement des fichiers du site synchronises
@dash.callback(
    Output('dd-site-compare', 'options'),
    Input('dd-database', 'value')
)
def update_site_dropdown(selected_db):
    if not selected_db:
        return []
    return db.get_all_sites(selected_db)



@dash.callback(
    Output('dd-files-compare', 'options'),
    Output('dd-files-compare', 'value'),
    Input('dd-site-compare', 'value'),
    Input('dd-database', 'value')
)
def update_file_dropdown(selected_site, selected_db):
    if not selected_site:
        return [], []

    files = db.get_files_for_site(selected_site, TARGET_TABLE, selected_db)

    pupitre_files = [f for f in files if f.endswith('.txt')]
    pigbrother_files = [f for f in files if f.endswith('.tdms')]

    # 1. Regrouper chaque Pupitre avec ses fichiers PigBrother correspondants
    matched_groups = []

    for p_file in pupitre_files:
        dt_p = db.parse_magnet_filename(p_file)
        matching_pbs = []

        for pb_file in pigbrother_files:
            if db.check_same_date(p_file, pb_file):
                matching_pbs.append(pb_file)

        # Si au moins un PigBrother correspond (ou pour afficher la session)
        if matching_pbs:
            matched_groups.append({
                'p_file': p_file,
                'date': dt_p,
                'pb_files': matching_pbs
            })

    # 2. Trier les groupes chronologiquement par date de run
    matched_groups.sort(key=lambda g: g['date'] if g['date'] is not None else pd.Timestamp.min)

    # 3. Construire les options Dash en plaçant Pupitre suivi immédiatement de ses PigBrother
    options = []
    seen_values = set()  # Évite les doublons 

    for group in matched_groups:
        p_base = os.path.basename(group['p_file'])
        
        # Ajouter le fichier Pupitre
        if p_base not in seen_values:
            options.append({'label': f"Pupitre: {p_base}", 'value': p_base})
            seen_values.add(p_base)

        # Ajouter immédiatement tous ses PigBrother associés
        for pb_file in group['pb_files']:
            pb_base = os.path.basename(pb_file)
            if pb_base not in seen_values:
                options.append({'label': f"PigBrother: {pb_base}", 'value': pb_base})
                seen_values.add(pb_base)

    return options, []

# CALLBACK 2 : Propose tous les groupes presents dans au moins un fichier selectionne
# get_common_groups() loads every selected file via load_mrun_object() sequentially,
# which also warms the shared cache that generate_pair_blocks() and
# update_single_pair_graph() rely on — dd-group's value can only reach them
# after this callback finishes, so they never see a cold cache.
# @dash.callback(
#     Output('dd-group', 'options'),
#     Output('dd-group', 'value'),
#     Input('dd-files-compare', 'value'),
#     Input('dd-site-compare', 'value'),
#     State('dd-group', 'value')
# )
# @db.chrono_callback
# def update_group_dropdown(selected_files, selected_site, current_group):
#     if not selected_files or not selected_site:
#         return [], None

#     housing = selected_site.split('_')[0]
#     valid_groups = db.get_common_groups(selected_files, housing)
#     if not valid_groups:
#         return [], None

#     options = [{'label': g, 'value': g} for g in valid_groups]

   
#     if current_group in valid_groups:
#         return options, dash.no_update

#     default_value = valid_groups[0]
#     return options, default_value


# Generation des blocs
@dash.callback(
    Output('accordion-container', 'children'),
    Output('sensors-message', 'children'),
    Input('dd-group', 'value'),
    Input('dd-files-compare', 'value'),
    State('dd-site-compare', 'value'),
)
def generate_pair_blocks(selected_group, selected_files, selected_site):
    if not selected_files or not selected_group or not selected_site:
        return [], "Select your files and a group."

    housing = selected_site.split('_')[0]
    pairs = db.get_comparable_pairs_for_group(selected_group, selected_files, housing)
    print(f"[comparison] generate_pair_blocks: selected_group={selected_group}, selected_files={selected_files}, housing={housing}")
    print(f"[comparison] generate_pair_blocks: pairs={len(pairs)}")
    for pair in pairs:
        print(f"[comparison] pair: {pair['label']} -> channels={pair['channels']}")

    if not pairs:
        return [], f"No data found for group '{selected_group}' in the selected files."

    blocks = []
    for pair in pairs:
        pair_id = pair['id']
        channels = pair['channels']  # {'pupitre': 'Idcct1', 'pigbrother': 'Courant_A1', ...}
        pair_title = f"{pair['label']} (" + ", ".join(f"{fmt}: {ch}" for fmt, ch in channels.items()) + ")"

        options = [
            {'label': f" {fmt.capitalize()} ({ch})", 'value': f"{fmt}:{ch}"}
            for fmt, ch in channels.items()
        ]

        default_values = [opt['value'] for opt in options]

        block = html.Details([
            
            # 1. LE BOUTON ACCORDÉON 
            html.Summary(f"📂 {pair_title}", style={
                'fontWeight': 'bold', 
                'cursor': 'pointer',
                'padding': '10px 15px',
                'backgroundColor': '#e9ecef',
                'borderBottom': '1px solid #ddd',
                'outline': 'none',
                'fontSize': '14px'
            }),
            
            # 2. LE CONTENU 
            html.Div([
                
                # Colonne Gauche (Checklist)
                html.Div([
                    html.P(pair['description'], style={'fontStyle': 'italic', 'fontSize': '11px', 'color': '#666', 'marginBottom': '6px'}),
                    dcc.Checklist(
                        id={'type': 'pair-checklist', 'index': pair_id},
                        options=options,
                        value=default_values,
                        labelStyle={'display': 'block', 'marginLeft': '10px', 'marginBottom': '4px', 'fontSize': '13px'} 
                    )
                ], style={
                    'width': '280px',
                    'flexShrink': 0,
                    'padding': '10px',
                    'borderRight': '1px solid #ddd',
                    'backgroundColor': '#ffffff'
                }),
                
                # Colonne Droite (Graphique)
                html.Div(
                    children=[
                        dcc.Graph(
                            id={'type': 'pair-graph', 'index': pair_id},
                            style={'height': '650px'}
                        )
                    ], 
                    style={
                        'flexGrow': 1,
                        'minWidth': '0',
                        'padding': '10px'
                    }
                )
                
            ], style={
                'display': 'flex',
                'flexDirection': 'row',
                'backgroundColor': '#f8f9fa'
            })
            
        ], open=True, style={
            'border': '1px solid #007bff',
            'borderRadius': '8px',
            'marginBottom': '20px',
            'boxShadow': '0 2px 4px rgba(0,0,0,0.05)',
            'overflow': 'hidden',
            'backgroundColor': '#ffffff'
        })
        
        blocks.append(block)
        
    return blocks, ""


# Calcul centralisé des décalages temporels 
@dash.callback(
    Output('sync-offsets-store', 'data'),
    Output('sync-offsets-display', 'children'),
    Input('dd-files-compare', 'value'),
    Input('dd-site-compare', 'value')
)
@db.chrono_callback
def calculate_all_offsets(selected_files, selected_site):
    if not selected_files or not selected_site:
        return {}, "No files selected for synchronization."
    
    housing = selected_site.split('_')[0]
    
    # 1. Identifier le GROUPE de fichiers Maîtres
    overview_files = [f for f in selected_files if 'overview' in f.lower()]
    
    if overview_files:
        master_files = overview_files
    else:
        # S'il n'y a pas d'Overview, les fichiers Pupitres deviennent les maîtres
        pupitres = [f for f in selected_files if f.endswith('.txt')]
        master_files = pupitres if pupitres else [selected_files[0]]
        
    # 2. CONSTRUIRE LA TIMELINE CONTINUE DU MAÎTRE 
    df_master_list = []
    for f in master_files:
        df_part = db.get_group_dataframe(f, housing, 'Courants_Alimentations')
        if df_part is not None and not df_part.empty:
            df_master_list.append(df_part)
            
    if not df_master_list:
        return {}, "Waiting for reference data..."
        
    # On colle tous les morceaux pour faire une chronologie géante
    df_master = pd.concat(df_master_list).sort_values(by='timestamp').reset_index(drop=True)
    t0_absolu = df_master['timestamp'].min()
    
    # Identifier la colonne pour la fonction mathématique
    col_master = 'Idcct1' if master_files[0].endswith('.txt') else 'Courant_A1'
    
    sync_data = {'offsets': {}, 't0_absolu': t0_absolu.isoformat()}
    
    display_elements = [
        html.H6("Time Synchronization", style={'marginBottom': '10px', 'fontWeight': 'bold'}),
        html.Div("Reference : " + ", ".join(master_files), style={'fontWeight': 'bold', 'color': '#007bff', 'marginBottom': '10px', 'wordWrap': 'break-word'})
    ]
    
    # 3. Calculer le lag de chaque fichier cible par rapport à la chronologie géante
    for f in selected_files:
        # A. Les fichiers qui composent le maître ne bougent pas
        if f in master_files:
            sync_data['offsets'][f] = 0.0  
            display_elements.append(html.Div([
                html.Span(f"{f} : ", style={'fontWeight': 'bold'}),
                html.Span("0.000 s (T0)", style={'color': '#007bff'})
            ], style={'fontSize': '14px', 'marginBottom': '4px'}))
            continue
            
        # On ignore le calcul complexe pour les fichiers d'événements
        file_type = classify_pigbrother_file(f)
        if file_type in ['default', 'spike', 'trigger', 'archive']:
            sync_data['offsets'][f] = 0.0  # Pas de lag calculé
            display_elements.append(html.Div([
                html.Span(f"{f} : ", style={'fontWeight': 'bold'}),
                html.Span("0.000 s", style={'color': '#17a2b8'}) # Bleu cyan pour différencier
            ], style={'fontSize': '14px', 'marginBottom': '4px'}))
            continue

        # C. Calcul normal pour les autres fichiers (Pupitres, Archives classiques...)
        df_target = db.get_group_dataframe(f, housing, 'Courants_Alimentations')
        if df_target is not None and not df_target.empty:
            col_target = 'Idcct1' if f.endswith('.txt') else 'Courant_A1'
            
            lag = db.get_lag(
                df_pupitre=df_master, 
                df_pb=df_target, 
                column_current_pupitre=col_master, 
                column_current_pigbrother=col_target
            )
            
            sync_data['offsets'][f] = lag
            
            display_elements.append(html.Div([
                html.Span(f"{f} : ", style={'fontWeight': 'bold'}),
                html.Span(f"{lag:.3f} s", style={'color': '#28a745' if lag == 0 else '#dc3545'})
            ], style={'fontSize': '14px', 'marginBottom': '4px'}))

            try:
                # 1. Utiliser le temps du maître comme référence
                t_ref = df_master['timestamp'].astype('int64') / 10**9
                y_ref = df_master[col_master].values
                
                # 2. Utiliser le temps de la cible
                t_target = df_target['timestamp'].astype('int64') / 10**9
                y_target = df_target[col_target].values
                
                # 3. Interpoler la cible sur la base de temps du maître (avec le lag)
                # Cela aligne les signaux et les met à la même dimension
                y_sec_aligned = np.interp(t_ref, t_target + lag, y_target, left=np.nan, right=np.nan)
                y_sec_unaligned = np.interp(t_ref, t_target, y_target, left=np.nan, right=np.nan)
                
                # 4. Calcul (evaluate_metrics gère les nan via nanmean/nanvar)
                results = evaluate_metrics(y_ref, y_sec_unaligned, y_sec_aligned)
                
                generate_metrics_report(
                    file_ref=master_files[0], 
                    sensor_ref=col_master,
                    file_sec=f,               
                    sensor_sec=col_target,
                    results=results,
                    lag_seconds=lag
                )
            except Exception as e:
                print(f"[metrics] Erreur rapport pour {f} : {e}")
    
    return sync_data, display_elements

# Création d'un graphique unique pour chaque paire de capteurs sélectionnée
@dash.callback(
    Output({'type': 'pair-graph', 'index': MATCH}, 'figure'),

    Input({'type': 'pair-checklist', 'index': MATCH}, 'value'),
    Input('comp-xaxis-selector', 'value'),
    Input('comp-method-selector', 'value'),
    Input('dd-site-compare', 'value'),

    State('sync-offsets-store', 'data'),
    State('dd-files-compare', 'value'),
    State('dd-group', 'value'),
    State({'type': 'pair-graph', 'index': ALL}, 'relayoutData')
)
@db.chrono_callback
def update_single_pair_graph(selected_pair_channels, xaxis_type, selected_method, selected_site, sync_data, selected_files, selected_group, all_relayout_data):
    
    if not selected_pair_channels or not selected_files or not selected_site:
        return go.Figure()

    # --- 1. Gestion du Zoom en mémoire ---
    maintain_zoom = False
    triggered_id = ctx.triggered_id
    if triggered_id == 'comp-method-selector' or (isinstance(triggered_id, dict) and triggered_id.get('type') == 'pair-checklist'):
        maintain_zoom = True

    x_range = None
    if maintain_zoom and all_relayout_data:
        for relayout in all_relayout_data:
            if relayout:
                for key, value in relayout.items():
                    if key.startswith('xaxis') and key.endswith('.range[0]'):
                        axis_name = key.split('.')[0]
                        x_range = [value, relayout.get(f'{axis_name}.range[1]')]
                        break
                    elif key.startswith('xaxis') and key.endswith('.range'):
                        x_range = [value[0], value[1]]
                        break
                if x_range:
                    break

    pupitre_sensors = [val.split(':')[1] for val in selected_pair_channels if val.startswith('pupitre:')]
    pigbrother_sensors = [val.split(':')[1] for val in selected_pair_channels if val.startswith('pigbrother:')]

    housing = selected_site.split('_')[0]
    sync_data = sync_data or {}
    offsets = sync_data.get('offsets', {})
    t0_str = sync_data.get('t0_absolu')
    t0_absolu = pd.to_datetime(t0_str) if t0_str else None

    # --- 2. PREPARATION DU PAQUET DE DONNÉES ---
    files_data = []
    
    for file in selected_files:
        is_pupitre = file.endswith('.txt')
        sensors_to_plot = pupitre_sensors if is_pupitre else pigbrother_sensors

        if not sensors_to_plot:
            continue

        try:
            mrun = db.load_mrun_object(file, housing)
            df_base = db.get_group_dataframe(file, housing, selected_group)
            
            if df_base is None or df_base.empty:
                continue

            # Calcul du t relatif si besoin
            if xaxis_type == 't' and t0_absolu is not None and 't' not in df_base.columns:
                df_base['t'] = (df_base['timestamp'] - t0_absolu).dt.total_seconds()

            #On applique le lag stocké de manière universelle
            lag_val = offsets.get(file, 0.0)

            files_data.append({
                'file': file,
                'df': df_base,
                'is_pupitre': is_pupitre,
                'sensors': sensors_to_plot,
                'lag': lag_val,
                'mrun': mrun,
                'group_name': selected_group
            })
        except Exception as e:
            print(f"Erreur chargement {file}: {e}")

    # --- 3. CREATION UNIQUE DE LA FIGURE ---
    fig = create_comparison_plot(
        files_data=files_data,
        x_col=xaxis_type,
        method=selected_method,
        t0_absolu=t0_absolu
    )

    # Re-application du zoom conservé si nécessaire
    if x_range is not None:
        fig.update_layout(
            xaxis_range=x_range, 
            xaxis_autorange=False
        )

    return fig

# Synchronisation du zoom entre tous les accordéons
@dash.callback(
    Output({'type': 'pair-graph', 'index': ALL}, 'figure', allow_duplicate=True),
    Output('zoom-state', 'data'),  
    Input({'type': 'pair-graph', 'index': ALL}, 'relayoutData'),
    State({'type': 'pair-graph', 'index': ALL}, 'id'),
    State('zoom-state', 'data'),   
    prevent_initial_call=True
)
def sync_zoom_comparison(relayout_data_list, graph_ids, current_zoom):
    triggered_id = ctx.triggered_id
    if not triggered_id or not graph_ids:
        raise PreventUpdate

    try:
        trigger_index = graph_ids.index(triggered_id)
        relayout_data = relayout_data_list[trigger_index]
    except ValueError:
        raise PreventUpdate

    if not relayout_data:
        raise PreventUpdate

    x_min, x_max = None, None
    autoscale = False

    # 1. Extraction des coordonnées du zoom X
    for key, value in relayout_data.items():
        if key.startswith('xaxis') and key.endswith('.range[0]'):
            axis_name = key.split('.')[0]
            x_min = value
            x_max = relayout_data.get(f'{axis_name}.range[1]')
            break
        elif key.startswith('xaxis') and key.endswith('.range'):
            x_min, x_max = value[0], value[1]
            break
        elif key.startswith('xaxis') and key.endswith('.autorange'):
            autoscale = True
            break

    if x_min is None and not autoscale:
        raise PreventUpdate

    new_state = {'autoscale': autoscale, 'range': [x_min, x_max] if not autoscale else None}

    # Anti-boucle infinie
    if new_state == current_zoom:
        raise PreventUpdate

    # 2. Application du Patch sur tous les autres graphiques
    patches = []
    for g_id in graph_ids:
        if g_id == triggered_id:
            patches.append(dash.no_update)
            continue
            
        patched_fig = Patch()
        
        if autoscale:
            patched_fig['layout']['xaxis']['autorange'] = True
            patched_fig['layout']['yaxis']['autorange'] = True
        else:
            patched_fig['layout']['xaxis']['range'] = [x_min, x_max]
            patched_fig['layout']['xaxis']['autorange'] = False
            
        patches.append(patched_fig)

    return patches, new_state