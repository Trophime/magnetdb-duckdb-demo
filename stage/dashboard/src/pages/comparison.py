import dash
from dash import html, dcc, Output, Input, State, MATCH, ALL, Patch, ctx
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import magnetdb_analysis as db
from magnetdb_plot import create_plot

target_table = 'operationaldata'

# --- 1. ENREGISTREMENT ET LAYOUT DASH ---
dash.register_page(
    __name__, 
    path='/comparison', 
    name="Multi-file comparison"
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
                html.Label("3. Choose Group :", style={'fontWeight': 'bold', 'marginTop': '15px', 'display': 'block'}),
                dcc.Dropdown(
                    id='dd-group',
                    options=[],
                    placeholder="Select a group..."
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
    Output('dd-files-compare', 'options'),
    Input('dd-site', 'value')
)
def update_file_dropdown(selected_site):
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
            options.append({'label': f"Pupitre: {p_file}", 'value': p_file})
            options.append({'label': f"PigBrother: {matched_pb_file}", 'value': matched_pb_file})
            pigbrother_files.remove(matched_pb_file)
        
    return options

# CALLBACK 2 : Ne propose QUE les groupes qui possedent des alias
@dash.callback(
    Output('dd-group', 'options'),
    Output('dd-group', 'value'),
    Input('dd-files-compare', 'value'),
    Input('dd-site', 'value'),
    State('dd-group', 'value')  
)
def update_group_dropdown(selected_files, selected_site, current_group):
    if not selected_files or not selected_site:
        return [], None
    
    valid_groups = db.get_comparable_groups()
    if not valid_groups:
        return [], None

    options = [{'label': g, 'value': g} for g in valid_groups]
    
    # <-- MAGIE : Si un groupe est déjà choisi, on refuse de le remettre à zéro !
    if current_group in valid_groups:
        return options, dash.no_update 
        
    default_value = valid_groups[0] 
    return options, default_value

# CALLBACK 3 : Generation des blocs
@dash.callback(
    Output('accordion-container', 'children'),
    Output('sensors-message', 'children'),
    Input('dd-group', 'value'),                  # <-- UNIQUE DÉCLENCHEUR (Input)
    State('dd-files-compare', 'value')           # <-- SIMPLE LECTURE (State)
)
@db.chrono_callback
def generate_pair_blocks(selected_group, selected_files):
    if not selected_files or not selected_group:
        return None, "Selectionnez vos fichiers et un groupe."
    
    pairs = db.get_comparable_pairs_for_group(selected_group)
    
    if not pairs:
        return None, f"Aucune paire comparable trouvee pour le groupe '{selected_group}'."
    
    blocks = []
    for pair in pairs:
        pair_id = pair['id']
        pair_title = f"{pair['label']} ({pair['pupitre']} ↔ {pair['pigbrother']})"
        
        options = [
            {'label': f" Pupitre ({pair['pupitre']})", 'value': f"pupitre:{pair['pupitre']}"},
            {'label': f" PigBrother ({pair['pigbrother']})", 'value': f"pigbrother:{pair['pigbrother']}"}
        ]

        default_values = []

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
                        style={'height': '350px'}
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

# CALLBACK 4 : Trace unifie avec Heritage du Zoom
@dash.callback(
    Output({'type': 'pair-graph', 'index': MATCH}, 'figure'),
    
    Input({'type': 'pair-checklist', 'index': MATCH}, 'value'),
    Input('dd-files-compare', 'value'),
    Input('comp-xaxis-selector', 'value'),
    Input('comp-method-selector', 'value'), 
    Input('dd-site', 'value'),
    State('dd-group', 'value'),
    State({'type': 'pair-graph', 'index': ALL}, 'relayoutData')
)
@db.chrono_callback
def update_single_pair_graph(selected_pair_channels, selected_files, xaxis_type, selected_method, selected_site, selected_group, all_relayout_data):
    
    # SI AUCUNE CASE N'EST COCHEE : graphique vide
    if not selected_pair_channels or not selected_files or not selected_site:
        fig_empty = go.Figure()
        fig_empty.update_layout(
            annotations=[{
                'text': "Cochez au moins un capteur dans le menu de gauche pour afficher la courbe",
                'xref': "paper", 'yref': "paper",
                'showarrow': False,
                'font': {'size': 13, 'color': '#888888'}
            }],
            xaxis={'showgrid': False, 'zeroline': False, 'visible': False},
            yaxis={'showgrid': False, 'zeroline': False, 'visible': False},
            template="plotly_white",
            margin=dict(l=20, r=20, t=30, b=20)
        )
        return fig_empty

    # --- ETAPE 1 : DETERMINER SI ON DOIT CONSERVER LE ZOOM ---
    maintain_zoom = False
    triggered_id = ctx.triggered_id
    
    if triggered_id == 'comp-method-selector' or (isinstance(triggered_id, dict) and triggered_id.get('type') == 'pair-checklist'):
        maintain_zoom = True

    # --- ETAPE 2 : EXTRAIRE LES LIMITES DU ZOOM ACTUEL ---
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

    # --- PREPARATION DES DONNEES ---
    pupitre_sensors = []
    pigbrother_sensors = []

    for val in selected_pair_channels:
        file_type, sensor = val.split(':', 1)
        if file_type == 'pupitre':
            pupitre_sensors.append(sensor)
        elif file_type == 'pigbrother':
            pigbrother_sensors.append(sensor)

    main_fig = None
    housing = selected_site.split('_')[0]

    # --- BOUCLE SUR LES FICHIERS POUR SUPERPOSER ---
    for file in selected_files:
        is_pupitre = file.endswith('.txt')
        sensors_to_plot = pupitre_sensors if is_pupitre else pigbrother_sensors
        
        if not sensors_to_plot:
            continue

        try:
            mrun = db.load_mrun_object(file, housing)
            if mrun is None:
                continue
                
            df = db.load_data(file, selected_site, housing) 
            
            sub_fig = create_plot(
                df=df, 
                x_col=xaxis_type, 
                y_cols=sensors_to_plot, 
                method=selected_method,  
                filename=file,
                mrun=mrun,
                group_name=selected_group 
            )
            
            # Gestion de la superposition
            if main_fig is None:
                main_fig = sub_fig
                for trace in main_fig.data:
                    trace.name = f"{file} - {trace.name}"
            else:
                for trace in sub_fig.data:
                    trace.name = f"{file} - {trace.name}"
                    main_fig.add_trace(trace)
                
        except Exception as e:
            print(f"Erreur lors du trace du fichier {file}: {e}")

    if main_fig is None:
        return go.Figure()

    # --- ETAPE 3 : APPLICATION DU LAYOUT FINAL ET DU ZOOM ---
    main_fig.update_layout(
        title=f"Comparaison de capteurs (Algo: {selected_method})",
        uirevision='constant'
    )
    
    if x_range is not None:
        main_fig.update_layout(xaxis=dict(range=x_range, autorange=False))

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