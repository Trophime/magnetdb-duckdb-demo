import argparse
import os

import dash
import dash_bootstrap_components as dbc
import flask
import i18n
import magnetdb_analysis as db
from dash import Dash, Input, Output, State, dcc, html

app = Dash(
    __name__,
    use_pages=True,
    suppress_callback_exceptions=True,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
)
server = app.server


@server.before_request
def _set_request_language():
    """Read the ``language`` cookie into ``flask.g.language`` for this request.

    Per-request, not a process-wide global, so concurrent visitors on
    different gunicorn threads never see each other's language — see
    :mod:`i18n`.
    """
    language = flask.request.cookies.get(i18n.COOKIE_NAME)
    if language not in i18n.SUPPORTED_LANGUAGES:
        language = i18n.default_language_for_new_visitors()
    flask.g.language = language

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

# Language names are always shown in their own language, and the button/modal
# chrome stays untranslated (a multilingual label) — a user who can't yet read
# the current language still needs to find and use this control.
_LANGUAGE_OPTIONS = [
    {"label": "English", "value": "en"},
    {"label": "Français", "value": "fr"},
    {"label": "Deutsch", "value": "de"},
    {"label": "Nederlands", "value": "nl"},
]


def _language_button():
    return html.Button(
        "🌐",
        id="language-gear",
        n_clicks=0,
        title="Language / Langue / Sprache / Taal",
        style={
            "border": "none",
            "background": "transparent",
            "cursor": "pointer",
            "fontSize": "18px",
            "lineHeight": "1",
            "marginLeft": "10px",
        },
    )


def _language_modal():
    return html.Div(
        [
            dcc.Store(id="language-saved"),
            dbc.Modal(
                [
                    dbc.ModalHeader(dbc.ModalTitle("Language / Langue / Sprache / Taal")),
                    dbc.ModalBody(
                        dcc.Dropdown(
                            id="language-select",
                            options=_LANGUAGE_OPTIONS,
                            value=i18n.current_language(),
                            clearable=False,
                        )
                    ),
                    dbc.ModalFooter(
                        dbc.Button(
                            "Save", id="language-save-btn", color="primary", n_clicks=0
                        )
                    ),
                ],
                id="language-modal",
                is_open=False,
            ),
        ]
    )


def serve_layout():
    """Build the app shell fresh on every full page load.

    A function (not a static layout) so the nav/title pick up this request's
    language (:func:`i18n.current_language`) when the language modal's Save
    action triggers a page reload — a static `app.layout` would only ever
    reflect whatever language happened to be active at process startup.
    """
    return html.Div(
        [
            html.H1(i18n._("Dashboard MagnetDB - LNCMI monitoring")),
            # Database selector, shared by every page
            html.Div(
                [
                    html.Label(
                        i18n._("Database :"),
                        style={"fontWeight": "bold", "marginRight": "10px"},
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
                    _language_button(),
                ],
                style={
                    "marginBottom": "15px",
                    "display": "flex",
                    "alignItems": "center",
                },
            ),
            # Simple nav bar to move between pages
            html.Div(
                [
                    dcc.Link(
                        children=i18n._(page["name"]),
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
            _language_modal(),
            # This is where each page's own content is rendered
            dash.page_container,
        ]
    )


app.layout = serve_layout


@dash.callback(
    Output("language-modal", "is_open"),
    Input("language-gear", "n_clicks"),
    prevent_initial_call=True,
)
def _open_language_modal(n_clicks):
    return True


@dash.callback(
    Output("language-saved", "data"),
    Input("language-save-btn", "n_clicks"),
    State("language-select", "value"),
    prevent_initial_call=True,
)
def _save_language(n_clicks, language):
    # One year, matching a "remember this until told otherwise" preference
    # cookie; no `secure=True` since this deployment is plain-HTTP-over-IP
    # for now (see README) — revisit once it sits behind HTTPS/SSO.
    dash.ctx.response.set_cookie(
        i18n.COOKIE_NAME, language, max_age=365 * 24 * 3600, samesite="Lax"
    )
    return language


app.clientside_callback(
    "function(language) {"
    "  if (language) { window.location.reload(); }"
    "  return window.dash_clientside.no_update;"
    "}",
    Output("language-modal", "is_open", allow_duplicate=True),
    Input("language-saved", "data"),
    prevent_initial_call=True,
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
