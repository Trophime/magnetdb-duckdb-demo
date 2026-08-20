import dash
import duckdb
import pandas as pd

from dash import Dash, html, dcc, Input, Output
from dash.dash_table import DataTable

import plotly.express as px
from plotly import graph_objects as go
from natsort import natsorted
import magnetdb_analysis as db
from experiment_links import experiment_link, overview_record_link
import dash_selectors as selectors

# --- 1. ENREGISTREMENT ET LAYOUT DASH ---
dash.register_page(__name__, path="/part_stats", name="Part stats", order=4)


S_TO_H = 3600

EXP_PART_BIN_STATS_COLUMNS = [
    "ID",
    "Experiment",
    "Part",
    "Type",
    "Magnet",
    "Assembly",
    "File",
    "Operating time (h)",
    "Peak hoop stress proxy (A^2)",
    "Hoop Stress Status",
    "Status",
    "Housing",
]


def _warn_exp_part_bin_stats(reason: str, db_path: str) -> None:
    print(
        f"[part_stats] Table 'exp_part_bin_stats' {reason}.\n"
        "  Populate it by running, for each assembly:\n"
        "    to_duckdb/venv-systempackages/bin/python3 to_duckdb/compute_exp_stats.py "
        f"--db {db_path} --assembly <ASSEMBLY_NAME>"
    )


def load_data(db_path=None):
    """Load per-experiment part-level operating stats joined with each part's magnet.

    Parts are not a direct column on ``experiments``: each experiment runs
    on an assembly, ``assembly_magnets`` links that assembly to the magnet(s) mounted
    on it, and ``magnet_parts`` links each magnet to its parts (helices,
    bitters, rings). Joining through both fans one experiment row out into
    one row per part.

    ``Hoop Stress Status`` reflects whether an experiment has an entry in
    ``hoop_stress_processed`` (the actual MPa hoop-stress computation),
    independent of the ``hoop_stress_proxy`` channel below (which is
    ``Icoil^2``, always available once ``exp_part_bin_stats`` is populated).

    Parameters
    ----------
    db_path : str, optional
        Path to the DuckDB database. Defaults to :data:`db.DB_PATH`.

    Returns
    -------
    :class:`~pandas.DataFrame`
        One row per (experiment, part) pair, with columns matching
        ``EXP_PART_BIN_STATS_COLUMNS`` plus ``Housing``.
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

    if "exp_part_bin_stats" not in tables:
        con.close()
        _warn_exp_part_bin_stats("does not exist", db_path)
        return pd.DataFrame(columns=EXP_PART_BIN_STATS_COLUMNS)

    n_scalars = con.execute("SELECT COUNT(*) FROM exp_part_bin_stats").fetchone()[0]
    if n_scalars == 0:
        _warn_exp_part_bin_stats("is empty", db_path)

    df = con.execute("""
            SELECT
                e.id AS ID, e.name AS Experiment, p.name AS Part, p.type AS Type,
                mp.magnet_name AS Magnet, e.assembly_name AS Assembly, e.file AS File,
                ROUND(SUM(CASE WHEN s.channel = 'Icoil' THEN s.sum_dt END) / 3600, 2) AS "Operating time (h)",
                ROUND(MAX(CASE WHEN s.channel = 'hoop_stress_proxy' THEN s.max_x END), 1) AS "Peak hoop stress proxy (A^2)",
                CASE WHEN hp.experiment_id IS NOT NULL THEN 'Computed' ELSE 'Not computed' END AS "Hoop Stress Status",
            e.status AS Status
            FROM experiments AS e
            JOIN assembly_magnets AS sm ON e.assembly_name = sm.assembly_name
            JOIN magnet_parts AS mp ON mp.magnet_name = sm.magnet_name
            JOIN parts AS p ON p.name = mp.part_name
            LEFT JOIN exp_part_bin_stats AS s ON s.experiment_id = e.id AND s.part_name = p.name
            LEFT JOIN (SELECT DISTINCT experiment_id FROM hoop_stress_processed) AS hp ON hp.experiment_id = e.id
            WHERE p.type IN ('bitter', 'helix', 'supra')
            GROUP BY e.id, e.name, p.name, p.type, mp.magnet_name, e.assembly_name, e.file, e.status, hp.experiment_id
            ORDER BY p.name, e.name
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
    for c in EXP_PART_BIN_STATS_COLUMNS
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

MAGNET_HISTORY_COLUMNS = [
    {"name": c, "id": c}
    for c in ("magnet_name", "type", "status", "assembled_at", "rank", "coil_index")
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
        page's current part selection.

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


def _magnet_history_section(selected_part, db_path):
    """Build the "Magnet history" accordion for the selected part, ascending by magnets.assembled_at."""
    if not selected_part or selected_part == selectors.ALL:
        return html.Div(
            "Select a part above to see its magnet history.",
            style={"color": "#888", "fontStyle": "italic"},
        )

    history = db.get_magnet_history_for_part(selected_part, db_path)
    if not history:
        return html.Div(
            f"No magnet history found for {selected_part}.",
            style={"color": "#888", "fontStyle": "italic"},
        )

    return DataTable(
        columns=MAGNET_HISTORY_COLUMNS,
        data=history,
        page_size=10,
        sort_action="native",
        style_table={"overflowX": "auto"},
        style_cell={"textAlign": "center", "padding": "6px"},
        style_header={"fontWeight": "bold"},
    )


def _assembly_history_section(selected_part, history):
    """Build the "Assembly history" accordion for the selected part, ascending by assemblies.commissioned_at."""
    if not selected_part or selected_part == selectors.ALL:
        return html.Div(
            "Select a part above to see its assembly history.",
            style={"color": "#888", "fontStyle": "italic"},
        )

    if not history:
        return html.Div(
            f"No assembly history found for {selected_part}.",
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


def _build_page_content(df, selected_part=None, db_path=None):
    """Build the figures, table rows, and summary text for a loaded (experiment, part) dataframe."""
    exp_df = df.drop_duplicates(subset="ID").copy()

    hours_by_part = df.groupby(["Part", "Housing"], as_index=False).agg(
        {"Operating time (h)": "sum"}
    )
    part_order = [
        p for p in db.get_all_parts(db_path) if p in set(hours_by_part["Part"])
    ]
    housing_order = natsorted(hours_by_part["Housing"].dropna().unique())

    fig_hours = px.bar(
        hours_by_part,
        x="Part",
        y="Operating time (h)",
        color="Housing",
        color_discrete_map={"M9": "red", "M10": "blue"},
        category_orders={"Part": part_order, "Housing": housing_order},
        barmode="group",
        title="Operating Time per Part (h)",
    )

    hours_by_part_magnet = df.groupby(["Part", "Magnet"], as_index=False).agg(
        {"Operating time (h)": "sum"}
    )
    magnet_order = [
        m
        for m in db.get_all_magnets(db_path)
        if m in set(hours_by_part_magnet["Magnet"])
    ]

    fig_magnet_time = px.bar(
        hours_by_part_magnet,
        x="Part",
        y="Operating time (h)",
        color="Magnet",
        category_orders={"Part": part_order, "Magnet": magnet_order},
        title="Magnet Time per Part (h)",
    )

    table_df = df.drop(columns=["File"])
    table_df["Experiment"] = df.apply(experiment_link, axis=1)

    counts = db.get_db_counts(db_path)
    parts_line = (
        f"Parts: 1 selected of {counts['parts']}"
        if selected_part and selected_part != selectors.ALL
        else f"Parts: {counts['parts']}"
    )
    summary = [
        html.B(parts_line),
        html.Br(),
        html.B(f"Experiments: {len(exp_df)}"),
        html.Br(),
        f"Processed: {(exp_df['Status'] == 'STATS DONE').sum()}",
        html.Br(),
        html.B(
            f"DB-wide: {counts['assemblies']} assemblies, {counts['magnets']} magnets, "
            f"{counts['overview_records']} overview records"
        ),
    ]

    return (
        fig_hours,
        fig_magnet_time,
        table_df.to_dict("records"),
        summary,
    )


def layout(part=None, **kwargs):
    return html.Div(
        [
            html.H1("MagnetDB Dashboard"),
            html.Div(
                [
                    selectors.aggregate_filter(
                        "part-stats-status-filter",
                        "Status",
                        style={"width": "250px"},
                    ),
                    selectors.aggregate_filter(
                        "part-stats-part-filter",
                        "Part",
                        style={"width": "400px"},
                        value=part,
                    ),
                ],
                style={"display": "flex", "gap": "30px", "marginBottom": "15px"},
            ),
            html.Div(
                id="part-stats-missing-banner",
                style={"color": "#a94442", "fontWeight": "bold"},
            ),
            html.Div(id="part-stats-summary"),
            html.Br(),
            html.Details(
                [
                    html.Summary(
                        "📈 Hoop stress history",
                        style={"fontWeight": "bold", "cursor": "pointer"},
                    ),
                    html.Div(
                        [
                            dcc.Graph(id="part-stats-hoop-stress-fig"),
                            DataTable(
                                id="part-stats-hoop-stress-table",
                                columns=[],
                                data=[],
                                page_size=10,
                                sort_action="native",
                                style_table={"overflowX": "auto"},
                                style_cell={"textAlign": "center", "padding": "6px"},
                                style_header={"fontWeight": "bold"},
                            ),
                        ],
                        style={"padding": "10px"},
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
            dcc.Graph(id="part-stats-fig-hours"),
            html.Br(),
            dcc.Graph(id="part-stats-fig-magnet-time"),
            html.Br(),
            html.Details(
                [
                    html.Summary(
                        "📁 Overview records",
                        style={"fontWeight": "bold", "cursor": "pointer"},
                    ),
                    html.Div(
                        id="part-stats-overview-records", style={"padding": "10px"}
                    ),
                ],
                open=False,
                style={
                    "border": "1px solid #ddd",
                    "borderRadius": "8px",
                    "marginBottom": "10px",
                },
            ),
            html.Br(),
            html.Details(
                [
                    html.Summary(
                        "📁 Magnet history",
                        style={"fontWeight": "bold", "cursor": "pointer"},
                    ),
                    html.Div(id="part-stats-magnet-history", style={"padding": "10px"}),
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
                        "📁 Assembly history",
                        style={"fontWeight": "bold", "cursor": "pointer"},
                    ),
                    html.Div(
                        id="part-stats-assembly-history", style={"padding": "10px"}
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
                            id="part-stats-table",
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
    Output("part-stats-fig-hours", "figure"),
    Output("part-stats-fig-hours", "style"),
    Output("part-stats-fig-magnet-time", "figure"),
    Output("part-stats-fig-magnet-time", "style"),
    Output("part-stats-table", "data"),
    Output("part-stats-summary", "children"),
    Output("part-stats-part-filter", "options"),
    Output("part-stats-status-filter", "options"),
    Output("part-stats-missing-banner", "children"),
    Output("part-stats-overview-records", "children"),
    Output("part-stats-magnet-history", "children"),
    Output("part-stats-assembly-history", "children"),
    Input("dd-database", "value"),
    Input("part-stats-part-filter", "value"),
    Input("part-stats-status-filter", "value"),
)
def update_part_stats(selected_db, selected_part, selected_status):
    if not selected_db:
        return (
            go.Figure(),
            {},
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

    status_options = [selectors.ALL] + db.get_distinct_statuses("parts", selected_db)
    names_with_status = (
        db.get_names_with_status("parts", selected_status, selected_db)
        if selected_status and selected_status != selectors.ALL
        else None
    )
    part_options = [selectors.ALL] + [
        p
        for p in db.get_all_parts(selected_db)
        if names_with_status is None or p in names_with_status
    ]

    plot_df = df[df["Part"] == selected_part] if selected_part != selectors.ALL else df
    if names_with_status is not None:
        plot_df = plot_df[plot_df["Part"].isin(names_with_status)]
    fig_hours_style = {"display": "none"} if selected_part != selectors.ALL else {}
    fig_magnet_time_style = (
        {"display": "none"} if selected_part != selectors.ALL else {}
    )

    (
        fig_hours,
        fig_magnet_time,
        table_records,
        summary,
    ) = _build_page_content(plot_df, selected_part, selected_db)

    magnet_history_section = _magnet_history_section(selected_part, selected_db)

    assembly_history = (
        db.get_assembly_history_for_part(selected_part, selected_db)
        if selected_part and selected_part != selectors.ALL
        else []
    )
    assembly_history_section = _assembly_history_section(
        selected_part, assembly_history
    )

    overview_plot_df = load_overview_records(selected_db)
    if selected_part and selected_part != selectors.ALL:
        assembly_names = [row["assembly_name"] for row in assembly_history]
        overview_plot_df = overview_plot_df[
            overview_plot_df["Assembly"].isin(assembly_names)
        ]
    if names_with_status is not None:
        status_assembly_names = db.get_assembly_names_for_parts(
            names_with_status, selected_db
        )
        overview_plot_df = overview_plot_df[
            overview_plot_df["Assembly"].isin(status_assembly_names)
        ]
    overview_records_section = _overview_records_section(overview_plot_df)
    return (
        fig_hours,
        fig_hours_style,
        fig_magnet_time,
        fig_magnet_time_style,
        table_records,
        summary,
        part_options,
        status_options,
        missing_banner,
        overview_records_section,
        magnet_history_section,
        assembly_history_section,
    )
