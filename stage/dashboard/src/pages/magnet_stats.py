import dash
import duckdb
import pandas as pd

from dash import Dash, html, dcc, Input, Output
from dash.dash_table import DataTable

import plotly.express as px
from plotly import graph_objects as go
import magnetdb_analysis as db
from experiment_links import experiment_link, overview_record_link, part_link
import dash_selectors as selectors

# --- 1. ENREGISTREMENT ET LAYOUT DASH ---
dash.register_page(__name__, path="/magnet_stats", name="Magnet stats", order=3)


J_TO_KWH = 3.6e6
S_TO_H = 3600

EXP_RUN_SCALARS_COLUMNS = [
    "ID",
    "Experiment",
    "Magnet",
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
        f"[magnet_stats] Table 'exp_run_scalars' {reason}.\n"
        "  Populate it by running, for each assembly:\n"
        "    to_duckdb/venv-systempackages/bin/python3 to_duckdb/compute_exp_stats.py "
        f"--db {db_path} --assembly <ASSEMBLY_NAME>"
    )


def load_data(db_path=None):
    """Load per-experiment energy stats joined with each experiment's magnets.

    Magnets are not a direct column on ``experiments``: each experiment runs
    on an assembly, and ``assembly_magnets`` links that assembly to the magnet(s) mounted
    on it (typically an insert and a bitters magnet run together). Joining
    through it fans one experiment row out into one row per magnet.

    Parameters
    ----------
    db_path : str, optional
        Path to the DuckDB database. Defaults to :data:`db.DB_PATH`.

    Returns
    -------
    :class:`~pandas.DataFrame`
        One row per (experiment, magnet) pair, with columns matching
        ``EXP_RUN_SCALARS_COLUMNS`` plus ``Housing``.
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
                e.id AS ID, e.name AS Experiment, sm.magnet_name AS Magnet,
                e.assembly_name AS Assembly, e.file AS File,
                ROUND(MAX(CASE WHEN s.channel = 'energy_j' THEN s.value END) / {J_TO_KWH}, 7) AS "Energy (kWh)",
                ROUND(MAX(CASE WHEN s.channel = 'heat_extracted_j' THEN s.value END) / {J_TO_KWH}, 2) AS "Extracted heat (kWh)",
                ROUND(MAX(CASE WHEN s.channel = 'duration_s' THEN s.value END), 2) AS "Duration (s)",
                ROUND(MAX(CASE WHEN s.channel = 'duration_field_on_s' THEN s.value END), 2) AS "Field ON (s)",
            e.status AS Status
            FROM experiments AS e
            JOIN assembly_magnets AS sm ON e.assembly_name = sm.assembly_name
            LEFT JOIN exp_run_scalars AS s ON e.id = s.experiment_id
            GROUP BY e.id, e.name, sm.magnet_name, e.assembly_name, e.file, e.status
            ORDER BY sm.magnet_name, e.name
        """).fetchdf()

    df["Experiment"] = pd.to_datetime(df["Experiment"])
    df["Housing"] = df["Assembly"].str.extract(r"^(M\d+)")

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
    (
        {"name": c, "id": c, "presentation": "markdown"}
        if c == "Overview Record"
        else {"name": c, "id": c}
    )
    for c in ("Overview Record", "Assembly", "Housing", "Mode", "t0")
]

ASSEMBLY_HISTORY_COLUMNS = [
    {"name": c, "id": c}
    for c in (
        "assembly_name",
        "housing",
        "status",
        "commissioned_at",
        "decommissioned_at",
    )
]


def _overview_records_section(overview_df):
    """Build the "Overview records" accordion content for a pre-filtered dataframe.

    Parameters
    ----------
    overview_df : :class:`~pandas.DataFrame`
        Rows from :func:`load_overview_records`, already filtered to the
        page's current magnet selection.

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

    return DataTable(
        columns=OVERVIEW_RECORD_COLUMNS,
        data=table_df.to_dict("records"),
        page_size=10,
        sort_action="native",
        style_table={"overflowX": "auto"},
        style_cell={"textAlign": "center", "padding": "6px"},
        style_header={"fontWeight": "bold"},
    )


def _assembly_history_section(selected_magnet, history):
    """Build the "Assembly history" accordion for the selected magnet, ascending by commissioning date."""
    if not selected_magnet or selected_magnet == selectors.ALL:
        return html.Div(
            "Select a magnet above to see its assembly history.",
            style={"color": "#888", "fontStyle": "italic"},
        )

    if not history:
        return html.Div(
            f"No assembly history found for {selected_magnet}.",
            style={"color": "#888", "fontStyle": "italic"},
        )

    return DataTable(
        columns=ASSEMBLY_HISTORY_COLUMNS,
        data=history,
        page_size=10,
        sort_action="native",
        style_table={"overflowX": "auto"},
        style_cell={"textAlign": "center", "padding": "6px"},
        style_header={"fontWeight": "bold"},
    )


PART_COLUMNS = [
    (
        {"name": c, "id": c, "presentation": "markdown"}
        if c == "Part"
        else {"name": c, "id": c}
    )
    for c in ("Part", "Type", "Status", "Material", "Manufactured")
]


def _parts_section(selected_magnet, db_path):
    """Build the "Parts" accordion content for the selected magnet.

    Parameters
    ----------
    selected_magnet : str or None
        Magnet name from the page's filter dropdown.
    db_path : str, optional
        Path to the DuckDB database.

    Returns
    -------
    :class:`~dash.html.Div` or :class:`dash.dash_table.DataTable`
        Placeholder text if no magnet is selected, a "no parts" message if
        the magnet has none, or a `DataTable` of its parts.
    """
    if not selected_magnet or selected_magnet == selectors.ALL:
        return html.Div(
            "Select a magnet above to see its parts.",
            style={"color": "#888", "fontStyle": "italic"},
        )

    parts = db.get_parts_for_magnet(selected_magnet, db_path)
    if not parts:
        return html.Div(
            f"No parts found for {selected_magnet}.",
            style={"color": "#888", "fontStyle": "italic"},
        )

    table_df = pd.DataFrame(parts).rename(
        columns={
            "name": "Part",
            "type": "Type",
            "status": "Status",
            "material_name": "Material",
            "manufactured_at": "Manufactured",
        }
    )
    table_df["Part"] = table_df.apply(part_link, axis=1)

    return DataTable(
        columns=PART_COLUMNS,
        data=table_df.to_dict("records"),
        page_size=10,
        sort_action="native",
        style_table={"overflowX": "auto"},
        style_cell={"textAlign": "center", "padding": "6px"},
        style_header={"fontWeight": "bold"},
    )


def _build_page_content(df, selected_magnet=None, db_path=None):
    """Build the figures, table rows, and summary text for a loaded (experiment, magnet) dataframe."""
    exp_df = df.drop_duplicates(subset="ID").copy()

    field_on_by_magnet = df.groupby(["Magnet", "Housing"], as_index=False).agg(
        {"Field ON (s)": "sum"}
    )
    field_on_by_magnet["Field ON (h)"] = field_on_by_magnet["Field ON (s)"] / S_TO_H

    magnet_order = [
        m for m in db.get_all_magnets(db_path) if m in set(field_on_by_magnet["Magnet"])
    ]

    fig_field_on = px.bar(
        field_on_by_magnet,
        x="Magnet",
        y="Field ON (h)",
        color="Housing",
        color_discrete_map={"M9": "red", "M10": "blue"},
        category_orders={"Magnet": magnet_order},
        barmode="group",
        title="Field ON Time per Magnet (h)",
    )

    table_df = df.drop(columns=["File"])
    table_df["Experiment"] = df.apply(experiment_link, axis=1)

    counts = db.get_db_counts(db_path)
    magnets_line = (
        f"Magnets: 1 selected of {counts['magnets']}"
        if selected_magnet and selected_magnet != selectors.ALL
        else f"Magnets: {counts['magnets']}"
    )
    summary = [
        html.B(magnets_line),
        html.Br(),
        html.B(f"Experiments: {len(exp_df)}"),
        html.Br(),
        f"Processed: {(exp_df['Status'] == 'STATS DONE').sum()}",
        html.Br(),
        html.B(
            f"DB-wide: {counts['assemblies']} assemblies, {counts['parts']} parts, "
            f"{counts['overview_records']} overview records"
        ),
    ]

    return (
        fig_field_on,
        table_df.to_dict("records"),
        summary,
    )


def layout(magnet=None, **kwargs):
    return html.Div(
        [
            html.H1("MagnetDB Dashboard"),
            html.Div(
                [
                    selectors.aggregate_filter(
                        "magnet-stats-status-filter",
                        "Status",
                        style={"width": "250px"},
                    ),
                    selectors.aggregate_filter(
                        "magnet-stats-magnet-filter",
                        "Magnet",
                        style={"width": "400px"},
                        value=magnet,
                    ),
                ],
                style={"display": "flex", "gap": "30px", "marginBottom": "15px"},
            ),
            html.Div(
                id="magnet-stats-missing-banner",
                style={"color": "#a94442", "fontWeight": "bold"},
            ),
            html.Div(id="magnet-stats-summary"),
            html.Br(),
            dcc.Graph(id="magnet-stats-fig-field-on"),
            html.Br(),
            html.Details(
                [
                    html.Summary(
                        "📁 Assembly history",
                        style={"fontWeight": "bold", "cursor": "pointer"},
                    ),
                    html.Div(
                        id="magnet-stats-assembly-history", style={"padding": "10px"}
                    ),
                ],
                open=False,
                style={
                    "border": "1px solid #ddd",
                    "borderRadius": "8px",
                    "marginBottom": "10px",
                },
            ),
            html.Details(
                [
                    html.Summary(
                        "🔩 Parts", style={"fontWeight": "bold", "cursor": "pointer"}
                    ),
                    html.Div(id="magnet-stats-parts", style={"padding": "10px"}),
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
                        id="magnet-stats-overview-records", style={"padding": "10px"}
                    ),
                ],
                open=False,
                style={
                    "border": "1px solid #ddd",
                    "borderRadius": "8px",
                    "marginBottom": "10px",
                },
            ),
            html.Details(
                [
                    html.Summary(
                        "📊 Experiments table",
                        style={"fontWeight": "bold", "cursor": "pointer"},
                    ),
                    html.Div(
                        DataTable(
                            id="magnet-stats-table",
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
    Output("magnet-stats-fig-field-on", "figure"),
    Output("magnet-stats-fig-field-on", "style"),
    Output("magnet-stats-table", "data"),
    Output("magnet-stats-summary", "children"),
    Output("magnet-stats-magnet-filter", "options"),
    Output("magnet-stats-status-filter", "options"),
    Output("magnet-stats-missing-banner", "children"),
    Output("magnet-stats-overview-records", "children"),
    Output("magnet-stats-assembly-history", "children"),
    Output("magnet-stats-parts", "children"),
    Input("dd-database", "value"),
    Input("magnet-stats-magnet-filter", "value"),
    Input("magnet-stats-status-filter", "value"),
)
def update_magnet_stats(selected_db, selected_magnet, selected_status):
    if not selected_db:
        return (
            go.Figure(),
            {},
            [],
            [],
            [],
            [],
            "",
            "",
            "",
            "",
        )

    df = load_data(selected_db)
    missing_banner = (
        "" if not df.empty else "No experiment data found for this database."
    )

    status_options = [selectors.ALL] + db.get_distinct_statuses("magnets", selected_db)
    names_with_status = (
        db.get_names_with_status("magnets", selected_status, selected_db)
        if selected_status and selected_status != selectors.ALL
        else None
    )
    magnet_options = [selectors.ALL] + [
        m
        for m in db.get_all_magnets(selected_db)
        if names_with_status is None or m in names_with_status
    ]

    plot_df = (
        df[df["Magnet"] == selected_magnet] if selected_magnet != selectors.ALL else df
    )
    if names_with_status is not None:
        plot_df = plot_df[plot_df["Magnet"].isin(names_with_status)]
    fig_field_on_style = {"display": "none"} if selected_magnet != selectors.ALL else {}

    (
        fig_field_on,
        table_records,
        summary,
    ) = _build_page_content(plot_df, selected_magnet, selected_db)

    assembly_history = (
        db.get_assembly_history_for_magnet(selected_magnet, selected_db)
        if selected_magnet and selected_magnet != selectors.ALL
        else []
    )
    assembly_history_section = _assembly_history_section(
        selected_magnet, assembly_history
    )

    overview_plot_df = load_overview_records(selected_db)
    if selected_magnet and selected_magnet != selectors.ALL:
        assembly_names = [row["assembly_name"] for row in assembly_history]
        overview_plot_df = overview_plot_df[
            overview_plot_df["Assembly"].isin(assembly_names)
        ]
    if names_with_status is not None:
        status_assembly_names = db.get_assembly_names_for_magnets(
            names_with_status, selected_db
        )
        overview_plot_df = overview_plot_df[
            overview_plot_df["Assembly"].isin(status_assembly_names)
        ]
    overview_records_section = _overview_records_section(overview_plot_df)

    parts_section = _parts_section(selected_magnet, selected_db)
    return (
        fig_field_on,
        fig_field_on_style,
        table_records,
        summary,
        magnet_options,
        status_options,
        missing_banner,
        overview_records_section,
        assembly_history_section,
        parts_section,
    )
