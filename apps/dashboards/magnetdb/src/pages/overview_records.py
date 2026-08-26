import dash
from dash import html, dcc, Input, Output, State, ALL, Patch, ctx
from dash.exceptions import PreventUpdate
from plotly import graph_objects as go

import magnetdb_analysis as db
import magnetdb_plot as plot
import dash_selectors as selectors

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
    margin=dict(l=20, r=20, t=30, b=20),
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
            dcc.Store(id="overview-records-group-entries"),
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
    group_entries,
    all_relayout_data,
):
    if not selected_record or not all_sensor_ids:
        return [_EMPTY_FIG for _ in all_sensor_ids]

    # Only checklist/downsampling/include-extra toggles keep the current zoom
    # (they refine the existing view); picking a different record, x-axis, or
    # database is a new view, so it autoscales instead.
    maintain_zoom = False
    triggered_id = ctx.triggered_id
    if triggered_id in ("overview-records-downsampling", "overview-records-include-extra") or (
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
            fig.update_layout(xaxis=dict(range=x_range, autorange=False))

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
