import dash
import duckdb
import pandas as pd

from dash import Dash, html, dcc
from dash.dash_table import DataTable

import plotly.express as px
import magnetdb_analysis as db

# --- 1. ENREGISTREMENT ET LAYOUT DASH ---
dash.register_page(__name__, path="/site_stats", name="Assembly stats")


EXP_RUN_SCALARS_COLUMNS = [
    "ID",
    "Experiment",
    "Site",
    "Energy (kWh)",
    "Extracted heat (kWh)",
    "Duration (s)",
    "Field ON (s)",
    "Status",
    "Magnet",
]


def _warn_exp_run_scalars(reason: str) -> None:
    print(
        f"[site_stats] Table 'exp_run_scalars' {reason}.\n"
        "  Populate it by running, for each site:\n"
        "    to_duckdb/venv-systempackages/bin/python3 to_duckdb/compute_exp_stats.py "
        f"--db {db.DB_PATH} --site <SITE_NAME>"
    )


# load experiments table from DuckDB
def load_data():

    con = duckdb.connect(db.DB_PATH, read_only=True)

    tables = con.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
    ).df()["table_name"].tolist()

    if "exp_run_scalars" not in tables:
        con.close()
        _warn_exp_run_scalars("does not exist")
        return pd.DataFrame(columns=EXP_RUN_SCALARS_COLUMNS)

    n_scalars = con.execute("SELECT COUNT(*) FROM exp_run_scalars").fetchone()[0]
    if n_scalars == 0:
        _warn_exp_run_scalars("is empty")

    df = con.execute("""
            SELECT 
                e.id AS ID, e.name AS Experiment, e.site_name AS Site, 
                ROUND(MAX(CASE WHEN s.channel = 'energy_j' THEN s.value END) / 3.6e6, 2) AS "Energy (kWh)",
                ROUND(MAX(CASE WHEN s.channel = 'heat_extracted_j' THEN s.value END) / 3.6e6, 2) AS "Extracted heat (kWh)",
                ROUND(MAX(CASE WHEN s.channel = 'duration_s' THEN s.value END), 2) AS "Duration (s)",
                ROUND(MAX(CASE WHEN s.channel = 'duration_field_on_s' THEN s.value END), 2) AS "Field ON (s)",
            e.status AS Status
            FROM experiments AS e
            LEFT JOIN exp_run_scalars AS s ON e.id = s.experiment_id
            GROUP BY e.id, e.name, e.site_name, e.status
            ORDER BY e.site_name, e.name
        """).fetchdf()

    df["Experiment"] = pd.to_datetime(df["Experiment"])
    df["Magnet"] = df["Site"].str.extract(r"^(M\d+)")

    con.close()

    return df


df = load_data()

fig_per_exp = px.bar(
    df.sort_values("Experiment"),
    x="Experiment",
    y="Energy (kWh)",
    color="Magnet",
    color_discrete_map={"M9": "red", "M10": "blue"},
    hover_data=["Site"],
    title="Energy per Experiment",
)

fig_per_exp.update_xaxes(tickformat="%b %Y", dtick="M1", title="Experiment Date")

fig_per_exp.update_traces(width=1000 * 60 * 60 * 24)

energy_by_site = df.groupby("Site", as_index=False)["Energy (kWh)"].sum()

fig_per_site = px.bar(
    energy_by_site, x="Site", y="Energy (kWh)", title="Energy per Site"
)

layout = html.Div(
    [
        html.H1("MagnetDB Dashboard"),
        #       dcc.Dropdown(
        #           id = "site",
        #           options = [{"label": s, "value": s} for s in sorted(df["Site"].unique())],
        #           value = df["Site"].iloc[0],
        #           clearable = False,
        #           style = {"width": "400px"},
        #       ),
        html.Div(
            [
                html.B(f"Experiments: {len(df)}"),
                html.Br(),
                f"Processed: {(df['Status'] == 'STATS DONE').sum()}",
            ]
        ),
        html.Br(),
        dcc.Graph(figure=fig_per_exp),
        html.Br(),
        dcc.Graph(figure=fig_per_site),
        html.Br(),
        DataTable(
            data=df.to_dict("records"),
            columns=[{"name": c, "id": c} for c in df.columns],
            page_size=20,
            sort_action="native",
            style_table={"overflowX": "auto"},
            style_cell={"textAlign": "center", "padding": "6px"},
            style_header={"fontWeight": "auto"},
        ),
    ],
    style={"padding": "20px"},
)
