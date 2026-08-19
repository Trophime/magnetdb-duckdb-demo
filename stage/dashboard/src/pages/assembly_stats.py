import dash
import duckdb
import pandas as pd

from dash import Dash, html, dcc, Input, Output
from dash.dash_table import DataTable

import plotly.express as px
from plotly import graph_objects as go
import magnetdb_analysis as db
from experiment_links import experiment_link, overview_record_link

# --- 1. ENREGISTREMENT ET LAYOUT DASH ---
dash.register_page(__name__, path="/assembly_stats", name="Assembly stats", order=2)


J_TO_KWH = 3.6e6
S_TO_H = 3600

EXP_RUN_SCALARS_COLUMNS = [
    "ID",
    "Experiment",
    "Assembly",
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
        f"[assembly_stats] Table 'exp_run_scalars' {reason}.\n"
        "  Populate it by running, for each assembly:\n"
        "    to_duckdb/venv-systempackages/bin/python3 to_duckdb/compute_exp_stats.py "
        f"--db {db_path} --assembly <ASSEMBLY_NAME>"
    )


def load_data(db_path=None):
    """Load per-experiment energy stats joined with assembly commissioning dates.

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
                e.id AS ID, e.name AS Experiment, e.assembly_name AS Assembly, e.file AS File,
                ROUND(MAX(CASE WHEN s.channel = 'energy_j' THEN s.value END) / {J_TO_KWH}, 7) AS "Energy (kWh)",
                ROUND(MAX(CASE WHEN s.channel = 'heat_extracted_j' THEN s.value END) / {J_TO_KWH}, 2) AS "Extracted heat (kWh)",
                ROUND(MAX(CASE WHEN s.channel = 'duration_s' THEN s.value END), 2) AS "Duration (s)",
                ROUND(MAX(CASE WHEN s.channel = 'duration_field_on_s' THEN s.value END), 2) AS "Field ON (s)",
            e.status AS Status,
            st.commissioned_at AS Commissioned
            FROM experiments AS e
            LEFT JOIN exp_run_scalars AS s ON e.id = s.experiment_id
            LEFT JOIN assemblies AS st ON e.assembly_name = st.name
            GROUP BY e.id, e.name, e.assembly_name, e.file, e.status, st.commissioned_at
            ORDER BY e.assembly_name, e.name
        """).fetchdf()

    df["Experiment"] = pd.to_datetime(df["Experiment"])
    df["Housing"] = df["Assembly"].str.extract(r"^(M\d+)")

    con.close()

    return df


def load_assembly_summary(db_path=None):
    """Count total assemblies and assemblies currently in operation.

    Parameters
    ----------
    db_path : str, optional
        Path to the DuckDB database. Defaults to :data:`db.DB_PATH`.

    Returns
    -------
    tuple of int
        ``(total_assemblies, assemblies_in_operation)``.
    """
    db_path = db_path or db.DB_PATH
    con = duckdb.connect(db_path, read_only=True)
    total_assemblies, assemblies_in_operation = con.execute(
        "SELECT COUNT(*), SUM(CASE WHEN status = 'in_operation' THEN 1 ELSE 0 END) FROM assemblies"
    ).fetchone()
    con.close()
    return total_assemblies, assemblies_in_operation or 0


TABLE_COLUMNS = [
    (
        {"name": c, "id": c, "presentation": "markdown"}
        if c == "Experiment"
        else {"name": c, "id": c}
    )
    for c in EXP_RUN_SCALARS_COLUMNS
    if c != "File"
]

OVERVIEW_RECORD_COLUMNS = [
    {"name": c, "id": c, "presentation": "markdown"} if c == "Overview Record" else {"name": c, "id": c}
    for c in ("Overview Record", "Housing", "Mode", "t0")
]


def _overview_records_section(selected_assembly, db_path):
    """Build the "Overview records" accordion for the selected assembly.

    Parameters
    ----------
    selected_assembly : str or None
        Assembly name from the page's filter dropdown.
    db_path : str, optional
        Path to the DuckDB database.

    Returns
    -------
    :class:`~dash.html.Div`
        Placeholder text if no assembly is selected, a "no records" message
        if the assembly has none, or a `DataTable` of its overview records
        (linked into ``/overview-records``) otherwise.
    """
    if not selected_assembly:
        return html.Div(
            "Select an assembly above to see its overview records.",
            style={"color": "#888", "fontStyle": "italic"},
        )

    records = db.get_overview_records_for_assembly(selected_assembly, db_path)
    if not records:
        return html.Div(
            f"No overview records found for {selected_assembly}.",
            style={"color": "#888", "fontStyle": "italic"},
        )

    table_df = pd.DataFrame(records).rename(columns={"filename": "Overview Record", "housing": "Housing", "mode": "Mode"})
    table_df["Assembly"] = selected_assembly
    table_df["Overview Record"] = table_df.apply(overview_record_link, axis=1)

    return DataTable(
        columns=OVERVIEW_RECORD_COLUMNS,
        data=table_df[["Overview Record", "Housing", "Mode", "t0"]].to_dict("records"),
        page_size=10,
        sort_action="native",
        style_table={"overflowX": "auto"},
        style_cell={"textAlign": "center", "padding": "6px"},
        style_header={"fontWeight": "bold"},
    )


def _build_page_content(df, total_assemblies, assemblies_in_operation, selected_assembly=None, db_path=None):
    """Build the figures, table rows, and summary text for a loaded experiments dataframe."""
    fig_per_exp = px.bar(
        df.sort_values("Experiment"),
        x="Experiment",
        y="Energy (kWh)",
        color="Housing",
        color_discrete_map={"M9": "red", "M10": "blue"},
        hover_data=["Assembly"],
        title="Energy per Experiment",
    )

    fig_per_exp.update_xaxes(tickformat="%b %Y", dtick="M1", title="Experiment Date")

    fig_per_exp.update_traces(width=1000 * 60 * 60 * 24)

    energy_by_assembly = df.groupby(["Assembly", "Housing"], as_index=False).agg(
        {"Energy (kWh)": "sum", "Commissioned": "min"}
    )
    energy_by_assembly = energy_by_assembly.sort_values("Commissioned")

    fig_per_assembly = px.bar(
        energy_by_assembly,
        x="Assembly",
        y="Energy (kWh)",
        color="Housing",
        color_discrete_map={"M9": "red", "M10": "blue"},
        category_orders={"Assembly": energy_by_assembly["Assembly"].tolist()},
        title="Energy per Assembly",
    )

    field_on_by_assembly = df.groupby(["Assembly", "Housing"], as_index=False).agg(
        {"Field ON (s)": "sum", "Commissioned": "min"}
    )
    field_on_by_assembly = field_on_by_assembly.sort_values("Commissioned")
    field_on_by_assembly["Field ON (h)"] = field_on_by_assembly["Field ON (s)"] / S_TO_H

    fig_field_on = px.bar(
        field_on_by_assembly,
        x="Assembly",
        y="Field ON (h)",
        color="Housing",
        color_discrete_map={"M9": "red", "M10": "blue"},
        category_orders={"Assembly": field_on_by_assembly["Assembly"].tolist()},
        title="Magnet Time per Assembly (h)",
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

    assemblies_line = (
        f"Assemblies: 1 selected of {total_assemblies}" if selected_assembly else f"Assemblies: {total_assemblies}"
    )
    counts = db.get_db_counts(db_path)
    summary = [
        html.B(assemblies_line),
        html.Br(),
        f"In operation: {assemblies_in_operation}",
        html.Br(),
        html.B(f"Experiments: {len(df)}"),
        html.Br(),
        f"Processed: {(df['Status'] == 'STATS DONE').sum()}",
        html.Br(),
        html.B(
            f"DB-wide: {counts['magnets']} magnets, {counts['parts']} parts, "
            f"{counts['overview_records']} overview records"
        ),
    ]

    return (
        fig_per_exp,
        fig_per_assembly,
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
                id="assembly-stats-assembly-filter",
                options=[],
                value=None,
                placeholder="Filter by assembly...",
                clearable=True,
                style={"width": "400px", "marginBottom": "15px"},
            ),
            html.Div(id="assembly-stats-missing-banner", style={"color": "#a94442", "fontWeight": "bold"}),
            html.Div(id="assembly-stats-summary"),
            html.Br(),
            html.Details(
                [
                    html.Summary("📁 Overview records", style={"fontWeight": "bold", "cursor": "pointer"}),
                    html.Div(id="assembly-stats-overview-records", style={"padding": "10px"}),
                ],
                open=False,
                style={"border": "1px solid #ddd", "borderRadius": "8px", "marginBottom": "20px"},
            ),
            html.Br(),
            dcc.Graph(id="fig-per-exp"),
            html.Br(),
            dcc.Graph(id="fig-per-assembly"),
            html.Br(),
            dcc.Graph(id="fig-field-on"),
            html.Br(),
            dcc.Graph(id="fig-energy-year"),
            html.Br(),
            dcc.Graph(id="fig-field-on-year"),
            html.Br(),
            DataTable(
                id="assembly-stats-table",
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
    Output("fig-per-assembly", "figure"),
    Output("fig-per-assembly", "style"),
    Output("fig-field-on", "figure"),
    Output("fig-field-on", "style"),
    Output("fig-energy-year", "figure"),
    Output("fig-field-on-year", "figure"),
    Output("assembly-stats-table", "data"),
    Output("assembly-stats-summary", "children"),
    Output("assembly-stats-assembly-filter", "options"),
    Output("assembly-stats-missing-banner", "children"),
    Output("assembly-stats-overview-records", "children"),
    Input("dd-database", "value"),
    Input("assembly-stats-assembly-filter", "value"),
)
def update_assembly_stats(selected_db, selected_assembly):
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
            "",
            "",
        )

    df = load_data(selected_db)
    assembly_options = sorted(df["Assembly"].unique())
    total_assemblies, assemblies_in_operation = load_assembly_summary(selected_db)
    missing_banner = "" if not df.empty else "No experiment data found for this database."

    plot_df = df[df["Assembly"] == selected_assembly] if selected_assembly else df
    fig_per_assembly_style = {"display": "none"} if selected_assembly else {}

    (
        fig_per_exp,
        fig_per_assembly,
        fig_field_on,
        fig_energy_year,
        fig_field_on_year,
        table_records,
        summary,
    ) = _build_page_content(plot_df, total_assemblies, assemblies_in_operation, selected_assembly, selected_db)
    overview_records_section = _overview_records_section(selected_assembly, selected_db)
    return (
        fig_per_exp,
        fig_per_assembly,
        fig_per_assembly_style,
        fig_field_on,
        fig_per_assembly_style,
        fig_energy_year,
        fig_field_on_year,
        table_records,
        summary,
        assembly_options,
        missing_banner,
        overview_records_section,
    )
