import dash
import dash_selectors as selectors
import i18n
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
from python_magnetrun.utils.timezone import local_to_utc_naive

dash.register_page(
    __name__,
    path="/stats_viewer",
    name="Pigbrother Stats viewer",
    order=9,
    title=lambda: i18n._("Pigbrother Stats viewer"),
)


# See file_viewer.py for the rationale behind seeding `dd-file`-style dropdowns
# with their query-string value (assembly/file here) instead of waiting for
# the options-loading callbacks.
def layout(assembly=None, file=None, **kwargs):
    return html.Div(
        [
            dcc.Store(id="sv-pending-auto-plot", data=["Field", "Champ_magn"]),
            html.Div(
                [
                    html.H2(
                        i18n._("Pigbrother Stats Viewer"),
                        style={"marginTop": "0px", "marginBottom": "20px"},
                    ),
                    html.Hr(),
                    html.Div(
                        [
                            selectors.aggregate_filter(
                                "sv-housing-filter",
                                i18n._("Housing"),
                                style={"width": "200px"},
                            ),
                            selectors.aggregate_filter(
                                "sv-year-filter", i18n._("Year"), style={"width": "150px"}
                            ),
                            selectors.aggregate_filter(
                                "sv-status-filter",
                                i18n._("Status"),
                                style={"width": "200px"},
                            ),
                        ],
                        style={
                            "display": "flex",
                            "gap": "30px",
                            "marginBottom": "15px",
                        },
                    ),
                    selectors.cascading_selector(
                        "sv-assembly", i18n._("Assembly"), 1, value=assembly
                    ),
                    html.Br(),
                    html.Div(id="sv-magnets-table", style={"marginBottom": "10px"}),
                    html.Br(),
                    html.Label(
                        i18n._("2. Choose a Pigbrother Stats File:"),
                        style={"fontWeight": "bold"},
                    ),
                    dcc.Dropdown(
                        id="sv-file",
                        options=[file] if file else [],
                        value=file,
                        placeholder=i18n._("Choose a Pigbrother Stats file..."),
                    ),
                    html.Br(),
                    html.Div(id="sv-file-stats", style={"marginBottom": "10px"}),
                    selectors.graph(
                        id="sv-field-histogram",
                        figure=plot.field_histogram_figure(None),
                        style={"height": "250px"},
                    ),
                    html.Br(),
                    html.Label(
                        i18n._("3. Choose X-axis :"),
                        style={"fontWeight": "bold", "color": "#007bff"},
                    ),
                    dcc.Dropdown(
                        id="sv-x-axis",
                        options=[
                            {"label": i18n._("Real Time (timestamp)"), "value": "timestamp"},
                            {"label": i18n._("Elapsed Time (t)"), "value": "t"},
                        ],
                        value="timestamp",
                        clearable=False,
                    ),
                    html.Br(),
                    html.Label(i18n._("4. Choose Sensors :"), style={"fontWeight": "bold"}),
                    dcc.Loading(
                        html.Div(
                            id="sv-sensors-selectors-container",
                            children=[],
                            style={"marginTop": "10px"},
                        ),
                        type="circle",
                    ),
                    style_editor.modal_component("sv"),
                    style_editor.download_store("sv"),
                    html.Br(),
                    html.Label(i18n._("5. Cursor sync:"), style={"fontWeight": "bold"}),
                    html.Div(
                        [
                            dcc.Checklist(
                                id="sv-sync-cursor-toggle",
                                options=[
                                    {
                                        "label": i18n._(" Sync cursor across graphs"),
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
                                i18n._("Clear cursors"), id="sv-clear-cursors-btn", n_clicks=0
                            ),
                        ],
                        style={"marginTop": "4px"},
                    ),
                    html.Br(),
                    html.Label(
                        i18n._("6. Downsampling Method:"), style={"fontWeight": "bold"}
                    ),
                    dcc.Dropdown(
                        id="sv-downsampling",
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
    Output("sv-housing-filter", "options"),
    Output("sv-year-filter", "options"),
    Output("sv-status-filter", "options"),
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

    status_options = [selectors.ALL] + db.get_distinct_statuses("assemblies")

    return housing_options, year_options, status_options


@dash.callback(
    Output("sv-assembly", "options"),
    Output("sv-assembly", "value"),
    Input("dd-database", "value"),
    Input("sv-housing-filter", "value"),
    Input("sv-year-filter", "value"),
    Input("sv-status-filter", "value"),
    State("sv-assembly", "value"),
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


@dash.callback(
    Output("sv-file", "options"),
    Input("sv-assembly", "value"),
    Input("dd-database", "value"),
)
def update_file_dropdown(selected_assembly, selected_db):
    if not selected_assembly:
        return []

    files = db.get_stats_files_for_assembly(selected_assembly, selected_db)
    return [{"label": f, "value": f} for f in files]


@dash.callback(
    Output("sv-magnets-table", "children"),
    Input("sv-assembly", "value"),
    Input("dd-database", "value"),
)
def update_magnets_table(selected_assembly, selected_db):
    return selectors.magnets_table_section(selected_assembly, selected_db)


@dash.callback(
    Output("sv-file-stats", "children"),
    Output("sv-field-histogram", "figure"),
    Input("sv-file", "value"),
    Input("sv-assembly", "value"),
    Input("sv-x-axis", "value"),
    Input({"type": "sv-dynamic-graph", "index": ALL}, "relayoutData"),
)
def update_file_stats(selected_file, selected_assembly, x_mode, all_relayout_data):
    empty = selectors.file_stats_banner(None, None), plot.field_histogram_figure(None)
    if not selected_file or not selected_assembly:
        return empty

    housing = selected_assembly.split("_")[0]
    mrun = db.load_mrun_object(selected_file, housing)
    if mrun is None:
        return empty

    # Same zoom-range extraction as update_outputs: any currently zoomed/panned
    # graph narrows the summary to that time window; switching file/assembly/
    # x-axis always resets to the full file.
    triggered_id = ctx.triggered_id
    x_range = None
    if triggered_id not in ("sv-file", "sv-assembly", "sv-x-axis") and all_relayout_data:
        for relayout in all_relayout_data:
            if relayout:
                if "xaxis.range[0]" in relayout:
                    x_range = [relayout["xaxis.range[0]"], relayout["xaxis.range[1]"]]
                    break
                elif "xaxis.range" in relayout:
                    x_range = [relayout["xaxis.range"][0], relayout["xaxis.range"][1]]
                    break

    analysis_range = x_range
    if x_range is not None and x_mode == "timestamp":
        # relayoutData holds the displayed local time (see
        # magnetdb_plot._display_x_series); the "timestamp" column is stored
        # as naive UTC, so the range needs converting back before filtering.
        analysis_range = [
            local_to_utc_naive(pd.Timestamp(x_range[0]), "Europe/Paris"),
            local_to_utc_naive(pd.Timestamp(x_range[1]), "Europe/Paris"),
        ]

    if x_range is not None:
        if x_mode == "timestamp":
            duration = (pd.Timestamp(x_range[1]) - pd.Timestamp(x_range[0])).total_seconds()
        else:
            duration = float(x_range[1]) - float(x_range[0])
    else:
        duration = mrun.MagnetData.getDuration()

    field_stats = db.get_field_column_stats([mrun], x_range=analysis_range, x_col=x_mode)
    energy_stats = db.get_energy_stats([mrun], x_range=analysis_range, x_col=x_mode)

    banner = selectors.file_stats_banner(
        duration, field_stats, energy_stats=energy_stats, zoomed=x_range is not None
    )
    return banner, plot.field_histogram_figure(field_stats)


def _sensor_group_block(group_name, options, saved_values, open_by_default=False):
    """Build one collapsible checklist+graph block for the sensor-selector panel."""
    return html.Details(
        [
            html.Summary(
                f"📂 {i18n._(group_name)}",
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
            style_editor.gear_button("sv", group_name),
            style_editor.download_button("sv", group_name),
            html.Div(
                [
                    html.Div(
                        [
                            dcc.Checklist(
                                id={
                                    "type": "sv-group-sensors-checklist",
                                    "index": group_name,
                                },
                                options=options,
                                value=saved_values,
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
                    html.Div(
                        children=[
                            selectors.graph(
                                id={
                                    "type": "sv-dynamic-graph",
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
        open=open_by_default,
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


@dash.callback(
    Output("sv-sensors-selectors-container", "children"),
    Output("sv-pending-auto-plot", "data"),
    Input("sv-file", "value"),
    Input("sv-assembly", "value"),
    State({"type": "sv-group-sensors-checklist", "index": ALL}, "value"),
    State({"type": "sv-group-sensors-checklist", "index": ALL}, "id"),
    State("sv-pending-auto-plot", "data"),
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

    # Sensors to auto-check on the page's first file selection. Consumed
    # once, then cleared below, so it doesn't keep overriding the user's
    # own choices on later file switches.
    pending_auto_plot = pending_auto_plot or []

    menus_blocks = []

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
            _sensor_group_block(
                group_name,
                options,
                saved_values_for_this_group,
                open_by_default=(group_name == "Magnetic_Field"),
            )
        )

    return menus_blocks, []


@dash.callback(
    Output({"type": "sv-dynamic-graph", "index": ALL}, "figure"),
    Input("sv-file", "value"),
    Input("sv-assembly", "value"),
    Input("sv-x-axis", "value"),
    Input({"type": "sv-group-sensors-checklist", "index": ALL}, "value"),
    Input({"type": "sv-group-sensors-checklist", "index": ALL}, "id"),
    Input("sv-downsampling", "value"),
    Input("sv-style-version", "data"),
    State({"type": "sv-dynamic-graph", "index": ALL}, "relayoutData"),
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
                "text": i18n._("Check a sensor to display its curve"),
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

    # On maintient le zoom seulement si l'action vient d'une case a cocher, d'un
    # changement d'algo de downsampling, ou d'une sauvegarde de style. Si on
    # change de fichier ou d'axe X, on veut que le graphique s'autoscale.
    maintain_zoom = False
    triggered_id = ctx.triggered_id

    if triggered_id in ("sv-downsampling", "sv-style-version") or (
        isinstance(triggered_id, dict)
        and triggered_id.get("type") == "sv-group-sensors-checklist"
    ):
        maintain_zoom = True

    x_range = None
    if maintain_zoom and all_relayout_data:
        for relayout in all_relayout_data:
            if relayout:
                if "xaxis.range[0]" in relayout:
                    x_range = [relayout["xaxis.range[0]"], relayout["xaxis.range[1]"]]
                    break
                elif "xaxis.range" in relayout:
                    x_range = [relayout["xaxis.range"][0], relayout["xaxis.range"][1]]
                    break

    housing = selected_assembly.split("_")[0]
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

        if group_name == "Infos":
            outputs_figures.append(empty_fig)
            continue

        sensors_in_this_group = sensors_map.get(group_name, [])
        if not sensors_in_this_group:
            outputs_figures.append(empty_fig)
            continue

        fig = None

        if group_name in mrun.MagnetData.list_groups():
            try:
                df = mrun.MagnetData.get_group_data(group_name)
            except KeyError:
                df = None
            if isinstance(df, pd.DataFrame):
                fig = plot.create_plot(
                    df,
                    selected_x,
                    sensors_in_this_group,
                    selected_algo,
                    filename=selected_file,
                    mrun=mrun,
                    group_name=group_name,
                )

        if fig is None:
            fig = empty_fig

        if x_range is not None:
            fig.update_layout(xaxis={"range": x_range, "autorange": False})

        outputs_figures.append(fig)

    return outputs_figures


@dash.callback(
    Output("sv-download-data", "data"),
    Input({"type": "sv-download-btn", "index": ALL}, "n_clicks"),
    State("sv-file", "value"),
    State("sv-assembly", "value"),
    State("sv-x-axis", "value"),
    State({"type": "sv-group-sensors-checklist", "index": ALL}, "value"),
    State({"type": "sv-group-sensors-checklist", "index": ALL}, "id"),
    State({"type": "sv-dynamic-graph", "index": ALL}, "relayoutData"),
    State({"type": "sv-dynamic-graph", "index": ALL}, "id"),
    prevent_initial_call=True,
)
def download_group_csv(
    all_clicks,
    selected_file,
    selected_assembly,
    selected_x,
    all_sensors_lists,
    all_sensors_ids,
    all_relayout_data,
    all_graph_ids,
):
    triggered_id = ctx.triggered_id
    if not isinstance(triggered_id, dict) or not ctx.triggered or not ctx.triggered[0]["value"]:
        raise PreventUpdate
    group_name = triggered_id["index"]

    if not selected_file or not selected_assembly:
        raise PreventUpdate

    sensors_map = {
        sensor_id["index"]: sensor_values
        for sensor_id, sensor_values in zip(all_sensors_ids, all_sensors_lists)
        if sensor_values is not None
    }
    sensors_in_this_group = sensors_map.get(group_name, [])
    if not sensors_in_this_group:
        raise PreventUpdate

    housing = selected_assembly.split("_")[0]
    mrun = db.load_mrun_object(selected_file, housing)
    if mrun is None:
        raise PreventUpdate

    # Same zoom-range extraction as update_outputs, scoped to this group's own
    # graph (cross-graph zoom sync keeps them all equal anyway, see
    # sync_zoom_stats below).
    relayout_by_group = {
        graph_id["index"]: relayout
        for graph_id, relayout in zip(all_graph_ids, all_relayout_data)
    }
    relayout = relayout_by_group.get(group_name)
    x_range = None
    if relayout:
        if "xaxis.range[0]" in relayout:
            x_range = [relayout["xaxis.range[0]"], relayout["xaxis.range[1]"]]
        elif "xaxis.range" in relayout:
            x_range = [relayout["xaxis.range"][0], relayout["xaxis.range"][1]]

    analysis_range = x_range
    if x_range is not None and selected_x == "timestamp":
        # relayoutData holds the displayed local time; the "timestamp" column
        # is stored as naive UTC, so the range needs converting back first.
        analysis_range = [
            local_to_utc_naive(pd.Timestamp(x_range[0]), "Europe/Paris"),
            local_to_utc_naive(pd.Timestamp(x_range[1]), "Europe/Paris"),
        ]

    if group_name not in mrun.MagnetData.list_groups():
        raise PreventUpdate

    try:
        group_df = mrun.MagnetData.get_group_data(group_name)
    except KeyError:
        raise PreventUpdate

    if not isinstance(group_df, pd.DataFrame) or selected_x not in group_df.columns:
        raise PreventUpdate

    group_df = db.filter_by_x_range(group_df, selected_x, analysis_range)
    tidy_frames = [
        pd.DataFrame({
            selected_x: group_df[selected_x],
            "file": selected_file,
            "sensor": sensor,
            "value": group_df[sensor],
        })
        for sensor in sensors_in_this_group
        if sensor in group_df.columns
    ]

    if not tidy_frames:
        raise PreventUpdate

    csv_df = pd.concat(tidy_frames, ignore_index=True)
    return dcc.send_data_frame(csv_df.to_csv, f"{selected_file}_{group_name}.csv", index=False)


# Synchronisation du zoom entre tous les graphiques de la page
@dash.callback(
    Output({"type": "sv-dynamic-graph", "index": ALL}, "figure", allow_duplicate=True),
    Input({"type": "sv-dynamic-graph", "index": ALL}, "relayoutData"),
    State({"type": "sv-dynamic-graph", "index": ALL}, "id"),
    prevent_initial_call=True,
)
def sync_zoom_stats(relayout_data_list, graph_ids):
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

    if "xaxis.range[0]" in relayout_data:
        x_min = relayout_data["xaxis.range[0]"]
        x_max = relayout_data["xaxis.range[1]"]
    elif "xaxis.range" in relayout_data:
        x_min = relayout_data["xaxis.range"][0]
        x_max = relayout_data["xaxis.range"][1]
    elif "xaxis.autorange" in relayout_data:
        autoscale = True
    else:
        raise PreventUpdate

    for g_id in graph_ids:
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


# Epingler/retirer une ligne verticale (curseur) sur un ou tous les graphiques
@dash.callback(
    Output({"type": "sv-dynamic-graph", "index": ALL}, "figure", allow_duplicate=True),
    Input({"type": "sv-dynamic-graph", "index": ALL}, "clickData"),
    State({"type": "sv-dynamic-graph", "index": ALL}, "id"),
    State({"type": "sv-dynamic-graph", "index": ALL}, "figure"),
    State("sv-sync-cursor-toggle", "value"),
    State("sv-x-axis", "value"),
    prevent_initial_call=True,
)
def pin_cursor_stats(click_data_list, graph_ids, figures, sync_toggle, x_mode):
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
    Output({"type": "sv-dynamic-graph", "index": ALL}, "figure", allow_duplicate=True),
    Input("sv-clear-cursors-btn", "n_clicks"),
    State({"type": "sv-dynamic-graph", "index": ALL}, "id"),
    prevent_initial_call=True,
)
def clear_cursors_stats(n_clicks, graph_ids):
    patches = []
    for _ in graph_ids:
        patched_fig = Patch()
        patched_fig["layout"]["shapes"] = []
        patches.append(patched_fig)
    return patches


@dash.callback(
    Output({"type": "sv-group-sensors-checklist", "index": ALL}, "value"),
    Input("sv-file", "value"),
    State({"type": "sv-group-sensors-checklist", "index": ALL}, "id"),
    prevent_initial_call=True,
)
def reset_checklists_stats(selected_file, all_checklists_ids):
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
    "sv",
    context_fn=_style_context_fn,
    extra_states=[State("sv-file", "value"), State("sv-assembly", "value")],
)
