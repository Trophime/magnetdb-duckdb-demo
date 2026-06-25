from dash import Dash, html, dcc, dash_table, Input, Output
import plotly.express as px
import magnetdb_analysis as db 
from magnetdb_downsampling import apply_downsampling
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

            html.Br(),
            html.Label("6. Downsampling Method:", style={'fontWeight': 'bold'}),
            dcc.Dropdown(
                id='dropdown-downsampling',
                options=['naive', 'minmax', 'M4', 'LTTB', 'raw data'],
                value='naive',
                clearable=False
)
            
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
    # On récupère les fichiers
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
    Input('dd-y-axis', 'value'),
    Input('dropdown-downsampling', 'value')
)

def update_outputs(selected_file, selected_site, selected_table, selected_x, selected_y, selected_algo):
    
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

    df_raw = db.load_data(filepath, selected_site)
    
    if df_raw.empty:
        print("ERROR : The returned DataFrame is empty.")
        return px.scatter(title="File is empty or corrupted"), [], [], [], None
    
    print(f"DEBUG: Columns present : {df_raw.columns.tolist()}")

    colonnes_dispo = df_raw.columns.tolist()
    options_y = [{'label': col, 'value': col} for col in colonnes_dispo]
    
    if not selected_y or selected_y not in colonnes_dispo:
        selected_y = colonnes_dispo[0]

    if not selected_algo:
        selected_algo = 'naive'

    if selected_algo == 'LTTB':
        dict_lttb = apply_downsampling(df_raw, method=selected_algo)
        
        if selected_y in dict_lttb:
            df_reduce = dict_lttb[selected_y]
    else:
        df_reduce = apply_downsampling(df_raw, method=selected_algo)
        

    UNITE_MAPPING = {
    # --- Time and Index ---
    't': 'Time (s)',
    'timestamp': 'Date / Time',

    # --- Global Physical Quantities ---
    'Field': 'Magnetic Field (T)',
    'Pmagnet': 'Magnet Power (MW)',
    'Ptot': 'Total Power (MW)',
    'Q': 'Heat Load / Thermal Power (MW)', 

    # --- Electricity (Currents & Voltages) ---
    'IH': 'Helix Current (A)',
    'IB': 'Bitter Current (A)',
    'IH_ref': 'Helix Current Setpoint (A)',
    'IB_ref': 'Bitter Current Setpoint (A)',
    'UH': 'Helix Voltage (V)',
    'UB': 'Bitter Voltage (V)',
    'Ucoil2': 'Coil 2 Voltage (V)',
    'Ucoil3': 'Coil 3 Voltage (V)',
    'Ucoil4': 'Coil 4 Voltage (V)',
    'Ucoil5': 'Coil 5 Voltage (V)',
    'Ucoil15': 'Coil 15 Voltage (V)',
    'Ucoil16': 'Coil 16 Voltage (V)',

    # --- Cooling (Temperatures) ---
    'TinH': 'Helix Inlet Temperature (°C)',
    'TinB': 'Bitter Inlet Temperature (°C)',
    'Tout': 'Global Outlet Temperature (°C)',
    'TAlimout': 'Power Supply Outlet Temp (°C)',
    'Tcal2': 'Calculated Temperature 2 (°C)',
    'teb': 'Coil Inlet Temperature (°C)',
    'tsb': 'Coil Outlet Temperature (°C)',

    # --- Hydraulics (Pressures & Flow Rates) ---
    'HPH': 'Helix High Pressure (bar)',
    'HPB': 'Bitter High Pressure (bar)',
    'BP': 'Low Pressure (bar)',
    'FlowH': 'Helix Flow Rate (L/s)',
    'FlowB': 'Bitter Flow Rate (L/s)',
    'debitbrut': 'Gross Flow Rate (L/s)',

    # --- Pumps (Rotational Speeds) ---
    'RpmH': 'Helix Pump Speed (rpm)',
    'RpmB': 'Bitter Pump Speed (rpm)'
}
    
    # Création du graphe
    fig = px.line(
        df_reduce, 
        x=selected_x,
        y=selected_y,
        title=f"Visualization : {selected_file} (Algo: {selected_algo})",
        labels=UNITE_MAPPING
    )
    
    columns = [{"name": i, "id": i} for i in df_raw.columns]
    data = df_raw.to_dict('records')
    
    return fig, columns, data, options_y, selected_y

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8051)