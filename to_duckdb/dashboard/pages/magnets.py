import duckdb
import pandas as pd

import dash
from dash import html, dcc
from dash.dash_table import DataTable
from pint import UnitRegistry

import plotly.express as px


dash.register_page(__name__, path = "/magnets", name = "Magnets")
DB = "../magnetdb.duckdb"
ureg = UnitRegistry()
J_TO_MWH = (1 * ureg.joule).to("megawatt_hour").magnitude

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

fig_per_site_pie = px.pie(
    energy_by_site,
    names = "Site",
    values = "Energy (kWh)",
    color_discrete_map = {"M9": "red", "M10": "blue"},
    hole = 0.3,
    title = "Energy per Site 2"
)

fig_per_site_pie.update_traces(
    textposition = "inside",
    textinfo = "percent+label"
)

layout = html.Div(
    [
        html.H2("Magnets"),

        html.Div(
            [
                html.B(f"Experiments: {len(df)}"),
                html.Br(),
                f"Processed: {(df['Status'] == 'STATS DONE').sum()}",
            ]
        ),
        html.Br(),

        dcc.Graph(id = "energy-exp", figure = fig_per_exp),
        html.Br(),

        dcc.Graph(id = "energy-site", figure = fig_per_site),
        html.Br(),

        dcc.Graph(id = "energy-site-pie", figure = fig_per_site_pie),
        html.Br(),

        DataTable(
            id = "exp_table", 
            data = df.to_dict("records"),
            columns = [{"name": c, "id": c} for c in df.columns],
            page_size = 20,
            sort_action = "native",

            style_table = {"overflowX": "auto"},

            
            style_cell = {"textAlign": "center",
                          "padding": "6px"},
        ),

    ],

    style = {"padding": "20px"},
)

