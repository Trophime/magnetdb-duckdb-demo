"""Shared gear-icon + modal UI for editing per-group/per-field trace styles.

Each page (`file_viewer.py`, `overview_records.py`) places one gear button per
group block via :func:`gear_button`, one shared modal via
:func:`modal_component`, and wires the open/save/reset/cancel callbacks once
at import time via :func:`register_callbacks`, passing its own id prefix and a
`context_fn` that resolves which raw sensor names and source-type keys are
relevant to a given group in that page's current state.
"""

import dash
import dash_bootstrap_components as dbc
import magnetdb_plot as plot
from dash import ALL, MATCH, Input, Output, State, ctx, dcc, html
from dash.exceptions import PreventUpdate

# Plotly/d3's default qualitative "category10" palette — the same 10 colors
# FILE_TYPE_STYLES' six source-type defaults are already drawn from, plus the
# four remaining ones, so the swatch picker stays visually consistent with
# colors already used elsewhere in the dashboard.
_COLOR_PALETTE = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
]
_COLOR_CELL_WIDTH = "72px"

_DASH_OPTIONS = ["solid", "dot", "dash", "longdash", "dashdot", "longdashdot"]
_MARKER_OPTIONS = [
    {"label": "None", "value": ""},
    {"label": "circle", "value": "circle"},
    {"label": "square", "value": "square"},
    {"label": "diamond", "value": "diamond"},
    {"label": "cross", "value": "cross"},
    {"label": "x", "value": "x"},
    {"label": "triangle-up", "value": "triangle-up"},
    {"label": "triangle-down", "value": "triangle-down"},
    {"label": "star", "value": "star"},
    {"label": "pentagon", "value": "pentagon"},
]


def gear_button(id_prefix: str, group_name: str):
    """Small gear icon, absolutely positioned over a group's Details/Summary bar.

    Parameters
    ----------
    id_prefix : str
        Page-specific id prefix (e.g. ``"fv"``, ``"ov"``).
    group_name : str
        The group this gear opens the style editor for.

    Returns
    -------
    :class:`~dash.html.Button`
        Not nested inside the group's `Summary` — see the caller's Details
        block, which must add ``position: relative`` so this anchors over it.
    """
    return html.Button(
        "⚙",
        id={"type": f"{id_prefix}-style-gear", "index": group_name},
        n_clicks=0,
        title="Edit style for this group",
        style={
            "position": "absolute",
            "top": "8px",
            "right": "15px",
            "zIndex": 2,
            "border": "none",
            "background": "transparent",
            "cursor": "pointer",
            "fontSize": "18px",
            "lineHeight": "1",
        },
    )


def modal_component(id_prefix: str):
    """Modal + supporting stores for one page. Place once in the page's `layout()`."""
    return html.Div(
        [
            dcc.Store(id=f"{id_prefix}-style-modal-group"),
            dcc.Store(id=f"{id_prefix}-style-version", data=0),
            dbc.Modal(
                [
                    dbc.ModalHeader(dbc.ModalTitle(id=f"{id_prefix}-style-modal-title")),
                    dbc.ModalBody(html.Div(id=f"{id_prefix}-style-modal-body")),
                    dbc.ModalFooter(
                        [
                            dbc.Button(
                                "Reset", id=f"{id_prefix}-style-reset-btn",
                                color="secondary", outline=True, n_clicks=0,
                            ),
                            dbc.Button(
                                "Cancel", id=f"{id_prefix}-style-cancel-btn",
                                color="secondary", n_clicks=0,
                            ),
                            dbc.Button(
                                "Save", id=f"{id_prefix}-style-save-btn",
                                color="primary", n_clicks=0,
                            ),
                        ]
                    ),
                ],
                id=f"{id_prefix}-style-modal",
                is_open=False,
                size="lg",
            ),
        ]
    )


def _color_cell(id_prefix: str, sensor: str, color: str):
    """Hex text input + a clickable preset-swatch palette, for one field row.

    ``dcc.Input``/``dbc.Input`` don't support ``type="color"`` (not in either
    component's ``type`` prop enum), so there's no native browser color-swatch
    picker available — this builds an equivalent out of a plain text input
    (still accepts any hex/CSS color typed or pasted directly) plus preset
    swatch buttons that fill it in on click.
    """
    return html.Div(
        [
            dcc.Input(
                type="text", value=color, placeholder="#rrggbb",
                id={"type": f"{id_prefix}-field-color", "sensor": sensor},
                style={"width": _COLOR_CELL_WIDTH, "marginBottom": "3px", "fontSize": "11px"},
            ),
            html.Div(
                [
                    html.Button(
                        "",
                        id={"type": f"{id_prefix}-field-swatch", "sensor": sensor, "color": c},
                        n_clicks=0,
                        title=c,
                        style={
                            "width": "14px", "height": "14px", "backgroundColor": c,
                            "border": "1px solid #999", "borderRadius": "2px",
                            "padding": "0", "cursor": "pointer",
                        },
                    )
                    for c in _COLOR_PALETTE
                ],
                style={"display": "flex", "flexWrap": "wrap", "gap": "2px", "width": _COLOR_CELL_WIDTH},
            ),
        ],
        style={"width": _COLOR_CELL_WIDTH, "flexShrink": 0},
    )


def _field_row(id_prefix: str, group_name: str, sensor: str, source_key: str | None):
    style = plot.FILE_TYPE_STYLES.get(source_key)
    override = plot._resolve_field_override(group_name, sensor)

    color = (override.color if override else None) or (style.color if style else "#1f77b4")
    dash_value = (override.dash if override else None) or (style.dash if style else "solid")
    width = override.width if (override and override.width is not None) else None
    if width is None:
        width = style.width if style else 2
    marker_symbol = (override.marker_symbol if override else None) or ""
    marker_every = (override.marker_every if override else None) or 1

    return html.Div(
        [
            html.Div(sensor, style={"width": "160px", "fontWeight": "bold"}),
            _color_cell(id_prefix, sensor, color),
            dcc.Dropdown(
                options=_DASH_OPTIONS, value=dash_value, clearable=False,
                id={"type": f"{id_prefix}-field-dash", "sensor": sensor},
                style={"width": "130px"},
            ),
            dcc.Input(
                type="number", value=width, min=0.5, step=0.5,
                id={"type": f"{id_prefix}-field-width", "sensor": sensor},
                style={"width": "60px"},
            ),
            dcc.Dropdown(
                options=_MARKER_OPTIONS, value=marker_symbol, clearable=False,
                id={"type": f"{id_prefix}-field-marker", "sensor": sensor},
                style={"width": "140px"},
            ),
            dcc.Input(
                type="number", value=marker_every, min=1, step=1,
                id={"type": f"{id_prefix}-field-every", "sensor": sensor},
                style={"width": "60px"},
            ),
        ],
        style={"display": "flex", "gap": "8px", "alignItems": "flex-start", "marginBottom": "6px"},
    )


def _source_opacity_row(id_prefix: str, source_key: str):
    style = plot.FILE_TYPE_STYLES.get(source_key)
    opacity = style.opacity if style else 1.0
    return html.Div(
        [
            html.Div(source_key, style={"width": "160px", "fontWeight": "bold"}),
            dcc.Input(
                type="number", value=opacity, min=0, max=1, step=0.05,
                id={"type": f"{id_prefix}-source-opacity", "source": source_key},
                style={"width": "80px"},
            ),
        ],
        style={"display": "flex", "gap": "8px", "alignItems": "center", "marginBottom": "6px"},
    )


def _build_modal_body(id_prefix: str, group_name: str, field_rows, source_keys):
    field_rows = list(dict(field_rows).items())
    if not field_rows:
        return html.Div("No fields available for this group.")

    header = html.Div(
        [
            html.Div("Field", style={"width": "160px", "fontWeight": "bold"}),
            html.Div("Color", style={"width": _COLOR_CELL_WIDTH, "fontWeight": "bold"}),
            html.Div("Dash", style={"width": "130px", "fontWeight": "bold"}),
            html.Div("Width", style={"width": "60px", "fontWeight": "bold"}),
            html.Div("Marker", style={"width": "140px", "fontWeight": "bold"}),
            html.Div("Every N", style={"width": "60px", "fontWeight": "bold"}),
        ],
        style={"display": "flex", "gap": "8px", "marginBottom": "8px"},
    )
    rows = [_field_row(id_prefix, group_name, sensor, source_key) for sensor, source_key in field_rows]
    sections = [html.H6(f"Field styles — {group_name}"), header, *rows]

    if source_keys:
        sections += [
            html.Hr(),
            html.H6("Opacity by source"),
            *[_source_opacity_row(id_prefix, key) for key in source_keys],
        ]
    return html.Div(sections)


def _updated_file_type_styles(opacity_map: dict) -> plot.FileTypeStyles:
    data = plot.FILE_TYPE_STYLES.to_dict()
    for source_key, opacity in opacity_map.items():
        if source_key in data and opacity is not None:
            data[source_key]["opacity"] = opacity
    return plot.FileTypeStyles.from_dict(data)


def register_callbacks(id_prefix: str, context_fn, extra_states: list | None = None):
    """Register the open/save/reset/cancel callbacks for one page's style editor.

    Parameters
    ----------
    id_prefix : str
        Page-specific id prefix, matching :func:`gear_button`/:func:`modal_component`.
    context_fn : callable
        ``context_fn(group_name, *extra_state_values) -> (field_rows, source_keys)``.
        ``field_rows`` is an iterable of ``(sensor_name, source_type_key)`` pairs
        for the group; ``source_keys`` is the distinct source-type keys to expose
        opacity controls for.
    extra_states : list of dash.State, optional
        Additional `State` dependencies (e.g. the page's selected file/record)
        forwarded to *context_fn* after `group_name`.
    """
    extra_states = extra_states or []

    @dash.callback(
        Output(f"{id_prefix}-style-modal", "is_open"),
        Output(f"{id_prefix}-style-modal-group", "data"),
        Output(f"{id_prefix}-style-modal-body", "children"),
        Output(f"{id_prefix}-style-modal-title", "children"),
        Input({"type": f"{id_prefix}-style-gear", "index": ALL}, "n_clicks"),
        *extra_states,
        prevent_initial_call=True,
    )
    def _open_style_modal(all_clicks, *extra_values):
        triggered = ctx.triggered_id
        if not isinstance(triggered, dict) or not ctx.triggered or not ctx.triggered[0]["value"]:
            raise PreventUpdate
        group_name = triggered["index"]
        field_rows, source_keys = context_fn(group_name, *extra_values)
        body = _build_modal_body(id_prefix, group_name, field_rows, source_keys)
        return True, group_name, body, f"Style — {group_name}"

    @dash.callback(
        Output({"type": f"{id_prefix}-field-color", "sensor": MATCH}, "value"),
        Input({"type": f"{id_prefix}-field-swatch", "sensor": MATCH, "color": ALL}, "n_clicks"),
        prevent_initial_call=True,
    )
    def _pick_swatch_color(all_clicks):
        triggered = ctx.triggered_id
        if not isinstance(triggered, dict) or not any(all_clicks or []):
            raise PreventUpdate
        return triggered["color"]

    @dash.callback(
        Output(f"{id_prefix}-style-modal", "is_open", allow_duplicate=True),
        Input(f"{id_prefix}-style-cancel-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def _cancel_style_modal(n_clicks):
        if not n_clicks:
            raise PreventUpdate
        return False

    @dash.callback(
        Output(f"{id_prefix}-style-modal", "is_open", allow_duplicate=True),
        Output(f"{id_prefix}-style-version", "data", allow_duplicate=True),
        Input(f"{id_prefix}-style-save-btn", "n_clicks"),
        State(f"{id_prefix}-style-modal-group", "data"),
        State({"type": f"{id_prefix}-field-color", "sensor": ALL}, "value"),
        State({"type": f"{id_prefix}-field-color", "sensor": ALL}, "id"),
        State({"type": f"{id_prefix}-field-dash", "sensor": ALL}, "value"),
        State({"type": f"{id_prefix}-field-dash", "sensor": ALL}, "id"),
        State({"type": f"{id_prefix}-field-width", "sensor": ALL}, "value"),
        State({"type": f"{id_prefix}-field-width", "sensor": ALL}, "id"),
        State({"type": f"{id_prefix}-field-marker", "sensor": ALL}, "value"),
        State({"type": f"{id_prefix}-field-marker", "sensor": ALL}, "id"),
        State({"type": f"{id_prefix}-field-every", "sensor": ALL}, "value"),
        State({"type": f"{id_prefix}-field-every", "sensor": ALL}, "id"),
        State({"type": f"{id_prefix}-source-opacity", "source": ALL}, "value"),
        State({"type": f"{id_prefix}-source-opacity", "source": ALL}, "id"),
        State(f"{id_prefix}-style-version", "data"),
        prevent_initial_call=True,
    )
    def _save_style(
        n_clicks, group_name,
        color_vals, color_ids, dash_vals, dash_ids, width_vals, width_ids,
        marker_vals, marker_ids, every_vals, every_ids,
        opacity_vals, opacity_ids, version,
    ):
        if not n_clicks or not group_name:
            raise PreventUpdate

        color_map = dict(zip([i["sensor"] for i in color_ids], color_vals))
        dash_map = dict(zip([i["sensor"] for i in dash_ids], dash_vals))
        width_map = dict(zip([i["sensor"] for i in width_ids], width_vals))
        marker_map = dict(zip([i["sensor"] for i in marker_ids], marker_vals))
        every_map = dict(zip([i["sensor"] for i in every_ids], every_vals))
        opacity_map = dict(zip([i["source"] for i in opacity_ids], opacity_vals))

        field_overrides = dict(plot.FIELD_STYLE_OVERRIDES)
        field_overrides[group_name] = {
            sensor: plot.FieldStyleOverride(
                color=color_map.get(sensor),
                dash=dash_map.get(sensor),
                width=width_map.get(sensor),
                marker_symbol=(marker_map.get(sensor) or None),
                marker_every=(every_map.get(sensor) if marker_map.get(sensor) else None),
            )
            for sensor in color_map
        }

        config = plot.StyleConfig(
            file_type_styles=_updated_file_type_styles(opacity_map),
            field_overrides=field_overrides,
        )
        plot.save_style_config(config, plot.USER_STYLE_CONFIG_PATH)
        plot.reload_style_config()

        return False, (version or 0) + 1

    @dash.callback(
        Output(f"{id_prefix}-style-modal", "is_open", allow_duplicate=True),
        Output(f"{id_prefix}-style-version", "data", allow_duplicate=True),
        Input(f"{id_prefix}-style-reset-btn", "n_clicks"),
        State(f"{id_prefix}-style-modal-group", "data"),
        State(f"{id_prefix}-style-version", "data"),
        prevent_initial_call=True,
    )
    def _reset_style_group(n_clicks, group_name, version):
        if not n_clicks or not group_name:
            raise PreventUpdate
        if group_name in plot.FIELD_STYLE_OVERRIDES:
            field_overrides = {
                k: v for k, v in plot.FIELD_STYLE_OVERRIDES.items() if k != group_name
            }
            config = plot.StyleConfig(
                file_type_styles=plot.FILE_TYPE_STYLES, field_overrides=field_overrides
            )
            plot.save_style_config(config, plot.USER_STYLE_CONFIG_PATH)
            plot.reload_style_config()
        return False, (version or 0) + 1
