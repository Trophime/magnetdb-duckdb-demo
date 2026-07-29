from dash import Dash, html, dcc, Input, Output, no_update, ALL, State, register_page, MATCH, Patch, ctx
import dash
from dash.exceptions import PreventUpdate
import plotly.express as px
from plotly import graph_objects as go
import magnetdb_analysis as db
import magnetdb_plot as plot
import pandas as pd

dash.register_page(__name__, path='/')


# `site`/`file` are populated by Dash Pages from the URL's query string (e.g. the
# links generated on the "Assembly stats" page: /?site=...&file=...), so the
# dropdowns get their initial value at first render instead of via a callback
# racing against the (async) options-loading callbacks below. Seeding `options`
# with the value itself guarantees the label is shown immediately, rather than
# a blank/placeholder box until the real option list (loaded from DuckDB by the
# callbacks further down) happens to include a matching entry.
def layout(site=None, file=None, **kwargs):
    return html.Div([
        dcc.Store(id='pending-auto-plot', data=['Field'] if (site and file) else []),
        html.Div([
            html.H2("Magnetdb Dashboard", style={'marginTop': '0px', 'marginBottom': '20px'}),
            html.Hr(),

            html.Label("1. Choose Site :", style={'fontWeight': 'bold'}),
            dcc.Dropdown(id='dd-site', options=[site] if site else [], value=site, placeholder="Choose a site..."),

            html.Br(),
            html.Label("2. Choose Table :", style={'fontWeight': 'bold'}),
            dcc.Dropdown(id='dd-table', options=['experiments', 'operationaldata'], value='experiments'),

            html.Br(),
            html.Label("3. Choose File :", style={'fontWeight': 'bold'}),
            dcc.Dropdown(id='dd-file', options=[file] if file else [], value=file, placeholder="Choose a file..."),

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
                options=['raw data', 'LTTB', 'minmax', 'M4', 'naive'],
                value='LTTB',
                clearable=False
            )

        ], style={'padding': '20px', 'backgroundColor': '#f8f9fa', 'minHeight': '100vh'})
    ])


# CALLBACK 0 : Met à jour la liste des sites en fonction de la Database sélectionnée
@dash.callback(
    Output('dd-site', 'options'),
    Input('dd-database', 'value')
)
def update_site_dropdown(selected_db):
    if not selected_db:
        return []
    return db.get_all_sites(selected_db)


# CALLBACK 1 : Met à jour la liste des fichiers en fonction du Site ET de la Table
@dash.callback(
    Output('dd-file', 'options'),
    Input('dd-site', 'value'),
    Input('dd-table', 'value'),
    Input('dd-database', 'value')
)
def update_file_dropdown(selected_site, selected_table, selected_db):
    if not selected_site or not selected_table:
        return []

    magnet_types = db.get_magnet_types_for_site(selected_site, selected_db)
    print(f"[home.py] selected_site={selected_site!r} magnet_types={magnet_types}")

    files = db.get_files_for_site(selected_site, selected_table, selected_db)
    return [{'label': f, 'value': f} for f in files]


@dash.callback(
    Output('sensors-selectors-container', 'children'),
    Output('pending-auto-plot', 'data'),
    Input('dd-file', 'value'), # Plus de dd-group ici !
    Input('dd-site', 'value'),
    State({'type': 'group-sensors-checklist', 'index': ALL}, 'value'),
    State({'type': 'group-sensors-checklist', 'index': ALL}, 'id'),
    State('pending-auto-plot', 'data'),
)
def update_sensors_menus(selected_file, selected_site, current_sensor_values, current_sensor_ids, pending_auto_plot):
    if not selected_file or not selected_site:
        return [], no_update

    housing = selected_site.split('_')[0]
    print(f"[home.py] update_sensors_menus: Loading data file: {selected_file} (site={selected_site}, housing={housing})")
    mrun = db.load_mrun_object(selected_file, housing)

    if mrun is None:
        return [], no_update

    # Mémorisation des cases cochées
    saved_state_map = {}
    if current_sensor_ids and current_sensor_values:
        saved_state_map = {
            s_id['index']: s_vals
            for s_id, s_vals in zip(current_sensor_ids, current_sensor_values)
            if s_vals is not None
        }

    # Sensors to auto-check on the first render after landing via a deep link
    # (e.g. from the "Assembly stats" page). Consumed once, then cleared below,
    # so it doesn't keep overriding the user's own choices on later file switches.
    pending_auto_plot = pending_auto_plot or []

    menus_blocks = []

    # On boucle sur TOUS les groupes existants dans le fichier
    for group_name in mrun.MagnetData.list_groups():
        if group_name == 'Infos':
            continue

        sensors = [c for c in mrun.MagnetData.get_group_data(group_name).columns if c not in ('t', 'timestamp')]
        options = [{'label': s, 'value': s} for s in sensors]

        saved_values_for_this_group = saved_state_map.get(group_name, [])
        for target in pending_auto_plot:
            if target in sensors and target not in saved_values_for_this_group:
                saved_values_for_this_group = saved_values_for_this_group + [target]

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
                    children=[
                        # ⚡ On place le dcc.Graph directement ici !
                        dcc.Graph(
                            id={'type': 'dynamic-graph', 'index': group_name},
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
                'display': 'flex', # C'est la commande magique pour mettre côte à côte
                'flexDirection': 'row',
                'border': '1px solid #007bff', # Un joli cadre bleu autour de tout le bloc du groupe
                'borderRadius': '8px',
                'marginBottom': '20px',
                'boxShadow': '0 2px 4px rgba(0,0,0,0.05)', # Petite ombre stylée
                'backgroundColor': '#f8f9fa'
            })
        )
        
    return menus_blocks, []

@dash.callback(
    Output({'type': 'dynamic-graph', 'index': ALL}, 'figure'),
    
    Input('dd-file', 'value'),
    Input('dd-site', 'value'),
    Input('dd-table', 'value'),
    Input('dd-x-axis', 'value'),
    Input({'type': 'group-sensors-checklist', 'index': ALL}, 'value'), 
    Input({'type': 'group-sensors-checklist', 'index': ALL}, 'id'), 
    Input('dropdown-downsampling', 'value'),
    State({'type': 'dynamic-graph', 'index': ALL}, 'relayoutData') 
)
def update_outputs(selected_file, selected_site, selected_table, selected_x, all_sensors_lists, all_sensors_ids, selected_algo, all_relayout_data):
    
    empty_fig = go.Figure()
    empty_fig.update_layout(
        annotations=[{'text': "Cochez un capteur pour afficher la courbe", 'xref': "paper", 'yref': "paper", 'showarrow': False, 'font': {'color': '#888888'}}],
        xaxis={'visible': False}, yaxis={'visible': False}, template="plotly_white", margin=dict(l=20, r=20, t=30, b=20)
    )

    if not selected_file or not selected_site:
        return [empty_fig for _ in all_sensors_ids]
    
    # --- ETAPE 1 : DETERMINER SI ON DOIT CONSERVER LE ZOOM ---
    maintain_zoom = False
    triggered_id = ctx.triggered_id
    
    # On maintient le zoom SEULEMENT si l'action vient d'une case a cocher ou d'un changement d'algo de downsampling.
    # Si on change de fichier ou d'axe X, on veut que le graphique s'autoscale (remise a zero).
    if triggered_id == 'dropdown-downsampling' or (isinstance(triggered_id, dict) and triggered_id.get('type') == 'group-sensors-checklist'):
        maintain_zoom = True

    # --- ETAPE 2 : EXTRAIRE LES LIMITES DU ZOOM ACTUEL ---
    x_range = None
    if maintain_zoom and all_relayout_data:
        # On cherche le premier graphique qui possede des informations de zoom
        for relayout in all_relayout_data:
            if relayout:
                if 'xaxis.range[0]' in relayout:
                    x_range = [relayout['xaxis.range[0]'], relayout['xaxis.range[1]']]
                    break
                elif 'xaxis.range' in relayout:
                    x_range = [relayout['xaxis.range'][0], relayout['xaxis.range'][1]]
                    break

    housing = selected_site.split('_')[0]
    print(f"[home.py] Loading data file: {selected_file} (site={selected_site}, housing={housing})")
    mrun = db.load_mrun_object(selected_file, housing)

    if mrun is None:
        return [empty_fig for _ in all_sensors_ids]

    sensors_map = {
        sensor_id['index']: sensor_values 
        for sensor_id, sensor_values in zip(all_sensors_ids, all_sensors_lists)
        if sensor_values is not None
    }

    outputs_figures = []
    
    for sensor_id in all_sensors_ids:
        group_name = sensor_id['index']

        if group_name == 'Infos' or group_name not in mrun.MagnetData.list_groups():
            outputs_figures.append(empty_fig)
            continue

        sensors_in_this_group = sensors_map.get(group_name, [])

        if not sensors_in_this_group:
            outputs_figures.append(empty_fig)
            continue

        try:
            df = mrun.MagnetData.get_group_data(group_name)
        except KeyError:
            outputs_figures.append(empty_fig)
            continue

        if not isinstance(df, pd.DataFrame):
            outputs_figures.append(empty_fig)
            continue

        # Creation du plot normal
        fig = plot.create_plot(df, selected_x, sensors_in_this_group, selected_algo, filename=f"{selected_file} - {group_name}", mrun=mrun, group_name=group_name)
        
        # --- ETAPE 3 : INJECTER LE ZOOM DANS LA NOUVELLE FIGURE ---
        if x_range is not None:
            fig.update_layout(xaxis=dict(range=x_range, autorange=False))
        
        outputs_figures.append(fig)
        
    return outputs_figures

# CALLBACK 5 : Synchronisation du zoom entre tous les graphiques de la page Home
@dash.callback(
    Output({'type': 'dynamic-graph', 'index': ALL}, 'figure', allow_duplicate=True),
    Input({'type': 'dynamic-graph', 'index': ALL}, 'relayoutData'),
    State({'type': 'dynamic-graph', 'index': ALL}, 'id'),
    prevent_initial_call=True
)
def sync_zoom_home(relayout_data_list, graph_ids):
    # 1. Identifier quel graphique a déclenché l'événement
    triggered_id = ctx.triggered_id
    if not triggered_id:
        raise PreventUpdate

    trigger_index = graph_ids.index(triggered_id)
    relayout_data = relayout_data_list[trigger_index]

    if not relayout_data:
        raise PreventUpdate

    patches = []
    x_min, x_max = None, None
    autoscale = False
    
    # --- ANALYSE DE L'ÉVÉNEMENT PLOTLY ---
    
    # Cas A : Zoom avec le rectangle de sélection 
    if 'xaxis.range[0]' in relayout_data:
        x_min = relayout_data['xaxis.range[0]']
        x_max = relayout_data['xaxis.range[1]']
        
    # Cas B : Déplacement avec l'outil "Pan" 
    elif 'xaxis.range' in relayout_data:
        x_min = relayout_data['xaxis.range'][0]
        x_max = relayout_data['xaxis.range'][1]
        
    # Cas C : Double-clic pour réinitialiser le zoom (Autoscale)
    elif 'xaxis.autorange' in relayout_data:
        autoscale = True
        
    # Cas D : Autre événement 
        raise PreventUpdate

    # --- APPLICATION DES MISES À JOUR (PATCH) ---
    
    for g_id in graph_ids:
        # On ne met pas à jour le graphique qui a déclenché l'action 
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
        
    return patches

@dash.callback(
    Output({'type': 'group-sensors-checklist', 'index': ALL}, 'value'),
    Input('dd-file', 'value'),
    State({'type': 'group-sensors-checklist', 'index': ALL}, 'id'),
    prevent_initial_call=True
)
def reset_checklists(selected_file, all_checklists_ids):
    if not all_checklists_ids:
        return dash.no_update
        
    num_checklists = len(all_checklists_ids)
    
    return [[] for _ in range(num_checklists)]