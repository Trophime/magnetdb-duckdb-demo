import dash
from dash import html, dcc, Input, Output, State, ALL
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


def _record_sources(record_filename, db_path):
    """Fetch one record's housing and its regular/event source-file lists.

    Returns
    -------
    tuple
        ``(housing, regular_files, event_files)``, or ``(None, [], [])`` if
        *record_filename* has no matching row.
    """
    info = db.get_overview_record_sources(record_filename, db_path)
    if info is None:
        return None, [], []
    regular_files = (
        list(info["sources_overview"]) + list(info["sources_archive"]) + list(info["sources_pupitre"])
    )
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
    Input("overview-records-record-filter", "value"),
    Input("dd-database", "value"),
)
def update_groups(selected_record, selected_db):
    if not selected_record:
        return [], ""

    housing, regular_files, event_files = _record_sources(selected_record, selected_db)
    if housing is None:
        return [], "This overview record was not found."
    if not regular_files:
        return [], "No overview/archive/pupitre files are attached to this record."

    groups = db.get_common_groups(regular_files, housing)
    if not groups:
        return [], "No data group is common to every source file for this record."

    # Load every file's MagnetRun once, up front — looping per-group over
    # load_mrun_object() directly would re-request the same files once per
    # group and thrash its small (maxsize=16) LRU cache across event-heavy
    # records (sources_default/sources_spike commonly run into the dozens).
    all_files = regular_files + event_files
    mruns = {filename: db.load_mrun_object(filename, housing) for filename in all_files}

    blocks = []
    for group_name in groups:
        sensors_seen = []
        for filename, mrun in mruns.items():
            if mrun is None or group_name not in mrun.MagnetData.list_groups():
                continue
            for c in db.get_group_dataframe(filename, housing, group_name).columns:
                if c not in ("t", "timestamp") and c not in sensors_seen:
                    sensors_seen.append(c)

        options = [{"label": s, "value": s} for s in sensors_seen]

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

    return blocks, ""


@dash.callback(
    Output({"type": "ov-dynamic-graph", "index": ALL}, "figure"),
    Input("overview-records-record-filter", "value"),
    Input("overview-records-x-axis", "value"),
    Input({"type": "ov-group-sensors-checklist", "index": ALL}, "value"),
    Input({"type": "ov-group-sensors-checklist", "index": ALL}, "id"),
    Input("overview-records-downsampling", "value"),
    Input("dd-database", "value"),
)
def update_graphs(selected_record, selected_x, all_sensor_values, all_sensor_ids, selected_algo, selected_db):
    if not selected_record or not all_sensor_ids:
        return [_EMPTY_FIG for _ in all_sensor_ids]

    housing, regular_files, event_files = _record_sources(selected_record, selected_db)
    if housing is None:
        return [_EMPTY_FIG for _ in all_sensor_ids]

    all_files = regular_files + event_files
    mruns = {filename: db.load_mrun_object(filename, housing) for filename in all_files}
    figures = []

    for sensor_id, sensor_values in zip(all_sensor_ids, all_sensor_values):
        group_name = sensor_id["index"]
        sensors = sensor_values or []
        if not sensors:
            figures.append(_EMPTY_FIG)
            continue

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

        figures.append(plot.create_annotated_plot(files_data, selected_x, selected_algo, group_name=group_name))

    return figures
