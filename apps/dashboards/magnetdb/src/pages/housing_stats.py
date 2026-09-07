import dash
import dash_bootstrap_components as dbc
import dash_selectors as selectors
import duckdb
import magnetdb_analysis as db
import pandas as pd
import plotly.express as px
from dash import Input, Output, dcc, html
from dash.dash_table import DataTable
from experiment_links import assembly_link
from natsort import natsorted
from plotly import graph_objects as go

dash.register_page(__name__, path="/", name="Housings", order=2)


J_TO_KWH = 3.6e6
S_TO_H = 3600
HOUSING_COLORS = {"M9": "red", "M10": "blue"}
_MONTH_LABELS = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
]

COMMISSIONING_COLUMNS = [
    (
        {"name": c, "id": c, "presentation": "markdown"}
        if c == "Assembly"
        else {"name": c, "id": c}
    )
    for c in ("Assembly", "Status", "Commissioned", "Decommissioned")
]


def load_housing_summary(db_path=None, assembly_names=None):
    """Aggregate total energy/field-on time and assembly counts per housing.

    Parameters
    ----------
    db_path : str, optional
        Path to the DuckDB database. Defaults to :data:`db.DB_PATH`.
    assembly_names : collection of str, optional
        Restrict to these assemblies only. Defaults to all assemblies.

    Returns
    -------
    :class:`~pandas.DataFrame`
        One row per housing, with ``Housing``, ``Energy (kWh)``,
        ``Time (h)``, ``Assemblies``, ``In operation``.
    """
    db_path = db_path or db.DB_PATH
    con = duckdb.connect(db_path, read_only=True)

    energy_query = f"""
        SELECT
            a.housing AS Housing,
            ROUND(SUM(CASE WHEN s.channel = 'energy_j' THEN s.value END) / {J_TO_KWH}, 2) AS "Energy (kWh)",
            ROUND(SUM(CASE WHEN s.channel = 'duration_field_on_s' THEN s.value END) / {S_TO_H}, 2) AS "Time (h)"
        FROM experiments AS e
        JOIN assemblies AS a ON a.name = e.assembly_name
        LEFT JOIN exp_run_scalars AS s ON s.experiment_id = e.id
    """
    counts_query = """
        SELECT
            housing AS Housing,
            COUNT(*) AS Assemblies,
            SUM(CASE WHEN status = 'in_operation' THEN 1 ELSE 0 END) AS "In operation"
        FROM assemblies
    """
    params = []
    if assembly_names is not None:
        energy_query += " WHERE a.name = ANY(?)"
        counts_query += " WHERE name = ANY(?)"
        params = [list(assembly_names)]
    energy_query += " GROUP BY a.housing"
    counts_query += " GROUP BY housing"

    energy_df = con.execute(energy_query, params).fetchdf()
    counts_df = con.execute(counts_query, params).fetchdf()
    con.close()

    return counts_df.merge(energy_df, on="Housing", how="left").fillna(0)


def load_field_bin_stats_by_housing(db_path=None, assembly_names=None):
    """Aggregate per-housing magnetic-field-bin time distribution.

    Parameters
    ----------
    db_path : str, optional
        Path to the DuckDB database. Defaults to :data:`db.DB_PATH`.
    assembly_names : collection of str, optional
        Restrict to these assemblies only. Defaults to all assemblies.

    Returns
    -------
    :class:`~pandas.DataFrame`
        One row per ``(Housing, field_bin_low, field_bin_high)``, with
        ``Housing``, ``field_bin_low``, ``field_bin_high`` [T], and
        ``Time (h)`` (summed ``sum_dt`` / 3600). The ``[0, 0.1)`` "field
        off" bin is excluded, so summing ``Time (h)`` per housing matches
        its "Magnet Time (h)" (``duration_field_on_s``, threshold 0.1 T).
        Empty if the table doesn't exist.
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
    if "exp_assembly_bin_stats" not in tables:
        con.close()
        return pd.DataFrame(
            columns=["Housing", "field_bin_low", "field_bin_high", "Time (h)"]
        )

    query = """
        SELECT
            a.housing AS Housing,
            s.field_bin_low,
            s.field_bin_high,
            SUM(s.sum_dt) / 3600 AS "Time (h)"
        FROM exp_assembly_bin_stats AS s
        JOIN experiments AS e ON e.id = s.experiment_id
        JOIN assemblies AS a ON a.name = e.assembly_name
        WHERE s.channel = 'Field' AND s.field_bin_low > 0
    """
    params = []
    if assembly_names is not None:
        query += " AND a.name = ANY(?)"
        params.append(list(assembly_names))
    query += " GROUP BY a.housing, s.field_bin_low, s.field_bin_high ORDER BY a.housing, s.field_bin_low"

    df = con.execute(query, params).fetchdf()
    con.close()

    return df


def load_housing_summary_by_year(db_path=None):
    """Aggregate total energy and field-on time per housing per year.

    Parameters
    ----------
    db_path : str, optional
        Path to the DuckDB database. Defaults to :data:`db.DB_PATH`.

    Returns
    -------
    :class:`~pandas.DataFrame`
        One row per (Housing, Year), with ``Energy (kWh)`` and
        ``Time (h)``.
    """
    db_path = db_path or db.DB_PATH
    con = duckdb.connect(db_path, read_only=True)

    df = con.execute(f"""
        SELECT
            a.housing AS Housing,
            CAST(regexp_extract(e.name, '^(\\d{{4}})', 1) AS INTEGER) AS Year,
            ROUND(SUM(CASE WHEN s.channel = 'energy_j' THEN s.value END) / {J_TO_KWH}, 2) AS "Energy (kWh)",
            ROUND(SUM(CASE WHEN s.channel = 'duration_field_on_s' THEN s.value END) / {S_TO_H}, 2) AS "Time (h)"
        FROM experiments AS e
        JOIN assemblies AS a ON a.name = e.assembly_name
        LEFT JOIN exp_run_scalars AS s ON s.experiment_id = e.id
        GROUP BY Housing, Year
        ORDER BY Year
    """).fetchdf()
    con.close()

    return df.fillna(0)


def load_housing_summary_by_month(year, db_path=None):
    """Aggregate total energy and field-on time per housing per month, for one year.

    Parameters
    ----------
    year : int
        Restrict to experiments starting in this year.
    db_path : str, optional
        Path to the DuckDB database. Defaults to :data:`db.DB_PATH`.

    Returns
    -------
    :class:`~pandas.DataFrame`
        One row per (Housing, Month), with ``Energy (kWh)`` and
        ``Time (h)``. ``Month`` is an integer 1-12.
    """
    db_path = db_path or db.DB_PATH
    con = duckdb.connect(db_path, read_only=True)

    df = con.execute(
        f"""
        SELECT
            a.housing AS Housing,
            CAST(regexp_extract(e.name, '^\\d{{4}}\\.(\\d{{2}})', 1) AS INTEGER) AS Month,
            ROUND(SUM(CASE WHEN s.channel = 'energy_j' THEN s.value END) / {J_TO_KWH}, 2) AS "Energy (kWh)",
            ROUND(SUM(CASE WHEN s.channel = 'duration_field_on_s' THEN s.value END) / {S_TO_H}, 2) AS "Time (h)"
        FROM experiments AS e
        JOIN assemblies AS a ON a.name = e.assembly_name
        LEFT JOIN exp_run_scalars AS s ON s.experiment_id = e.id
        WHERE regexp_extract(e.name, '^(\\d{{4}})', 1) = ?
        GROUP BY Housing, Month
        ORDER BY Month
    """,
        [str(year)],
    ).fetchdf()
    con.close()

    return df.fillna(0)


def load_field_bin_stats_by_housing_year(db_path=None):
    """Aggregate per-housing-per-year magnetic-field-bin time distribution.

    Parameters
    ----------
    db_path : str, optional
        Path to the DuckDB database. Defaults to :data:`db.DB_PATH`.

    Returns
    -------
    :class:`~pandas.DataFrame`
        One row per ``(Housing, Year, field_bin_low, field_bin_high)``,
        with ``Housing``, ``Year``, ``field_bin_low``, ``field_bin_high``
        [T], and ``Time (h)`` (summed ``sum_dt`` / 3600). The ``[0, 0.1)``
        "field off" bin is excluded. Empty if the table doesn't exist.
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
    if "exp_assembly_bin_stats" not in tables:
        con.close()
        return pd.DataFrame(
            columns=["Housing", "Year", "field_bin_low", "field_bin_high", "Time (h)"]
        )

    df = con.execute("""
        SELECT
            a.housing AS Housing,
            CAST(regexp_extract(e.name, '^(\\d{4})', 1) AS INTEGER) AS Year,
            s.field_bin_low,
            s.field_bin_high,
            SUM(s.sum_dt) / 3600 AS "Time (h)"
        FROM exp_assembly_bin_stats AS s
        JOIN experiments AS e ON e.id = s.experiment_id
        JOIN assemblies AS a ON a.name = e.assembly_name
        WHERE s.channel = 'Field' AND s.field_bin_low > 0
        GROUP BY a.housing, Year, s.field_bin_low, s.field_bin_high
        ORDER BY a.housing, Year, s.field_bin_low
    """).fetchdf()
    con.close()

    return df


def load_field_bin_stats_by_housing_month(year, db_path=None):
    """Aggregate per-housing-per-month magnetic-field-bin time distribution, for one year.

    Parameters
    ----------
    year : int
        Restrict to experiments starting in this year.
    db_path : str, optional
        Path to the DuckDB database. Defaults to :data:`db.DB_PATH`.

    Returns
    -------
    :class:`~pandas.DataFrame`
        One row per ``(Housing, Month, field_bin_low, field_bin_high)``,
        with ``Housing``, ``Month`` (integer 1-12), ``field_bin_low``,
        ``field_bin_high`` [T], and ``Time (h)`` (summed ``sum_dt`` /
        3600). The ``[0, 0.1)`` "field off" bin is excluded. Empty if the
        table doesn't exist.
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
    if "exp_assembly_bin_stats" not in tables:
        con.close()
        return pd.DataFrame(
            columns=["Housing", "Month", "field_bin_low", "field_bin_high", "Time (h)"]
        )

    df = con.execute(
        """
        SELECT
            a.housing AS Housing,
            CAST(regexp_extract(e.name, '^\\d{4}\\.(\\d{2})', 1) AS INTEGER) AS Month,
            s.field_bin_low,
            s.field_bin_high,
            SUM(s.sum_dt) / 3600 AS "Time (h)"
        FROM exp_assembly_bin_stats AS s
        JOIN experiments AS e ON e.id = s.experiment_id
        JOIN assemblies AS a ON a.name = e.assembly_name
        WHERE s.channel = 'Field' AND s.field_bin_low > 0
            AND regexp_extract(e.name, '^(\\d{4})', 1) = ?
        GROUP BY a.housing, Month, s.field_bin_low, s.field_bin_high
        ORDER BY a.housing, Month, s.field_bin_low
    """,
        [str(year)],
    ).fetchdf()
    con.close()

    return df


def _add_field_bin_columns(df, percent_group_cols):
    """Add a "Field bin" label column and a per-group "Percent" column to a bin-stats df.

    Parameters
    ----------
    df : :class:`~pandas.DataFrame`
        Must have ``field_bin_low``, ``field_bin_high``, ``Time (h)``
        columns, as returned by the ``load_field_bin_stats_by_housing*``
        functions. Mutated in place with the new ``"Field bin"`` and
        ``"Percent"`` columns.
    percent_group_cols : list of str
        Columns to group by when computing each row's ``Percent`` of its
        group's total ``Time (h)``.

    Returns
    -------
    tuple of (list of str, list of str)
        ``(bin_order, bin_colors)`` -- the field-bin labels in ascending
        field order, and a matching Viridis color for each.
    """
    df["Field bin"] = [
        f"{low:g}-{high:g} T"
        for low, high in zip(df["field_bin_low"], df["field_bin_high"])
    ]
    bin_order = (
        df[["field_bin_low", "Field bin"]]
        .drop_duplicates()
        .sort_values("field_bin_low")["Field bin"]
        .tolist()
    )
    bin_colors = px.colors.sample_colorscale(
        "Viridis", [i / max(len(bin_order) - 1, 1) for i in range(len(bin_order))]
    )
    df["Percent"] = (
        df["Time (h)"]
        / df.groupby(percent_group_cols)["Time (h)"].transform("sum")
        * 100
    )
    return bin_order, bin_colors


def load_commissioning_history(db_path=None, assemblies_in_year=None):
    """Return assemblies grouped by housing, ordered by commissioning date.

    Parameters
    ----------
    db_path : str, optional
        Path to the DuckDB database. Defaults to :data:`db.DB_PATH`.
    assemblies_in_year : set of str, optional
        Restrict to these assembly names only. Defaults to all assemblies.

    Returns
    -------
    dict of str -> list of dict
        Housing name -> list of ``{"Assembly", "Status", "Commissioned",
        "Decommissioned"}`` dicts, ascending by ``Commissioned`` (NULLs last).
        ``Commissioned``/``Decommissioned`` are converted to
        :data:`db.DISPLAY_TZ` for display.
    """
    db_path = db_path or db.DB_PATH
    con = duckdb.connect(db_path, read_only=True)
    df = con.execute("""
        SELECT
            housing AS Housing,
            name AS Assembly,
            status AS Status,
            commissioned_at AS Commissioned,
            decommissioned_at AS Decommissioned
        FROM assemblies
        WHERE housing IS NOT NULL
        ORDER BY housing, commissioned_at NULLS LAST
    """).fetchdf()
    con.close()

    if df.empty:
        return {}
    if assemblies_in_year is not None:
        df = df[df["Assembly"].isin(assemblies_in_year)]
        if df.empty:
            return {}
    df["Commissioned"] = db.to_display_tz(df["Commissioned"])
    df["Decommissioned"] = db.to_display_tz(df["Decommissioned"])
    df["Assembly"] = df.apply(assembly_link, axis=1)
    return {
        housing: group.drop(columns=["Housing"]).to_dict("records")
        for housing, group in df.groupby("Housing")
    }


def _field_activity_strip(housing, db_path=None, assembly_names=None, year=None):
    """Build a small CSS strip of per-period activity for one housing.

    One cell per month (or, when *year* is given, per week within that
    year): green = at least one experiment or overview record occurred that
    period, blank = none. A red bar marks a period an assembly was
    commissioned; a black bar marks a year boundary (month mode only).
    """
    history = db.get_field_bin_history(
        housing, db_path, assembly_names=assembly_names, year=year
    )
    if not history:
        return html.Div(
            "No commissioning history yet.",
            style={"color": "#888", "fontStyle": "italic"},
        )

    cells = []
    for row in history:
        start, end = row["period_start"], row["period_end"]
        color, label = (
            ("#2ca02c", "activity")
            if row["has_activity"]
            else ("#ffffff", "no activity")
        )
        if year is not None:
            period_desc = f"{start:%b %d} – {end:%b %d} {start.year}"
        else:
            period_desc = f"{_MONTH_LABELS[start.month - 1]} {start.year}"
        cells.append(
            html.Div(
                title=f"{period_desc} — {label}",
                style={
                    "width": "10px",
                    "height": "18px",
                    "backgroundColor": color,
                    "display": "inline-block",
                    "marginRight": "1px",
                    "border": "1px solid #ddd",
                },
            )
        )
        if row["commissioned"]:
            cells.append(
                html.Div(
                    title=f"Commissioned: {', '.join(row['commissioned'])}",
                    style={
                        "width": "3px",
                        "height": "18px",
                        "backgroundColor": "#d62728",
                        "display": "inline-block",
                        "marginRight": "1px",
                    },
                )
            )
        if year is None and start.month == 12:
            cells.append(
                html.Div(
                    style={
                        "width": "3px",
                        "height": "18px",
                        "backgroundColor": "#000000",
                        "display": "inline-block",
                        "marginRight": "1px",
                    },
                )
            )
    return html.Div(
        cells,
        style={"whiteSpace": "nowrap", "overflowX": "auto", "padding": "4px 0"},
    )


def _housing_section(
    housing,
    summary_row,
    commissioning_rows,
    db_path=None,
    assembly_names=None,
    year=None,
):
    """Build one housing's summary card as a collapsible accordion item."""
    energy = summary_row["Energy (kWh)"] if summary_row is not None else 0
    field_on = summary_row["Time (h)"] if summary_row is not None else 0
    n_assemblies = int(summary_row["Assemblies"]) if summary_row is not None else 0
    n_in_operation = int(summary_row["In operation"]) if summary_row is not None else 0

    return dbc.AccordionItem(
        [
            html.Div(
                [
                    html.Span(
                        f"Energy: {energy:,.2f} kWh", style={"marginRight": "25px"}
                    ),
                    html.Span(
                        f"Magnet time: {field_on:,.2f} h", style={"marginRight": "25px"}
                    ),
                    html.Span(
                        f"Assemblies: {n_assemblies} ({n_in_operation} in operation)"
                    ),
                ],
                style={"marginBottom": "10px"},
            ),
            html.Label(
                "Commissioning activity by month:",
                style={"fontSize": "13px", "color": "#555"},
            ),
            _field_activity_strip(housing, db_path, assembly_names, year),
            html.Br(),
            DataTable(
                columns=COMMISSIONING_COLUMNS,
                data=commissioning_rows,
                page_size=10,
                sort_action="native",
                style_table={"overflowX": "auto"},
                style_cell={"textAlign": "center", "padding": "6px"},
                style_header={"fontWeight": "bold"},
            ),
            html.Br(),
            dcc.Link("View all assemblies →", href="/assembly_stats"),
        ],
        title=housing,
        item_id=housing,
    )


def layout(**kwargs):
    return html.Div(
        [
            html.H1("Housing Dashboard"),
            selectors.aggregate_filter(
                "housing-stats-year-filter",
                "Year",
                style={"width": "150px", "marginBottom": "15px"},
            ),
            html.Div(id="housing-stats-summary"),
            dcc.Graph(id="housing-stats-energy-fig"),
            html.Br(),
            dcc.Graph(id="housing-stats-field-bins-fig"),
            html.Br(),
            dcc.Graph(id="housing-stats-energy-year-fig"),
            html.Br(),
            dcc.Graph(id="housing-stats-field-on-year-fig"),
            html.Br(),
            dcc.Graph(id="housing-stats-field-bins-year-fig"),
            html.Br(),
            html.Div(id="housing-stats-sections"),
        ],
        style={"padding": "20px"},
    )


@dash.callback(
    Output("housing-stats-summary", "children"),
    Output("housing-stats-energy-fig", "figure"),
    Output("housing-stats-field-bins-fig", "figure"),
    Output("housing-stats-energy-year-fig", "figure"),
    Output("housing-stats-field-on-year-fig", "figure"),
    Output("housing-stats-field-bins-year-fig", "figure"),
    Output("housing-stats-sections", "children"),
    Output("housing-stats-year-filter", "options"),
    Input("dd-database", "value"),
    Input("housing-stats-year-filter", "value"),
)
def update_housing_stats(selected_db, selected_year):
    if not selected_db:
        return (
            [],
            go.Figure(),
            go.Figure(),
            go.Figure(),
            go.Figure(),
            go.Figure(),
            [],
            [selectors.ALL],
        )

    summary_df = load_housing_summary(selected_db)
    summary_by_year_df = load_housing_summary_by_year(selected_db)
    counts = db.get_db_counts(selected_db)
    housing_order = natsorted(summary_df["Housing"].dropna().unique())

    assemblies_meta = db.load_assemblies_meta(selected_db)
    assemblies_in_year = None
    year_filter = None
    if selected_year and selected_year != selectors.ALL:
        year_filter = int(selected_year)
        assemblies_in_year = db.assemblies_active_in_year(assemblies_meta, year_filter)

    year_range = db.assemblies_year_range(assemblies_meta)
    if year_range is not None:
        year_options = [selectors.ALL] + [
            str(y) for y in range(year_range[0], year_range[1] + 1)
        ]
    else:
        year_options = [selectors.ALL]

    section_summary_df = (
        load_housing_summary(selected_db, assembly_names=assemblies_in_year)
        if assemblies_in_year is not None
        else summary_df
    )
    commissioning = load_commissioning_history(selected_db, assemblies_in_year)

    housing_file_summary_df = db.get_housing_file_summary(
        selected_db, assembly_names=assemblies_in_year
    )
    per_housing_lines = []
    for row in housing_file_summary_df.itertuples():
        per_housing_lines += [
            html.Br(),
            html.Br(),
            html.B(row.housing),
            html.Br(),
            f"Experiments: {row.n_experiments}",
            html.Br(),
            f"Overview records: {row.n_overview_records}",
        ]

    top_summary = [
        html.B(f"Housings: {counts['housings']}"),
        html.Br(),
        html.B(f"Assemblies: {counts['assemblies']}"),
        html.Br(),
        html.B(f"Magnets: {counts['magnets']}"),
        html.Br(),
        html.B(f"Parts: {counts['parts']}"),
        html.Br(),
        html.B(f"Experiments: {counts['experiments']}"),
        html.Br(),
        html.B(f"Overview records: {counts['overview_records']}"),
        *per_housing_lines,
    ]

    year_suffix = f" ({year_filter})" if year_filter is not None else ""

    fig = px.bar(
        section_summary_df,
        x="Housing",
        y="Energy (kWh)",
        color="Housing",
        color_discrete_map=HOUSING_COLORS,
        category_orders={"Housing": housing_order},
        title=f"Total Energy per Housing{year_suffix}",
    )

    field_bin_df = load_field_bin_stats_by_housing(
        selected_db, assembly_names=assemblies_in_year
    )
    if field_bin_df.empty:
        fig_field_bins = go.Figure()
    else:
        bin_order, bin_colors = _add_field_bin_columns(field_bin_df, ["Housing"])

        fig_field_bins = px.bar(
            field_bin_df,
            x="Housing",
            y="Time (h)",
            color="Field bin",
            category_orders={"Housing": housing_order, "Field bin": bin_order},
            color_discrete_sequence=bin_colors,
            custom_data=["Percent"],
            title=f"Magnet Time per Housing by Field Bin (h){year_suffix}",
        )
        fig_field_bins.update_traces(
            hovertemplate=(
                "%{fullData.name}<br>%{x}<br>"
                "%{y:.1f} h (%{customdata[0]:.1f}% of housing total)<extra></extra>"
            )
        )

    if year_filter is not None:
        summary_by_month_df = load_housing_summary_by_month(year_filter, selected_db)

        fig_energy_year = px.bar(
            summary_by_month_df,
            x="Month",
            y="Energy (kWh)",
            color="Housing",
            color_discrete_map=HOUSING_COLORS,
            category_orders={"Housing": housing_order},
            barmode="group",
            title=f"Energy per Housing per Month{year_suffix}",
        )
        fig_energy_year.update_xaxes(
            dtick=1, tickvals=list(range(1, 13)), ticktext=_MONTH_LABELS, title="Month"
        )

        fig_field_on_year = px.bar(
            summary_by_month_df,
            x="Month",
            y="Time (h)",
            color="Housing",
            color_discrete_map=HOUSING_COLORS,
            category_orders={"Housing": housing_order},
            barmode="group",
            title=f"Magnet Time per Housing per Month (h){year_suffix}",
        )
        fig_field_on_year.update_xaxes(
            dtick=1, tickvals=list(range(1, 13)), ticktext=_MONTH_LABELS, title="Month"
        )

        field_bin_period_df = load_field_bin_stats_by_housing_month(
            year_filter, selected_db
        )
        if field_bin_period_df.empty:
            fig_field_bins_year = go.Figure()
        else:
            bin_order_p, bin_colors_p = _add_field_bin_columns(
                field_bin_period_df, ["Housing", "Month"]
            )
            fig_field_bins_year = px.bar(
                field_bin_period_df,
                x="Month",
                y="Time (h)",
                color="Field bin",
                facet_col="Housing",
                category_orders={"Housing": housing_order, "Field bin": bin_order_p},
                color_discrete_sequence=bin_colors_p,
                custom_data=["Percent"],
                title=f"Magnet Time per Housing per Month by Field Bin (h){year_suffix}",
            )
            fig_field_bins_year.update_xaxes(
                dtick=1,
                tickvals=list(range(1, 13)),
                ticktext=_MONTH_LABELS,
                title="Month",
            )
    else:
        fig_energy_year = px.bar(
            summary_by_year_df,
            x="Year",
            y="Energy (kWh)",
            color="Housing",
            color_discrete_map=HOUSING_COLORS,
            category_orders={"Housing": housing_order},
            barmode="group",
            title="Energy per Housing per Year",
        )
        fig_energy_year.update_xaxes(dtick=1, title="Year")

        fig_field_on_year = px.bar(
            summary_by_year_df,
            x="Year",
            y="Time (h)",
            color="Housing",
            color_discrete_map=HOUSING_COLORS,
            category_orders={"Housing": housing_order},
            barmode="group",
            title="Magnet Time per Housing per Year (h)",
        )
        fig_field_on_year.update_xaxes(dtick=1, title="Year")

        field_bin_period_df = load_field_bin_stats_by_housing_year(selected_db)
        if field_bin_period_df.empty:
            fig_field_bins_year = go.Figure()
        else:
            bin_order_p, bin_colors_p = _add_field_bin_columns(
                field_bin_period_df, ["Housing", "Year"]
            )
            fig_field_bins_year = px.bar(
                field_bin_period_df,
                x="Year",
                y="Time (h)",
                color="Field bin",
                facet_col="Housing",
                category_orders={"Housing": housing_order, "Field bin": bin_order_p},
                color_discrete_sequence=bin_colors_p,
                custom_data=["Percent"],
                title="Magnet Time per Housing per Year by Field Bin (h)",
            )
            fig_field_bins_year.update_xaxes(dtick=1, title="Year")

    fig_field_bins_year.update_traces(
        hovertemplate=(
            "%{fullData.name}<br>%{x}<br>"
            "%{y:.1f} h (%{customdata[0]:.1f}% of housing total)<extra></extra>"
        )
    )
    fig_field_bins_year.for_each_annotation(
        lambda a: a.update(text=a.text.split("=")[-1])
    )

    sections = []
    for housing in housing_order:
        matching_rows = section_summary_df[section_summary_df["Housing"] == housing]
        row = matching_rows.iloc[0] if not matching_rows.empty else None
        sections.append(
            _housing_section(
                housing,
                row,
                commissioning.get(housing, []),
                selected_db,
                assemblies_in_year,
                year_filter,
            )
        )

    return (
        top_summary,
        fig,
        fig_field_bins,
        fig_energy_year,
        fig_field_on_year,
        fig_field_bins_year,
        dbc.Accordion(sections),
        year_options,
    )
