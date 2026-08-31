import dash
import dash_selectors as selectors
import duckdb
import magnetdb_analysis as db
import pandas as pd
import plotly.express as px
from dash import Input, Output, dcc, html
from dash.dash_table import DataTable
from experiment_links import (
    assembly_link,
    experiment_link,
    magnet_link,
    overview_record_link,
    part_link,
)
from plotly import graph_objects as go
from python_magnetrun.utils.downsampling import DownsampleConfig, downsample_dataframe

# --- 1. ENREGISTREMENT ET LAYOUT DASH ---
dash.register_page(__name__, path="/part_stats", name="Part stats", order=4)


S_TO_H = 3600

EXP_PART_BIN_STATS_COLUMNS = [
    "ID",
    "Experiment",
    "Part",
    "Type",
    "Magnet",
    "Assembly",
    "File",
    "Time (h)",
    "Peak hoop stress proxy (A^2)",
    "Hoop Stress Status",
    "Status",
    "Housing",
]


def _warn_exp_part_bin_stats(reason: str, db_path: str) -> None:
    print(
        f"[part_stats] Table 'exp_part_bin_stats' {reason}.\n"
        "  Populate it by running, for each assembly:\n"
        "    to_duckdb/venv-systempackages/bin/python3 to_duckdb/compute_exp_stats.py "
        f"--db {db_path} --assembly <ASSEMBLY_NAME>"
    )


def load_data(db_path=None):
    """Load per-experiment part-level operating stats joined with each part's magnet.

    Parts are not a direct column on ``experiments``: each experiment runs
    on an assembly, ``assembly_magnets`` links that assembly to the magnet(s) mounted
    on it, and ``magnet_parts`` links each magnet to its parts (helices,
    bitters, rings). Joining through both fans one experiment row out into
    one row per part.

    ``Hoop Stress Status`` reflects whether an experiment has an entry in
    ``hoop_stress_processed`` (the actual MPa hoop-stress computation),
    independent of the ``hoop_stress_proxy`` channel below (which is
    ``Icoil^2``, always available once ``exp_part_bin_stats`` is populated).

    Parameters
    ----------
    db_path : str, optional
        Path to the DuckDB database. Defaults to :data:`db.DB_PATH`.

    Returns
    -------
    :class:`~pandas.DataFrame`
        One row per (experiment, part) pair, with columns matching
        ``EXP_PART_BIN_STATS_COLUMNS`` plus ``Housing``.
    """
    db_path = db_path or db.DB_PATH
    con = duckdb.connect(db_path, read_only=True)

    tables = (
        con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        )
        .df()["table_name"]
        .tolist()
    )

    if "exp_part_bin_stats" not in tables:
        con.close()
        _warn_exp_part_bin_stats("does not exist", db_path)
        return pd.DataFrame(columns=EXP_PART_BIN_STATS_COLUMNS)

    n_scalars = con.execute("SELECT COUNT(*) FROM exp_part_bin_stats").fetchone()[0]
    if n_scalars == 0:
        _warn_exp_part_bin_stats("is empty", db_path)

    df = con.execute("""
            SELECT
                e.id AS ID, e.name AS Experiment, p.name AS Part, p.type AS Type,
                mp.magnet_name AS Magnet, e.assembly_name AS Assembly, e.file AS File,
                ROUND(MAX(fo.value) / 3600, 2) AS "Time (h)",
                ROUND(MAX(CASE WHEN s.channel = 'hoop_stress_proxy' THEN s.max_x END), 1) AS "Peak hoop stress proxy (A^2)",
                CASE WHEN hp.experiment_id IS NOT NULL THEN 'Computed' ELSE 'Not computed' END AS "Hoop Stress Status",
            e.status AS Status
            FROM experiments AS e
            JOIN assembly_magnets AS sm ON e.assembly_name = sm.assembly_name
            JOIN magnet_parts AS mp ON mp.magnet_name = sm.magnet_name
            JOIN parts AS p ON p.name = mp.part_name
            LEFT JOIN exp_part_bin_stats AS s ON s.experiment_id = e.id AND s.part_name = p.name
            LEFT JOIN exp_run_scalars AS fo ON fo.experiment_id = e.id AND fo.channel = 'duration_field_on_s'
            LEFT JOIN (SELECT DISTINCT experiment_id FROM hoop_stress_processed) AS hp ON hp.experiment_id = e.id
            WHERE p.type IN ('bitter', 'helix', 'supra')
            GROUP BY e.id, e.name, p.name, p.type, mp.magnet_name, e.assembly_name, e.file, e.status, hp.experiment_id
            ORDER BY p.name, e.name
        """).fetchdf()

    df["Experiment"] = pd.to_datetime(df["Experiment"])
    df["Housing"] = df["Assembly"].str.extract(r"^(M\d+)")

    con.close()

    return df


def load_overview_records(db_path=None):
    """Load all overview_records rows, joined with their assembly and housing.

    Parameters
    ----------
    db_path : str, optional
        Path to the DuckDB database. Defaults to :data:`db.DB_PATH`.

    Returns
    -------
    :class:`~pandas.DataFrame`
        One row per overview record, with ``Overview Record``, ``Assembly``,
        ``Housing``, ``Mode``, and ``t0`` columns.
    """
    db_path = db_path or db.DB_PATH
    con = duckdb.connect(db_path, read_only=True)

    df = con.execute("""
            SELECT
                filename AS "Overview Record",
                assembly_name AS Assembly,
                housing AS Housing,
                mode AS Mode,
                t0
            FROM overview_records
            WHERE merged_into IS NULL
            ORDER BY t0 NULLS LAST, filename
        """).fetchdf()

    con.close()

    return df


_TABLE_MARKDOWN_COLUMNS = {"Experiment", "Part", "Magnet", "Assembly"}

TABLE_COLUMNS = [
    (
        {"name": c, "id": c, "presentation": "markdown"}
        if c in _TABLE_MARKDOWN_COLUMNS
        else {"name": "Magnet Time (h)", "id": c}
        if c == "Time (h)"
        else {"name": c, "id": c}
    )
    for c in EXP_PART_BIN_STATS_COLUMNS
    if c not in ("File", "Peak hoop stress proxy (A^2)")
]

OVERVIEW_RECORD_COLUMNS = [
    (
        {"name": c, "id": c, "presentation": "markdown"}
        if c in ("Overview Record", "Assembly")
        else {"name": c, "id": c}
    )
    for c in ("Overview Record", "Assembly", "Housing", "Mode", "t0")
]

MAGNET_HISTORY_COLUMNS = [
    (
        {"name": c, "id": c, "presentation": "markdown"}
        if c == "magnet_name"
        else {"name": c, "id": c}
    )
    for c in ("magnet_name", "type", "status", "assembled_at", "rank", "coil_index")
]

ASSEMBLY_HISTORY_COLUMNS = [
    (
        {"name": c, "id": c, "presentation": "markdown"}
        if c == "assembly_name"
        else {"name": c, "id": c}
    )
    for c in (
        "assembly_name",
        "housing",
        "status",
        "commissioned_at",
        "decommissioned_at",
    )
]

HOOP_STRESS_SUMMARY_COLUMNS = [
    {"name": c, "id": c}
    for c in (
        "Experiments",
        "Samples",
        "Mean (MPa)",
        "Std dev (MPa)",
        "Peak (MPa)",
        "Cycles",
        "Fatigue proxy (MPa³)",
    )
]

FATIGUE_TABLE_COLUMNS = [
    (
        {"name": c, "id": c, "presentation": "markdown"}
        if c in ("Experiment", "Assembly")
        else {"name": c, "id": c}
    )
    for c in ("ID", "Experiment", "Assembly", "Cycles", "Fatigue proxy (MPa^3)")
]


def _overview_records_section(overview_df, start_date=None, end_date=None):
    """Build the "Overview records" accordion content for a pre-filtered dataframe.

    Parameters
    ----------
    overview_df : :class:`~pandas.DataFrame`
        Rows from :func:`load_overview_records`, already filtered to the
        page's current part selection.
    start_date, end_date : str, optional
        Inclusive ``t0`` date bounds (``"YYYY-MM-DD"``) from the section's
        date-range picker. No date filtering when both are ``None``.

    Returns
    -------
    :class:`~dash.html.Div` or :class:`dash.dash_table.DataTable`
        A "no records" message if *overview_df* is empty, otherwise a
        `DataTable` of its rows (linked into ``/overview-records``).
    """
    overview_df = selectors.filter_by_date_range(overview_df, "t0", start_date, end_date)

    if overview_df.empty:
        return html.Div(
            "No overview records found for the current filters.",
            style={"color": "#888", "fontStyle": "italic"},
        )

    table_df = overview_df.copy()
    table_df["Overview Record"] = table_df.apply(overview_record_link, axis=1)
    table_df["Assembly"] = table_df.apply(assembly_link, axis=1)

    return DataTable(
        columns=OVERVIEW_RECORD_COLUMNS,
        data=table_df.to_dict("records"),
        page_size=10,
        sort_action="native",
        style_table={"overflowX": "auto"},
        style_cell={"textAlign": "center", "padding": "6px"},
        style_header={"fontWeight": "bold"},
    )


def _magnet_history_section(selected_part, db_path):
    """Build the "Magnet history" accordion for the selected part, ascending by magnets.assembled_at."""
    if not selected_part or selected_part == selectors.ALL:
        return html.Div(
            "Select a part above to see its magnet history.",
            style={"color": "#888", "fontStyle": "italic"},
        )

    history = db.get_magnet_history_for_part(selected_part, db_path)
    if not history:
        return html.Div(
            f"No magnet history found for {selected_part}.",
            style={"color": "#888", "fontStyle": "italic"},
        )

    history = [
        {**h, "magnet_name": magnet_link({"Magnet": h["magnet_name"]})} for h in history
    ]

    return DataTable(
        columns=MAGNET_HISTORY_COLUMNS,
        data=history,
        page_size=10,
        sort_action="native",
        style_table={"overflowX": "auto"},
        style_cell={"textAlign": "center", "padding": "6px"},
        style_header={"fontWeight": "bold"},
    )


def _assembly_history_section(selected_part, history):
    """Build the "Assembly history" accordion for the selected part, ascending by assemblies.commissioned_at."""
    if not selected_part or selected_part == selectors.ALL:
        return html.Div(
            "Select a part above to see its assembly history.",
            style={"color": "#888", "fontStyle": "italic"},
        )

    if not history:
        return html.Div(
            f"No assembly history found for {selected_part}.",
            style={"color": "#888", "fontStyle": "italic"},
        )

    history = [
        {**h, "assembly_name": assembly_link({"Assembly": h["assembly_name"]})}
        for h in history
    ]

    return DataTable(
        columns=ASSEMBLY_HISTORY_COLUMNS,
        data=history,
        page_size=10,
        sort_action="native",
        style_table={"overflowX": "auto"},
        style_cell={"textAlign": "center", "padding": "6px"},
        style_header={"fontWeight": "bold"},
    )


def _hoop_stress_banner(text):
    return html.Div(
        text, style={"color": "#888", "fontStyle": "italic", "whiteSpace": "pre-line"}
    )


def _hoop_stress_section(selected_part, db_path):
    """Build the "Hoop stress history" accordion content for the selected part.

    Returns
    -------
    tuple
        ``(banner, table_data, bin_fig, history_fig)`` for the accordion's
        four callback outputs.
    """
    empty_fig = go.Figure()

    if not selected_part or selected_part == selectors.ALL:
        return (
            _hoop_stress_banner("Select a part above to see its hoop-stress history."),
            [],
            empty_fig,
            empty_fig,
        )

    summary = db.get_hoop_stress_summary_for_part(selected_part, db_path)
    if not summary["n_experiments"]:
        return (
            _hoop_stress_banner(
                f"No hoop-stress data computed for {selected_part}. Run, for its assembly:\n"
                "to_duckdb/venv-systempackages/bin/python3 to_duckdb/magnetdb.py "
                f"hoop-stress compute <ASSEMBLY_NAME> --db {db_path}"
            ),
            [],
            empty_fig,
            empty_fig,
        )

    table_data = [
        {
            "Experiments": summary["n_experiments"],
            "Samples": summary["n_samples"],
            "Mean (MPa)": (
                round(summary["mean_MPa"], 1)
                if summary["mean_MPa"] is not None
                else None
            ),
            "Std dev (MPa)": (
                round(summary["stddev_MPa"], 1)
                if summary["stddev_MPa"] is not None
                else None
            ),
            "Peak (MPa)": (
                round(summary["peak_MPa"], 1)
                if summary["peak_MPa"] is not None
                else None
            ),
            "Cycles": round(summary["n_cycles"], 1),
            "Fatigue proxy (MPa³)": round(summary["sum_range3"], 1),
        }
    ]

    bin_df = db.get_hoop_stress_bin_stats_for_part(selected_part, db_path)
    bin_df["bin"] = [
        f"{low:.0f}-{high:.0f}"
        for low, high in zip(bin_df["stress_bin_low"], bin_df["stress_bin_high"])
    ]
    bin_df["hours"] = bin_df["sum_dt"] / 3600
    bin_fig = px.bar(
        bin_df,
        x="bin",
        y="hours",
        category_orders={"bin": bin_df["bin"].tolist()},
        labels={"bin": "Hoop stress (MPa)", "hours": "Time at stress level (h)"},
        title=f"Hoop Stress Distribution — {selected_part}",
    )

    history_df = db.load_hoop_stress_history_for_part(selected_part, db_path)
    if history_df is None:
        history_fig = empty_fig
        banner = _hoop_stress_banner(
            f"Raw hoop-stress history not built yet for {selected_part}. Run:\n"
            "to_duckdb/venv-systempackages/bin/python3 to_duckdb/magnetdb.py "
            f"hoop-stress part-history {selected_part} --db {db_path}"
        )
    else:
        plot_df = downsample_dataframe(
            history_df,
            time_col="timestamp",
            value_cols=["hoop_stress_MPa"],
            config=DownsampleConfig(n_out=1000, method="lttb"),
        )
        history_fig = go.Figure(
            go.Scattergl(
                x=plot_df["timestamp"],
                y=plot_df["hoop_stress_MPa"],
                mode="lines",
                line={"width": 1},
            )
        )
        history_fig.update_layout(
            title=f"Hoop Stress History — {selected_part}",
            xaxis_title="Time",
            yaxis_title="Hoop stress (MPa)",
        )
        banner = ""

    return banner, table_data, bin_fig, history_fig


def _fatigue_section(selected_part, db_path):
    """Build the "Fatigue results" accordion content for the selected part.

    Returns
    -------
    tuple
        ``(banner, table_data, cycles_fig, range3_fig)`` for the accordion's
        four callback outputs.
    """
    empty_fig = go.Figure()

    if not selected_part or selected_part == selectors.ALL:
        return (
            _hoop_stress_banner("Select a part above to see its fatigue results."),
            [],
            empty_fig,
            empty_fig,
        )

    fatigue_df = db.get_hoop_stress_fatigue_for_part(selected_part, db_path)
    if fatigue_df.empty:
        return (
            _hoop_stress_banner(
                f"No fatigue data computed for {selected_part}. Run, for its assembly:\n"
                "to_duckdb/venv-systempackages/bin/python3 to_duckdb/magnetdb.py "
                f"hoop-stress compute <ASSEMBLY_NAME> --db {db_path}"
            ),
            [],
            empty_fig,
            empty_fig,
        )

    table_df = fatigue_df.drop(columns=["File"]).copy()
    table_df["Experiment"] = fatigue_df.apply(experiment_link, axis=1)
    table_df["Assembly"] = fatigue_df.apply(assembly_link, axis=1)

    # Categorical x-axis: with a raw datetime x, Plotly infers bar width from
    # the smallest gap between experiments, which can collapse to near-zero
    # when some are minutes apart but the overall range spans months.
    plot_df = fatigue_df.copy()
    plot_df["Experiment label"] = plot_df["Experiment"].dt.strftime("%Y-%m-%d %H:%M")
    experiment_order = plot_df["Experiment label"].tolist()

    cycles_fig = px.bar(
        plot_df,
        x="Experiment label",
        y="Cycles",
        category_orders={"Experiment label": experiment_order},
        title=f"Rainflow Cycles per Experiment — {selected_part}",
        labels={"Experiment label": "Experiment", "Cycles": "Cycles"},
    )
    range3_fig = px.bar(
        plot_df,
        x="Experiment label",
        y="Fatigue proxy (MPa^3)",
        category_orders={"Experiment label": experiment_order},
        title=f"Fatigue Proxy per Experiment — {selected_part}",
        labels={
            "Experiment label": "Experiment",
            "Fatigue proxy (MPa^3)": "Fatigue proxy (MPa³)",
        },
    )
    # Plotly auto-detects date-like x labels and reverts to a date axis
    # (silently ignoring category_orders) unless the type is forced.
    cycles_fig.update_xaxes(type="category")
    range3_fig.update_xaxes(type="category")

    return "", table_df.to_dict("records"), cycles_fig, range3_fig


def _build_page_content(
    df, selected_part=None, db_path=None, table_start_date=None, table_end_date=None
):
    """Build the figures, table rows, and summary text for a loaded (experiment, part) dataframe.

    Parameters
    ----------
    table_start_date, table_end_date : str, optional
        Inclusive ``Experiment`` date bounds (``"YYYY-MM-DD"``) from the
        Experiments table's date-range picker. Only the returned table rows
        are restricted to this range; figures and summary use the full *df*.
    """
    exp_df = df.drop_duplicates(subset="ID").copy()

    part_order = [p for p in db.get_all_parts(db_path) if p in set(df["Part"])]

    field_on_by_part_magnet = df.groupby(["Part", "Magnet"], as_index=False).agg(
        {"Time (h)": "sum"}
    )
    magnet_order = [
        m
        for m in db.get_all_magnets(db_path)
        if m in set(field_on_by_part_magnet["Magnet"])
    ]

    fig_magnet_time = px.bar(
        field_on_by_part_magnet,
        x="Part",
        y="Time (h)",
        color="Magnet",
        category_orders={"Part": part_order, "Magnet": magnet_order},
        title="Magnet Time per Part (h)",
    )

    table_source_df = selectors.filter_by_date_range(
        df, "Experiment", table_start_date, table_end_date
    )
    table_df = table_source_df.drop(columns=["File"])
    table_df["Experiment"] = table_source_df.apply(experiment_link, axis=1)
    table_df["Part"] = table_source_df.apply(part_link, axis=1)
    table_df["Magnet"] = table_source_df.apply(magnet_link, axis=1)
    table_df["Assembly"] = table_source_df.apply(assembly_link, axis=1)

    counts = db.get_db_counts(db_path)
    parts_line = (
        f"Parts: 1 selected of {counts['parts']}"
        if selected_part and selected_part != selectors.ALL
        else f"Parts: {counts['parts']}"
    )
    summary = [
        html.B(parts_line),
        html.Br(),
        html.B(f"Experiments: {len(exp_df)}"),
        html.Br(),
        f"Processed: {(exp_df['Status'] == 'STATS DONE').sum()}",
        html.Br(),
        html.B(
            f"DB-wide: {counts['assemblies']} assemblies, {counts['magnets']} magnets, "
            f"{counts['overview_records']} overview records"
        ),
    ]

    return (
        fig_magnet_time,
        table_df.to_dict("records"),
        summary,
    )


def layout(part=None, **kwargs):
    return html.Div(
        [
            html.H1("MagnetDB Dashboard"),
            html.Div(
                [
                    selectors.aggregate_filter(
                        "part-stats-status-filter",
                        "Status",
                        style={"width": "250px"},
                    ),
                    selectors.aggregate_filter(
                        "part-stats-part-filter",
                        "Part",
                        style={"width": "400px"},
                        value=part,
                    ),
                ],
                style={"display": "flex", "gap": "30px", "marginBottom": "15px"},
            ),
            html.Div(
                id="part-stats-missing-banner",
                style={"color": "#a94442", "fontWeight": "bold"},
            ),
            html.Div(id="part-stats-summary"),
            html.Br(),
            html.Details(
                [
                    html.Summary(
                        "📈 Hoop stress history",
                        style={"fontWeight": "bold", "cursor": "pointer"},
                    ),
                    html.Div(
                        [
                            html.Div(id="part-stats-hoop-stress-banner"),
                            DataTable(
                                id="part-stats-hoop-stress-table",
                                columns=HOOP_STRESS_SUMMARY_COLUMNS,
                                data=[],
                                style_table={"overflowX": "auto"},
                                style_cell={"textAlign": "center", "padding": "6px"},
                                style_header={"fontWeight": "bold"},
                            ),
                            dcc.Graph(id="part-stats-hoop-stress-fig"),
                            dcc.Graph(id="part-stats-hoop-stress-history-fig"),
                        ],
                        style={"padding": "10px"},
                    ),
                ],
                open=False,
                style={
                    "border": "1px solid #ddd",
                    "borderRadius": "8px",
                    "marginBottom": "20px",
                },
            ),
            html.Br(),
            html.Details(
                [
                    html.Summary(
                        "🔧 Fatigue results",
                        style={"fontWeight": "bold", "cursor": "pointer"},
                    ),
                    html.Div(
                        [
                            html.Div(id="part-stats-fatigue-banner"),
                            DataTable(
                                id="part-stats-fatigue-table",
                                columns=FATIGUE_TABLE_COLUMNS,
                                data=[],
                                page_size=20,
                                sort_action="native",
                                style_table={"overflowX": "auto"},
                                style_cell={"textAlign": "center", "padding": "6px"},
                                style_header={"fontWeight": "bold"},
                            ),
                            dcc.Graph(id="part-stats-fatigue-cycles-fig"),
                            dcc.Graph(id="part-stats-fatigue-range3-fig"),
                        ],
                        style={"padding": "10px"},
                    ),
                ],
                open=False,
                style={
                    "border": "1px solid #ddd",
                    "borderRadius": "8px",
                    "marginBottom": "20px",
                },
            ),
            html.Br(),
            dcc.Graph(id="part-stats-fig-magnet-time"),
            html.Br(),
            html.Details(
                [
                    html.Summary(
                        "📁 Overview records",
                        style={"fontWeight": "bold", "cursor": "pointer"},
                    ),
                    html.Div(
                        [
                            selectors.date_range_filter(
                                "part-stats-overview-date-filter",
                                "Filter by record date (t0)",
                                style={"marginBottom": "10px"},
                            ),
                            html.Div(id="part-stats-overview-records"),
                        ],
                        style={"padding": "10px"},
                    ),
                ],
                open=False,
                style={
                    "border": "1px solid #ddd",
                    "borderRadius": "8px",
                    "marginBottom": "10px",
                },
            ),
            html.Br(),
            html.Details(
                [
                    html.Summary(
                        "📁 Magnet history",
                        style={"fontWeight": "bold", "cursor": "pointer"},
                    ),
                    html.Div(id="part-stats-magnet-history", style={"padding": "10px"}),
                ],
                open=False,
                style={
                    "border": "1px solid #ddd",
                    "borderRadius": "8px",
                    "marginBottom": "10px",
                },
            ),
            html.Details(
                [
                    html.Summary(
                        "📁 Assembly history",
                        style={"fontWeight": "bold", "cursor": "pointer"},
                    ),
                    html.Div(
                        id="part-stats-assembly-history", style={"padding": "10px"}
                    ),
                ],
                open=False,
                style={
                    "border": "1px solid #ddd",
                    "borderRadius": "8px",
                    "marginBottom": "10px",
                },
            ),
            html.Details(
                [
                    html.Summary(
                        "📊 Experiments table",
                        style={"fontWeight": "bold", "cursor": "pointer"},
                    ),
                    html.Div(
                        [
                            selectors.date_range_filter(
                                "part-stats-table-date-filter",
                                "Filter by experiment date",
                                style={"marginBottom": "10px"},
                            ),
                            DataTable(
                                id="part-stats-table",
                                columns=TABLE_COLUMNS,
                                data=[],
                                page_size=20,
                                sort_action="native",
                                style_table={"overflowX": "auto"},
                                style_cell={"textAlign": "center", "padding": "6px"},
                                style_header={"fontWeight": "auto"},
                            ),
                        ],
                        style={"padding": "10px"},
                    ),
                ],
                open=True,
                style={
                    "border": "1px solid #ddd",
                    "borderRadius": "8px",
                    "marginBottom": "20px",
                },
            ),
        ],
        style={"padding": "20px"},
    )


@dash.callback(
    Output("part-stats-fig-magnet-time", "figure"),
    Output("part-stats-fig-magnet-time", "style"),
    Output("part-stats-table", "data"),
    Output("part-stats-summary", "children"),
    Output("part-stats-part-filter", "options"),
    Output("part-stats-status-filter", "options"),
    Output("part-stats-missing-banner", "children"),
    Output("part-stats-overview-records", "children"),
    Output("part-stats-magnet-history", "children"),
    Output("part-stats-assembly-history", "children"),
    Output("part-stats-hoop-stress-banner", "children"),
    Output("part-stats-hoop-stress-table", "data"),
    Output("part-stats-hoop-stress-fig", "figure"),
    Output("part-stats-hoop-stress-history-fig", "figure"),
    Output("part-stats-fatigue-banner", "children"),
    Output("part-stats-fatigue-table", "data"),
    Output("part-stats-fatigue-cycles-fig", "figure"),
    Output("part-stats-fatigue-range3-fig", "figure"),
    Input("dd-database", "value"),
    Input("part-stats-part-filter", "value"),
    Input("part-stats-status-filter", "value"),
    Input("part-stats-table-date-filter", "start_date"),
    Input("part-stats-table-date-filter", "end_date"),
    Input("part-stats-overview-date-filter", "start_date"),
    Input("part-stats-overview-date-filter", "end_date"),
)
def update_part_stats(
    selected_db,
    selected_part,
    selected_status,
    table_start_date,
    table_end_date,
    overview_start_date,
    overview_end_date,
):
    if not selected_db:
        return (
            go.Figure(),
            {},
            [],
            [],
            [],
            [],
            "",
            "",
            "",
            "",
            "",
            [],
            go.Figure(),
            go.Figure(),
            "",
            [],
            go.Figure(),
            go.Figure(),
        )

    df = load_data(selected_db)
    missing_banner = (
        "" if not df.empty else "No experiment data found for this database."
    )

    status_options = [selectors.ALL] + db.get_distinct_statuses("parts", selected_db)
    names_with_status = (
        db.get_names_with_status("parts", selected_status, selected_db)
        if selected_status and selected_status != selectors.ALL
        else None
    )
    part_options = [selectors.ALL] + [
        p
        for p in db.get_all_parts(selected_db)
        if names_with_status is None or p in names_with_status
    ]

    plot_df = df[df["Part"] == selected_part] if selected_part != selectors.ALL else df
    if names_with_status is not None:
        plot_df = plot_df[plot_df["Part"].isin(names_with_status)]
    fig_magnet_time_style = (
        {"display": "none"} if selected_part != selectors.ALL else {}
    )

    (
        fig_magnet_time,
        table_records,
        summary,
    ) = _build_page_content(
        plot_df, selected_part, selected_db, table_start_date, table_end_date
    )

    magnet_history_section = _magnet_history_section(selected_part, selected_db)

    assembly_history = (
        db.get_assembly_history_for_part(selected_part, selected_db)
        if selected_part and selected_part != selectors.ALL
        else []
    )
    assembly_history_section = _assembly_history_section(
        selected_part, assembly_history
    )

    overview_plot_df = load_overview_records(selected_db)
    if selected_part and selected_part != selectors.ALL:
        assembly_names = [row["assembly_name"] for row in assembly_history]
        overview_plot_df = overview_plot_df[
            overview_plot_df["Assembly"].isin(assembly_names)
        ]
    if names_with_status is not None:
        status_assembly_names = db.get_assembly_names_for_parts(
            names_with_status, selected_db
        )
        overview_plot_df = overview_plot_df[
            overview_plot_df["Assembly"].isin(status_assembly_names)
        ]
    overview_records_section = _overview_records_section(
        overview_plot_df, overview_start_date, overview_end_date
    )

    (
        hoop_stress_banner,
        hoop_stress_table,
        hoop_stress_fig,
        hoop_stress_history_fig,
    ) = _hoop_stress_section(selected_part, selected_db)

    (
        fatigue_banner,
        fatigue_table,
        fatigue_cycles_fig,
        fatigue_range3_fig,
    ) = _fatigue_section(selected_part, selected_db)

    return (
        fig_magnet_time,
        fig_magnet_time_style,
        table_records,
        summary,
        part_options,
        status_options,
        missing_banner,
        overview_records_section,
        magnet_history_section,
        assembly_history_section,
        hoop_stress_banner,
        hoop_stress_table,
        hoop_stress_fig,
        hoop_stress_history_fig,
        fatigue_banner,
        fatigue_table,
        fatigue_cycles_fig,
        fatigue_range3_fig,
    )
