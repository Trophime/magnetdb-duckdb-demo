import dash
import duckdb
import pandas as pd

from urllib.parse import quote

from dash import Dash, html, dcc, Input, Output
from dash.dash_table import DataTable

import plotly.express as px
from plotly import graph_objects as go
import magnetdb_analysis as db

# --- 1. ENREGISTREMENT ET LAYOUT DASH ---
dash.register_page(__name__, path="/magnet_stats", name="Magnet stats")


J_TO_KWH = 3.6e6
S_TO_H = 3600

EXP_RUN_SCALARS_COLUMNS = [
    "ID",
    "Experiment",
    "Magnet",
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
        f"[magnet_stats] Table 'exp_run_scalars' {reason}.\n"
        "  Populate it by running, for each site:\n"
        "    to_duckdb/venv-systempackages/bin/python3 to_duckdb/compute_exp_stats.py "
        f"--db {db_path} --site <SITE_NAME>"
    )


def load_data(db_path=None):
    """Load per-experiment energy stats joined with each experiment's magnets.

    Magnets are not a direct column on ``experiments``: each experiment runs
    on a site, and ``site_magnets`` links that site to the magnet(s) mounted
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
                e.site_name AS Site, e.file AS File,
                ROUND(MAX(CASE WHEN s.channel = 'energy_j' THEN s.value END) / {J_TO_KWH}, 7) AS "Energy (kWh)",
                ROUND(MAX(CASE WHEN s.channel = 'heat_extracted_j' THEN s.value END) / {J_TO_KWH}, 2) AS "Extracted heat (kWh)",
                ROUND(MAX(CASE WHEN s.channel = 'duration_s' THEN s.value END), 2) AS "Duration (s)",
                ROUND(MAX(CASE WHEN s.channel = 'duration_field_on_s' THEN s.value END), 2) AS "Field ON (s)",
            e.status AS Status
            FROM experiments AS e
            JOIN site_magnets AS sm ON e.site_name = sm.site_name
            LEFT JOIN exp_run_scalars AS s ON e.id = s.experiment_id
            GROUP BY e.id, e.name, sm.magnet_name, e.site_name, e.file, e.status
            ORDER BY sm.magnet_name, e.name
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
    for c in EXP_RUN_SCALARS_COLUMNS
    if c != "File"
]


def _experiment_link(row):
    """Render the Experiment cell as a markdown link pre-loading Home with this row's site/file."""
    label = (
        row["Experiment"].strftime("%Y-%m-%d - %H:%M:%S")
        if pd.notna(row["Experiment"])
        else str(row["Experiment"])
    )
    if pd.isna(row["File"]) or not row["File"]:
        return label
    href = f"/?site={quote(str(row['Site']), safe='')}&file={quote(str(row['File']), safe='')}"
    return f"[{label}]({href})"


def _build_page_content(df):
    """Build the figures, table rows, and summary text for a loaded (experiment, magnet) dataframe."""
    exp_df = df.drop_duplicates(subset="ID").copy()

    field_on_by_magnet = df.groupby(["Magnet", "Housing"], as_index=False).agg(
        {"Field ON (s)": "sum", "Experiment": "min"}
    )
    field_on_by_magnet = field_on_by_magnet.sort_values("Experiment")
    field_on_by_magnet["Field ON (h)"] = field_on_by_magnet["Field ON (s)"] / S_TO_H

    fig_field_on = px.bar(
        field_on_by_magnet,
        x="Magnet",
        y="Field ON (h)",
        color="Housing",
        color_discrete_map={"M9": "red", "M10": "blue"},
        category_orders={"Magnet": field_on_by_magnet["Magnet"].tolist()},
        title="Field ON Time per Magnet (h)",
    )

    table_df = df.drop(columns=["File"])
    table_df["Experiment"] = df.apply(_experiment_link, axis=1)

    summary = [
        html.B(f"Experiments: {len(exp_df)}"),
        html.Br(),
        f"Processed: {(exp_df['Status'] == 'STATS DONE').sum()}",
    ]

    return (
        fig_field_on,
        table_df.to_dict("records"),
        summary,
    )


def layout(**kwargs):
    return html.Div(
        [
            html.H1("MagnetDB Dashboard"),
            dcc.Dropdown(
                id="magnet-stats-magnet-filter",
                options=[],
                value=None,
                placeholder="Filter by magnet...",
                clearable=True,
                style={"width": "400px", "marginBottom": "15px"},
            ),
            html.Div(id="magnet-stats-summary"),
            html.Br(),
            dcc.Graph(id="magnet-stats-fig-field-on"),
            html.Br(),
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
        ],
        style={"padding": "20px"},
    )


@dash.callback(
    Output("magnet-stats-fig-field-on", "figure"),
    Output("magnet-stats-fig-field-on", "style"),
    Output("magnet-stats-table", "data"),
    Output("magnet-stats-summary", "children"),
    Output("magnet-stats-magnet-filter", "options"),
    Input("dd-database", "value"),
    Input("magnet-stats-magnet-filter", "value"),
)
def update_magnet_stats(selected_db, selected_magnet):
    if not selected_db:
        return (
            go.Figure(),
            {},
            [],
            [],
            [],
        )

    df = load_data(selected_db)
    magnet_options = sorted(df["Magnet"].unique())

    plot_df = df[df["Magnet"] == selected_magnet] if selected_magnet else df
    fig_field_on_style = {"display": "none"} if selected_magnet else {}

    (
        fig_field_on,
        table_records,
        summary,
    ) = _build_page_content(plot_df)
    return (
        fig_field_on,
        fig_field_on_style,
        table_records,
        summary,
        magnet_options,
    )
