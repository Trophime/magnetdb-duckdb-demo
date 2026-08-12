import dash
import duckdb
import pandas as pd

from dash import Dash, html, dcc, Input, Output
from dash.dash_table import DataTable

import plotly.express as px
from plotly import graph_objects as go
import magnetdb_analysis as db
from experiment_links import experiment_link

# --- 1. ENREGISTREMENT ET LAYOUT DASH ---
dash.register_page(__name__, path="/", name="Assembly stats", order=1)


J_TO_KWH = 3.6e6
S_TO_H = 3600

EXP_RUN_SCALARS_COLUMNS = [
    "ID",
    "Experiment",
    "Site",
    "File",
    "Energy (kWh)",
    "Extracted heat (kWh)",
    "Duration (s)",
    "Field ON (s)",
    "Status",
    "Housing",
]


def _warn_exp_run_scalars(reason: str, db_path: str) -> None:
    print(
        f"[site_stats] Table 'exp_run_scalars' {reason}.\n"
        "  Populate it by running, for each site:\n"
        "    to_duckdb/venv-systempackages/bin/python3 to_duckdb/compute_exp_stats.py "
        f"--db {db_path} --site <SITE_NAME>"
    )


def load_data(db_path=None):
    """Load per-experiment energy stats joined with site commissioning dates.

    Parameters
    ----------
    db_path : str, optional
        Path to the DuckDB database. Defaults to :data:`db.DB_PATH`.

    Returns
    -------
    :class:`~pandas.DataFrame`
        One row per experiment, with columns matching
        ``EXP_RUN_SCALARS_COLUMNS`` plus ``Housing`` and ``Commissioned``.
    """
    db_path = db_path or db.DB_PATH
    con = duckdb.connect(db_path, read_only=True)

    tables = (
        con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        )
        .df()["table_name"]
        .tolist()
    )

    if "exp_run_scalars" not in tables:
        con.close()
        _warn_exp_run_scalars("does not exist", db_path)
        return pd.DataFrame(columns=EXP_RUN_SCALARS_COLUMNS)

    n_scalars = con.execute("SELECT COUNT(*) FROM exp_run_scalars").fetchone()[0]
    if n_scalars == 0:
        _warn_exp_run_scalars("is empty", db_path)

    df = con.execute(f"""
            SELECT
                e.id AS ID, e.name AS Experiment, e.site_name AS Site, e.file AS File,
                ROUND(MAX(CASE WHEN s.channel = 'energy_j' THEN s.value END) / {J_TO_KWH}, 7) AS "Energy (kWh)",
                ROUND(MAX(CASE WHEN s.channel = 'heat_extracted_j' THEN s.value END) / {J_TO_KWH}, 2) AS "Extracted heat (kWh)",
                ROUND(MAX(CASE WHEN s.channel = 'duration_s' THEN s.value END), 2) AS "Duration (s)",
                ROUND(MAX(CASE WHEN s.channel = 'duration_field_on_s' THEN s.value END), 2) AS "Field ON (s)",
            e.status AS Status,
            st.commissioned_at AS Commissioned
            FROM experiments AS e
            LEFT JOIN exp_run_scalars AS s ON e.id = s.experiment_id
            LEFT JOIN sites AS st ON e.site_name = st.name
            GROUP BY e.id, e.name, e.site_name, e.file, e.status, st.commissioned_at
            ORDER BY e.site_name, e.name
        """).fetchdf()

    df["Experiment"] = pd.to_datetime(df["Experiment"])
    df["Housing"] = df["Site"].str.extract(r"^(M\d+)")

    con.close()

    return df


def load_site_summary(db_path=None):
    """Count total sites and sites currently in operation.

    Parameters
    ----------
    db_path : str, optional
        Path to the DuckDB database. Defaults to :data:`db.DB_PATH`.

    Returns
    -------
    tuple of int
        ``(total_sites, sites_in_operation)``.
    """
    db_path = db_path or db.DB_PATH
    con = duckdb.connect(db_path, read_only=True)
    total_sites, sites_in_operation = con.execute(
        "SELECT COUNT(*), SUM(CASE WHEN status = 'in_operation' THEN 1 ELSE 0 END) FROM sites"
    ).fetchone()
    con.close()
    return total_sites, sites_in_operation or 0


TABLE_COLUMNS = [
    (
        {"name": c, "id": c, "presentation": "markdown"}
        if c == "Experiment"
        else {"name": c, "id": c}
    )
    for c in EXP_RUN_SCALARS_COLUMNS
    if c != "File"
]


def _build_page_content(df, total_sites, sites_in_operation):
    """Build the figures, table rows, and summary text for a loaded experiments dataframe."""
    fig_per_exp = px.bar(
        df.sort_values("Experiment"),
        x="Experiment",
        y="Energy (kWh)",
        color="Housing",
        color_discrete_map={"M9": "red", "M10": "blue"},
        hover_data=["Site"],
        title="Energy per Experiment",
    )

    fig_per_exp.update_xaxes(tickformat="%b %Y", dtick="M1", title="Experiment Date")

    fig_per_exp.update_traces(width=1000 * 60 * 60 * 24)

    energy_by_site = df.groupby(["Site", "Housing"], as_index=False).agg(
        {"Energy (kWh)": "sum", "Commissioned": "min"}
    )
    energy_by_site = energy_by_site.sort_values("Commissioned")

    fig_per_site = px.bar(
        energy_by_site,
        x="Site",
        y="Energy (kWh)",
        color="Housing",
        color_discrete_map={"M9": "red", "M10": "blue"},
        category_orders={"Site": energy_by_site["Site"].tolist()},
        title="Energy per Site",
    )

    field_on_by_site = df.groupby(["Site", "Housing"], as_index=False).agg(
        {"Field ON (s)": "sum", "Commissioned": "min"}
    )
    field_on_by_site = field_on_by_site.sort_values("Commissioned")
    field_on_by_site["Field ON (h)"] = field_on_by_site["Field ON (s)"] / S_TO_H

    fig_field_on = px.bar(
        field_on_by_site,
        x="Site",
        y="Field ON (h)",
        color="Housing",
        color_discrete_map={"M9": "red", "M10": "blue"},
        category_orders={"Site": field_on_by_site["Site"].tolist()},
        title="Magnet Time per Site (h)",
    )

    df["Year"] = df["Experiment"].dt.year

    energy_by_housing_year = df.groupby(["Year", "Housing"], as_index=False)[
        "Energy (kWh)"
    ].sum()
    energy_by_housing_year = energy_by_housing_year.sort_values("Year")

    fig_energy_year = px.bar(
        energy_by_housing_year,
        x="Year",
        y="Energy (kWh)",
        color="Housing",
        color_discrete_map={"M9": "red", "M10": "blue"},
        barmode="group",
        title="Energy per Housing per Year",
    )
    fig_energy_year.update_xaxes(dtick=1, title="Year")

    field_on_by_housing_year = df.groupby(["Year", "Housing"], as_index=False)[
        "Field ON (s)"
    ].sum()
    field_on_by_housing_year = field_on_by_housing_year.sort_values("Year")
    field_on_by_housing_year["Field ON (h)"] = (
        field_on_by_housing_year["Field ON (s)"] / S_TO_H
    )

    fig_field_on_year = px.bar(
        field_on_by_housing_year,
        x="Year",
        y="Field ON (h)",
        color="Housing",
        color_discrete_map={"M9": "red", "M10": "blue"},
        barmode="group",
        title="Magnet Time per Housing per Year (h)",
    )
    fig_field_on_year.update_xaxes(dtick=1, title="Year")

    table_df = df.drop(columns=["File"])
    table_df["Experiment"] = df.apply(experiment_link, axis=1)

    summary = [
        html.B(f"Sites: {total_sites}"),
        html.Br(),
        f"In operation: {sites_in_operation}",
        html.Br(),
        html.B(f"Experiments: {len(df)}"),
        html.Br(),
        f"Processed: {(df['Status'] == 'STATS DONE').sum()}",
    ]

    return (
        fig_per_exp,
        fig_per_site,
        fig_field_on,
        fig_energy_year,
        fig_field_on_year,
        table_df.to_dict("records"),
        summary,
    )


def layout(**kwargs):
    return html.Div(
        [
            html.H1("MagnetDB Dashboard"),
            dcc.Dropdown(
                id="site-stats-site-filter",
                options=[],
                value=None,
                placeholder="Filter by site...",
                clearable=True,
                style={"width": "400px", "marginBottom": "15px"},
            ),
            html.Div(id="site-stats-summary"),
            html.Br(),
            dcc.Graph(id="fig-per-exp"),
            html.Br(),
            dcc.Graph(id="fig-per-site"),
            html.Br(),
            dcc.Graph(id="fig-field-on"),
            html.Br(),
            dcc.Graph(id="fig-energy-year"),
            html.Br(),
            dcc.Graph(id="fig-field-on-year"),
            html.Br(),
            DataTable(
                id="site-stats-table",
                columns=TABLE_COLUMNS,
                data=[],
                page_size=20,
                sort_action="native",
                style_table={"overflowX": "auto"},
                style_cell={"textAlign": "center", "padding": "6px"},
                style_header={"fontWeight": "auto"},
            ),
        ],
        style={"padding": "20px"},
    )


@dash.callback(
    Output("fig-per-exp", "figure"),
    Output("fig-per-site", "figure"),
    Output("fig-per-site", "style"),
    Output("fig-field-on", "figure"),
    Output("fig-field-on", "style"),
    Output("fig-energy-year", "figure"),
    Output("fig-field-on-year", "figure"),
    Output("site-stats-table", "data"),
    Output("site-stats-summary", "children"),
    Output("site-stats-site-filter", "options"),
    Input("dd-database", "value"),
    Input("site-stats-site-filter", "value"),
)
def update_site_stats(selected_db, selected_site):
    if not selected_db:
        return (
            go.Figure(),
            go.Figure(),
            {},
            go.Figure(),
            {},
            go.Figure(),
            go.Figure(),
            [],
            [],
            [],
        )

    df = load_data(selected_db)
    site_options = sorted(df["Site"].unique())
    total_sites, sites_in_operation = load_site_summary(selected_db)

    plot_df = df[df["Site"] == selected_site] if selected_site else df
    fig_per_site_style = {"display": "none"} if selected_site else {}

    (
        fig_per_exp,
        fig_per_site,
        fig_field_on,
        fig_energy_year,
        fig_field_on_year,
        table_records,
        summary,
    ) = _build_page_content(plot_df, total_sites, sites_in_operation)
    return (
        fig_per_exp,
        fig_per_site,
        fig_per_site_style,
        fig_field_on,
        fig_per_site_style,
        fig_energy_year,
        fig_field_on_year,
        table_records,
        summary,
        site_options,
    )
