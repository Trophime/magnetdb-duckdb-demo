import duckdb

from dash import Dash, html
from dash.dash_table import DataTable

DB = "magnetdb.duckdb"

app = Dash(__name__)


# load experiments table from DuckDB
def load_data():

    con = duckdb.connect(DB)

    df = con.execute(
        """
            SELECT 
                e.id AS ID, e.name AS Experiment, e.site_name AS Site, 
                ROUND(MAX(CASE WHEN s.channel = 'energy_j' THEN s.value END) / 1e6, 2) AS "Energy (MJ)",
                ROUND(MAX(CASE WHEN s.channel = 'heat_extracted_j' THEN s.value END) / 1e6, 2) AS "Extracted heat (MJ)",
                ROUND(MAX(CASE WHEN s.channel = 'duration_s' THEN s.value END), 2) AS "Duration (s)",
                ROUND(MAX(CASE WHEN s.channel = 'duration_field_on_s' THEN s.value END), 2) AS "Field ON (s)",
            e.status AS Status
            FROM experiments AS e
            LEFT JOIN exp_run_scalars AS s ON e.id = s.experiment_id
            GROUP BY e.id, e.name, e.site_name, e.status
            ORDER BY e.site_name, e.name
        """
    ).fetchdf()

    con.close()

    return df


df = load_data()


app.layout = html.Div(
    [
        html.H1("MagnetDB Dashboard"),
        
 #       dcc.Dropdown(
 #           id = "site",
 #           options = [{"label": s, "value": s} for s in sorted(df["site_name"].unique())],
 #           value = df["site_name"].iloc[0],
 #           clearable = False,
 #           style = {"width": "400px"},
 #       ),
        
        html.Div(
            [
                html.B(f"Experiments: {len(df)}"),
                html.Br(),
                f"Processed: {(df['Status'] == 'STATS DONE').sum()}",
            ]
        ),
        html.Br(),

        DataTable(
            data = df.to_dict("records"),
            columns = [{"name": c, "id": c} for c in df.columns],
            page_size = 20,
            sort_action = "native",
        ),
    ],

    style = {"padding": "20px"},
)


if __name__ == "__main__":

    app.run(debug = True, port = 8050)