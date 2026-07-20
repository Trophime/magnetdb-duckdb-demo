import dash
from dash import Dash, html, dcc


app = Dash(__name__, use_pages=True, suppress_callback_exceptions=True)

# Layout principal : il contient la barre de navigation ou les liens globaux
app.layout = html.Div([
    html.H1("Dashboard MagnetDB - Suivi LNCMI"),
    
    # Barre de navigation simple pour passer d'une page à l'autre
    html.Div([
        dcc.Link(
            children=page["name"], 
            href=page["relative_path"],
            style={"marginRight": "15px", "textDecoration": "none", "fontWeight": "bold"}
        )
        for page in dash.page_registry.values()
    ], style={"display": "flex", "gap": "15px", "marginBottom": "20px"}),
    # C'est ici que le contenu de home.py (ou comparison.py) va s'injecter
    dash.page_container
])

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')