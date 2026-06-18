from dash import Dash, html, dcc, dash_table, Input, Output, State
import magnetdb_analysis # On importe notre fichier d'analyse

app = Dash(__name__)

app.layout = html.Div([
    html.H1("Dashboard for magnetdb"),
    
    html.Div([
        html.Label("1. Table :"),
        dcc.Dropdown(
            id='dropdown-table-select',
            # On appelle directement get_all_tables() ici
            options=[{'label': t, 'value': t} for t in magnetdb_analysis.get_all_tables()],
            placeholder="Choose a table..."
        )
    ], style={'marginBottom': '20px'}),
    
    html.Div([
        html.Label("2. explore the records / files of this table :"),
        dcc.Dropdown(
            id='dropdown-row-select',
            placeholder="Select an item..."
        )
    ], style={'marginBottom': '20px'}),
    
    html.H3("Data :"),
    dash_table.DataTable(
        id='universal-data-table',
        page_size=10,
        style_table={'overflowX': 'auto'}
    )
])

# Callback 1 : Remplir le menu 2
@app.callback(
    Output('dropdown-row-select', 'options'),
    Output('dropdown-row-select', 'placeholder'),
    Input('dropdown-table-select', 'value')
)
def update_row_dropdown(selected_table):
    # La logique est déléguée au fichier d'analyse
    return magnetdb_analysis.get_row_dropdown_data(selected_table)

# Callback 2 : Afficher le tableau
@app.callback(
    Output('universal-data-table', 'columns'),
    Output('universal-data-table', 'data'),
    Input('dropdown-row-select', 'value'),
    State('dropdown-table-select', 'value')
)
def display_selected_data(selected_value, selected_table):
    # La requête SQL et la création des colonnes sont gérées par l'analyse
    return magnetdb_analysis.get_table_data(selected_table, selected_value)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')