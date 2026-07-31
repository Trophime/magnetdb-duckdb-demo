import os
import dash
from dash import html, dcc, Output, Input, State, MATCH, ALL, Patch, ctx
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import magnetdb_analysis as db
from magnetdb_plot import create_plot, create_comparison_plot
import pandas as pd
from plotly.subplots import make_subplots
from metrics import evaluate_metrics, generate_metrics_report


TARGET_TABLE = 'operationaldata'

# --- 1. ENREGISTREMENT ET LAYOUT DASH ---
dash.register_page(
    __name__, 
    path='/comparison', 
    name="Multi-file comparison",
    order=5
)

layout = html.Div([
    html.H2("Visualisation et Comparaison Multi-fichiers"),
    html.P("Superposez et comparez les capteurs equivalents entre plusieurs fichiers (Pupitre et PigBrother)."),

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
            html.H5("Comparaison des paires de capteurs"),
            html.Div(id='sensors-message', children="Selectionnez vos fichiers et un groupe."),
            
            # Conteneur dynamique
            html.Div(id='accordion-container')
        ], width=9)
        
    ], className="g-4")
])

# --- 2. CALLBACKS ---

# CALLBACK 1 : Chargement des fichiers du site synchronises
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

    options = []
    for p_file in pupitre_files:
        matched_pb_file = None
        for pb_file in pigbrother_files:
            if db.check_same_date(p_file, pb_file):
                matched_pb_file = pb_file
                break

        if matched_pb_file:
            options.append({'label': f"Pupitre: {os.path.basename(p_file)}", 'value': os.path.basename(p_file)})
            options.append({'label': f"PigBrother: {os.path.basename(matched_pb_file)}", 'value': os.path.basename(matched_pb_file)})
            pigbrother_files.remove(matched_pb_file)

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


# CALLBACK 3 : Generation des blocs
@dash.callback(
    Output('accordion-container', 'children'),
    Output('sensors-message', 'children'),
    Input('dd-group', 'value'),
    Input('dd-files-compare', 'value'),
    State('dd-site-compare', 'value'),
)
@db.chrono_callback
def generate_pair_blocks(selected_group, selected_files, selected_site):
    if not selected_files or not selected_group or not selected_site:
        return [], "Selectionnez vos fichiers et un groupe."

    housing = selected_site.split('_')[0]
    pairs = db.get_comparable_pairs_for_group(selected_group, selected_files, housing)
    print(f"[comparison] generate_pair_blocks: selected_group={selected_group}, selected_files={selected_files}, housing={housing}")
    print(f"[comparison] generate_pair_blocks: pairs={len(pairs)}")
    for pair in pairs:
        print(f"[comparison] pair: {pair['label']} -> channels={pair['channels']}")

    if not pairs:
        return [], f"Aucune donnee trouvee pour le groupe '{selected_group}' dans les fichiers selectionnes."

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

        block = html.Div([
            html.Div([
                html.Details([
                    html.Summary(f"📂 {pair_title}", style={
                        'fontWeight': 'bold', 
                        'cursor': 'pointer',
                        'marginBottom': '5px',
                        'outline': 'none',
                        'fontSize': '14px'
                    }),
                    
                    html.Div([
                        html.P(pair['description'], style={'fontStyle': 'italic', 'fontSize': '11px', 'color': '#666', 'marginBottom': '6px'}),
                        dcc.Checklist(
                            id={'type': 'pair-checklist', 'index': pair_id},
                            options=options,
                            value=default_values,
                            labelStyle={'display': 'block', 'marginLeft': '10px', 'marginBottom': '4px', 'fontSize': '13px'} 
                        )
                    ], style={'marginBottom': '10px'})
                ], open=True)
            ], style={
                'width': '280px',
                'flexShrink': 0,
                'padding': '10px',
                'borderRight': '1px solid #ddd',
                'backgroundColor': '#ffffff'
            }),
            
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
            'border': '1px solid #007bff',
            'borderRadius': '8px',
            'marginBottom': '20px',
            'boxShadow': '0 2px 4px rgba(0,0,0,0.05)',
            'backgroundColor': '#f8f9fa'
        })
        
        blocks.append(block)
        
    return blocks, ""


# CALLBACK NOUVEAU : Calcul centralisé des décalages temporels
@dash.callback(
    Output('sync-offsets-store', 'data'),
    Output('sync-offsets-display', 'children'),
    Input('dd-files-compare', 'value'),
    Input('dd-site-compare', 'value')
)
@db.chrono_callback
def calculate_all_offsets(selected_files, selected_site):
    if not selected_files or not selected_site:
        return {}, "Aucun fichier sélectionné pour la synchronisation."
    
    housing = selected_site.split('_')[0]
    
    # 1. Construire le Master Pupitre pour le T0
    df_pupitres_list = []
    for f in selected_files:
        if f.endswith('.txt'):
            df_ref = db.get_group_dataframe(f, housing, 'Courants_Alimentations')
            if df_ref is not None and not df_ref.empty:
                df_pupitres_list.append(df_ref.copy())
    
    if not df_pupitres_list:
        return {}, "En attente d'un fichier Pupitre (horloge maître)..."
        
    df_pupitre_master = pd.concat(df_pupitres_list).sort_values(by='timestamp').reset_index(drop=True)
    t0_absolu = df_pupitre_master['timestamp'].min()
    
    # Préparation du dictionnaire de stockage
    # On convertit le T0 en texte ISO pour pouvoir le passer dans dcc.Store (JSON)
    sync_data = {'offsets': {}, 't0_absolu': t0_absolu.isoformat()}
    
    # Préparation de l'affichage HTML
    display_elements = [
        html.H6("Synchronisation Temporelle", style={'marginBottom': '10px', 'fontWeight': 'bold'})
    ]
    
    # 2. Calculer le lag unique pour chaque PigBrother
    for f in selected_files:
        if f.endswith('.tdms'):
            df_pb_ref = db.get_group_dataframe(f, housing, 'Courants_Alimentations')
            if df_pb_ref is not None and not df_pb_ref.empty:
                lag = db.get_lag(
                    df_pupitre_master, df_pb_ref, 
                    column_current_pupitre='Idcct1', 
                    column_current_pigbrother='Courant_A1'
                )
                sync_data['offsets'][f] = lag
                
                # Ajout de la ligne visuelle sur le site
                display_elements.append(html.Div([
                    html.Span(f"{f} : ", style={'fontWeight': 'bold'}),
                    html.Span(f"{lag:.3f} s", style={'color': '#28a745' if lag == 0 else '#dc3545'})
                ], style={'fontSize': '14px', 'marginBottom': '4px'}))
    
    if not sync_data['offsets']:
        display_elements.append(html.Div("Aucun fichier PigBrother à décaler.", style={'fontSize': '14px'}))
        
    return sync_data, display_elements

# CALLBACK 4 : Trace unifie avec Heritage du Zoom (AVEC SUBPLOTS AVANT/APRES VIA FONCTION EXTERNE)
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

    maintain_zoom = False
    triggered_id = ctx.triggered_id
    if triggered_id == 'comp-method-selector' or (isinstance(triggered_id, dict) and triggered_id.get('type') == 'pair-checklist'):
        maintain_zoom = True

    x_range = None
    if maintain_zoom and all_relayout_data:
        for relayout in all_relayout_data:
            if relayout:
                if 'xaxis.range[0]' in relayout:
                    x_range = [relayout['xaxis.range[0]'], relayout['xaxis.range[1]']]
                    break
                elif 'xaxis.range' in relayout:
                    x_range = [relayout['xaxis.range'][0], relayout['xaxis.range'][1]]
                    break

    pupitre_sensors = [val.split(':')[1] for val in selected_pair_channels if val.startswith('pupitre:')]
    pigbrother_sensors = [val.split(':')[1] for val in selected_pair_channels if val.startswith('pigbrother:')]

    housing = selected_site.split('_')[0]
    sync_data = sync_data or {}
    offsets = sync_data.get('offsets', {})
    t0_str = sync_data.get('t0_absolu')
    t0_absolu = pd.to_datetime(t0_str) if t0_str else None

# --- CONTENEUR POUR STOCKER LES DONNÉES DES MÉTRIQUES ---
    metrics_data = {
        'ref_file': None, 'ref_sensor': None, 'ref_y': None,          
        'sec_file': None, 'sec_sensor': None, 'sec_y_unaligned': None,
        'sec_y_aligned': None,
        'sec_lag': 0.0                                                 
    }
    # --- CRÉATION DU CONTENEUR PRINCIPAL ---
    main_fig = make_subplots(
        rows=2, cols=1, 
        shared_xaxes=True, 
        vertical_spacing=0.1,
        subplot_titles=("Signaux Bruts (Avant alignement)", "Signaux Synchronisés (Après alignement)")
    )

    for file in selected_files:
        is_pupitre = file.endswith('.txt')
        sensors_to_plot = pupitre_sensors if is_pupitre else pigbrother_sensors

        if not sensors_to_plot:
            continue

        try:
            mrun = db.load_mrun_object(file, housing)
            if mrun is None:
                continue

            df_base = db.get_group_dataframe(file, housing, selected_group)
            if df_base is None or df_base.empty:
                continue
            
            # --- 1. PRÉPARATION DU DF BRUT  ---
            df_unaligned = df_base.copy()
            if xaxis_type == 't' and t0_absolu is not None:
                df_unaligned['t'] = (df_unaligned['timestamp'] - t0_absolu).dt.total_seconds()

            # --- 2. PRÉPARATION DU DF ALIGNÉ ---
            df_aligned = df_base.copy()
            if not is_pupitre and file in offsets:
                # --- Sauvegarde du lag ---
                lag_val = offsets[file]
                metrics_data['sec_lag'] = lag_val
                df_aligned['timestamp'] = df_aligned['timestamp'] + pd.to_timedelta(lag_val, unit='s')
            
            if xaxis_type == 't' and t0_absolu is not None:
                df_aligned['t'] = (df_aligned['timestamp'] - t0_absolu).dt.total_seconds()

            # --- EXTRACTION DES VECTEURS POUR LES MÉTRIQUES ---
            col_metric = sensors_to_plot[0] 
            if is_pupitre:
                metrics_data['ref_file'] = file
                metrics_data['ref_sensor'] = col_metric  
                metrics_data['ref_y'] = df_aligned[col_metric].values 
            else:
                metrics_data['sec_file'] = file
                metrics_data['sec_sensor'] = col_metric  
                metrics_data['sec_y_unaligned'] = df_unaligned[col_metric].values
                metrics_data['sec_y_aligned'] = df_aligned[col_metric].values

            # --- 3. APPEL DE LA FONCTION CRÉANT LES TRACES ---
            sub_fig = create_comparison_plot(
                df_unaligned=df_unaligned,
                df_aligned=df_aligned,
                x_col=xaxis_type,
                y_cols=sensors_to_plot,
                method=selected_method,
                filename=file,
                mrun=mrun,
                group_name=selected_group
            )

            # --- 4. TRANSFERT DES TRACES DANS LE SUBPLOT PRINCIPAL ---
            for trace in sub_fig.data:
                row_idx = 1 if getattr(trace, 'yaxis', 'y') in [None, 'y', 'y1'] else 2
                trace.name = f"{file} - {trace.name}"
                trace.legendgroup = file
                main_fig.add_trace(trace, row=row_idx, col=1)

        except Exception as e:
            print(f"Erreur lors du tracé du fichier {file}: {e}")

   # --- GÉNÉRATION DU RAPPORT DE MÉTRIQUES ---
    if metrics_data['ref_y'] is not None and metrics_data['sec_y_aligned'] is not None:
        try:
            results = evaluate_metrics(
                metrics_data['ref_y'], 
                metrics_data['sec_y_unaligned'], 
                metrics_data['sec_y_aligned']
            )
            # --- NOUVEAU : On passe les capteurs et le lag_seconds ---
            report_path = generate_metrics_report(
                metrics_data['ref_file'], 
                metrics_data['ref_sensor'], 
                metrics_data['sec_file'], 
                metrics_data['sec_sensor'], 
                results,
                lag_seconds=metrics_data['sec_lag']
            )
            print(f"Report generated: {report_path}")
        except Exception as e:
            print(f"Error occurred while generating metrics: {e}")

    # --- 5. MISE EN FORME GLOBALE ---
    main_fig.update_layout(
        title=f"Comparaison Avant/Après (Algo: {selected_method})", 
        uirevision='constant',
        margin=dict(t=50, b=20, l=20, r=20),
        hovermode="x unified",
        template="plotly_white",
        legend=dict(orientation="h", yanchor="bottom", y=1.05, xanchor="right", x=1)
    )
    
    if x_range is not None:
        main_fig.update_layout(
            xaxis=dict(range=x_range, autorange=False)
        )

    return main_fig

# CALLBACK 5 : Synchronisation du zoom a la souris avec sécurité Anti-Boucle
@dash.callback(
    Output({'type': 'pair-graph', 'index': ALL}, 'figure', allow_duplicate=True),
    Output('zoom-state', 'data'),  # <-- NOUVEL OUTPUT
    Input({'type': 'pair-graph', 'index': ALL}, 'relayoutData'),
    State({'type': 'pair-graph', 'index': ALL}, 'id'),
    State('zoom-state', 'data'),   # <-- NOUVEAU STATE
    prevent_initial_call=True
)
@db.chrono_callback
def sync_zoom_comparison(relayout_data_list, graph_ids, current_zoom):
    triggered_id = ctx.triggered_id
    if not triggered_id:
        raise PreventUpdate

    if triggered_id not in graph_ids:
        raise PreventUpdate
    trigger_index = graph_ids.index(triggered_id)
    relayout_data = relayout_data_list[trigger_index]

    if not relayout_data:
        raise PreventUpdate

    x_min, x_max = None, None
    autoscale = False

    # On ne considère un "vrai" zoom que si les clés sont exactement celles d'un drag utilisateur
    keys = set(relayout_data.keys())
    if {'xaxis.range[0]', 'xaxis.range[1]'}.issubset(keys):
        x_min = relayout_data['xaxis.range[0]']
        x_max = relayout_data['xaxis.range[1]']
    elif 'xaxis.range' in relayout_data:
        x_min, x_max = relayout_data['xaxis.range']
    elif keys == {'xaxis.autorange', 'yaxis.autorange'} or keys == {'xaxis.autorange'}:
        autoscale = True
    else:
        # Événement "bruit" (autosize, redraw complet déclenché par Dash) -> on ignore
        raise PreventUpdate

    new_state = {'autoscale': autoscale, 'range': [x_min, x_max] if not autoscale else None}

    # VERROU ANTI-BOUCLE INFINIE : si l'état ne change pas réellement, on stoppe la propagation
    if new_state == current_zoom:
        raise PreventUpdate

    patches = []
    for g_id in graph_ids:
        if g_id == triggered_id:
            patches.append(dash.no_update)
            continue
            
        patched_fig = Patch()
        
        if autoscale:
            patched_fig['layout']['xaxis']['autorange'] = True
        else:
            patched_fig['layout']['xaxis']['range'] = [x_min, x_max]
            patched_fig['layout']['xaxis']['autorange'] = False
            
        patches.append(patched_fig)

    return patches, new_state