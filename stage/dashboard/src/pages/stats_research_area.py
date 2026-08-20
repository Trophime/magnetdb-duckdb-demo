import dash
from dash import html, dcc, callback, Input, Output
from dash.dash_table import DataTable

import plotly.express as px
import magnetdb_analysis as db
import dash_selectors as selectors

dash.register_page(__name__, path="/research-area", name="Research areas", order=7)

layout = html.Div(
    [
        html.H2("Research Area Statistics"),
        html.Br(),
        html.Div(
            [
                selectors.aggregate_filter("ra-housing", "Housing", options=db.get_housings(), style={"width": "250px"}),
                selectors.aggregate_filter(
                    "ra-year",
                    "Year",
                    options=["2022", "2023", "2024", "2025", "2026"],
                    style={"width": "250 px"},
                ),
            ],
            style={"display": "flex", "gap": "30px", "marginBottom": "30px"},
        ),
        dcc.Graph(id="ra-exp"),
        dcc.Graph(id="ra-time"),
        dcc.Graph(id="ra-users"),
        html.H3("Statistics"),
        DataTable(
            id="ra-table",
            page_size=10,
            sort_action="native",
            style_table={"overflowX": "auto"},
            style_cell={"textAlign": "center", "padding": "6px"},
        ),
    ],
    style={"padding": "20px"},
)


@callback(
    Output("ra-table", "data"),
    Output("ra-table", "columns"),
    Output("ra-exp", "figure"),
    Output("ra-users", "figure"),
    Output("ra-time", "figure"),
    Input("ra-housing", "value"),
    Input("ra-year", "value"),
)
def update(housing, year):

    df = db.get_research_area_stats(
        housing=None if housing == "All" else housing,
        year=None if year == "All" else year,
    )

    fig_exp = px.bar(
        df,
        x="research_area",
        y="n_experiments",
        title="Experiments per research area",
    )

    fig_users = px.bar(
        df,
        x="research_area",
        y="n_users",
        title="Users per research area",
    )

    fig_time = px.bar(
        df,
        x="research_area",
        y="total_field_time_s",
        title="Total field time",
    )

    return (
        df.to_dict("records"),
        [{"name": c, "id": c} for c in df.columns],
        fig_exp,
        fig_users,
        fig_time,
    )
