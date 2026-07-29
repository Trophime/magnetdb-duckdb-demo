import duckdb
import pandas as pd

from dash import Dash, html, dcc
from dash.dash_table import DataTable

import plotly.express as px

DB = "magnetdb.duckdb"

app = Dash(__name__)


# load experiments table from DuckDB
def load_data():

    con = duckdb.connect(DB)

    df = con.execute(
        """
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
        """
    ).fetchdf()

    df["Experiment"] = pd.to_datetime(df["Experiment"])
    df["Magnet"] = df["Site"].str.extract(r"^(M\d+)")

    con.close()

    return df


df = load_data()

fig_per_exp = px.bar(
    df.sort_values("Experiment"),
    x = "Experiment",
    y = "Energy (kWh)",
    color = "Magnet",
    color_discrete_map = {"M9": "red", "M10": "blue"},
    hover_data = ["Site"],
    title = "Energy per Experiment"
)

fig_per_exp.update_xaxes(
    tickformat = "%b %Y",
    dtick = "M1",
    title = "Experiment Date"
)

fig_per_exp.update_traces(
    width = 1000 * 60 * 60 * 24
)

energy_by_site = (
    df.groupby("Site", as_index = False)["Energy (kWh)"].sum()
)

fig_per_site = px.bar(
    energy_by_site,
    x = "Site",
    y = "Energy (kWh)",
    title = "Energy per Site"
)

app.layout = html.Div(
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

        dcc.Graph(figure = fig_per_exp),
        html.Br(),
        dcc.Graph(figure = fig_per_site),
        html.Br(),

        DataTable(
            data = df.to_dict("records"),
            columns = [{"name": c, "id": c} for c in df.columns],
            page_size = 20,
            sort_action = "native",

            style_table = {"overflowX": "auto"},

            
            style_cell = {"textAlign": "center",
                          "padding": "6px"},

            
            style_header = {"fontWeight": "auto"}
        ),
    ],

    style = {"padding": "20px"},
)


if __name__ == "__main__":

    app.run(debug = True, port = 8050)