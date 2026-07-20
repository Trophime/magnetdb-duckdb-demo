import dash
from dash import Dash, html, dcc


app = Dash(__name__, use_pages = True)

app.layout = html.Div(
    [
        html.H1("MagnetDB Dashboard"),
        
        html.Div(
            [
                dcc.Link(
                    page["name"],
                    href = page["relative_path"],
                    style = {
                        "margin-right": "20px",
                        "font-weight": "bold"
                    },
                )
                for page in dash.page_registry.values()
            ]
        ),
        html.Hr(),
        dash.page_container,
    ],
    style = {"padding": "20px"},
)


if __name__ == "__main__":

    app.run(debug = True, port = 8050)