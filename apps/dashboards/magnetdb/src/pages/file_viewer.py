import dash
import dash_selectors as selectors
import magnetdb_analysis as db
import magnetdb_plot as plot
import pandas as pd
import style_editor
from dash import (
    ALL,
    Input,
    Output,
    Patch,
    State,
    ctx,
    dcc,
    html,
    no_update,
)
from dash.exceptions import PreventUpdate
from plotly import graph_objects as go

dash.register_page(__name__, path="/file_viewer", name="File viewer", order=6)


# `assembly`/`file` are populated by Dash Pages from the URL's query string (e.g. the
# links generated on the "Assembly stats" page: /file_viewer?assembly=...&file=...), so the
# dropdowns get their initial value at first render instead of via a callback
# racing against the (async) options-loading callbacks below. Seeding `options`
# with the value itself guarantees the label is shown immediately, rather than
# a blank/placeholder box until the real option list (loaded from DuckDB by the
# callbacks further down) happens to include a matching entry.
def layout(assembly=None, file=None, **kwargs):
    return html.Div(
        [
            dcc.Store(
                id="pending-auto-plot", data=["Field"] if (assembly and file) else []
            ),
            html.Div(
                [
                    html.H2(
                        "Pupitre Dashboard",
                        style={"marginTop": "0px", "marginBottom": "20px"},
                    ),
                    html.Hr(),
                    html.Div(
                        [
                            selectors.aggregate_filter(
                                "fv-housing-filter", "Housing", style={"width": "200px"}
                            ),
                            selectors.aggregate_filter(
                                "fv-year-filter", "Year", style={"width": "150px"}
                            ),
                            selectors.aggregate_filter(
                                "fv-status-filter", "Status", style={"width": "200px"}
                            ),
                        ],
                        style={
                            "display": "flex",
                            "gap": "30px",
                            "marginBottom": "15px",
                        },
                    ),
                    selectors.cascading_selector(
                        "dd-assembly", "Assembly", 1, value=assembly
                    ),
                    html.Br(),
                    html.Div(id="fv-magnets-table", style={"marginBottom": "10px"}),
                    html.Br(),
                    html.Label("2. Choose File :", style={"fontWeight": "bold"}),
                    dcc.Dropdown(
                        id="dd-file",
                        options=[file] if file else [],
                        value=file,
                        placeholder="Choose a file...",
                    ),
                    html.Br(),
                    html.Div(id="fv-file-stats", style={"marginBottom": "10px"}),
                    html.Br(),
                    html.Label(
                        "3. Choose X-axis :",
                        style={"fontWeight": "bold", "color": "#007bff"},
                    ),
                    dcc.Dropdown(
                        id="dd-x-axis",
                        options=[
                            {"label": "Real Time (timestamp)", "value": "timestamp"},
                            {"label": "Elapsed Time (t)", "value": "t"},
                        ],
                        value="timestamp",
                        clearable=False,
                    ),
                    html.Br(),
                    html.Label("4. Choose Sensors :", style={"fontWeight": "bold"}),
                    # C'est ce conteneur unique qui contiendra tout (Groupes + Checklist + Graphiques associés)
                    dcc.Loading(
                        html.Div(
                            id="sensors-selectors-container",
                            children=[],
                            style={"marginTop": "10px"},
                        ),
                        type="circle",
                    ),
                    style_editor.modal_component("fv"),
                    html.Br(),
                    html.Label("5. Cursor sync:", style={"fontWeight": "bold"}),
                    html.Div(
                        [
                            dcc.Checklist(
                                id="fv-sync-cursor-toggle",
                                options=[
                                    {
                                        "label": " Sync cursor across graphs",
                                        "value": "sync",
                                    }
                                ],
                                value=["sync"],
                                style={
                                    "display": "inline-block",
                                    "marginRight": "15px",
                                },
                            ),
                            html.Button(
                                "Clear cursors", id="fv-clear-cursors-btn", n_clicks=0
                            ),
                        ],
                        style={"marginTop": "4px"},
                    ),
                    html.Br(),
                    html.Label("6. Downsampling Method:", style={"fontWeight": "bold"}),
                    dcc.Dropdown(
                        id="dropdown-downsampling",
                        options=["raw data", "LTTB", "minmax", "M4", "naive"],
                        value="LTTB",
                        clearable=False,
                    ),
                ],
                style={
                    "padding": "20px",
                    "backgroundColor": "#f8f9fa",
                    "minHeight": "100vh",
                },
            ),
        ]
    )


@dash.callback(
    Output("fv-housing-filter", "options"),
    Output("fv-year-filter", "options"),
    Output("fv-status-filter", "options"),
    Input("dd-database", "value"),
)
def update_filter_options(selected_db):
    if not selected_db:
        return [selectors.ALL], [selectors.ALL], [selectors.ALL]

    housing_options = [selectors.ALL] + db.get_housings(selected_db)

    assemblies_meta = db.load_assemblies_meta(selected_db)
    year_range = db.assemblies_year_range(assemblies_meta)
    year_options = (
        [selectors.ALL] + [str(y) for y in range(year_range[0], year_range[1] + 1)]
        if year_range is not None
        else [selectors.ALL]
    )

    status_options = [selectors.ALL] + db.get_distinct_statuses(
        "assemblies", selected_db
    )

    return housing_options, year_options, status_options


# CALLBACK 0 : Met à jour la liste des assemblies en fonction de la Database sélectionnée et des filtres
@dash.callback(
    Output("dd-assembly", "options"),
    Output("dd-assembly", "value"),
    Input("dd-database", "value"),
    Input("fv-housing-filter", "value"),
    Input("fv-year-filter", "value"),
    Input("fv-status-filter", "value"),
    State("dd-assembly", "value"),
)
def update_assembly_dropdown(
    selected_db, selected_housing, selected_year, selected_status, current_assembly
):
    if not selected_db:
        return [], None

    all_assemblies = db.get_all_assemblies(selected_db)

    assemblies_in_year = None
    if selected_year and selected_year != selectors.ALL:
        assemblies_meta = db.load_assemblies_meta(selected_db)
        assemblies_in_year = db.assemblies_active_in_year(
            assemblies_meta, int(selected_year)
        )

    assemblies_with_status = (
        db.get_names_with_status("assemblies", selected_status, selected_db)
        if selected_status and selected_status != selectors.ALL
        else None
    )

    assemblies = [
        a
        for a in all_assemblies
        if (
            not selected_housing
            or selected_housing == selectors.ALL
            or a.startswith(f"{selected_housing}_")
        )
        and (assemblies_in_year is None or a in assemblies_in_year)
        and (assemblies_with_status is None or a in assemblies_with_status)
    ]

    if current_assembly in assemblies:
        return assemblies, dash.no_update
    return assemblies, (assemblies[0] if assemblies else None)


# CALLBACK 1 : Met à jour la liste des fichiers en fonction du Assembly
@dash.callback(
    Output("dd-file", "options"),
    Input("dd-assembly", "value"),
    Input("dd-database", "value"),
)
def update_file_dropdown(selected_assembly, selected_db):
    if not selected_assembly:
        return []

    magnet_types = db.get_magnet_types_for_assembly(selected_assembly, selected_db)
    print(
        f"[file_viewer.py] selected_assembly={selected_assembly!r} magnet_types={magnet_types}"
    )

    files = db.get_files_for_assembly(selected_assembly, "experiments", selected_db)
    return [{"label": f, "value": f} for f in files]


@dash.callback(
    Output("fv-magnets-table", "children"),
    Input("dd-assembly", "value"),
    Input("dd-database", "value"),
)
def update_magnets_table(selected_assembly, selected_db):
    return selectors.magnets_table_section(selected_assembly, selected_db)


@dash.callback(
    Output("fv-file-stats", "children"),
    Input("dd-file", "value"),
    Input("dd-assembly", "value"),
)
def update_file_stats(selected_file, selected_assembly):
    if not selected_file or not selected_assembly:
        return selectors.file_stats_banner(None, None)

    housing = selected_assembly.split("_")[0]
    mrun = db.load_mrun_object(selected_file, housing)
    if mrun is None:
        return selectors.file_stats_banner(None, None)

    duration = mrun.MagnetData.getDuration()
    field_stats = db.get_field_column_stats([mrun])
    return selectors.file_stats_banner(duration, field_stats)


@dash.callback(
    Output("sensors-selectors-container", "children"),
    Output("pending-auto-plot", "data"),
    Input("dd-file", "value"),
    Input("dd-assembly", "value"),
    State({"type": "group-sensors-checklist", "index": ALL}, "value"),
    State({"type": "group-sensors-checklist", "index": ALL}, "id"),
    State("pending-auto-plot", "data"),
)
def update_sensors_menus(
    selected_file,
    selected_assembly,
    current_sensor_values,
    current_sensor_ids,
    pending_auto_plot,
):
    if not selected_file or not selected_assembly:
        return [], no_update

    housing = selected_assembly.split("_")[0]
    print(
        f"[file_viewer.py] update_sensors_menus: Loading data file: {selected_file} (assembly={selected_assembly}, housing={housing})"
    )
    mrun = db.load_mrun_object(selected_file, housing)

    if mrun is None:
        return [], no_update

    # Mémorisation des cases cochées
    saved_state_map = {}
    if current_sensor_ids and current_sensor_values:
        saved_state_map = {
            s_id["index"]: s_vals
            for s_id, s_vals in zip(current_sensor_ids, current_sensor_values)
            if s_vals is not None
        }

    # Sensors to auto-check on the first render after landing via a deep link
    # (e.g. from the "Assembly stats" page). Consumed once, then cleared below,
    # so it doesn't keep overriding the user's own choices on later file switches.
    pending_auto_plot = pending_auto_plot or []

    menus_blocks = []

    # On boucle sur TOUS les groupes existants dans le fichier
    for group_name in db.order_groups(mrun.MagnetData.list_groups()):
        if group_name == "Infos":
            continue

        sensors = [
            c
            for c in mrun.MagnetData.get_group_data(group_name).columns
            if c not in ("t", "timestamp")
        ]

        options = []
        for s in sensors:
            symbol, unit = plot.group_display_unit(mrun, group_name, s)
            options.append(
                {"label": plot.format_sensor_label(s, symbol, unit), "value": s}
            )

        saved_values_for_this_group = saved_state_map.get(group_name, [])
        for target in pending_auto_plot:
            if target in sensors and target not in saved_values_for_this_group:
                saved_values_for_this_group = saved_values_for_this_group + [target]

        menus_blocks.append(
            html.Details(
                [
                    # 1. EN-TÊTE : Le titre cliquable qui contrôle TOUT le bloc
                    html.Summary(
                        f"📂 {group_name}",
                        style={
                            "fontWeight": "bold",
                            "cursor": "pointer",
                            "padding": "10px 15px",
                            "backgroundColor": "#e9ecef",
                            "borderBottom": "1px solid #ddd",
                            "outline": "none",
                            "fontSize": "16px",
                        },
                    ),
                    style_editor.gear_button("fv", group_name),
                    # 2. CONTENU : Les deux colonnes (Checklist et Graphique)
                    html.Div(
                        [
                            # --- PARTIE GAUCHE : Les cases à cocher ---
                            html.Div(
                                [
                                    dcc.Checklist(
                                        id={
                                            "type": "group-sensors-checklist",
                                            "index": group_name,
                                        },
                                        options=options,
                                        value=saved_values_for_this_group,
                                        labelStyle={
                                            "display": "block",
                                            "marginLeft": "25px",
                                            "marginBottom": "4px",
                                        },
                                    )
                                ],
                                style={
                                    "width": "250px",
                                    "flexShrink": 0,
                                    "padding": "10px",
                                    "borderRight": "1px solid #ddd",
                                    "backgroundColor": "#ffffff",
                                },
                            ),
                            # --- PARTIE DROITE : Le conteneur du Graphique ---
                            html.Div(
                                children=[
                                    dcc.Graph(
                                        id={
                                            "type": "dynamic-graph",
                                            "index": group_name,
                                        },
                                        style={"height": "350px"},
                                    )
                                ],
                                style={
                                    "flexGrow": 1,
                                    "minWidth": "0",
                                    "padding": "10px",
                                },
                            ),
                        ],
                        style={
                            "display": "flex",
                            "flexDirection": "row",
                            "backgroundColor": "#f8f9fa",
                        },
                    ),
                ],
                open=(group_name == "Magnetic_Field"),
                style={
                    "border": "1px solid #007bff",
                    "borderRadius": "8px",
                    "marginBottom": "20px",
                    "boxShadow": "0 2px 4px rgba(0,0,0,0.05)",
                    "overflow": "hidden",
                    "backgroundColor": "#ffffff",
                    "position": "relative",
                },
            )
        )

    return menus_blocks, []


@dash.callback(
    Output({"type": "dynamic-graph", "index": ALL}, "figure"),
    Input("dd-file", "value"),
    Input("dd-assembly", "value"),
    Input("dd-x-axis", "value"),
    Input({"type": "group-sensors-checklist", "index": ALL}, "value"),
    Input({"type": "group-sensors-checklist", "index": ALL}, "id"),
    Input("dropdown-downsampling", "value"),
    Input("fv-style-version", "data"),
    State({"type": "dynamic-graph", "index": ALL}, "relayoutData"),
)
def update_outputs(
    selected_file,
    selected_assembly,
    selected_x,
    all_sensors_lists,
    all_sensors_ids,
    selected_algo,
    _style_version,
    all_relayout_data,
):

    empty_fig = go.Figure()
    empty_fig.update_layout(
        annotations=[
            {
                "text": "Cochez un capteur pour afficher la courbe",
                "xref": "paper",
                "yref": "paper",
                "showarrow": False,
                "font": {"color": "#888888"},
            }
        ],
        xaxis={"visible": False},
        yaxis={"visible": False},
        template="plotly_white",
        margin={"l": 20, "r": 20, "t": 30, "b": 20},
    )

    if not selected_file or not selected_assembly:
        return [empty_fig for _ in all_sensors_ids]

    # --- ETAPE 1 : DETERMINER SI ON DOIT CONSERVER LE ZOOM ---
    maintain_zoom = False
    triggered_id = ctx.triggered_id

    # On maintient le zoom SEULEMENT si l'action vient d'une case a cocher, d'un changement
    # d'algo de downsampling, ou d'une sauvegarde de style. Si on change de fichier ou d'axe X,
    # on veut que le graphique s'autoscale (remise a zero).
    if triggered_id in ("dropdown-downsampling", "fv-style-version") or (
        isinstance(triggered_id, dict)
        and triggered_id.get("type") == "group-sensors-checklist"
    ):
        maintain_zoom = True

    # --- ETAPE 2 : EXTRAIRE LES LIMITES DU ZOOM ACTUEL ---
    x_range = None
    if maintain_zoom and all_relayout_data:
        # On cherche le premier graphique qui possede des informations de zoom
        for relayout in all_relayout_data:
            if relayout:
                if "xaxis.range[0]" in relayout:
                    x_range = [relayout["xaxis.range[0]"], relayout["xaxis.range[1]"]]
                    break
                elif "xaxis.range" in relayout:
                    x_range = [relayout["xaxis.range"][0], relayout["xaxis.range"][1]]
                    break

    housing = selected_assembly.split("_")[0]
    print(
        f"[file_viewer.py] Loading data file: {selected_file} (assembly={selected_assembly}, housing={housing})"
    )
    mrun = db.load_mrun_object(selected_file, housing)

    if mrun is None:
        return [empty_fig for _ in all_sensors_ids]

    sensors_map = {
        sensor_id["index"]: sensor_values
        for sensor_id, sensor_values in zip(all_sensors_ids, all_sensors_lists)
        if sensor_values is not None
    }

    outputs_figures = []

    for sensor_id in all_sensors_ids:
        group_name = sensor_id["index"]

        if group_name == "Infos" or group_name not in mrun.MagnetData.list_groups():
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
        fig = plot.create_plot(
            df,
            selected_x,
            sensors_in_this_group,
            selected_algo,
            filename=selected_file,
            mrun=mrun,
            group_name=group_name,
        )

        # --- ETAPE 3 : INJECTER LE ZOOM DANS LA NOUVELLE FIGURE ---
        if x_range is not None:
            fig.update_layout(xaxis={"range": x_range, "autorange": False})

        outputs_figures.append(fig)

    return outputs_figures


# CALLBACK 5 : Synchronisation du zoom entre tous les graphiques de la page Home
@dash.callback(
    Output({"type": "dynamic-graph", "index": ALL}, "figure", allow_duplicate=True),
    Input({"type": "dynamic-graph", "index": ALL}, "relayoutData"),
    State({"type": "dynamic-graph", "index": ALL}, "id"),
    prevent_initial_call=True,
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

    # Cas A : Zoom avec le rectangle de sélection
    if "xaxis.range[0]" in relayout_data:
        x_min = relayout_data["xaxis.range[0]"]
        x_max = relayout_data["xaxis.range[1]"]

    # Cas B : Déplacement avec l'outil "Pan"
    elif "xaxis.range" in relayout_data:
        x_min = relayout_data["xaxis.range"][0]
        x_max = relayout_data["xaxis.range"][1]

    # Cas C : Double-clic pour réinitialiser le zoom (Autoscale)
    elif "xaxis.autorange" in relayout_data:
        autoscale = True

        # Cas D : Autre événement
        raise PreventUpdate

    for g_id in graph_ids:
        # On ne met pas à jour le graphique qui a déclenché l'action
        if g_id == triggered_id:
            patches.append(dash.no_update)
            continue

        patched_fig = Patch()

        if autoscale:
            patched_fig["layout"]["xaxis"]["autorange"] = True
        else:
            patched_fig["layout"]["xaxis"]["range"] = [x_min, x_max]
            patched_fig["layout"]["xaxis"]["autorange"] = False

        patches.append(patched_fig)

    return patches


_CURSOR_LINE_STYLE = {"color": "#888888", "width": 1, "dash": "dot"}
_CURSOR_MATCH_THRESHOLD = {"timestamp": 2.0, "t": 0.5}  # seconds


def _cursor_line_shape(x):
    return {
        "type": "line",
        "x0": x,
        "x1": x,
        "y0": 0,
        "y1": 1,
        "xref": "x",
        "yref": "paper",
        "line": _CURSOR_LINE_STYLE,
    }


def _cursor_x_distance(a, b, x_mode):
    if x_mode == "timestamp":
        return abs((pd.Timestamp(a) - pd.Timestamp(b)).total_seconds())
    return abs(float(a) - float(b))


# CALLBACK 6 : Epingler/retirer une ligne verticale (curseur) sur un ou tous les graphiques
@dash.callback(
    Output({"type": "dynamic-graph", "index": ALL}, "figure", allow_duplicate=True),
    Input({"type": "dynamic-graph", "index": ALL}, "clickData"),
    State({"type": "dynamic-graph", "index": ALL}, "id"),
    State({"type": "dynamic-graph", "index": ALL}, "figure"),
    State("fv-sync-cursor-toggle", "value"),
    State("dd-x-axis", "value"),
    prevent_initial_call=True,
)
def pin_cursor_home(click_data_list, graph_ids, figures, sync_toggle, x_mode):
    triggered_id = ctx.triggered_id
    if not triggered_id:
        raise PreventUpdate

    trigger_index = graph_ids.index(triggered_id)
    click_data = click_data_list[trigger_index]
    if not click_data or not click_data.get("points"):
        raise PreventUpdate
    clicked_x = click_data["points"][0]["x"]

    threshold = _CURSOR_MATCH_THRESHOLD.get(x_mode, _CURSOR_MATCH_THRESHOLD["t"])
    current_shapes = (figures[trigger_index].get("layout") or {}).get("shapes") or []
    match_idx = next(
        (
            i
            for i, s in enumerate(current_shapes)
            if _cursor_x_distance(s["x0"], clicked_x, x_mode) <= threshold
        ),
        None,
    )
    if match_idx is not None:
        new_shapes = current_shapes[:match_idx] + current_shapes[match_idx + 1 :]
    else:
        new_shapes = current_shapes + [_cursor_line_shape(clicked_x)]

    propagate = bool(sync_toggle)
    patches = []
    for g_id in graph_ids:
        if g_id == triggered_id:
            patched_fig = Patch()
            patched_fig["layout"]["shapes"] = new_shapes
            patches.append(patched_fig)
            continue

        if not propagate:
            patches.append(dash.no_update)
            continue

        patched_fig = Patch()
        patched_fig["layout"]["shapes"] = new_shapes
        patches.append(patched_fig)

    return patches


@dash.callback(
    Output({"type": "dynamic-graph", "index": ALL}, "figure", allow_duplicate=True),
    Input("fv-clear-cursors-btn", "n_clicks"),
    State({"type": "dynamic-graph", "index": ALL}, "id"),
    prevent_initial_call=True,
)
def clear_cursors_home(n_clicks, graph_ids):
    patches = []
    for _ in graph_ids:
        patched_fig = Patch()
        patched_fig["layout"]["shapes"] = []
        patches.append(patched_fig)
    return patches


@dash.callback(
    Output({"type": "group-sensors-checklist", "index": ALL}, "value"),
    Input("dd-file", "value"),
    State({"type": "group-sensors-checklist", "index": ALL}, "id"),
    prevent_initial_call=True,
)
def reset_checklists(selected_file, all_checklists_ids):
    if not all_checklists_ids:
        return dash.no_update

    num_checklists = len(all_checklists_ids)

    return [[] for _ in range(num_checklists)]


def _style_context_fn(group_name, selected_file, selected_assembly):
    """Resolve this group's raw sensor names + source-type key for the style-editor modal."""
    if not selected_file or not selected_assembly:
        return [], []

    housing = selected_assembly.split("_")[0]
    mrun = db.load_mrun_object(selected_file, housing)
    if mrun is None or group_name not in mrun.MagnetData.list_groups():
        return [], []

    sensors = [
        c
        for c in mrun.MagnetData.get_group_data(group_name).columns
        if c not in ("t", "timestamp")
    ]
    source_key = plot.resolve_file_type_key(selected_file)
    field_rows = [(s, source_key) for s in sensors]
    source_keys = [source_key] if source_key else []
    return field_rows, source_keys


style_editor.register_callbacks(
    "fv",
    context_fn=_style_context_fn,
    extra_states=[State("dd-file", "value"), State("dd-assembly", "value")],
)
