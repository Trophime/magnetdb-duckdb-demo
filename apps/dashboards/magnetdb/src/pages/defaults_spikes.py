import os

import dash
import dash_selectors as selectors
import magnetdb_analysis as db
import magnetdb_plot as plot
import pandas as pd
import style_editor
from dash import ALL, Input, Output, Patch, State, ctx, dcc, html
from dash.exceptions import PreventUpdate
from plotly import graph_objects as go
from python_magnetrun.utils.files import classify_pigbrother_file
from python_magnetrun.utils.timestamps import parse_filename_timestamp
from python_magnetrun.utils.timezone import local_to_utc_naive, utc_naive_to_local

dash.register_page(__name__, path="/defaults-spikes", name="Defaults & Spikes", order=8)


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


def _record_sources(record_filename, db_path, include_archive=False):
    """Fetch one record's housing, regular source files, and default/spike incident files.

    Parameters
    ----------
    include_archive : bool, optional
        When True, also include archive files in the regular set — excluded
        by default since a record can have dozens of them.

    Returns
    -------
    tuple
        ``(housing, regular_files, event_files)``, or ``(None, [], [])`` if
        *record_filename* has no matching row. ``event_files`` is always
        ``sources_default + sources_spike`` — this page's purpose is
        inspecting incidents, so it is never gated by a toggle.
    """
    info = db.get_overview_record_sources(record_filename, db_path)
    if info is None:
        return None, [], []
    regular_files = list(info["sources_overview"]) + list(info["sources_pupitre"])
    if include_archive:
        regular_files += list(info["sources_archive"])
    event_files = list(info["sources_default"]) + list(info["sources_spike"])
    return info["housing"], regular_files, event_files


def _resolve_t0_reference(info):
    """Best-effort naive-UTC t=0 reference for elapsed-time (``t``) mode.

    Tries the first ``sources_overview`` file, then ``sources_archive``, then
    ``sources_pupitre`` (first non-empty list wins), parsing only its filename
    (never loading data) via :func:`~python_magnetrun.utils.timestamps.parse_filename_timestamp`
    and converting local time to naive UTC.

    Parameters
    ----------
    info : dict
        Result of :func:`~magnetdb_analysis.get_overview_record_sources`.

    Returns
    -------
    :class:`~pandas.Timestamp` or None
        Naive-UTC reference timestamp, or ``None`` if no source file is
        available or parseable.
    """
    for key in ("sources_overview", "sources_archive", "sources_pupitre"):
        files = info.get(key) or []
        if len(files) == 0:
            continue
        dt_local = parse_filename_timestamp(files[0])
        if dt_local is not None:
            return pd.Timestamp(local_to_utc_naive(dt_local, "Europe/Paris"))
    return None


def _list_incidents(event_files):
    """Parse *event_files* (default/spike) into sorted, timestamped incident entries.

    Parameters
    ----------
    event_files : list of str
        Filenames from ``sources_default`` + ``sources_spike``.

    Returns
    -------
    list of dict
        Each entry has ``file``, ``type`` (``"default"`` or ``"spike"``),
        ``subtype`` (fault-subtype suffix for "default" files, else None),
        ``dt_local`` (naive local :class:`~datetime.datetime` from the
        filename), and ``dt_utc`` (naive UTC :class:`~pandas.Timestamp`).
        Sorted by ``dt_utc`` ascending; files that fail to classify or parse
        are skipped.
    """
    incidents = []
    for file in event_files:
        file_type = classify_pigbrother_file(file)
        if file_type not in ("default", "spike"):
            continue
        dt_local = parse_filename_timestamp(file)
        if dt_local is None:
            continue
        dt_utc = pd.Timestamp(local_to_utc_naive(dt_local, "Europe/Paris"))
        subtype = None
        if file_type == "default":
            name_parts = os.path.splitext(os.path.basename(file))[0].split("_")
            subtype = name_parts[3] if len(name_parts) > 3 and name_parts[3] else None
        incidents.append(
            {"file": file, "type": file_type, "subtype": subtype, "dt_local": dt_local, "dt_utc": dt_utc}
        )
    incidents.sort(key=lambda e: e["dt_utc"])
    return incidents


def _incident_x_range(dt_utc, window_seconds, x_col, record_t0_utc):
    """Fixed x-axis range ``[dt_utc - window, dt_utc + window]``, in *x_col*'s coordinate.

    Parameters
    ----------
    dt_utc : :class:`~pandas.Timestamp`
        Naive-UTC incident timestamp to center the range on.
    window_seconds : float
        Half-width of the range, in seconds.
    x_col : str
        ``"timestamp"`` or ``"t"``.
    record_t0_utc : :class:`~pandas.Timestamp` or None
        Naive-UTC ``t=0`` reference, required only for ``x_col="t"``.

    Returns
    -------
    list or None
        For ``x_col="timestamp"``: ``[start, end]`` as ISO datetime strings,
        converted from naive UTC to Europe/Paris local time to match the
        plotted traces (see :func:`~magnetdb_plot._display_x_series`). For
        ``x_col="t"``: as floats (elapsed seconds). ``None`` if
        *record_t0_utc* is unavailable in ``"t"`` mode.
    """
    window = pd.Timedelta(seconds=window_seconds)
    if x_col == "timestamp":
        start, end = dt_utc - window, dt_utc + window
        return [utc_naive_to_local(start).isoformat(), utc_naive_to_local(end).isoformat()]
    if x_col == "t" and record_t0_utc is not None:
        incident_t = (dt_utc - pd.Timestamp(record_t0_utc)).total_seconds()
        return [incident_t - window_seconds, incident_t + window_seconds]
    return None


def layout(assembly=None, record=None, incident=None, **kwargs):
    return html.Div(
        [
            html.H2("Defaults & Spikes Viewer", style={"marginTop": "0px", "marginBottom": "20px"}),
            html.Hr(),
            html.Div(
                [
                    selectors.aggregate_filter(
                        "ds-housing-filter", "Housing", style={"width": "200px"}
                    ),
                    selectors.aggregate_filter(
                        "ds-year-filter", "Year", style={"width": "150px"}
                    ),
                    selectors.aggregate_filter(
                        "ds-status-filter", "Status", style={"width": "200px"}
                    ),
                ],
                style={"display": "flex", "gap": "30px", "marginBottom": "15px"},
            ),
            selectors.cascading_selector("ds-assembly-filter", "Assembly", 1, value=assembly),
            html.Br(),
            html.Div(id="ds-magnets-table", style={"marginBottom": "10px"}),
            html.Br(),
            html.Label("2. Choose Overview Record :", style={"fontWeight": "bold"}),
            dcc.Dropdown(
                id="ds-record-filter",
                options=[record] if record else [],
                value=record,
                placeholder="Choose an overview record...",
            ),
            html.Br(),
            html.Label(
                "3. Choose Default/Spike incident :",
                style={"fontWeight": "bold", "color": "#a94442"},
            ),
            dcc.Dropdown(
                id="ds-incident-filter",
                options=[incident] if incident else [],
                value=incident,
                placeholder="Choose a default or spike incident...",
            ),
            html.Br(),
            html.Label(
                "4. Time window — ± seconds around incident :",
                style={"fontWeight": "bold"},
            ),
            dcc.Input(
                id="ds-window-seconds",
                type="number",
                value=2,
                min=0.1,
                step=0.1,
                style={"width": "100px"},
            ),
            html.Div(
                id="ds-incident-warning",
                style={"color": "#a94442", "fontWeight": "bold", "marginTop": "4px"},
            ),
            html.Br(),
            html.Label("5. Choose X-axis :", style={"fontWeight": "bold", "color": "#007bff"}),
            dcc.Dropdown(
                id="ds-x-axis",
                options=[
                    {"label": "Real Time (timestamp)", "value": "timestamp"},
                    {"label": "Elapsed Time (t)", "value": "t"},
                ],
                value="timestamp",
                clearable=False,
            ),
            html.Br(),
            html.Label("6. Downsampling Method:", style={"fontWeight": "bold"}),
            dcc.Dropdown(
                id="ds-downsampling",
                options=["raw data", "LTTB", "minmax", "M4", "naive"],
                value="raw data",
                clearable=False,
            ),
            html.Br(),
            html.Label("7. Data scope:", style={"fontWeight": "bold"}),
            dcc.Checklist(
                id="ds-include-archive",
                options=[{"label": " Include archive files (slower)", "value": "archive"}],
                value=["archive"],
                style={"marginTop": "4px"},
            ),
            html.Br(),
            html.Label("8. Cursor sync:", style={"fontWeight": "bold"}),
            html.Div(
                [
                    dcc.Checklist(
                        id="ds-sync-cursor-toggle",
                        options=[{"label": " Sync cursor across graphs", "value": "sync"}],
                        value=["sync"],
                        style={"display": "inline-block", "marginRight": "15px"},
                    ),
                    html.Button("Clear cursors", id="ds-clear-cursors-btn", n_clicks=0),
                ],
                style={"marginTop": "4px"},
            ),
            html.Br(),
            dcc.Store(id="ds-group-entries"),
            style_editor.modal_component("ds"),
            dcc.Loading(
                [
                    html.Div(
                        id="ds-missing-banner",
                        style={"color": "#a94442", "fontWeight": "bold"},
                    ),
                    html.Div(
                        id="ds-groups-container",
                        children=[],
                        style={"marginTop": "10px"},
                    ),
                ],
                type="circle",
            ),
        ],
        style={"padding": "20px", "backgroundColor": "#f8f9fa", "minHeight": "100vh"},
    )


@dash.callback(
    Output("ds-housing-filter", "options"),
    Output("ds-year-filter", "options"),
    Output("ds-status-filter", "options"),
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

    status_options = [selectors.ALL] + db.get_distinct_statuses("assemblies", selected_db)

    return housing_options, year_options, status_options


@dash.callback(
    Output("ds-assembly-filter", "options"),
    Output("ds-assembly-filter", "value"),
    Input("dd-database", "value"),
    Input("ds-housing-filter", "value"),
    Input("ds-year-filter", "value"),
    Input("ds-status-filter", "value"),
    State("ds-assembly-filter", "value"),
)
def update_assembly_options(selected_db, selected_housing, selected_year, selected_status, current_assembly):
    if not selected_db:
        return [], None

    all_assemblies = db.get_all_assemblies(selected_db)

    assemblies_in_year = None
    if selected_year and selected_year != selectors.ALL:
        assemblies_meta = db.load_assemblies_meta(selected_db)
        assemblies_in_year = db.assemblies_active_in_year(assemblies_meta, int(selected_year))

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
    Output("ds-magnets-table", "children"),
    Input("ds-assembly-filter", "value"),
    Input("dd-database", "value"),
)
def update_magnets_table(selected_assembly, selected_db):
    return selectors.magnets_table_section(selected_assembly, selected_db)


@dash.callback(
    Output("ds-include-archive", "options"),
    Input("ds-record-filter", "value"),
    Input("dd-database", "value"),
)
def update_include_archive_label(selected_record, selected_db):
    default_label = " Include archive files (slower)"
    if not selected_record or not selected_db:
        return [{"label": default_label, "value": "archive"}]

    info = db.get_overview_record_sources(selected_record, selected_db)
    if info is None:
        return [{"label": default_label, "value": "archive"}]

    n_archive = len(info["sources_archive"])
    label = f" Include archive files — {n_archive} archives (slower)"
    return [{"label": label, "value": "archive"}]


@dash.callback(
    Output("ds-record-filter", "options"),
    Output("ds-record-filter", "value"),
    Input("ds-assembly-filter", "value"),
    Input("dd-database", "value"),
    State("ds-record-filter", "value"),
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
    Output("ds-incident-filter", "options"),
    Output("ds-incident-filter", "value"),
    Input("ds-record-filter", "value"),
    Input("dd-database", "value"),
    State("ds-incident-filter", "value"),
)
def update_incident_options(selected_record, selected_db, current_incident):
    if not selected_record or not selected_db:
        return [], None

    info = db.get_overview_record_sources(selected_record, selected_db)
    if info is None:
        return [], None

    event_files = list(info["sources_default"]) + list(info["sources_spike"])
    incidents = _list_incidents(event_files)
    if not incidents:
        return [], None

    options = []
    for entry in incidents:
        subtype_suffix = f" ({entry['subtype']})" if entry["subtype"] else ""
        label = (
            f"{entry['dt_local']:%Y-%m-%d %H:%M:%S} — {entry['type'].capitalize()}"
            f"{subtype_suffix} — {os.path.basename(entry['file'])}"
        )
        options.append({"label": label, "value": entry["file"]})

    values = [entry["file"] for entry in incidents]
    if current_incident in values:
        return options, dash.no_update
    return options, values[0]


@dash.callback(
    Output("ds-groups-container", "children"),
    Output("ds-missing-banner", "children"),
    Output("ds-group-entries", "data"),
    Input("ds-record-filter", "value"),
    Input("dd-database", "value"),
    Input("ds-include-archive", "value"),
)
def update_groups(selected_record, selected_db, include_archive_value):
    if not selected_record:
        return [], "", {}

    include_archive = bool(include_archive_value)
    housing, regular_files, _event_files = _record_sources(selected_record, selected_db, include_archive)
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
        default_checked = [
            e["value"]
            for e in entries
            if group_name == "Magnetic_Field"
            and (
                e["channels"].get("pupitre", {}).get("channel") == "Field"
                or e["channels"].get("pigbrother", {}).get("channel") == "Champ_magn"
            )
        ]

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
                    style_editor.gear_button("ds", group_name),
                    html.Div(
                        [
                            html.Div(
                                dcc.Checklist(
                                    id={"type": "ds-group-sensors-checklist", "index": group_name},
                                    options=options,
                                    value=default_checked,
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
                                    id={"type": "ds-dynamic-graph", "index": group_name},
                                    figure=_EMPTY_FIG,
                                    style={"height": "350px"},
                                ),
                                style={"flexGrow": 1, "minWidth": "0", "padding": "10px"},
                            ),
                        ],
                        style={"display": "flex", "flexDirection": "row", "backgroundColor": "#f8f9fa"},
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

    return blocks, "", group_entries


@dash.callback(
    Output({"type": "ds-dynamic-graph", "index": ALL}, "figure"),
    Output("ds-incident-warning", "children"),
    Input("ds-record-filter", "value"),
    Input("ds-incident-filter", "value"),
    Input("ds-window-seconds", "value"),
    Input("ds-x-axis", "value"),
    Input({"type": "ds-group-sensors-checklist", "index": ALL}, "value"),
    Input({"type": "ds-group-sensors-checklist", "index": ALL}, "id"),
    Input("ds-downsampling", "value"),
    Input("dd-database", "value"),
    Input("ds-include-archive", "value"),
    Input("ds-style-version", "data"),
    State("ds-group-entries", "data"),
    State({"type": "ds-dynamic-graph", "index": ALL}, "relayoutData"),
)
def update_graphs(
    selected_record,
    selected_incident,
    window_seconds,
    selected_x,
    all_sensor_values,
    all_sensor_ids,
    selected_algo,
    selected_db,
    include_archive_value,
    _style_version,
    group_entries,
    all_relayout_data,
):
    if not selected_record or not all_sensor_ids:
        return [_EMPTY_FIG for _ in all_sensor_ids], ""

    # Only checklist/downsampling/include-archive/style-save toggles keep the
    # current zoom (they refine the existing view); picking a different
    # record, incident, window, x-axis, or database re-centers instead.
    maintain_zoom = False
    triggered_id = ctx.triggered_id
    if triggered_id in (
        "ds-downsampling",
        "ds-include-archive",
        "ds-style-version",
    ) or (
        isinstance(triggered_id, dict)
        and triggered_id.get("type") == "ds-group-sensors-checklist"
    ):
        maintain_zoom = True

    include_archive = bool(include_archive_value)
    housing, regular_files, event_files = _record_sources(selected_record, selected_db, include_archive)
    if housing is None:
        return [_EMPTY_FIG for _ in all_sensor_ids], ""

    record_t0_utc = None
    if selected_x == "t":
        info = db.get_overview_record_sources(selected_record, selected_db)
        record_t0_utc = _resolve_t0_reference(info) if info else None

    x_range = None
    if selected_incident:
        dt_local = parse_filename_timestamp(selected_incident)
        if dt_local is not None:
            incident_dt_utc = pd.Timestamp(local_to_utc_naive(dt_local, "Europe/Paris"))
            window = float(window_seconds) if window_seconds else 2.0
            x_range = _incident_x_range(incident_dt_utc, window, selected_x, record_t0_utc)

    incident_warning = ""
    if selected_x == "t" and record_t0_utc is None and event_files:
        incident_warning = (
            "No overview, archive, or pupitre source file available to "
            "anchor elapsed time (t) — incidents and time window are not shown."
        )

    if maintain_zoom and all_relayout_data:
        for relayout in all_relayout_data:
            if relayout:
                if "xaxis.range[0]" in relayout:
                    x_range = [relayout["xaxis.range[0]"], relayout["xaxis.range[1]"]]
                    break
                elif "xaxis.range" in relayout:
                    x_range = [relayout["xaxis.range"][0], relayout["xaxis.range"][1]]
                    break

    mruns = {filename: db.load_mrun_object(filename, housing) for filename in regular_files}
    group_entries = group_entries or {}
    figures = []

    for sensor_id, sensor_values in zip(all_sensor_ids, all_sensor_values):
        group_name = sensor_id["index"]
        selected_values = sensor_values or []
        if not selected_values:
            figures.append(_EMPTY_FIG)
            continue

        files_data = db.collect_group_files_data(
            mruns, housing, group_name, selected_values, group_entries
        )

        fig = plot.create_annotated_plot(
            files_data,
            selected_x,
            selected_algo,
            group_name=group_name,
            event_files=event_files,
            record_t0_utc=record_t0_utc,
        )

        if x_range is not None:
            fig.update_layout(xaxis={"range": x_range, "autorange": False})

        figures.append(fig)

    return figures, incident_warning


# Live cross-graph zoom sync: propagates one plot's zoom/pan/autoscale to all
# the others without rebuilding any figure (mirrors overview_records.py's
# sync_zoom_overview).
@dash.callback(
    Output({"type": "ds-dynamic-graph", "index": ALL}, "figure", allow_duplicate=True),
    Input({"type": "ds-dynamic-graph", "index": ALL}, "relayoutData"),
    State({"type": "ds-dynamic-graph", "index": ALL}, "id"),
    prevent_initial_call=True,
)
def sync_zoom_defaults_spikes(relayout_data_list, graph_ids):
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


# Pin/remove a cursor line on one or all graphs, mirroring
# sync_zoom_defaults_spikes's pattern-matching id lookup.
@dash.callback(
    Output({"type": "ds-dynamic-graph", "index": ALL}, "figure", allow_duplicate=True),
    Input({"type": "ds-dynamic-graph", "index": ALL}, "clickData"),
    State({"type": "ds-dynamic-graph", "index": ALL}, "id"),
    State({"type": "ds-dynamic-graph", "index": ALL}, "figure"),
    State("ds-sync-cursor-toggle", "value"),
    State("ds-x-axis", "value"),
    prevent_initial_call=True,
)
def pin_cursor_defaults_spikes(click_data_list, graph_ids, figures, sync_toggle, x_mode):
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
            i for i, s in enumerate(current_shapes)
            if s.get("name") != plot.INCIDENT_SHAPE_NAME
            and _cursor_x_distance(s["x0"], clicked_x, x_mode) <= threshold
        ),
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
    Output({"type": "ds-dynamic-graph", "index": ALL}, "figure", allow_duplicate=True),
    Input("ds-clear-cursors-btn", "n_clicks"),
    State({"type": "ds-dynamic-graph", "index": ALL}, "figure"),
    prevent_initial_call=True,
)
def clear_cursors_defaults_spikes(n_clicks, figures):
    patches = []
    for figure in figures:
        current_shapes = (figure.get("layout") or {}).get("shapes") or []
        patched_fig = Patch()
        patched_fig["layout"]["shapes"] = [
            s for s in current_shapes if s.get("name") == plot.INCIDENT_SHAPE_NAME
        ]
        patches.append(patched_fig)
    return patches


def _style_context_fn(group_name, selected_record, selected_db, include_archive_value, group_entries):
    """Resolve this group's raw sensor names + source-type keys for the style-editor modal.

    Only the regular (pupitre/overview/archive) files are considered — event
    files (default/spike) render as overlay lines, not styleable data traces,
    so they're excluded from both the field rows and the opacity-by-source
    section.
    """
    if not selected_record:
        return [], []

    include_archive = bool(include_archive_value)
    housing, regular_files, _event_files = _record_sources(selected_record, selected_db, include_archive)
    if housing is None:
        return [], []

    return db.collect_group_field_rows(regular_files, housing, group_name, group_entries or {})


style_editor.register_callbacks(
    "ds",
    context_fn=_style_context_fn,
    extra_states=[
        State("ds-record-filter", "value"),
        State("dd-database", "value"),
        State("ds-include-archive", "value"),
        State("ds-group-entries", "data"),
    ],
)
