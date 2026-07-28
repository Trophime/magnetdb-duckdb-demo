import duckdb
import pandas as pd

import dash
from dash import html, dcc
import plotly.express as px

dash.register_page(__name__, path = "/", name = "Home")
DB = "../magnetdb.duckdb"

###
con = duckdb.connect(DB, read_only=True)

df = con.execute("""
    SELECT
    name,
    MAX(CASE WHEN channel='energy_j' THEN value END) / 3.6e6 AS energy_kwh
    FROM experiments e
    LEFT JOIN exp_run_scalars s
        ON e.id = s.experiment_id
    GROUP BY name
""").fetchdf()

con.close()

df["Date"] = pd.to_datetime(df["name"])
df["Year"] = df["Date"].dt.year

energy_by_year = (
    df.groupby("Year", as_index=False)["energy_kwh"].sum()
)

fig_year = px.pie(
    energy_by_year,
    names="Year",
    values="energy_kwh",
    title="Energy Distribution by Year (kWh)",
    color="Year",
)

fig_year.update_traces(
    textinfo="percent+label",
    hole=0.45,
)

###
layout = html.Div(
    [
        html.H2("Welcome to MagnetDB Dashboard"),
        html.P("Yearly Overview"),
        dcc.Graph(id = "energy-exp", figure = fig_year),
        html.Br(),
    ]
)