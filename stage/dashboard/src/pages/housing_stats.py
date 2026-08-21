import dash
import duckdb
import pandas as pd

from dash import html, dcc, Input, Output
from dash.dash_table import DataTable
from natsort import natsorted

import plotly.express as px
from plotly import graph_objects as go
import dash_bootstrap_components as dbc
import magnetdb_analysis as db
import dash_selectors as selectors
from experiment_links import assembly_link

dash.register_page(__name__, path="/", name="Housing stats", order=1)


J_TO_KWH = 3.6e6
S_TO_H = 3600
HOUSING_COLORS = {"M9": "red", "M10": "blue"}
_MONTH_LABELS = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]

COMMISSIONING_COLUMNS = [
    {"name": c, "id": c, "presentation": "markdown"} if c == "Assembly" else {"name": c, "id": c}
    for c in ("Assembly", "Status", "Commissioned", "Decommissioned")
]


def load_housing_summary(db_path=None, assembly_names=None):
    """Aggregate total energy/field-on time and assembly counts per housing.

    Parameters
    ----------
    db_path : str, optional
        Path to the DuckDB database. Defaults to :data:`db.DB_PATH`.
    assembly_names : collection of str, optional
        Restrict to these assemblies only. Defaults to all assemblies.

    Returns
    -------
    :class:`~pandas.DataFrame`
        One row per housing, with ``Housing``, ``Energy (kWh)``,
        ``Field ON (h)``, ``Assemblies``, ``In operation``.
    """
    db_path = db_path or db.DB_PATH
    con = duckdb.connect(db_path, read_only=True)

    energy_query = f"""
        SELECT
            a.housing AS Housing,
            ROUND(SUM(CASE WHEN s.channel = 'energy_j' THEN s.value END) / {J_TO_KWH}, 2) AS "Energy (kWh)",
            ROUND(SUM(CASE WHEN s.channel = 'duration_field_on_s' THEN s.value END) / {S_TO_H}, 2) AS "Field ON (h)"
        FROM experiments AS e
        JOIN assemblies AS a ON a.name = e.assembly_name
        LEFT JOIN exp_run_scalars AS s ON s.experiment_id = e.id
    """
    counts_query = """
        SELECT
            housing AS Housing,
            COUNT(*) AS Assemblies,
            SUM(CASE WHEN status = 'in_operation' THEN 1 ELSE 0 END) AS "In operation"
        FROM assemblies
    """
    params = []
    if assembly_names is not None:
        energy_query += " WHERE a.name = ANY(?)"
        counts_query += " WHERE name = ANY(?)"
        params = [list(assembly_names)]
    energy_query += " GROUP BY a.housing"
    counts_query += " GROUP BY housing"

    energy_df = con.execute(energy_query, params).fetchdf()
    counts_df = con.execute(counts_query, params).fetchdf()
    con.close()

    return counts_df.merge(energy_df, on="Housing", how="left").fillna(0)


def load_housing_summary_by_year(db_path=None):
    """Aggregate total energy and field-on time per housing per year.

    Parameters
    ----------
    db_path : str, optional
        Path to the DuckDB database. Defaults to :data:`db.DB_PATH`.

    Returns
    -------
    :class:`~pandas.DataFrame`
        One row per (Housing, Year), with ``Energy (kWh)`` and
        ``Field ON (h)``.
    """
    db_path = db_path or db.DB_PATH
    con = duckdb.connect(db_path, read_only=True)

    df = con.execute(f"""
        SELECT
            a.housing AS Housing,
            CAST(regexp_extract(e.name, '^(\\d{{4}})', 1) AS INTEGER) AS Year,
            ROUND(SUM(CASE WHEN s.channel = 'energy_j' THEN s.value END) / {J_TO_KWH}, 2) AS "Energy (kWh)",
            ROUND(SUM(CASE WHEN s.channel = 'duration_field_on_s' THEN s.value END) / {S_TO_H}, 2) AS "Field ON (h)"
        FROM experiments AS e
        JOIN assemblies AS a ON a.name = e.assembly_name
        LEFT JOIN exp_run_scalars AS s ON s.experiment_id = e.id
        GROUP BY Housing, Year
        ORDER BY Year
    """).fetchdf()
    con.close()

    return df.fillna(0)


def load_commissioning_history(db_path=None, assemblies_in_year=None):
    """Return assemblies grouped by housing, ordered by commissioning date.

    Parameters
    ----------
    db_path : str, optional
        Path to the DuckDB database. Defaults to :data:`db.DB_PATH`.
    assemblies_in_year : set of str, optional
        Restrict to these assembly names only. Defaults to all assemblies.

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
    if assemblies_in_year is not None:
        df = df[df["Assembly"].isin(assemblies_in_year)]
        if df.empty:
            return {}
    df["Assembly"] = df.apply(assembly_link, axis=1)
    return {housing: group.drop(columns=["Housing"]).to_dict("records") for housing, group in df.groupby("Housing")}


def _field_activity_strip(housing, db_path=None, assembly_names=None, year=None):
    """Build a small CSS strip of per-period activity for one housing.

    One cell per month (or, when *year* is given, per week within that
    year): green = at least one experiment or overview record occurred that
    period, blank = none. A red bar marks a period an assembly was
    commissioned; a black bar marks a year boundary (month mode only).
    """
    history = db.get_field_bin_history(housing, db_path, assembly_names=assembly_names, year=year)
    if not history:
        return html.Div("No commissioning history yet.", style={"color": "#888", "fontStyle": "italic"})

    cells = []
    for row in history:
        start, end = row["period_start"], row["period_end"]
        color, label = ("#2ca02c", "activity") if row["has_activity"] else ("#ffffff", "no activity")
        if year is not None:
            period_desc = f"{start:%b %d} – {end:%b %d} {start.year}"
        else:
            period_desc = f"{_MONTH_LABELS[start.month - 1]} {start.year}"
        cells.append(
            html.Div(
                title=f"{period_desc} — {label}",
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
        if row["commissioned"]:
            cells.append(
                html.Div(
                    title=f"Commissioned: {', '.join(row['commissioned'])}",
                    style={
                        "width": "3px",
                        "height": "18px",
                        "backgroundColor": "#d62728",
                        "display": "inline-block",
                        "marginRight": "1px",
                    },
                )
            )
        if year is None and start.month == 12:
            cells.append(
                html.Div(
                    style={
                        "width": "3px",
                        "height": "18px",
                        "backgroundColor": "#000000",
                        "display": "inline-block",
                        "marginRight": "1px",
                    },
                )
            )
    return html.Div(
        cells,
        style={"whiteSpace": "nowrap", "overflowX": "auto", "padding": "4px 0"},
    )


def _housing_section(housing, summary_row, commissioning_rows, db_path=None, assembly_names=None, year=None):
    """Build one housing's summary card as a collapsible accordion item."""
    energy = summary_row["Energy (kWh)"] if summary_row is not None else 0
    field_on = summary_row["Field ON (h)"] if summary_row is not None else 0
    n_assemblies = int(summary_row["Assemblies"]) if summary_row is not None else 0
    n_in_operation = int(summary_row["In operation"]) if summary_row is not None else 0

    return dbc.AccordionItem(
        [
            html.Div(
                [
                    html.Span(f"Energy: {energy:,.2f} kWh", style={"marginRight": "25px"}),
                    html.Span(f"Magnet time: {field_on:,.2f} h", style={"marginRight": "25px"}),
                    html.Span(f"Assemblies: {n_assemblies} ({n_in_operation} in operation)"),
                ],
                style={"marginBottom": "10px"},
            ),
            html.Label("Commissioning activity by month:", style={"fontSize": "13px", "color": "#555"}),
            _field_activity_strip(housing, db_path, assembly_names, year),
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
        title=housing,
        item_id=housing,
    )


def layout(**kwargs):
    return html.Div(
        [
            html.H1("MagnetDB Dashboard"),
            selectors.aggregate_filter(
                "housing-stats-year-filter", "Year", style={"width": "150px", "marginBottom": "15px"}
            ),
            html.Div(id="housing-stats-summary"),
            dcc.Graph(id="housing-stats-energy-fig"),
            html.Br(),
            dcc.Graph(id="housing-stats-energy-year-fig"),
            html.Br(),
            dcc.Graph(id="housing-stats-field-on-year-fig"),
            html.Br(),
            html.Div(id="housing-stats-sections"),
        ],
        style={"padding": "20px"},
    )


@dash.callback(
    Output("housing-stats-summary", "children"),
    Output("housing-stats-energy-fig", "figure"),
    Output("housing-stats-energy-year-fig", "figure"),
    Output("housing-stats-field-on-year-fig", "figure"),
    Output("housing-stats-sections", "children"),
    Output("housing-stats-year-filter", "options"),
    Input("dd-database", "value"),
    Input("housing-stats-year-filter", "value"),
)
def update_housing_stats(selected_db, selected_year):
    if not selected_db:
        return [], go.Figure(), go.Figure(), go.Figure(), [], [selectors.ALL]

    summary_df = load_housing_summary(selected_db)
    summary_by_year_df = load_housing_summary_by_year(selected_db)
    counts = db.get_db_counts(selected_db)
    housing_order = natsorted(summary_df["Housing"].dropna().unique())

    assemblies_meta = db.load_assemblies_meta(selected_db)
    assemblies_in_year = None
    year_filter = None
    if selected_year and selected_year != selectors.ALL:
        year_filter = int(selected_year)
        assemblies_in_year = db.assemblies_active_in_year(assemblies_meta, year_filter)

    year_range = db.assemblies_year_range(assemblies_meta)
    if year_range is not None:
        year_options = [selectors.ALL] + [str(y) for y in range(year_range[0], year_range[1] + 1)]
    else:
        year_options = [selectors.ALL]

    section_summary_df = (
        load_housing_summary(selected_db, assembly_names=assemblies_in_year)
        if assemblies_in_year is not None
        else summary_df
    )
    commissioning = load_commissioning_history(selected_db, assemblies_in_year)

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
        category_orders={"Housing": housing_order},
        title="Total Energy per Housing",
    )

    fig_energy_year = px.bar(
        summary_by_year_df,
        x="Year",
        y="Energy (kWh)",
        color="Housing",
        color_discrete_map=HOUSING_COLORS,
        category_orders={"Housing": housing_order},
        barmode="group",
        title="Energy per Housing per Year",
    )
    fig_energy_year.update_xaxes(dtick=1, title="Year")

    fig_field_on_year = px.bar(
        summary_by_year_df,
        x="Year",
        y="Field ON (h)",
        color="Housing",
        color_discrete_map=HOUSING_COLORS,
        category_orders={"Housing": housing_order},
        barmode="group",
        title="Magnet Time per Housing per Year (h)",
    )
    fig_field_on_year.update_xaxes(dtick=1, title="Year")

    sections = []
    for housing in housing_order:
        matching_rows = section_summary_df[section_summary_df["Housing"] == housing]
        row = matching_rows.iloc[0] if not matching_rows.empty else None
        sections.append(
            _housing_section(
                housing, row, commissioning.get(housing, []), selected_db, assemblies_in_year, year_filter
            )
        )

    return top_summary, fig, fig_energy_year, fig_field_on_year, dbc.Accordion(sections), year_options
