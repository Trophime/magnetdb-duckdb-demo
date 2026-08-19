import dash
import duckdb
import pandas as pd

from dash import html, dcc, Input, Output
from dash.dash_table import DataTable

import plotly.express as px
from plotly import graph_objects as go
import magnetdb_analysis as db

dash.register_page(__name__, path="/", name="Housing stats", order=1)


J_TO_KWH = 3.6e6
S_TO_H = 3600
HOUSING_COLORS = {"M9": "red", "M10": "blue"}
_MONTH_LABELS = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]

COMMISSIONING_COLUMNS = [{"name": c, "id": c} for c in ("Assembly", "Status", "Commissioned", "Decommissioned")]


def load_housing_summary(db_path=None):
    """Aggregate total energy/field-on time and assembly counts per housing.

    Parameters
    ----------
    db_path : str, optional
        Path to the DuckDB database. Defaults to :data:`db.DB_PATH`.

    Returns
    -------
    :class:`~pandas.DataFrame`
        One row per housing, with ``Housing``, ``Energy (kWh)``,
        ``Field ON (h)``, ``Assemblies``, ``In operation``.
    """
    db_path = db_path or db.DB_PATH
    con = duckdb.connect(db_path, read_only=True)

    energy_df = con.execute(f"""
        SELECT
            a.housing AS Housing,
            ROUND(SUM(CASE WHEN s.channel = 'energy_j' THEN s.value END) / {J_TO_KWH}, 2) AS "Energy (kWh)",
            ROUND(SUM(CASE WHEN s.channel = 'duration_field_on_s' THEN s.value END) / {S_TO_H}, 2) AS "Field ON (h)"
        FROM experiments AS e
        JOIN assemblies AS a ON a.name = e.assembly_name
        LEFT JOIN exp_run_scalars AS s ON s.experiment_id = e.id
        GROUP BY a.housing
    """).fetchdf()

    counts_df = con.execute("""
        SELECT
            housing AS Housing,
            COUNT(*) AS Assemblies,
            SUM(CASE WHEN status = 'in_operation' THEN 1 ELSE 0 END) AS "In operation"
        FROM assemblies
        GROUP BY housing
    """).fetchdf()
    con.close()

    return counts_df.merge(energy_df, on="Housing", how="left").fillna(0)


def load_commissioning_history(db_path=None):
    """Return assemblies grouped by housing, ordered by commissioning date.

    Parameters
    ----------
    db_path : str, optional
        Path to the DuckDB database. Defaults to :data:`db.DB_PATH`.

    Returns
    -------
    dict of str -> list of dict
        Housing name -> list of ``{"Assembly", "Status", "Commissioned",
        "Decommissioned"}`` dicts, ascending by ``Commissioned`` (NULLs last).
    """
    db_path = db_path or db.DB_PATH
    con = duckdb.connect(db_path, read_only=True)
    df = con.execute("""
        SELECT
            housing AS Housing,
            name AS Assembly,
            status AS Status,
            commissioned_at AS Commissioned,
            decommissioned_at AS Decommissioned
        FROM assemblies
        WHERE housing IS NOT NULL
        ORDER BY housing, commissioned_at NULLS LAST
    """).fetchdf()
    con.close()

    if df.empty:
        return {}
    return {housing: group.drop(columns=["Housing"]).to_dict("records") for housing, group in df.groupby("Housing")}


def _field_activity_strip(housing, db_path=None):
    """Build a small CSS strip of monthly magnet-on activity for one housing.

    One cell per month with at least one experiment: green = field was on
    that month (``duration_field_on_s > 0`` in ``exp_run_scalars``), light
    gray = off (backed by real stats), mid gray hatch = ``exp_run_scalars``
    not backfilled yet for that month's experiments (missing data, not a
    real "off").
    """
    history = db.get_field_bin_history(housing, db_path)
    if not history:
        return html.Div("No experiment history yet.", style={"color": "#888", "fontStyle": "italic"})

    cells = []
    for row in history:
        if not row["has_stats"]:
            color, label = "#bbbbbb", "no stats yet"
        elif row["field_on"]:
            color, label = "#2ca02c", "field on"
        else:
            color, label = "#f2f2f2", "field off"
        cells.append(
            html.Div(
                title=f"{_MONTH_LABELS[row['month'] - 1]} {row['year']} — {label}",
                style={
                    "width": "10px",
                    "height": "18px",
                    "backgroundColor": color,
                    "display": "inline-block",
                    "marginRight": "1px",
                    "border": "1px solid #ddd",
                },
            )
        )
    return html.Div(
        cells,
        style={"whiteSpace": "nowrap", "overflowX": "auto", "padding": "4px 0"},
    )


def _housing_section(housing, summary_row, commissioning_rows, db_path=None):
    """Build one housing's summary card: energy/field-on/assembly counts, activity strip, commissioning table."""
    energy = summary_row["Energy (kWh)"] if summary_row is not None else 0
    field_on = summary_row["Field ON (h)"] if summary_row is not None else 0
    n_assemblies = int(summary_row["Assemblies"]) if summary_row is not None else 0
    n_in_operation = int(summary_row["In operation"]) if summary_row is not None else 0

    return html.Div(
        [
            html.H3(housing, style={"marginBottom": "5px"}),
            html.Div(
                [
                    html.Span(f"Energy: {energy:,.2f} kWh", style={"marginRight": "25px"}),
                    html.Span(f"Magnet time: {field_on:,.2f} h", style={"marginRight": "25px"}),
                    html.Span(f"Assemblies: {n_assemblies} ({n_in_operation} in operation)"),
                ],
                style={"marginBottom": "10px"},
            ),
            html.Label("Commissioning activity by month:", style={"fontSize": "13px", "color": "#555"}),
            _field_activity_strip(housing, db_path),
            html.Br(),
            DataTable(
                columns=COMMISSIONING_COLUMNS,
                data=commissioning_rows,
                page_size=10,
                sort_action="native",
                style_table={"overflowX": "auto"},
                style_cell={"textAlign": "center", "padding": "6px"},
                style_header={"fontWeight": "bold"},
            ),
            html.Br(),
            dcc.Link("View all assemblies →", href="/assembly_stats"),
        ],
        style={
            "border": "1px solid #ddd",
            "borderRadius": "8px",
            "padding": "15px",
            "marginBottom": "20px",
            "boxShadow": "0 2px 4px rgba(0,0,0,0.05)",
        },
    )


def layout(**kwargs):
    return html.Div(
        [
            html.H1("MagnetDB Dashboard"),
            html.Div(id="housing-stats-summary"),
            dcc.Graph(id="housing-stats-energy-fig"),
            html.Br(),
            html.Div(id="housing-stats-sections"),
        ],
        style={"padding": "20px"},
    )


@dash.callback(
    Output("housing-stats-summary", "children"),
    Output("housing-stats-energy-fig", "figure"),
    Output("housing-stats-sections", "children"),
    Input("dd-database", "value"),
)
def update_housing_stats(selected_db):
    if not selected_db:
        return [], go.Figure(), []

    summary_df = load_housing_summary(selected_db)
    commissioning = load_commissioning_history(selected_db)
    counts = db.get_db_counts(selected_db)

    top_summary = [
        html.B(f"Housings: {counts['housings']}"), html.Br(),
        html.B(f"Assemblies: {counts['assemblies']}"), html.Br(),
        html.B(f"Magnets: {counts['magnets']}"), html.Br(),
        html.B(f"Parts: {counts['parts']}"), html.Br(),
        html.B(f"Experiments: {counts['experiments']}"), html.Br(),
        html.B(f"Overview records: {counts['overview_records']}"),
    ]

    fig = px.bar(
        summary_df,
        x="Housing",
        y="Energy (kWh)",
        color="Housing",
        color_discrete_map=HOUSING_COLORS,
        title="Total Energy per Housing",
    )

    sections = []
    for housing in sorted(summary_df["Housing"].dropna().unique()):
        row = summary_df[summary_df["Housing"] == housing].iloc[0]
        sections.append(
            _housing_section(housing, row, commissioning.get(housing, []), selected_db)
        )

    return top_summary, fig, sections
