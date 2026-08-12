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
dash.register_page(__name__, path="/part_stats", name="Part stats", order=3)


S_TO_H = 3600

EXP_PART_BIN_STATS_COLUMNS = [
    "ID",
    "Experiment",
    "Part",
    "Type",
    "Magnet",
    "Site",
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
        "  Populate it by running, for each site:\n"
        "    to_duckdb/venv-systempackages/bin/python3 to_duckdb/compute_exp_stats.py "
        f"--db {db_path} --site <SITE_NAME>"
    )


def load_data(db_path=None):
    """Load per-experiment part-level operating stats joined with each part's magnet.

    Parts are not a direct column on ``experiments``: each experiment runs
    on a site, ``site_magnets`` links that site to the magnet(s) mounted
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
                mp.magnet_name AS Magnet, e.site_name AS Site, e.file AS File,
                ROUND(SUM(CASE WHEN s.channel = 'Icoil' THEN s.sum_dt END) / 3600, 2) AS "Operating time (h)",
                ROUND(MAX(CASE WHEN s.channel = 'hoop_stress_proxy' THEN s.max_x END), 1) AS "Peak hoop stress proxy (A^2)",
                CASE WHEN hp.experiment_id IS NOT NULL THEN 'Computed' ELSE 'Not computed' END AS "Hoop Stress Status",
            e.status AS Status
            FROM experiments AS e
            JOIN site_magnets AS sm ON e.site_name = sm.site_name
            JOIN magnet_parts AS mp ON mp.magnet_name = sm.magnet_name
            JOIN parts AS p ON p.name = mp.part_name
            LEFT JOIN exp_part_bin_stats AS s ON s.experiment_id = e.id AND s.part_name = p.name
            LEFT JOIN (SELECT DISTINCT experiment_id FROM hoop_stress_processed) AS hp ON hp.experiment_id = e.id
            WHERE p.type IN ('bitter', 'helix', 'supra')
            GROUP BY e.id, e.name, p.name, p.type, mp.magnet_name, e.site_name, e.file, e.status, hp.experiment_id
            ORDER BY p.name, e.name
        """).fetchdf()

    df["Experiment"] = pd.to_datetime(df["Experiment"])
    df["Housing"] = df["Site"].str.extract(r"^(M\d+)")

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


def _build_page_content(df):
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

    summary = [
        html.B(f"Experiments: {len(exp_df)}"),
        html.Br(),
        f"Processed: {(exp_df['Status'] == 'STATS DONE').sum()}",
        html.Br(),
        f"Parts: {df['Part'].nunique()}",
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
            html.Div(id="part-stats-summary"),
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
        )

    df = load_data(selected_db)
    part_options = sorted(df["Part"].unique())

    plot_df = df[df["Part"] == selected_part] if selected_part else df
    fig_hours_style = {"display": "none"} if selected_part else {}

    (
        fig_hours,
        table_records,
        summary,
    ) = _build_page_content(plot_df)
    return (
        fig_hours,
        fig_hours_style,
        table_records,
        summary,
        part_options,
    )
