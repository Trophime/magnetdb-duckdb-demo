import sys
from pathlib import Path

import duckdb
import pandas as pd

import dash
from dash import html, dcc
from dash.dash_table import DataTable
from pint import UnitRegistry

import plotly.express as px

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from config import J_TO_KWH

dash.register_page(__name__, path = "/magnets", name = "Magnets")
DB = "../magnetdb.duckdb"
ureg = UnitRegistry()
J_TO_MWH = (1 * ureg.joule).to("megawatt_hour").magnitude

def load_data():

    con = duckdb.connect(DB, read_only=True)

    df = con.execute(
        f"""
            SELECT
                e.id AS ID, e.name AS Experiment, e.assembly_name AS Assembly,
                ROUND(MAX(CASE WHEN s.channel = 'energy_j' THEN s.value END) / {J_TO_KWH}, 2) AS "Energy (kWh)",
                ROUND(MAX(CASE WHEN s.channel = 'heat_extracted_j' THEN s.value END) / {J_TO_KWH}, 2) AS "Extracted heat (kWh)",
                ROUND(MAX(CASE WHEN s.channel = 'duration_s' THEN s.value END), 2) AS "Duration (s)",
                ROUND(MAX(CASE WHEN s.channel = 'duration_field_on_s' THEN s.value END), 2) AS "Field ON (s)",
            e.status AS Status
            FROM experiments AS e
            LEFT JOIN exp_run_scalars AS s ON e.id = s.experiment_id
            GROUP BY e.id, e.name, e.assembly_name, e.status
            ORDER BY e.assembly_name, e.name
        """
    ).fetchdf()

    df["Experiment"] = pd.to_datetime(df["Experiment"])
    df["Magnet"] = df["Assembly"].str.extract(r"^(M\d+)")

    con.close()

    return df




df = load_data()

fig_per_exp = px.bar(
    df.sort_values("Experiment"),
    x = "Experiment",
    y = "Energy (kWh)",
    color = "Magnet",
    color_discrete_map = {"M9": "red", "M10": "blue"},
    hover_data = ["Assembly"],
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

energy_by_assembly = (
    df.groupby("Assembly", as_index = False)["Energy (kWh)"].sum()
)

fig_per_assembly = px.bar(
    energy_by_assembly,
    x = "Assembly",
    y = "Energy (kWh)",
    title = "Energy per Assembly"
)

fig_per_assembly_pie = px.pie(
    energy_by_assembly,
    names = "Assembly",
    values = "Energy (kWh)",
    color_discrete_map = {"M9": "red", "M10": "blue"},
    hole = 0.3,
    title = "Energy per Assembly 2"
)

fig_per_assembly_pie.update_traces(
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

        dcc.Graph(id = "energy-assembly", figure = fig_per_assembly),
        html.Br(),

        dcc.Graph(id = "energy-assembly-pie", figure = fig_per_assembly_pie),
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

