import dash
import dash_selectors as selectors
import magnetdb_analysis as db
import pandas as pd
import plotly.express as px
from dash import Input, Output, callback, dcc, html
from dash.dash_table import DataTable
from experiment_links import assembly_link, experiment_link, overview_record_link
from plotly import graph_objects as go

dash.register_page(__name__, path="/research-area", name="Manips", order=1)

RA_STATS_COLUMNS = [
    {"name": c, "id": c}
    for c in ("research_area", "n_experiments", "n_manips", "total_field_time_h")
]

EXPERIMENTS_COLUMNS = [
    (
        {"name": c, "id": c, "presentation": "markdown"}
        if c in ("Experiment", "Assembly")
        else {"name": c, "id": c}
    )
    for c in ("ID", "Experiment", "Assembly", "Housing", "Status")
]

OVERVIEW_RECORD_COLUMNS = [
    (
        {"name": c, "id": c, "presentation": "markdown"}
        if c in ("Overview Record", "Assembly")
        else {"name": c, "id": c}
    )
    for c in ("Overview Record", "Assembly", "Housing", "Mode", "t0")
]


def _no_data_message(text):
    """One-liner italic-gray placeholder for an empty accordion section."""
    return html.Div(text, style={"color": "#888", "fontStyle": "italic"})


def _experiments_section(exp_df):
    """Build the "Matching experiments" accordion content for a filtered dataframe."""
    if exp_df.empty:
        return _no_data_message("No experiments found for the current filters.")
    source_df = exp_df.rename(
        columns={
            "id": "ID",
            "name": "Experiment",
            "file": "File",
            "assembly_name": "Assembly",
            "status": "Status",
        }
    )
    source_df["Experiment"] = pd.to_datetime(source_df["Experiment"])
    source_df["Housing"] = source_df["Assembly"].str.extract(r"^(M\d+)")

    table_df = source_df.drop(columns=["File"])
    table_df["Experiment"] = source_df.apply(experiment_link, axis=1)
    table_df["Assembly"] = source_df.apply(assembly_link, axis=1)
    table_df = table_df[["ID", "Experiment", "Assembly", "Housing", "Status"]]

    return DataTable(
        columns=EXPERIMENTS_COLUMNS,
        data=table_df.to_dict("records"),
        page_size=10,
        sort_action="native",
        style_table={"overflowX": "auto"},
        style_cell={"textAlign": "center", "padding": "6px"},
        style_header={"fontWeight": "bold"},
    )


def _overview_records_section(ov_df):
    """Build the "Matching overview records" accordion content for a filtered dataframe."""
    if ov_df.empty:
        return _no_data_message("No overview records found for the current filters.")
    source_df = ov_df.rename(
        columns={
            "filename": "Overview Record",
            "assembly_name": "Assembly",
            "housing": "Housing",
            "mode": "Mode",
        }
    )

    table_df = source_df[
        ["Overview Record", "Assembly", "Housing", "Mode", "t0"]
    ].copy()
    table_df["Overview Record"] = source_df.apply(overview_record_link, axis=1)
    table_df["Assembly"] = source_df.apply(assembly_link, axis=1)

    return DataTable(
        columns=OVERVIEW_RECORD_COLUMNS,
        data=table_df.to_dict("records"),
        page_size=10,
        sort_action="native",
        style_table={"overflowX": "auto"},
        style_cell={"textAlign": "center", "padding": "6px"},
        style_header={"fontWeight": "bold"},
    )


def _add_field_bin_columns(df, percent_group_cols):
    """Add a "Field bin" label column and a per-group "Percent" column to a bin-stats df.

    Parameters
    ----------
    df : :class:`~pandas.DataFrame`
        Must have ``field_bin_low``, ``field_bin_high``, ``Time (h)``
        columns, as returned by :func:`db.get_research_area_field_bin_stats_by_year`.
        Mutated in place with the new ``"Field bin"`` and ``"Percent"``
        columns.
    percent_group_cols : list of str
        Columns to group by when computing each row's ``Percent`` of its
        group's total ``Time (h)``.

    Returns
    -------
    tuple of (list of str, list of str)
        ``(bin_order, bin_colors)`` -- the field-bin labels in ascending
        field order, and a matching Viridis color for each.
    """
    df["Field bin"] = [
        f"{low:g}-{high:g} T"
        for low, high in zip(df["field_bin_low"], df["field_bin_high"])
    ]
    bin_order = (
        df[["field_bin_low", "Field bin"]]
        .drop_duplicates()
        .sort_values("field_bin_low")["Field bin"]
        .tolist()
    )
    bin_colors = px.colors.sample_colorscale(
        "Viridis", [i / max(len(bin_order) - 1, 1) for i in range(len(bin_order))]
    )
    df["Percent"] = (
        df["Time (h)"]
        / df.groupby(percent_group_cols)["Time (h)"].transform("sum")
        * 100
    )
    return bin_order, bin_colors


def _file_range_text(label, count, start, end):
    """One summary line: "<label>: <count> (<start> -> <end>)", or "none"/no-range fallback."""
    if not count:
        return f"{label}: none"
    if pd.isna(start):
        return f"{label}: {count}"
    return f"{label}: {count} ({start:%Y-%m-%d} → {end:%Y-%m-%d})"


def _housing_summary():
    """Build the per-housing experiments/overview-records summary banner."""
    summary_df = db.get_housing_file_summary()
    lines = []
    for row in summary_df.itertuples():
        lines.append(html.B(row.housing))
        lines.append(html.Br())
        lines.append(
            _file_range_text(
                "  Experiments",
                row.n_experiments,
                row.experiments_start,
                row.experiments_end,
            )
        )
        lines.append(html.Br())
        lines.append(
            _file_range_text(
                "  Overview records",
                row.n_overview_records,
                row.overview_records_start,
                row.overview_records_end,
            )
        )
        lines.append(html.Br())
    return lines


layout = html.Div(
    [
        html.H2("Manip Dashboard"),
        html.Br(),
        html.Div(
            [
                selectors.aggregate_filter(
                    "ra-research-area",
                    "Research area",
                    options=db.get_research_areas(),
                    style={"width": "250px"},
                ),
                selectors.aggregate_filter(
                    "ra-housing",
                    "Housing",
                    options=db.get_housings(),
                    style={"width": "250px"},
                ),
                selectors.aggregate_filter(
                    "ra-year",
                    "Year",
                    options=["2022", "2023", "2024", "2025", "2026"],
                    style={"width": "250px"},
                ),
                selectors.aggregate_filter(
                    "ra-user", "Manip", options=db.get_users(), style={"width": "250px"}
                ),
            ],
            style={"display": "flex", "gap": "30px", "marginBottom": "30px"},
        ),
        html.Div(_housing_summary(), id="ra-summary"),
        html.Br(),
        dcc.Graph(id="ra-exp"),
        dcc.Graph(id="ra-time"),
        dcc.Graph(id="ra-time-by-bin"),
        dcc.Graph(id="ra-users"),
        html.Details(
            [
                html.Summary(
                    "📊 Statistics", style={"fontWeight": "bold", "cursor": "pointer"}
                ),
                html.Div(
                    DataTable(
                        id="ra-table",
                        columns=RA_STATS_COLUMNS,
                        data=[],
                        page_size=10,
                        sort_action="native",
                        style_table={"overflowX": "auto"},
                        style_cell={"textAlign": "center", "padding": "6px"},
                        style_header={"fontWeight": "auto"},
                    ),
                    style={"padding": "10px"},
                ),
            ],
            open=True,
            style={
                "border": "1px solid #ddd",
                "borderRadius": "8px",
                "marginBottom": "20px",
            },
        ),
        html.Details(
            [
                html.Summary(
                    "📊 Matching experiments",
                    style={"fontWeight": "bold", "cursor": "pointer"},
                ),
                html.Div(id="ra-experiments-content", style={"padding": "10px"}),
            ],
            id="ra-experiments",
            open=False,
            style={
                "border": "1px solid #ddd",
                "borderRadius": "8px",
                "marginBottom": "10px",
                "display": "none",
            },
        ),
        html.Details(
            [
                html.Summary(
                    "📁 Matching overview records",
                    style={"fontWeight": "bold", "cursor": "pointer"},
                ),
                html.Div(id="ra-overview-records-content", style={"padding": "10px"}),
            ],
            id="ra-overview-records",
            open=False,
            style={
                "border": "1px solid #ddd",
                "borderRadius": "8px",
                "marginBottom": "10px",
                "display": "none",
            },
        ),
    ],
    style={"padding": "20px"},
)


@callback(
    Output("ra-table", "data"),
    Output("ra-exp", "figure"),
    Output("ra-users", "figure"),
    Output("ra-time", "figure"),
    Output("ra-time-by-bin", "figure"),
    Output("ra-experiments", "style"),
    Output("ra-experiments-content", "children"),
    Output("ra-overview-records", "style"),
    Output("ra-overview-records-content", "children"),
    Input("ra-research-area", "value"),
    Input("ra-housing", "value"),
    Input("ra-year", "value"),
    Input("ra-user", "value"),
)
def update(research_area, housing, year, user):

    research_area = None if research_area == "All" else research_area
    housing = None if housing == "All" else housing
    year = None if year == "All" else year
    user = None if user == "All" else user

    df = db.get_research_area_stats(
        housing=housing,
        year=year,
        research_area=research_area,
        user=user,
    )
    df = df.rename(
        columns={"total_field_time_s": "total_field_time_h", "n_users": "n_manips"}
    )
    df["total_field_time_h"] = df["total_field_time_h"] / 3600

    by_year_df = db.get_research_area_stats_by_year(
        housing=housing, year=year, research_area=research_area, user=user
    )
    by_year_df["year"] = by_year_df["year"].astype(int).astype(str)
    by_year_df = by_year_df.rename(
        columns={"total_field_time_s": "total_field_time_h", "n_users": "n_manips"}
    )
    by_year_df["total_field_time_h"] = by_year_df["total_field_time_h"] / 3600

    fig_exp = px.bar(
        by_year_df,
        x="research_area",
        y="n_experiments",
        color="year",
        barmode="group",
        title="Experiments per research area",
    )

    fig_users = px.bar(
        by_year_df,
        x="research_area",
        y="n_manips",
        color="year",
        barmode="group",
        title="Manips per research area",
    )

    fig_time = px.bar(
        by_year_df,
        x="research_area",
        y="total_field_time_h",
        color="year",
        barmode="group",
        title="Total field time (h)",
    )

    bin_df = db.get_research_area_field_bin_stats_by_year(
        housing=housing, year=year, research_area=research_area, user=user
    )
    if bin_df.empty:
        fig_time_by_bin = go.Figure()
    else:
        bin_df["year"] = bin_df["year"].astype(int).astype(str)
        bin_df = bin_df.rename(
            columns={"total_time_h": "Time (h)", "n_users": "n_manips"}
        )
        bin_order, bin_colors = _add_field_bin_columns(
            bin_df, ["research_area", "year"]
        )

        fig_time_by_bin = px.bar(
            bin_df,
            x="year",
            y="Time (h)",
            color="Field bin",
            facet_col="research_area",
            category_orders={"Field bin": bin_order},
            color_discrete_sequence=bin_colors,
            custom_data=["Percent"],
            title="Total field time per research area per year by field bin (h)",
        )
        fig_time_by_bin.update_traces(
            hovertemplate=(
                "%{fullData.name}<br>%{x}<br>"
                "%{y:.1f} h (%{customdata[0]:.1f}% of research area total)<extra></extra>"
            )
        )
        fig_time_by_bin.for_each_annotation(
            lambda a: a.update(text=a.text.split("=")[-1])
        )

    filters_active = any(v is not None for v in (research_area, housing, year, user))

    section_style = {
        "border": "1px solid #ddd",
        "borderRadius": "8px",
        "marginBottom": "10px",
    }

    if filters_active:
        exp_df = db.get_experiments_for_filters(
            housing=housing, year=year, research_area=research_area, user=user
        )
        ov_df = db.get_overview_records_for_filters(
            housing=housing, year=year, research_area=research_area, user=user
        )
        section_style = {**section_style, "display": "block"}
        exp_content = _experiments_section(exp_df)
        ov_content = _overview_records_section(ov_df)
    else:
        section_style = {**section_style, "display": "none"}
        exp_content = ov_content = None

    return (
        df.to_dict("records"),
        fig_exp,
        fig_users,
        fig_time,
        fig_time_by_bin,
        section_style,
        exp_content,
        section_style,
        ov_content,
    )
