"""Demo of a redesigned landing page (stat cards, activity chart, freshness).

Self-contained proposal for the About page: delete this file to drop it.
"""

import dash
import dash_bootstrap_components as dbc
import dash_selectors as selectors
import i18n
import magnetdb_analysis as db
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, dcc, html
from natsort import natsorted

dash.register_page(
    __name__,
    path="/about-demo",
    name="About (demo)",
    order=11,
    title=lambda: i18n._("About (demo)"),
)

# Categorical slots, fixed order (validated adjacent-pair CVD-safe for 5 slots).
# A housing keeps its slot whatever the selected metric; past 8 it falls to grey.
_HOUSING_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
_OTHER_COLOR = "#898781"

_STATUS_COLORS = {
    "in_operation": "#0ca30c",
    "in_stock": "#2a78d6",
    "in_study": "#86b6ef",
    "dead": "#d03b3b",
    "retired": "#c3c2b7",
    "disassembled": "#c3c2b7",
}

_INK_PRIMARY = "#0b0b0b"
_INK_SECONDARY = "#52514e"
_INK_MUTED = "#898781"
_GRID = "#e1e0d9"
_SURFACE = "#ffffff"

# Freshness thresholds [days]
_FRESH_DAYS = 7

_METRICS = {
    "experiments": "Experiments",
    "overview_records": "Overview records",
    "manips": "Manips",
}


def layout(**kwargs):
    """Build the demo landing page layout.

    Parameters
    ----------
    **kwargs
        URL query parameters (unused).

    Returns
    -------
    :class:`~dash.html.Div`
    """
    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.H1(
                                i18n._("MagnetDB"),
                                style={"marginBottom": "0", "fontWeight": "600"},
                            ),
                            html.Div(
                                i18n._("LNCMI magnet database"),
                                style={"color": _INK_SECONDARY, "fontSize": "1.1rem"},
                            ),
                            html.Div(id="about-demo-range", style={"color": _INK_MUTED}),
                        ]
                    ),
                    html.Div(id="about-demo-freshness"),
                ],
                style={
                    "display": "flex",
                    "justifyContent": "space-between",
                    "alignItems": "flex-start",
                    "marginBottom": "24px",
                },
            ),
            selectors.loading_region(
                [
                    html.Div(
                        id="about-demo-cards",
                        style={
                            "display": "grid",
                            "gridTemplateColumns": "repeat(auto-fill, minmax(170px, 1fr))",
                            "gap": "16px",
                            "marginBottom": "32px",
                        },
                    ),
                    dcc.Store(id="about-demo-activity"),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.H4(i18n._("Activity per year"), style={"margin": "0"}),
                                    dbc.RadioItems(
                                        id="about-demo-metric",
                                        options=[
                                            {"label": i18n._(label), "value": key}
                                            for key, label in _METRICS.items()
                                        ],
                                        value="experiments",
                                        className="btn-group",
                                        inputClassName="btn-check",
                                        labelClassName="btn btn-outline-primary btn-sm",
                                        labelCheckedClassName="active",
                                    ),
                                ],
                                style={
                                    "display": "flex",
                                    "justifyContent": "space-between",
                                    "alignItems": "center",
                                    "marginBottom": "8px",
                                },
                            ),
                            selectors.graph(id="about-demo-chart", style={"height": "380px"}),
                            html.Details(
                                [
                                    html.Summary(
                                        i18n._("Show as table"),
                                        style={"cursor": "pointer", "color": _INK_SECONDARY},
                                    ),
                                    html.Div(id="about-demo-table", style={"paddingTop": "8px"}),
                                ]
                            ),
                        ],
                        style={"marginBottom": "32px"},
                    ),
                    html.H4(i18n._("Recent activity")),
                    html.Div(id="about-demo-recent"),
                    html.Div(
                        dcc.Link(i18n._("Full operation log →"), href="/"),
                        style={"marginTop": "8px"},
                    ),
                ],
                target_components={"about-demo-cards": "children"},
            ),
        ],
        style={"padding": "20px", "maxWidth": "1400px"},
    )


def _housing_color_map(housings):
    """Map each housing to a fixed categorical slot (natsorted DB-wide order)."""
    return {
        h: _HOUSING_COLORS[i] if i < len(_HOUSING_COLORS) else _OTHER_COLOR
        for i, h in enumerate(housings)
    }


def _status_bar(by_status):
    """Thin segmented bar plus a dot-keyed legend for a ``{status: count}`` dict."""
    items = [(s, n) for s, n in by_status.items() if n]
    total = sum(n for _, n in items)
    if not total:
        return html.Div()
    bar = html.Div(
        [
            html.Div(
                title=f"{s}: {n}",
                style={
                    "flex": f"{n} 0 0",
                    "backgroundColor": _STATUS_COLORS.get(s, _OTHER_COLOR),
                },
            )
            for s, n in items
        ],
        style={
            "display": "flex",
            "gap": "2px",
            "height": "8px",
            "borderRadius": "4px",
            "overflow": "hidden",
            "margin": "10px 0 6px",
        },
    )
    legend = html.Div(
        [
            html.Span(
                [
                    html.Span(
                        style={
                            "display": "inline-block",
                            "width": "8px",
                            "height": "8px",
                            "borderRadius": "50%",
                            "backgroundColor": _STATUS_COLORS.get(s, _OTHER_COLOR),
                            "marginRight": "4px",
                        }
                    ),
                    f"{s.replace('_', ' ')} {i18n.format_number(n, precision=0)}",
                ],
                style={"marginRight": "10px", "whiteSpace": "nowrap"},
            )
            for s, n in items
        ],
        style={"fontSize": "0.8rem", "color": _INK_SECONDARY, "lineHeight": "1.6"},
    )
    return html.Div([bar, legend])


def _stat_card(label, value, href, detail=None):
    """One clickable stat card: label, big value, optional detail block."""
    return dcc.Link(
        dbc.Card(
            dbc.CardBody(
                [
                    html.Div(label, style={"color": _INK_SECONDARY, "fontSize": "0.9rem"}),
                    html.Div(
                        i18n.format_number(value, precision=0),
                        style={
                            "fontSize": "2.2rem",
                            "fontWeight": "600",
                            "color": _INK_PRIMARY,
                            "lineHeight": "1.2",
                        },
                    ),
                    detail or html.Div(),
                ]
            ),
            className="h-100 shadow-sm",
            style={"borderRadius": "10px"},
        ),
        href=href,
        style={"textDecoration": "none", "color": "inherit"},
    )


def _muted(text):
    """Small secondary-ink line under a card value."""
    return html.Div(text, style={"color": _INK_MUTED, "fontSize": "0.8rem", "marginTop": "6px"})


def _latest_year_line(by_year_housing):
    """``"<year>: <n>"`` for the most recent year of a year x housing pivot."""
    if by_year_housing is None or by_year_housing.empty:
        return None
    year = by_year_housing.index.max()
    n = int(by_year_housing.loc[year].sum())
    return _muted(i18n._("{year}: {n}").format(year=year, n=i18n.format_number(n, precision=0)))


def _freshness_badge(log_df):
    """Status pill (icon + label) for the most recent ``operation_log`` row."""
    if log_df.empty:
        return dbc.Badge(f"⚠️ {i18n._('No import recorded')}", color="warning", text_color="dark")
    last = log_df.iloc[0]
    days = (pd.Timestamp.now() - pd.Timestamp(last["Timestamp"])).days
    when = i18n._("today") if days == 0 else i18n._("{n} days ago").format(n=days)
    if last["Status"] != "ok":
        icon, color, ink = "❌", "danger", "white"
        text = i18n._("Last import failed {when}").format(when=when)
    elif days < _FRESH_DAYS:
        icon, color, ink = "✅", "success", "white"
        text = i18n._("Last import {when}").format(when=when)
    else:
        icon, color, ink = "⚠️", "warning", "dark"
        text = i18n._("Last import {when}").format(when=when)
    return html.Div(
        [
            dbc.Badge(
                f"{icon} {text}",
                pill=True,
                color=color,
                text_color=ink,
                style={"fontSize": "0.95rem", "padding": "8px 14px"},
            ),
            html.Div(
                i18n.format_datetime(last["Timestamp"]),
                style={"color": _INK_MUTED, "fontSize": "0.8rem", "textAlign": "right", "marginTop": "4px"},
            ),
        ]
    )


def _recent_list(log_df, n=5):
    """Compact list of the *n* most recent operations."""
    if log_df.empty:
        return html.Div(i18n._("No operation recorded."), style={"color": _INK_MUTED})
    return dbc.ListGroup(
        [
            dbc.ListGroupItem(
                html.Div(
                    [
                        html.Span(
                            i18n.format_datetime(row["Timestamp"]),
                            style={"color": _INK_MUTED, "width": "160px", "flexShrink": "0"},
                        ),
                        dbc.Badge(row["Operation"], color="light", text_color="dark", style={"width": "110px"}),
                        html.Span(row["Table"], style={"color": _INK_SECONDARY, "width": "110px"}),
                        html.Span(row["Record"], style={"fontWeight": "600", "flexGrow": "1"}),
                        html.Span("✅" if row["Status"] == "ok" else f"❌ {row['Status']}"),
                    ],
                    style={"display": "flex", "gap": "16px", "alignItems": "center"},
                )
            )
            for _, row in log_df.head(n).iterrows()
        ],
        flush=True,
    )


def _activity_tables(summary):
    """Year x housing count pivots for every metric, as JSON-able ``split`` dicts."""
    manips = summary["manips"]["by_year_housing"]
    manips_wide = (
        manips.pivot(index="year", columns="housing", values="n").fillna(0).astype(int)
        if manips is not None and not manips.empty
        else pd.DataFrame()
    )
    tables = {
        "experiments": summary["experiments"]["by_year_housing"],
        "overview_records": summary["overview_records"]["by_year_housing"],
        "manips": manips_wide,
    }
    return {k: v.to_dict("split") if not v.empty else None for k, v in tables.items()}


def _activity_figure(wide, color_map):
    """Stacked year x housing column chart."""
    fig = go.Figure()
    for housing in natsorted(wide.columns):
        fig.add_trace(
            go.Bar(
                x=wide.index,
                y=wide[housing],
                name=housing,
                marker={
                    "color": color_map.get(housing, _OTHER_COLOR),
                    "line": {"color": _SURFACE, "width": 2},
                },
                hovertemplate=f"<b>{housing}</b> · %{{x}}: %{{y}}<extra></extra>",
            )
        )
    totals = wide.sum(axis=1)
    fig.update_layout(
        barmode="stack",
        barcornerradius=4,
        bargap=0.35,
        plot_bgcolor=_SURFACE,
        paper_bgcolor=_SURFACE,
        margin={"l": 50, "r": 20, "t": 40, "b": 40},
        legend={
            "orientation": "h",
            "traceorder": "normal",
            "yanchor": "bottom",
            "y": 1.02,
            "x": 0,
            "font": {"color": _INK_SECONDARY},
        },
        hovermode="x unified",
        font={"family": 'system-ui, -apple-system, "Segoe UI", sans-serif', "color": _INK_SECONDARY},
        xaxis={"dtick": 1, "showgrid": False, "linecolor": "#c3c2b7", "tickfont": {"color": _INK_MUTED}},
        yaxis={"gridcolor": _GRID, "zeroline": False, "tickfont": {"color": _INK_MUTED}},
    )
    # Label only the busiest year (selective direct label)
    if not totals.empty:
        peak = totals.idxmax()
        fig.add_annotation(
            x=peak,
            y=totals[peak],
            text=f"{i18n.format_number(totals[peak], precision=0)}",
            showarrow=False,
            yshift=12,
            font={"color": _INK_PRIMARY, "size": 12},
        )
    return fig


@dash.callback(
    Output("about-demo-range", "children"),
    Output("about-demo-freshness", "children"),
    Output("about-demo-cards", "children"),
    Output("about-demo-recent", "children"),
    Output("about-demo-activity", "data"),
    Input("dd-database", "value"),
)
def update_about_demo(selected_db):
    """Fill the header, stat cards, recent activity and chart data.

    Parameters
    ----------
    selected_db : str
        Path to the selected DuckDB database.

    Returns
    -------
    tuple
        Date-range text, freshness badge, stat cards, recent-operations
        list, and per-metric year x housing tables for the chart.
    """
    if not selected_db:
        return "", None, [], None, None

    summary = db.get_database_summary(selected_db)
    log_df = db.get_operation_log(selected_db)

    manips = summary["manips"]
    date_range = (
        i18n._("Data from {from_date} to {to_date}").format(
            from_date=i18n.format_date(manips["from_date"], format="medium"),
            to_date=i18n.format_date(manips["to_date"], format="medium"),
        )
        if manips["from_date"] is not None
        else ""
    )

    housings = summary["housings"]
    manips_table = manips["by_year_housing"]
    manips_total = int(manips_table["n"].sum()) if manips_table is not None and not manips_table.empty else manips["total"]
    parts = summary["parts"]

    cards = [
        _stat_card(
            i18n._("Housings"),
            housings["total"],
            "/housings",
            _muted(" · ".join(housings["names"])),
        ),
        _stat_card(
            i18n._("Assemblies"), summary["assemblies"]["total"], "/assembly_stats",
            _status_bar(summary["assemblies"]["by_status"]),
        ),
        _stat_card(
            i18n._("Magnets"), summary["magnets"]["total"], "/magnet_stats",
            _status_bar(summary["magnets"]["by_status"]),
        ),
        _stat_card(
            i18n._("Parts"), parts["total"], "/part_stats",
            html.Div(
                [
                    _muted(i18n._("{n} coils (helix / bitter / supra)").format(n=parts["coil_total"])),
                    _status_bar(parts["by_status"]),
                ]
            ),
        ),
        _stat_card(
            i18n._("Experiments"), summary["experiments"]["total"], "/file_viewer",
            _latest_year_line(summary["experiments"]["by_year_housing"]),
        ),
        _stat_card(
            i18n._("Overview records"), summary["overview_records"]["total"], "/overview-records",
            _latest_year_line(summary["overview_records"]["by_year_housing"]),
        ),
        _stat_card(
            i18n._("Manips"), manips_total, "/research-area",
            _muted(i18n._("{n} unique users").format(n=manips["total"])),
        ),
    ]

    activity = _activity_tables(summary)
    # Union over metrics: manips can name housings with no assembly in the DB
    activity["housings"] = natsorted(
        {h for split in activity.values() if split for h in split["columns"]}
    )

    return date_range, _freshness_badge(log_df), cards, _recent_list(log_df), activity


@dash.callback(
    Output("about-demo-chart", "figure"),
    Output("about-demo-table", "children"),
    Input("about-demo-metric", "value"),
    Input("about-demo-activity", "data"),
)
def update_about_demo_chart(metric, activity):
    """Draw the year x housing chart and its table view for *metric*.

    Parameters
    ----------
    metric : str
        Key of :data:`_METRICS`.
    activity : dict
        Store written by :func:`update_about_demo`.

    Returns
    -------
    tuple
        Plotly figure and the matching table (or placeholder).
    """
    if not activity or not activity.get(metric):
        return go.Figure(), html.Div(i18n._("No data."), style={"color": _INK_MUTED})
    split = activity[metric]
    wide = pd.DataFrame(split["data"], index=split["index"], columns=split["columns"])
    wide.index.name = "year"
    fig = _activity_figure(wide, _housing_color_map(activity["housings"]))
    return fig, selectors._year_housing_pivot_table(wide)
