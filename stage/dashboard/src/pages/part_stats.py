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
    {"name": c, "id": c, "presentation": "markdown"} if c == "Overview Record" else {"name": c, "id": c}
    for c in ("Overview Record", "Housing", "Mode", "t0")
]

MAGNET_HISTORY_COLUMNS = [
    {"name": c, "id": c}
    for c in ("magnet_name", "type", "status", "assembled_at", "rank", "coil_index")
]


def _overview_records_section(selected_part, db_path):
    """Build the "Overview records" accordion for the selected part."""
    if not selected_part:
        return html.Div(
            "Select a part above to see its overview records.",
            style={"color": "#888", "fontStyle": "italic"},
        )

    records = db.get_overview_records_for_part(selected_part, db_path)
    if not records:
        return html.Div(
            f"No overview records found for {selected_part}.",
            style={"color": "#888", "fontStyle": "italic"},
        )

    table_df = pd.DataFrame(records).rename(
        columns={"filename": "Overview Record", "assembly_name": "Assembly", "housing": "Housing", "mode": "Mode"}
    )
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


def _magnet_history_section(selected_part, db_path):
    """Build the "Magnet history" accordion for the selected part, ascending by magnets.assembled_at."""
    if not selected_part:
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


def _build_page_content(df, selected_part=None, db_path=None):
    """Build the figures, table rows, and summary text for a loaded (experiment, part) dataframe."""
    exp_df = df.drop_duplicates(subset="ID").copy()

    hours_by_part = df.groupby(["Part", "Housing"], as_index=False).agg(
        {"Operating time (h)": "sum", "Experiment": "min"}
    )
    hours_by_part = hours_by_part.sort_values("Experiment")

    fig_hours = px.bar(
        hours_by_part,
        x="Part",
        y="Operating time (h)",
        color="Housing",
        color_discrete_map={"M9": "red", "M10": "blue"},
        category_orders={"Part": hours_by_part["Part"].tolist()},
        title="Operating Time per Part (h)",
    )

    table_df = df.drop(columns=["File"])
    table_df["Experiment"] = df.apply(experiment_link, axis=1)

    counts = db.get_db_counts(db_path)
    parts_line = f"Parts: 1 selected of {counts['parts']}" if selected_part else f"Parts: {counts['parts']}"
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
        table_df.to_dict("records"),
        summary,
    )


def layout(**kwargs):
    return html.Div(
        [
            html.H1("MagnetDB Dashboard"),
            dcc.Dropdown(
                id="part-stats-part-filter",
                options=[],
                value=None,
                placeholder="Filter by part...",
                clearable=True,
                style={"width": "400px", "marginBottom": "15px"},
            ),
            html.Div(id="part-stats-missing-banner", style={"color": "#a94442", "fontWeight": "bold"}),
            html.Div(id="part-stats-summary"),
            html.Br(),
            html.Details(
                [
                    html.Summary("📁 Overview records", style={"fontWeight": "bold", "cursor": "pointer"}),
                    html.Div(id="part-stats-overview-records", style={"padding": "10px"}),
                ],
                open=False,
                style={"border": "1px solid #ddd", "borderRadius": "8px", "marginBottom": "10px"},
            ),
            html.Details(
                [
                    html.Summary("📁 Magnet history", style={"fontWeight": "bold", "cursor": "pointer"}),
                    html.Div(id="part-stats-magnet-history", style={"padding": "10px"}),
                ],
                open=False,
                style={"border": "1px solid #ddd", "borderRadius": "8px", "marginBottom": "20px"},
            ),
            html.Br(),
            dcc.Graph(id="part-stats-fig-hours"),
            html.Br(),
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
        ],
        style={"padding": "20px"},
    )


@dash.callback(
    Output("part-stats-fig-hours", "figure"),
    Output("part-stats-fig-hours", "style"),
    Output("part-stats-table", "data"),
    Output("part-stats-summary", "children"),
    Output("part-stats-part-filter", "options"),
    Output("part-stats-missing-banner", "children"),
    Output("part-stats-overview-records", "children"),
    Output("part-stats-magnet-history", "children"),
    Input("dd-database", "value"),
    Input("part-stats-part-filter", "value"),
)
def update_part_stats(selected_db, selected_part):
    if not selected_db:
        return (
            go.Figure(),
            {},
            [],
            [],
            [],
            "",
            "",
            "",
        )

    df = load_data(selected_db)
    part_options = sorted(df["Part"].unique())
    missing_banner = "" if not df.empty else "No experiment data found for this database."

    plot_df = df[df["Part"] == selected_part] if selected_part else df
    fig_hours_style = {"display": "none"} if selected_part else {}

    (
        fig_hours,
        table_records,
        summary,
    ) = _build_page_content(plot_df, selected_part, selected_db)
    overview_records_section = _overview_records_section(selected_part, selected_db)
    magnet_history_section = _magnet_history_section(selected_part, selected_db)
    return (
        fig_hours,
        fig_hours_style,
        table_records,
        summary,
        part_options,
        missing_banner,
        overview_records_section,
        magnet_history_section,
    )
