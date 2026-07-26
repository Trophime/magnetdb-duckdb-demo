import os
import dash
from dash import Dash, html, dcc
import magnetdb_analysis as db


app = Dash(__name__, use_pages=True, suppress_callback_exceptions=True)
server = app.server

# Opt-in cProfile instrumentation — one .prof file per callback request.
# Enable with: MAGNETDB_PROFILE=1 python magnetdb_app.py
# Inspect with: snakeviz profiles/<file>.prof  (pip install snakeviz)
if os.environ.get("MAGNETDB_PROFILE"):
    from werkzeug.middleware.profiler import ProfilerMiddleware

    os.makedirs("profiles", exist_ok=True)
    server.wsgi_app = ProfilerMiddleware(
        server.wsgi_app,
        profile_dir="profiles",
        stream=None,
    )

_db_options = db.get_available_databases()
_default_db_values = [o['value'] for o in _db_options]
_default_db = db.DB_PATH if db.DB_PATH in _default_db_values else (_default_db_values[0] if _default_db_values else None)

# Layout principal : il contient la barre de navigation ou les liens globaux
app.layout = html.Div([
    html.H1("Dashboard MagnetDB - Suivi LNCMI"),

    # Sélecteur de base de données, partagé par toutes les pages
    html.Div([
        html.Label("Database :", style={'fontWeight': 'bold', 'marginRight': '10px'}),
        dcc.Dropdown(
            id='dd-database',
            options=_db_options,
            value=_default_db,
            clearable=False,
            style={'width': '350px', 'display': 'inline-block', 'verticalAlign': 'middle'}
        ),
    ], style={'marginBottom': '15px'}),

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