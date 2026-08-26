import dash
import duckdb
import pandas as pd

from dash import Dash, html, dcc, Input, Output
from dash.dash_table import DataTable

import plotly.express as px
from plotly import graph_objects as go
import magnetdb_analysis as db
from experiment_links import (
    experiment_link,
    overview_record_link,
    magnet_link,
    assembly_link,
)
import dash_selectors as selectors

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
    "Magnet Time (s)",
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


def _housing_sort_key(df):
    """Extract the numeric housing suffix (e.g. 'M10' -> 10) for natural M1..M10 sorting."""
    return df["Housing"].str.extract(r"(\d+)", expand=False).astype(int)


def _adaptive_time_ticks(span_days):
    """Pick a bar-chart x-axis (dtick, tickformat) pair sized to a date span in days."""
    if span_days <= 21:
        return "D1", "%d %b"
    if span_days <= 120:
        return "D7", "%d %b"
    if span_days <= 730:
        return "M1", "%b %Y"
    return "M3", "%b %Y"


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
                ROUND(MAX(CASE WHEN s.channel = 'duration_field_on_s' THEN s.value END), 2) AS "Magnet Time (s)",
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
    df = (
        df.assign(_housing_n=_housing_sort_key(df))
        .sort_values(["_housing_n", "Assembly", "Experiment"])
        .drop(columns="_housing_n")
    )

    con.close()

    return df


def load_overview_records(db_path=None):
    """Load all overview_records rows, joined with their assembly and housing.

    Parameters
    ----------
    db_path : str, optional
        Path to the DuckDB database. Defaults to :data:`db.DB_PATH`.

    Returns
    -------
    :class:`~pandas.DataFrame`
        One row per overview record, with ``Overview Record``, ``Assembly``,
        ``Housing``, ``Mode``, and ``t0`` columns.
    """
    db_path = db_path or db.DB_PATH
    con = duckdb.connect(db_path, read_only=True)

    df = con.execute("""
            SELECT
                filename AS "Overview Record",
                assembly_name AS Assembly,
                housing AS Housing,
                mode AS Mode,
                t0
            FROM overview_records
            WHERE merged_into IS NULL
            ORDER BY t0 NULLS LAST, filename
        """).fetchdf()

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


_TABLE_MARKDOWN_COLUMNS = {"Experiment", "Assembly"}

TABLE_COLUMNS = [
    (
        {"name": c, "id": c, "presentation": "markdown"}
        if c in _TABLE_MARKDOWN_COLUMNS
        else {"name": c, "id": c}
    )
    for c in EXP_RUN_SCALARS_COLUMNS
    if c != "File"
]

OVERVIEW_RECORD_COLUMNS = [
    (
        {"name": c, "id": c, "presentation": "markdown"}
        if c in ("Overview Record", "Assembly")
        else {"name": c, "id": c}
    )
    for c in ("Overview Record", "Assembly", "Housing", "Mode", "t0")
]


def _overview_records_section(overview_df):
    """Build the "Overview records" accordion content for a pre-filtered dataframe.

    Parameters
    ----------
    overview_df : :class:`~pandas.DataFrame`
        Rows from :func:`load_overview_records`, already filtered to the
        page's current Housing/Year/Assembly selection.

    Returns
    -------
    :class:`~dash.html.Div` or :class:`dash.dash_table.DataTable`
        A "no records" message if *overview_df* is empty, otherwise a
        `DataTable` of its rows (linked into ``/overview-records``).
    """
    if overview_df.empty:
        return html.Div(
            "No overview records found for the current filters.",
            style={"color": "#888", "fontStyle": "italic"},
        )

    table_df = overview_df.copy()
    table_df["Overview Record"] = table_df.apply(overview_record_link, axis=1)
    table_df["Assembly"] = table_df.apply(assembly_link, axis=1)

    return DataTable(
        columns=OVERVIEW_RECORD_COLUMNS,
        data=table_df.to_dict("records"),
        page_size=10,
        sort_action="native",
        style_table={"overflowX": "auto"},
        style_cell={"textAlign": "center", "padding": "6px"},
        style_header={"fontWeight": "bold"},
    )


MAGNET_COLUMNS = [
    (
        {"name": c, "id": c, "presentation": "markdown"}
        if c == "Magnet"
        else {"name": c, "id": c}
    )
    for c in ("Magnet", "Type", "Status", "Assembled")
]


def _magnets_section(selected_assembly, db_path):
    """Build the "Magnets" accordion content for the selected assembly.

    Parameters
    ----------
    selected_assembly : str or None
        Assembly name from the page's filter dropdown.
    db_path : str, optional
        Path to the DuckDB database.

    Returns
    -------
    :class:`~dash.html.Div` or :class:`dash.dash_table.DataTable`
        Placeholder text if no assembly is selected, a "no magnets" message
        if the assembly has none, or a `DataTable` of its magnets.
    """
    if not selected_assembly or selected_assembly == selectors.ALL:
        return html.Div(
            "Select an assembly above to see its magnets.",
            style={"color": "#888", "fontStyle": "italic"},
        )

    magnets = db.get_magnets_for_assembly(selected_assembly, db_path)
    if not magnets:
        return html.Div(
            f"No magnets found for {selected_assembly}.",
            style={"color": "#888", "fontStyle": "italic"},
        )

    table_df = pd.DataFrame(magnets).rename(
        columns={
            "name": "Magnet",
            "type": "Type",
            "status": "Status",
            "assembled_at": "Assembled",
        }
    )
    table_df["Magnet"] = table_df.apply(magnet_link, axis=1)

    return DataTable(
        columns=MAGNET_COLUMNS,
        data=table_df.to_dict("records"),
        page_size=10,
        sort_action="native",
        style_table={"overflowX": "auto"},
        style_cell={"textAlign": "center", "padding": "6px"},
        style_header={"fontWeight": "bold"},
    )


def _build_page_content(
    df,
    total_assemblies,
    assemblies_in_operation,
    selected_assembly=None,
    selected_housing=None,
    selected_year=None,
    assemblies_meta=None,
    db_path=None,
):
    """Build the figures, table rows, and summary text for a loaded experiments dataframe."""
    housing_order = sorted(df["Housing"].dropna().unique(), key=lambda h: int(h[1:]))

    fig_per_exp = px.bar(
        df.sort_values("Experiment"),
        x="Experiment",
        y="Energy (kWh)",
        color="Housing",
        color_discrete_map={"M9": "red", "M10": "blue"},
        category_orders={"Housing": housing_order},
        hover_data=["Assembly"],
        title="Energy per Experiment",
    )

    x_range = None
    dtick, tickformat = "M1", "%b %Y"
    bar_width_ms = 1000 * 60 * 60 * 24
    if selected_assembly and selected_assembly != selectors.ALL:
        bar_width_ms *= 0.3
    if (
        selected_assembly
        and selected_assembly != selectors.ALL
        and assemblies_meta is not None
    ):
        match = assemblies_meta.loc[assemblies_meta["Assembly"] == selected_assembly]
        if not match.empty:
            range_start = db.to_display_tz(match["Commissioned"].iloc[0])
            range_end = db.to_display_tz(match["Decommissioned"].iloc[0])
            if pd.isna(range_end):
                range_end = pd.Timestamp.now()
            if selected_year and selected_year != selectors.ALL:
                year = int(selected_year)
                range_start = max(range_start, pd.Timestamp(f"{year}-01-01"))
                range_end = min(range_end, pd.Timestamp(f"{year}-12-31"))
            x_range = [range_start, range_end]
            dtick, tickformat = _adaptive_time_ticks((range_end - range_start).days)

    fig_per_exp.update_xaxes(
        tickformat=tickformat, dtick=dtick, title="Experiment Date", range=x_range
    )

    fig_per_exp.update_traces(width=bar_width_ms)

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
        category_orders={
            "Assembly": energy_by_assembly["Assembly"].tolist(),
            "Housing": housing_order,
        },
        title="Energy per Assembly",
    )

    field_on_by_assembly = df.groupby(["Assembly", "Housing"], as_index=False).agg(
        {"Magnet Time (s)": "sum", "Commissioned": "min"}
    )
    field_on_by_assembly = field_on_by_assembly.sort_values("Commissioned")
    field_on_by_assembly["Time (h)"] = field_on_by_assembly["Magnet Time (s)"] / S_TO_H

    fig_field_on = px.bar(
        field_on_by_assembly,
        x="Assembly",
        y="Time (h)",
        color="Housing",
        color_discrete_map={"M9": "red", "M10": "blue"},
        category_orders={
            "Assembly": field_on_by_assembly["Assembly"].tolist(),
            "Housing": housing_order,
        },
        title="Magnet Time per Assembly (h)",
    )

    table_df = df.drop(columns=["File"])
    table_df["Experiment"] = df.apply(experiment_link, axis=1)
    table_df["Assembly"] = df.apply(assembly_link, axis=1)

    if selected_assembly and selected_assembly != selectors.ALL:
        assemblies_line = f"Assemblies: 1 selected of {total_assemblies}"
    elif (selected_housing and selected_housing != selectors.ALL) or (
        selected_year and selected_year != selectors.ALL
    ):
        assemblies_line = (
            f"Assemblies: {df['Assembly'].nunique()} selected of {total_assemblies}"
        )
    else:
        assemblies_line = f"Assemblies: {total_assemblies}"
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
        table_df.to_dict("records"),
        summary,
    )


def layout(assembly=None, **kwargs):
    return html.Div(
        [
            html.H1("MagnetDB Dashboard"),
            html.Div(
                [
                    selectors.aggregate_filter(
                        "assembly-stats-housing-filter",
                        "Housing",
                        options=db.get_housings(),
                        style={"width": "250px"},
                    ),
                    selectors.aggregate_filter(
                        "assembly-stats-year-filter",
                        "Year",
                        style={"width": "150px"},
                    ),
                    selectors.aggregate_filter(
                        "assembly-stats-assembly-filter",
                        "Assembly",
                        style={"width": "400px"},
                        value=assembly,
                    ),
                ],
                style={"display": "flex", "gap": "30px", "marginBottom": "15px"},
            ),
            html.Div(
                id="assembly-stats-missing-banner",
                style={"color": "#a94442", "fontWeight": "bold"},
            ),
            html.Div(id="assembly-stats-summary"),
            html.Br(),
            dcc.Graph(id="fig-per-exp"),
            html.Br(),
            dcc.Graph(id="fig-per-assembly"),
            html.Br(),
            dcc.Graph(id="fig-field-on"),
            html.Br(),
            html.Details(
                [
                    html.Summary(
                        "🧲 Magnets",
                        style={"fontWeight": "bold", "cursor": "pointer"},
                    ),
                    html.Div(id="assembly-stats-magnets", style={"padding": "10px"}),
                ],
                open=False,
                style={
                    "border": "1px solid #ddd",
                    "borderRadius": "8px",
                    "marginBottom": "20px",
                },
            ),
            html.Br(),
            html.Details(
                [
                    html.Summary(
                        "📁 Overview records",
                        style={"fontWeight": "bold", "cursor": "pointer"},
                    ),
                    html.Div(
                        id="assembly-stats-overview-records", style={"padding": "10px"}
                    ),
                ],
                open=False,
                style={
                    "border": "1px solid #ddd",
                    "borderRadius": "8px",
                    "marginBottom": "20px",
                },
            ),
            html.Br(),
            html.Details(
                [
                    html.Summary(
                        "📊 Experiments table",
                        style={"fontWeight": "bold", "cursor": "pointer"},
                    ),
                    html.Div(
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
        ],
        style={"padding": "20px"},
    )


@dash.callback(
    Output("fig-per-exp", "figure"),
    Output("fig-per-assembly", "figure"),
    Output("fig-per-assembly", "style"),
    Output("fig-field-on", "figure"),
    Output("fig-field-on", "style"),
    Output("assembly-stats-table", "data"),
    Output("assembly-stats-summary", "children"),
    Output("assembly-stats-assembly-filter", "options"),
    Output("assembly-stats-housing-filter", "options"),
    Output("assembly-stats-year-filter", "options"),
    Output("assembly-stats-missing-banner", "children"),
    Output("assembly-stats-overview-records", "children"),
    Output("assembly-stats-magnets", "children"),
    Input("dd-database", "value"),
    Input("assembly-stats-housing-filter", "value"),
    Input("assembly-stats-year-filter", "value"),
    Input("assembly-stats-assembly-filter", "value"),
)
def update_assembly_stats(
    selected_db, selected_housing, selected_year, selected_assembly
):
    if not selected_db:
        return (
            go.Figure(),
            go.Figure(),
            {},
            go.Figure(),
            {},
            [],
            [],
            [],
            [],
            [],
            "",
            "",
            "",
        )

    df = load_data(selected_db)
    all_assemblies = db.get_all_assemblies(selected_db)
    assemblies_meta = db.load_assemblies_meta(selected_db)

    assemblies_in_year = None
    if selected_year and selected_year != selectors.ALL:
        assemblies_in_year = db.assemblies_active_in_year(
            assemblies_meta, int(selected_year)
        )

    year_range = db.assemblies_year_range(assemblies_meta)
    if year_range is not None:
        year_options = [selectors.ALL] + [
            str(y) for y in range(year_range[0], year_range[1] + 1)
        ]
    else:
        year_options = [selectors.ALL]

    assembly_options = [selectors.ALL] + [
        a
        for a in all_assemblies
        if (
            not selected_housing
            or selected_housing == selectors.ALL
            or a.startswith(f"{selected_housing}_")
        )
        and (assemblies_in_year is None or a in assemblies_in_year)
    ]
    housing_options = [selectors.ALL] + db.get_housings(selected_db)
    total_assemblies, assemblies_in_operation = load_assembly_summary(selected_db)
    missing_banner = (
        "" if not df.empty else "No experiment data found for this database."
    )

    plot_df = df
    if selected_housing and selected_housing != selectors.ALL:
        plot_df = plot_df[plot_df["Housing"] == selected_housing]
    if assemblies_in_year is not None:
        plot_df = plot_df[plot_df["Assembly"].isin(assemblies_in_year)]
    if selected_assembly != selectors.ALL:
        plot_df = plot_df[plot_df["Assembly"] == selected_assembly]
    fig_per_assembly_style = (
        {"display": "none"} if selected_assembly != selectors.ALL else {}
    )

    overview_plot_df = load_overview_records(selected_db)
    if selected_housing and selected_housing != selectors.ALL:
        overview_plot_df = overview_plot_df[
            overview_plot_df["Housing"] == selected_housing
        ]
    if assemblies_in_year is not None:
        overview_plot_df = overview_plot_df[
            overview_plot_df["Assembly"].isin(assemblies_in_year)
        ]
    if selected_assembly != selectors.ALL:
        overview_plot_df = overview_plot_df[
            overview_plot_df["Assembly"] == selected_assembly
        ]

    (
        fig_per_exp,
        fig_per_assembly,
        fig_field_on,
        table_records,
        summary,
    ) = _build_page_content(
        plot_df,
        total_assemblies,
        assemblies_in_operation,
        selected_assembly,
        selected_housing,
        selected_year,
        assemblies_meta,
        selected_db,
    )
    overview_records_section = _overview_records_section(overview_plot_df)
    magnets_section = _magnets_section(selected_assembly, selected_db)
    return (
        fig_per_exp,
        fig_per_assembly,
        fig_per_assembly_style,
        fig_field_on,
        fig_per_assembly_style,
        table_records,
        summary,
        assembly_options,
        housing_options,
        year_options,
        missing_banner,
        overview_records_section,
        magnets_section,
    )


@dash.callback(
    Output("assembly-stats-housing-filter", "value"),
    Input("assembly-stats-assembly-filter", "value"),
)
def sync_housing_from_assembly(selected_assembly):
    if not selected_assembly or selected_assembly == selectors.ALL:
        return dash.no_update
    return selected_assembly.split("_")[0]
