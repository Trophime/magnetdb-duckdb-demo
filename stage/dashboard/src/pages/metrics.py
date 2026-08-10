from dash import Input, Output, callback, html, dcc
import dash
import magnetdb_analysis as db

dash.register_page(__name__, path="/metrics", name="Metrics", order=6)

layout = html.Div(
    [
        html.Div(
            [
                html.H2("Metrics Page"),
                html.P(
                    "This page is under construction. Metrics will be displayed here."
                ),
                html.Hr(),
                html.Label("Select Housing:", style={"fontWeight": "bold"}),
                dcc.Dropdown(
                    id="dropdown-housing",
                    options=db.get_housings(),
                    placeholder="Select a housing",
                ),
                # html.Label("Select Overview Pupitre:", style={'fontWeight': 'bold', 'marginTop': '10px'}),
                # dcc.Dropdown(
                #     id='dropdown-ovrview',
                #     options= db.get_pupitres(),
                #     placeholder="Select a pupitre"
                # ),
            ],
            style={
                "padding": "20px",
                "backgroundColor": "#f8f9fa",
                "minHeight": "100vh",
            },
        )
    ]
)


@callback(
    Output("texte-overview", "children"),
    Output("texte-archive", "children"),
    Output("texte-default", "children"),
    Input("dropdown-housing", "value"),
    Input("dropdown-pupitre", "value"),
)
def update_file_links(housing_selectionne, pupitre_selectionne):
    # Si l'utilisateur n'a pas encore tout sélectionné
    if not housing_selectionne or not pupitre_selectionne:
        return "En attente...", "En attente...", "En attente..."

    # On interroge la base de données
    fichiers = db.get_linked_files(housing_selectionne, pupitre_selectionne)

    if fichiers:
        # On extrait les noms ou on met "Non trouvé" si la case est vide
        overview = fichiers["pigbrother_file"] or "Aucun fichier Overview"
        archive = fichiers["archive_file"] or "Aucune archive"
        default = fichiers["default_file"] or "Aucun fichier default"

        return overview, archive, default
    else:
        return "Erreur", "Erreur", "Erreur"
