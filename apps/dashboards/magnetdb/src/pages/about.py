import dash
import dash_selectors as selectors
import magnetdb_analysis as db
from dash import Input, Output, html
from dash.dash_table import DataTable

dash.register_page(__name__, path="/about", name="About", order=9)

LOG_TABLE_COLUMNS = [
    {"name": c, "id": c}
    for c in ("ID", "Timestamp", "Operation", "Table", "Record", "User", "Status", "Details")
]


def layout(**kwargs):
    return html.Div(
        [
            html.H1("About"),
            html.Div(id="about-summary"),
            html.Br(),
            html.H3("Operation log"),
            html.Div(
                [
                    selectors.aggregate_filter(
                        "about-log-table-filter", "Table", style={"width": "250px"}
                    ),
                    selectors.aggregate_filter(
                        "about-log-operation-filter", "Operation", style={"width": "250px"}
                    ),
                    selectors.aggregate_filter(
                        "about-log-status-filter", "Status", style={"width": "150px"}
                    ),
                    selectors.date_range_filter(
                        "about-log-date-filter", "Filter by date", style={"width": "300px"}
                    ),
                ],
                style={"display": "flex", "gap": "30px", "marginBottom": "15px"},
            ),
            DataTable(
                id="about-log-table",
                columns=LOG_TABLE_COLUMNS,
                data=[],
                page_size=20,
                sort_action="native",
                style_table={"overflowX": "auto"},
                style_cell={"textAlign": "center", "padding": "6px"},
                style_header={"fontWeight": "bold"},
            ),
        ],
        style={"padding": "20px"},
    )


@dash.callback(
    Output("about-summary", "children"),
    Output("about-log-table", "data"),
    Output("about-log-table-filter", "options"),
    Output("about-log-operation-filter", "options"),
    Output("about-log-status-filter", "options"),
    Input("dd-database", "value"),
    Input("about-log-table-filter", "value"),
    Input("about-log-operation-filter", "value"),
    Input("about-log-status-filter", "value"),
    Input("about-log-date-filter", "start_date"),
    Input("about-log-date-filter", "end_date"),
)
def update_about(
    selected_db,
    selected_table,
    selected_operation,
    selected_status,
    start_date,
    end_date,
):
    if not selected_db:
        return [], [], [], [], []

    summary = selectors.database_summary_banner(db.get_database_summary(selected_db))

    table_filter = selected_table if selected_table and selected_table != selectors.ALL else None
    operation_filter = (
        selected_operation if selected_operation and selected_operation != selectors.ALL else None
    )
    status_filter = selected_status if selected_status and selected_status != selectors.ALL else None

    log_df = db.get_operation_log(
        selected_db,
        table_name=table_filter,
        operation=operation_filter,
        status=status_filter,
    )
    log_df = selectors.filter_by_date_range(log_df, "Timestamp", start_date, end_date)

    table_options = [selectors.ALL] + db.get_operation_log_values("table_name", selected_db)
    operation_options = [selectors.ALL] + db.get_operation_log_values("operation", selected_db)
    status_options = [selectors.ALL] + db.get_operation_log_values("status", selected_db)

    return (
        summary,
        log_df.to_dict("records"),
        table_options,
        operation_options,
        status_options,
    )
