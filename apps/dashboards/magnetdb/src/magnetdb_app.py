import argparse
import os

import dash
import dash_bootstrap_components as dbc
import magnetdb_analysis as db
from dash import Dash, dcc, html

app = Dash(
    __name__,
    use_pages=True,
    suppress_callback_exceptions=True,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
)
server = app.server

if os.environ.get("MAGNETDB_PROFILE"):
    # cProfile per request, gated by env var so it's opt-in.
    # Dumps one .prof per HTTP request (assets, page loads, and every callback
    # invocation via POST /_dash-update-component) into profile_dir.
    # Filenames embed the path, so callback profiles can be picked out with
    # e.g. `ls profiles/ | grep update-component`.
    # Open a .prof file with: snakeviz profiles/<file>.prof
    from pathlib import Path

    from werkzeug.middleware.profiler import ProfilerMiddleware

    profile_dir = Path(os.environ.get("PROFILE_DIR", "profiles"))
    profile_dir.mkdir(exist_ok=True)
    server.wsgi_app = ProfilerMiddleware(
        server.wsgi_app,
        stream=None,
        profile_dir=str(profile_dir),
        filename_format="{time:.0f}-{method}-{path}-{elapsed:.0f}ms.prof",
    )

_db_options = db.get_available_databases()
_default_db_values = [o["value"] for o in _db_options]
_default_db = (
    db.DB_PATH
    if db.DB_PATH in _default_db_values
    else (_default_db_values[0] if _default_db_values else None)
)

# Layout principal : il contient la barre de navigation ou les liens globaux
app.layout = html.Div(
    [
        html.H1("Dashboard MagnetDB - LNCMI monitoring"),
        # Sélecteur de base de données, partagé par toutes les pages
        html.Div(
            [
                html.Label(
                    "Database :", style={"fontWeight": "bold", "marginRight": "10px"}
                ),
                dcc.Dropdown(
                    id="dd-database",
                    options=_db_options,
                    value=_default_db,
                    clearable=False,
                    style={
                        "width": "350px",
                        "display": "inline-block",
                        "verticalAlign": "middle",
                    },
                ),
            ],
            style={"marginBottom": "15px"},
        ),
        # Barre de navigation simple pour passer d'une page à l'autre
        html.Div(
            [
                dcc.Link(
                    children=page["name"],
                    href=page["relative_path"],
                    style={
                        "marginRight": "15px",
                        "textDecoration": "none",
                        "fontWeight": "bold",
                    },
                )
                for page in dash.page_registry.values()
            ],
            style={"display": "flex", "gap": "15px", "marginBottom": "20px"},
        ),
        # C'est ici que le contenu des pages sera affiché, selon la page sélectionnée
        dash.page_container,
    ]
)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument(
        "--dev-tools-ui", action=argparse.BooleanOptionalAction, default=False
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8050)
    args = parser.parse_args()
    app.run(
        debug=args.debug,
        dev_tools_ui=args.dev_tools_ui,
        host=args.host,
        port=args.port,
    )
