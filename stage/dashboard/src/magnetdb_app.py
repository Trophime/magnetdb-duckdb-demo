from dash import Dash, html, dcc, dash_table, Input, Output
import plotly.express as px
import magnetdb_analysis as db # Ton fichier nettoyé
import os

app = Dash(__name__)
app.layout = html.Div([
    
    # Contenant principal avec deux colonnes : gauche (25%) et droite (75%)
    html.Div([
        
        # contenant de gauche (25% de l'écran)
        html.Div([
            html.H2("Magnetdb Dashboard", style={'marginTop': '0px', 'marginBottom': '20px'}),
            html.Hr(), # Petite ligne de séparation
            
            html.Label("1. Choose Site :", style={'fontWeight': 'bold'}),
            dcc.Dropdown(id='dd-site', options=db.get_all_sites(), placeholder="Choose a site..."),
            
            html.Br(),
            html.Label("2. Choose Table :", style={'fontWeight': 'bold'}),
            dcc.Dropdown(id='dd-table', options=['experiments', 'operationaldata'], value='experiments'),
            
            html.Br(),
            html.Label("3. Choose File :", style={'fontWeight': 'bold'}),
            dcc.Dropdown(id='dd-file', placeholder="Choose a file..."),

            html.Br(),
            html.Label("4. Choose X-axis :", style={'fontWeight': 'bold', 'color':'#007bff'}),
            dcc.Dropdown(
                id='dd-x-axis',
                options=[
                    {'label': 'Real Time (timestamp)', 'value': 'timestamp'},
                    {'label': 'Elapsed Time (t)', 'value': 't'}
                ],
                value='timestamp', # La valeur sélectionnée par défaut
                clearable=False    # On empêche d'avoir un axe vide pour ne pas faire planter le graphe
            ),

            html.Br(),
            html.Label("5. Choose Y-axis :", style={'fontWeight': 'bold', 'color': '#007bff'}),
            dcc.Dropdown( id='dd-y-axis', placeholder="Choose a column..."),
            
        ], style={
            'width': '25%', 
            'padding': '20px', 
            'backgroundColor': '#f8f9fa',
            'borderRight': '1px solid #dee2e6', # Petite bordure pour séparer du graphe
            'minHeight': '100vh' # Pour que le gris descende jusqu'en bas
        }),

        # Partie qui montre le graphe et le tableau de données (75% de l'écran)
        html.Div([
            dcc.Graph(id='main-graph'),
            html.Hr(),
            html.H3("Raw Data :"),
            dash_table.DataTable(
                id='data-table', 
                page_size=10,
                style_table={'overflowX': 'auto'} # Pour éviter que le tableau déborde de l'écran
            )
        ], style={'width': '75%', 'padding': '20px'})
        
    ], style={'display': 'flex', 'flexDirection': 'row'}) # Aligne gauche et droite
])

# CALLBACK 1 : Met à jour la liste des fichiers en fonction du Site ET de la Table
@app.callback(
    Output('dd-file', 'options'),
    Input('dd-site', 'value'),
    Input('dd-table', 'value')
)
def update_file_dropdown(selected_site, selected_table):
    if not selected_site or not selected_table:
        return []
    # On récupère les fichiers via ta nouvelle fonction SQL
    files = db.get_files_for_site(selected_site, selected_table)
    return [{'label': f, 'value': f} for f in files]

# CALLBACK 2 : Met à jour le Graphique et le Tableau quand le fichier change
@app.callback(
    Output('main-graph', 'figure'),
    Output('data-table', 'columns'),
    Output('data-table', 'data'),
    Output('dd-y-axis', 'options'),
    Output('dd-y-axis', 'value'),
    Input('dd-file', 'value'),
    Input('dd-site', 'value'),
    Input('dd-table', 'value'),
    Input('dd-x-axis', 'value'),
    Input('dd-y-axis', 'value')
)

def update_outputs(selected_file, selected_site, selected_table, selected_x, selected_y):
    
    # Si rien a été sélectionné, on retourne un graphe vide et un tableau vide
    if not selected_file or not selected_site:
        return {}, [], [], [], None 
    
    base_dir = "/mnt/LNCMIG-Data/records"
    filepath = os.path.join(base_dir, selected_file)
    print(f"DEBUG: Constructed path : {filepath}")
    
    # Si le fichier n'existe pas, on retourne un message d'erreur dans le graphe et un tableau vide
    if not os.path.exists(filepath):
        print(f"ERROR : File not found : {filepath}")
        return px.scatter(title="File not found"), [], [], [], None

    df = db.load_data(filepath, selected_site)
    
    # --- CORRECTION 3 ---
    if df.empty:
        print("ERROR : The returned DataFrame is empty.")
        return px.scatter(title="File is empty or corrupted"), [], [], [], None
    
    print(f"DEBUG: Columns present : {df.columns.tolist()}")

    # La magie de l'axe Y
    colonnes_dispo = df.columns.tolist()
    options_y = [{'label': col, 'value': col} for col in colonnes_dispo]
    
    if not selected_y or selected_y not in colonnes_dispo:
        selected_y = colonnes_dispo[0] 
    
    # Création du graphe
    fig = px.line(
        df, 
        x=selected_x,
        y=selected_y,
        title=f"Visualization : {selected_file}"
    )
    
    columns = [{"name": i, "id": i} for i in df.columns]
    data = df.to_dict('records')
    
    return fig, columns, data, options_y, selected_y

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')