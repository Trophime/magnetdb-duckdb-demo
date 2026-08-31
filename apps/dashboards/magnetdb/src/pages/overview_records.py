import dash
import dash_selectors as selectors
import magnetdb_analysis as db
import magnetdb_plot as plot
import pandas as pd
import style_editor
from dash import ALL, Input, Output, Patch, State, ctx, dcc, html
from dash.exceptions import PreventUpdate
from plotly import graph_objects as go

dash.register_page(__name__, path="/overview-records", name="Overview records", order=5)


_EMPTY_FIG = go.Figure()
_EMPTY_FIG.update_layout(
    annotations=[
        {
            "text": "Check a sensor to display its curve",
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


def _record_sources(record_filename, db_path, include_extra=False):
    """Fetch one record's housing and its regular/event source-file lists.

    Parameters
    ----------
    include_extra : bool, optional
        When True, also include archive and event (default/spike) files —
        excluded by default since a record can have dozens of them.

    Returns
    -------
    tuple
        ``(housing, regular_files, event_files)``, or ``(None, [], [])`` if
        *record_filename* has no matching row.
    """
    info = db.get_overview_record_sources(record_filename, db_path)
    if info is None:
        return None, [], []
    regular_files = list(info["sources_overview"]) + list(info["sources_pupitre"])
    event_files = []
    if include_extra:
        regular_files += list(info["sources_archive"])
        event_files = list(info["sources_default"]) + list(info["sources_spike"])
    return info["housing"], regular_files, event_files


def layout(assembly=None, record=None, **kwargs):
    return html.Div(
        [
            html.H2("Overview Record Viewer", style={"marginTop": "0px", "marginBottom": "20px"}),
            html.Hr(),
            selectors.cascading_selector("overview-records-assembly-filter", "Assembly", 1, value=assembly),
            html.Br(),
            html.Label("2. Choose Overview Record :", style={"fontWeight": "bold"}),
            dcc.Dropdown(
                id="overview-records-record-filter",
                options=[record] if record else [],
                value=record,
                placeholder="Choose an overview record...",
            ),
            html.Br(),
            html.Label("3. Choose X-axis :", style={"fontWeight": "bold", "color": "#007bff"}),
            dcc.Dropdown(
                id="overview-records-x-axis",
                options=[
                    {"label": "Real Time (timestamp)", "value": "timestamp"},
                    {"label": "Elapsed Time (t)", "value": "t"},
                ],
                value="timestamp",
                clearable=False,
            ),
            html.Br(),
            html.Label("4. Downsampling Method:", style={"fontWeight": "bold"}),
            dcc.Dropdown(
                id="overview-records-downsampling",
                options=["raw data", "LTTB", "minmax", "M4", "naive"],
                value="LTTB",
                clearable=False,
            ),
            html.Br(),
            html.Label("5. Data scope:", style={"fontWeight": "bold"}),
            dcc.Checklist(
                id="overview-records-include-extra",
                options=[{"label": " Include archive & event files (slower)", "value": "extra"}],
                value=[],
                style={"marginTop": "4px"},
            ),
            html.Br(),
            html.Label("6. Cursor sync:", style={"fontWeight": "bold"}),
            html.Div(
                [
                    dcc.Checklist(
                        id="overview-records-sync-cursor-toggle",
                        options=[{"label": " Sync cursor across graphs", "value": "sync"}],
                        value=["sync"],
                        style={"display": "inline-block", "marginRight": "15px"},
                    ),
                    html.Button("Clear cursors", id="overview-records-clear-cursors-btn", n_clicks=0),
                ],
                style={"marginTop": "4px"},
            ),
            html.Br(),
            dcc.Store(id="overview-records-group-entries"),
            style_editor.modal_component("ov"),
            html.Div(id="overview-records-missing-banner", style={"color": "#a94442", "fontWeight": "bold"}),
            html.Div(id="overview-records-groups-container", children=[], style={"marginTop": "10px"}),
        ],
        style={"padding": "20px", "backgroundColor": "#f8f9fa", "minHeight": "100vh"},
    )


@dash.callback(
    Output("overview-records-assembly-filter", "options"),
    Input("dd-database", "value"),
)
def update_assembly_options(selected_db):
    if not selected_db:
        return []
    return db.get_all_assemblies(selected_db)


@dash.callback(
    Output("overview-records-include-extra", "options"),
    Input("overview-records-record-filter", "value"),
    Input("dd-database", "value"),
)
def update_include_extra_label(selected_record, selected_db):
    default_label = " Include archive & event files (slower)"
    if not selected_record or not selected_db:
        return [{"label": default_label, "value": "extra"}]

    info = db.get_overview_record_sources(selected_record, selected_db)
    if info is None:
        return [{"label": default_label, "value": "extra"}]

    n_archive = len(info["sources_archive"])
    n_incident = len(info["sources_default"]) + len(info["sources_spike"])
    label = (
        f" Include archive & event files — {n_archive} archives, "
        f"{n_incident} incidents (slower)"
    )
    return [{"label": label, "value": "extra"}]


@dash.callback(
    Output("overview-records-record-filter", "options"),
    Output("overview-records-record-filter", "value"),
    Input("overview-records-assembly-filter", "value"),
    Input("dd-database", "value"),
    State("overview-records-record-filter", "value"),
)
def update_record_options(selected_assembly, selected_db, current_record):
    if not selected_assembly or not selected_db:
        return [], None

    records = db.get_overview_records_for_assembly(selected_assembly, selected_db)
    options = [
        {
            "label": f"{r['t0']} — {r['filename']}" if r.get("t0") else r["filename"],
            "value": r["filename"],
        }
        for r in records
    ]
    values = [r["filename"] for r in records]
    if current_record in values:
        return options, dash.no_update
    return options, (values[0] if values else None)


@dash.callback(
    Output("overview-records-groups-container", "children"),
    Output("overview-records-missing-banner", "children"),
    Output("overview-records-group-entries", "data"),
    Input("overview-records-record-filter", "value"),
    Input("dd-database", "value"),
    Input("overview-records-include-extra", "value"),
)
def update_groups(selected_record, selected_db, include_extra_value):
    if not selected_record:
        return [], "", {}

    include_extra = bool(include_extra_value)
    housing, regular_files, _event_files = _record_sources(selected_record, selected_db, include_extra)
    if housing is None:
        return [], "This overview record was not found.", {}
    if not regular_files:
        return [], "No overview/archive/pupitre files are attached to this record.", {}

    group_entries = db.get_overview_group_entries(regular_files, housing)
    if not group_entries:
        return [], "No data group found for this record's source files.", {}

    blocks = []
    for group_name, entries in group_entries.items():
        options = [{"label": e["label"], "value": e["value"]} for e in entries]

        blocks.append(
            html.Details(
                [
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
                    style_editor.gear_button("ov", group_name),
                    html.Div(
                        [
                            html.Div(
                                dcc.Checklist(
                                    id={"type": "ov-group-sensors-checklist", "index": group_name},
                                    options=options,
                                    value=[],
                                    labelStyle={
                                        "display": "block",
                                        "marginLeft": "25px",
                                        "marginBottom": "4px",
                                    },
                                ),
                                style={
                                    "width": "250px",
                                    "flexShrink": 0,
                                    "padding": "10px",
                                    "borderRight": "1px solid #ddd",
                                    "backgroundColor": "#ffffff",
                                },
                            ),
                            html.Div(
                                dcc.Graph(
                                    id={"type": "ov-dynamic-graph", "index": group_name},
                                    figure=_EMPTY_FIG,
                                    style={"height": "350px"},
                                ),
                                style={"flexGrow": 1, "minWidth": "0", "padding": "10px"},
                            ),
                        ],
                        style={"display": "flex", "flexDirection": "row", "backgroundColor": "#f8f9fa"},
                    ),
                ],
                open=True,
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

    return blocks, "", group_entries


@dash.callback(
    Output({"type": "ov-dynamic-graph", "index": ALL}, "figure"),
    Input("overview-records-record-filter", "value"),
    Input("overview-records-x-axis", "value"),
    Input({"type": "ov-group-sensors-checklist", "index": ALL}, "value"),
    Input({"type": "ov-group-sensors-checklist", "index": ALL}, "id"),
    Input("overview-records-downsampling", "value"),
    Input("dd-database", "value"),
    Input("overview-records-include-extra", "value"),
    Input("ov-style-version", "data"),
    State("overview-records-group-entries", "data"),
    State({"type": "ov-dynamic-graph", "index": ALL}, "relayoutData"),
)
def update_graphs(
    selected_record,
    selected_x,
    all_sensor_values,
    all_sensor_ids,
    selected_algo,
    selected_db,
    include_extra_value,
    _style_version,
    group_entries,
    all_relayout_data,
):
    if not selected_record or not all_sensor_ids:
        return [_EMPTY_FIG for _ in all_sensor_ids]

    # Only checklist/downsampling/include-extra/style-save toggles keep the current zoom
    # (they refine the existing view); picking a different record, x-axis, or
    # database is a new view, so it autoscales instead.
    maintain_zoom = False
    triggered_id = ctx.triggered_id
    if triggered_id in (
        "overview-records-downsampling", "overview-records-include-extra", "ov-style-version"
    ) or (
        isinstance(triggered_id, dict)
        and triggered_id.get("type") == "ov-group-sensors-checklist"
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

    include_extra = bool(include_extra_value)
    housing, regular_files, event_files = _record_sources(selected_record, selected_db, include_extra)
    if housing is None:
        return [_EMPTY_FIG for _ in all_sensor_ids]

    all_files = regular_files + event_files
    mruns = {filename: db.load_mrun_object(filename, housing) for filename in all_files}
    group_entries = group_entries or {}
    figures = []

    for sensor_id, sensor_values in zip(all_sensor_ids, all_sensor_values):
        group_name = sensor_id["index"]
        selected_values = sensor_values or []
        if not selected_values:
            figures.append(_EMPTY_FIG)
            continue

        channels_by_value = {e["value"]: e["channels"] for e in group_entries.get(group_name, [])}
        sensors = [
            name
            for value in selected_values
            for name in channels_by_value.get(value, {}).values()
        ]

        files_data = []
        for filename, mrun in mruns.items():
            if mrun is None or group_name not in mrun.MagnetData.list_groups():
                continue
            try:
                df = db.get_group_dataframe(filename, housing, group_name)
            except KeyError:
                continue
            file_sensors = [s for s in sensors if s in df.columns]
            if not file_sensors:
                continue
            files_data.append({"file": filename, "df": df, "sensors": file_sensors, "mrun": mrun})

        fig = plot.create_annotated_plot(files_data, selected_x, selected_algo, group_name=group_name)

        if x_range is not None:
            fig.update_layout(xaxis={"range": x_range, "autorange": False})

        figures.append(fig)

    return figures


# Live cross-graph zoom sync: propagates one plot's zoom/pan/autoscale to all
# the others without rebuilding any figure (mirrors file_viewer's sync_zoom_home).
@dash.callback(
    Output({"type": "ov-dynamic-graph", "index": ALL}, "figure", allow_duplicate=True),
    Input({"type": "ov-dynamic-graph", "index": ALL}, "relayoutData"),
    State({"type": "ov-dynamic-graph", "index": ALL}, "id"),
    prevent_initial_call=True,
)
def sync_zoom_overview(relayout_data_list, graph_ids):
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
        "type": "line", "x0": x, "x1": x, "y0": 0, "y1": 1,
        "xref": "x", "yref": "paper", "line": _CURSOR_LINE_STYLE,
    }


def _cursor_x_distance(a, b, x_mode):
    if x_mode == "timestamp":
        return abs((pd.Timestamp(a) - pd.Timestamp(b)).total_seconds())
    return abs(float(a) - float(b))


# Pin/remove a cursor line on one or all graphs, mirroring sync_zoom_overview's
# pattern-matching id lookup.
@dash.callback(
    Output({"type": "ov-dynamic-graph", "index": ALL}, "figure", allow_duplicate=True),
    Input({"type": "ov-dynamic-graph", "index": ALL}, "clickData"),
    State({"type": "ov-dynamic-graph", "index": ALL}, "id"),
    State({"type": "ov-dynamic-graph", "index": ALL}, "figure"),
    State("overview-records-sync-cursor-toggle", "value"),
    State("overview-records-x-axis", "value"),
    prevent_initial_call=True,
)
def pin_cursor_overview(click_data_list, graph_ids, figures, sync_toggle, x_mode):
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
        (i for i, s in enumerate(current_shapes) if _cursor_x_distance(s["x0"], clicked_x, x_mode) <= threshold),
        None,
    )
    if match_idx is not None:
        new_shapes = current_shapes[:match_idx] + current_shapes[match_idx + 1:]
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
    Output({"type": "ov-dynamic-graph", "index": ALL}, "figure", allow_duplicate=True),
    Input("overview-records-clear-cursors-btn", "n_clicks"),
    State({"type": "ov-dynamic-graph", "index": ALL}, "id"),
    prevent_initial_call=True,
)
def clear_cursors_overview(n_clicks, graph_ids):
    patches = []
    for _ in graph_ids:
        patched_fig = Patch()
        patched_fig["layout"]["shapes"] = []
        patches.append(patched_fig)
    return patches


def _style_context_fn(group_name, selected_record, selected_db, include_extra_value):
    """Resolve this group's raw sensor names + source-type keys for the style-editor modal.

    Only the regular (pupitre/overview/archive) files are considered — event
    files (default/spike/trigger) render as marker+text annotations, not
    styleable lines, so they're excluded from both the field rows and the
    opacity-by-source section.
    """
    if not selected_record:
        return [], []

    include_extra = bool(include_extra_value)
    housing, regular_files, _event_files = _record_sources(selected_record, selected_db, include_extra)
    if housing is None:
        return [], []

    field_rows = []
    seen_sensors = set()
    source_keys = []
    seen_sources = set()
    for filename in regular_files:
        mrun = db.load_mrun_object(filename, housing)
        if mrun is None or group_name not in mrun.MagnetData.list_groups():
            continue
        try:
            df = db.get_group_dataframe(filename, housing, group_name)
        except KeyError:
            continue

        source_key = plot.resolve_file_type_key(filename)
        for sensor in df.columns:
            if sensor in ("t", "timestamp") or sensor in seen_sensors:
                continue
            seen_sensors.add(sensor)
            field_rows.append((sensor, source_key))
        if source_key and source_key not in seen_sources:
            seen_sources.add(source_key)
            source_keys.append(source_key)

    return field_rows, source_keys


style_editor.register_callbacks(
    "ov",
    context_fn=_style_context_fn,
    extra_states=[
        State("overview-records-record-filter", "value"),
        State("dd-database", "value"),
        State("overview-records-include-extra", "value"),
    ],
)
