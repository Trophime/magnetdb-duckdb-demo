import json

import dash_bootstrap_components as dbc
import i18n
import magnetdb_analysis as db
import pandas as pd
from dash import dcc, html
from dash.dash_table import DataTable
from experiment_links import file_viewer_href, magnet_link
from natsort import natsorted

ALL = "All"

# Background of a magnet whose geometry cannot be rebuilt from its parts
# (``magnets.geometry_problem`` set by to_duckdb).
GEOMETRY_PROBLEM_COLOR = "#f8d7da"

# Background of a date cell left empty (date not set in the database).
MISSING_DATE_COLOR = "#fff3cd"

# Fixed file-integrity colours of the experiment tables (PLAN_file_check_rules.md);
# to_duckdb's etl_spec refuses them, and the two above, as tag colours.
TRUNCATED_COLOR = "#ffe5d0"
UNREADABLE_COLOR = "#f1aeb5"

FILE_INTEGRITY_COLUMN = "File integrity"
ETL_CHECKS_COLUMN = "ETL checks"
# hidden column holding each row's colour key, so colours survive sorting
_FLAG_COLUMN = "_flag"


def missing_date_style(*columns, status_column=None):
    """Build ``style_data_conditional`` rules highlighting blank date cells.

    Parameters
    ----------
    *columns : str
        Date column ids. Dates are rendered by :func:`i18n.format_date`,
        which gives ``""`` for a missing date, so the rule is
        ``{col} is blank``. The ``Experiment`` markdown column shows
        ``"NaT"`` when the experiment name does not parse (see
        :func:`experiment_links.experiment_link`), so its rule matches that.
    status_column : str, optional
        Column holding the assembly status; when given, rows whose status
        is ``in_study`` are not highlighted (no commissioning date yet is
        normal for them).

    Returns
    -------
    list[dict]
        One rule per column, in :data:`MISSING_DATE_COLOR`, to append to a
        `DataTable`'s ``style_data_conditional``.
    """
    rules = []
    for col in columns:
        query = f'{{{col}}} contains "NaT"' if col == "Experiment" else f"{{{col}}} is blank"
        if status_column:
            query += f' && {{{status_column}}} != "in_study"'
        rules.append(
            {"if": {"filter_query": query, "column_id": col}, "backgroundColor": MISSING_DATE_COLOR}
        )
    return rules


def graph(figure=None, **kwargs):
    """:class:`~dash.dcc.Graph` pre-configured with the current language's Plotly.js locale.

    Parameters
    ----------
    figure : :class:`~plotly.graph_objects.Figure`, optional
        Figure to display. Omit for a placeholder ``dcc.Graph`` whose
        ``figure`` a page callback fills in later — the ``locale`` config
        set here still applies once that callback sets the figure.
    **kwargs
        Forwarded to :class:`~dash.dcc.Graph` (e.g. ``id``, ``style``).

    Returns
    -------
    :class:`~dash.dcc.Graph`
    """
    if figure is not None:
        kwargs["figure"] = figure
    return dcc.Graph(config={"locale": i18n.current_language()}, **kwargs)


def loading_region(children, target_components=None):
    """:class:`~dash.dcc.Loading` that blurs *children* under a labelled spinner card.

    While loading, the wrapped content stays visible but blurred and dimmed,
    and clicks on it are blocked by ``dcc.Loading``'s own overlay. The card
    sticks near the top of the region so it stays visible in tall regions.

    Parameters
    ----------
    children : dash component or list of dash components
        Content to wrap.
    target_components : dict, optional
        ``{component_id: prop or [props]}`` — only these outputs trigger the
        spinner, so other callbacks writing inside *children* (zoom sync,
        cursor pins, ...) don't. ``None`` reacts to any descendant.

    Returns
    -------
    :class:`~dash.dcc.Loading`
    """
    card = html.Div(
        [
            dbc.Spinner(color="primary", size="sm"),
            html.Span(i18n._("Be patient while data are processed…")),
        ],
        className="mdb-loading-card",
        style={
            "position": "sticky",
            "top": "1rem",
            "alignSelf": "flex-start",
            "marginTop": "16px",
            "display": "flex",
            "alignItems": "center",
            "gap": "10px",
            "padding": "10px 16px",
            "backgroundColor": "#ffffff",
            "borderRadius": "8px",
            "boxShadow": "0 2px 8px rgba(0,0,0,0.15)",
            "fontWeight": "bold",
            "color": "#495057",
        },
    )
    kwargs = {"target_components": target_components} if target_components else {}
    return dcc.Loading(
        children,
        custom_spinner=card,
        overlay_style={
            "visibility": "visible",
            "filter": "blur(3px)",
            "opacity": 0.5,
            "minHeight": "80px",
        },
        parent_style={"transition": "filter 0.2s, opacity 0.2s"},
        delay_show=300,
        show_initially=False,
        **kwargs,
    )

def magnets_table_columns():
    return [
        (
            {"name": c, "id": c, "presentation": "markdown"}
            if c == "Magnet"
            else {"name": c, "id": c}
        )
        for c in ("Magnet", "Description", "Type", "Composition", "Status", "Assembled")
    ]


def entity_count_line(label, total, in_scope_count):
    """One summary line: a plain total, or an "N selected of Total" refinement.

    Parameters
    ----------
    label : str
        Entity name, e.g. ``"Assemblies"``.
    total : int
        DB-wide count for this entity.
    in_scope_count : int
        Count after the page's current filters are applied.

    Returns
    -------
    str
        ``"{label}: {total}"`` when *in_scope_count* equals *total* (no
        filter narrows the set), otherwise
        ``"{label}: {in_scope_count} selected of {total}"``.
    """
    if in_scope_count == total:
        return f"{label}: {total}"
    return f"{label}: {in_scope_count} selected of {total}"


def status_breakdown_text(status_counts, order):
    """One-line "status: count, status: count, ..." summary.

    Parameters
    ----------
    status_counts : dict of str -> int
        From :func:`magnetdb_analysis.get_status_counts`.
    order : list of str
        Status values to include, and their display order. Statuses absent
        from *status_counts* are shown with a count of 0.

    Returns
    -------
    str
    """
    return ", ".join(f"{status}: {status_counts.get(status, 0)}" for status in order)


def _year_housing_pivot_table(by_year_housing):
    """Build a `DataTable` for a year x housing pivot, or a placeholder if empty.

    Parameters
    ----------
    by_year_housing : :class:`~pandas.DataFrame`
        Indexed by year, one column per housing, as returned by
        :func:`magnetdb_analysis.get_database_summary`.

    Returns
    -------
    :class:`~dash.html.Div` or :class:`dash.dash_table.DataTable`
    """
    if by_year_housing.empty:
        return html.Div(
            i18n._("No dated records for the current scope."),
            style={"color": "#888", "fontStyle": "italic"},
        )
    table_df = by_year_housing.reset_index().rename(columns={"year": "Year"})
    return DataTable(
        columns=[
            (
                {"name": c, "id": c}
                if c == "Year"
                else {"name": c, "id": c, "type": "numeric", "format": i18n.localized_number_format(precision=0)}
            )
            for c in table_df.columns
        ],
        data=table_df.to_dict("records"),
        sort_action="native",
        style_table={"overflowX": "auto"},
        style_cell={"textAlign": "center", "padding": "6px"},
        style_header={"fontWeight": "bold"},
    )


def _manips_year_housing_table(by_year_housing):
    """Build a captioned year x housing `DataTable` of manip cells.

    Each cell reads ``"n (exp with / without | ov with / without | no HStop)"``.

    Parameters
    ----------
    by_year_housing : :class:`~pandas.DataFrame`
        ``manips["by_year_housing"]`` from
        :func:`magnetdb_analysis.get_database_summary`.

    Returns
    -------
    :class:`~dash.html.Div`
        Caption and table: one row per year, a ``Total`` column summed over
        housings, then one column per housing (natsorted); cells with no
        manip are left blank.
    """
    count_cols = ["n", "with_exp", "without_exp", "with_ov", "without_ov", "no_hstop"]
    totals = by_year_housing.groupby("year")[count_cols].sum().reset_index()
    cells = pd.concat([by_year_housing, totals.assign(housing="Total")])
    cells["cell"] = [
        "{} ({} / {} | {} / {} | {})".format(*(i18n.format_number(v, precision=0) for v in row))
        for row in cells[count_cols].itertuples(index=False)
    ]
    housings = natsorted(by_year_housing["housing"].unique())
    table_df = (
        cells.pivot(index="year", columns="housing", values="cell")
        .reindex(columns=["Total", *housings])
        .fillna("")
        .reset_index()
        .rename(columns={"year": "Year"})
    )
    return html.Div(
        [
            html.Div(
                i18n._(
                    "Manips (experiments with / without | overview records with / without | no HStop)"
                ),
                style={"fontWeight": "bold"},
            ),
            DataTable(
                columns=[{"name": c, "id": c} for c in table_df.columns],
                data=table_df.to_dict("records"),
                sort_action="native",
                style_table={"overflowX": "auto"},
                style_cell={"textAlign": "center", "padding": "6px"},
                style_header={"fontWeight": "bold"},
            ),
        ]
    )


def database_summary_banner(summary):
    """Render the shared DB-wide (or assembly-scoped) counts summary.

    Parameters
    ----------
    summary : dict
        Result of :func:`magnetdb_analysis.get_database_summary`.

    Returns
    -------
    :class:`~dash.html.Div`
        One line per category (housings, assemblies, magnets, parts,
        manips), plus a collapsed `html.Details` per category (experiments,
        overview records) holding a year x housing pivot `DataTable`. For
        DB-wide summaries the manips line is itself a collapsed
        `html.Details`, with the registered total in its title, holding the
        table from :func:`_manips_year_housing_table`.
    """
    housings, assemblies, magnets, parts = (
        summary["housings"],
        summary["assemblies"],
        summary["magnets"],
        summary["parts"],
    )
    lines = [
        html.Div(
            i18n._("Housings: {n} ({names})").format(
                n=housings["total"], names=", ".join(housings["names"])
            )
        ),
        html.Div(
            [
                i18n._("Assemblies: {n} (").format(n=assemblies["total"]),
                status_breakdown_text(assemblies["by_status"], db.get_distinct_statuses("assemblies")),
                ")",
            ]
        ),
        html.Div(
            [
                i18n._("Magnets: {n} (").format(n=magnets["total"]),
                status_breakdown_text(magnets["by_status"], db.get_distinct_statuses("magnets")),
                ")",
            ]
        ),
        html.Div(
            [
                i18n._("Parts: {n} (helix/bitter/supra: {coil_total} - ").format(
                    n=parts["total"], coil_total=parts["coil_total"]
                ),
                status_breakdown_text(parts["by_status"], db.get_distinct_statuses("parts")),
                ")",
            ]
        ),
    ]

    for label, key in (
        (i18n._("Experiments"), "experiments"),
        (i18n._("Overview records"), "overview_records"),
    ):
        category = summary[key]
        lines.append(
            html.Details(
                [
                    html.Summary(f"{label}: {category['total']}"),
                    _year_housing_pivot_table(category["by_year_housing"]),
                ],
                open=False,
            )
        )

    manips = summary["manips"]
    manips_by_year_housing = manips["by_year_housing"]
    has_manips_table = manips_by_year_housing is not None and not manips_by_year_housing.empty
    if manips["from_date"] is None:
        manips_text = i18n._("Manips: {n}").format(n=manips["total"])
    else:
        dates = {
            "from_date": i18n.format_date(manips["from_date"]),
            "to_date": i18n.format_date(manips["to_date"]),
        }
        if has_manips_table:
            manips_text = i18n._(
                "Manips: {total} registered, {n} unique users ({from_date} → {to_date})"
            ).format(total=manips_by_year_housing["n"].sum(), n=manips["total"], **dates)
        else:
            manips_text = i18n._("Manips: {n} unique users ({from_date} → {to_date})").format(
                n=manips["total"], **dates
            )

    if has_manips_table:
        lines.append(
            html.Details(
                [html.Summary(manips_text), _manips_year_housing_table(manips_by_year_housing)],
                open=False,
            )
        )
    else:
        lines.append(html.Div(manips_text))

    return html.Div(lines)


def cascading_selector(id, label, step_n, value=None):
    """Build a required, cascading-selection dropdown (e.g. Assembly -> Record/File).

    Parameters
    ----------
    id : str
        Dash component id for the ``dcc.Dropdown``.
    label : str
        Text shown above the dropdown (e.g. ``"Choose Assembly"``).
    step_n : int
        Step number shown in the label prefix (e.g. ``1`` -> ``"1. Choose Assembly :"``).
    value : str, optional
        Initial value, typically seeded from the page's URL query string.

    Returns
    -------
    :class:`~dash.html.Div`
        Label plus ``dcc.Dropdown``, matching the existing overview-records /
        file_viewer markup. Options are seeded with ``value`` so its label
        renders immediately, before the options-loading callback runs.
    """
    return html.Div(
        [
            html.Label(f"{step_n}. {label} :", style={"fontWeight": "bold"}),
            dcc.Dropdown(
                id=id,
                options=[value] if value else [],
                value=value,
                placeholder=i18n._("Choose {label}...").format(label=label),
            ),
        ]
    )


def aggregate_filter(id, label, options=None, style=None, value=None):
    """Build an optional aggregate-filter dropdown with an explicit "All" option.

    Parameters
    ----------
    id : str
        Dash component id for the ``dcc.Dropdown``.
    label : str
        Text shown above the dropdown (e.g. ``"Assembly"``).
    options : list of str, optional
        Entries besides :data:`ALL` to seed at layout time (for pages that
        don't populate ``options`` via a callback). Defaults to none.
    style : dict, optional
        CSS style applied to the wrapping ``html.Div``.
    value : str, optional
        Initial value, typically seeded from the page's URL query string.
        Seeded into ``options`` too so its label renders immediately, before
        the options-loading callback runs.

    Returns
    -------
    :class:`~dash.html.Div`
        Label plus ``dcc.Dropdown``, defaulting to :data:`ALL` and
        non-clearable.
    """
    seeded_options = [ALL] + list(options or [])
    if value and value not in seeded_options:
        seeded_options.append(value)
    return html.Div(
        [
            html.Label(label),
            dcc.Dropdown(
                id=id,
                options=seeded_options,
                value=value or ALL,
                clearable=False,
            ),
        ],
        style=style or {},
    )


def newest_first(items):
    """Return date-ordered dropdown entries with the most recent first.

    Data helpers (e.g. :func:`magnetdb_analysis.get_all_assemblies`) return
    oldest-first lists, which also drive chart category order; dropdowns
    reverse them at option-building time instead.

    Parameters
    ----------
    items : list
        Entries sorted oldest first.

    Returns
    -------
    list
        A new list with *items* in reverse order; *items* is left unchanged.
    """
    return list(reversed(items))


def year_options(year_range):
    """Build a Year filter's options, most recent year first.

    Parameters
    ----------
    year_range : tuple of int, optional
        Inclusive ``(min_year, max_year)``, as returned by
        :func:`magnetdb_analysis.assemblies_year_range`.

    Returns
    -------
    list of str
        :data:`ALL` followed by every year of *year_range*, newest first;
        just ``[ALL]`` when *year_range* is ``None``.
    """
    if year_range is None:
        return [ALL]
    return [ALL] + newest_first([str(y) for y in range(year_range[0], year_range[1] + 1)])


def date_range_filter(id, label, style=None):
    """Build a labeled, clearable date-range picker for filtering a table's rows.

    Parameters
    ----------
    id : str
        Dash component id for the ``dcc.DatePickerRange``.
    label : str
        Text shown above the picker (e.g. ``"Filter by experiment date"``).
    style : dict, optional
        CSS style applied to the wrapping ``html.Div``.

    Returns
    -------
    :class:`~dash.html.Div`
        Label plus ``dcc.DatePickerRange``, with both bounds unset (no
        filtering) until the user picks dates.
    """
    return html.Div(
        [
            html.Label(label),
            html.Br(),
            dcc.DatePickerRange(
                id=id,
                display_format="YYYY-MM-DD",
                clearable=True,
            ),
        ],
        style=style or {},
    )


def filter_by_date_range(df, column, start_date, end_date):
    """Filter *df* to rows whose *column* date falls within [*start_date*, *end_date*].

    Parameters
    ----------
    df : :class:`~pandas.DataFrame`
        Rows to filter.
    column : str
        Name of the datetime column to filter on.
    start_date : str or None
        Inclusive lower bound (``"YYYY-MM-DD"``), from a
        ``dcc.DatePickerRange``'s ``start_date``. No lower bound if ``None``.
    end_date : str or None
        Inclusive upper bound (``"YYYY-MM-DD"``), from a
        ``dcc.DatePickerRange``'s ``end_date``. No upper bound if ``None``.

    Returns
    -------
    :class:`~pandas.DataFrame`
        *df* unchanged if it's empty or neither bound is set; otherwise the
        rows whose *column* date lies in the closed range. Rows with a null
        *column* value are excluded once a bound is set.
    """
    if df.empty or (not start_date and not end_date):
        return df

    dates = pd.to_datetime(df[column]).dt.date
    mask = pd.Series(True, index=df.index)
    if start_date:
        mask &= dates >= pd.to_datetime(start_date).date()
    if end_date:
        mask &= dates <= pd.to_datetime(end_date).date()
    return df[mask]


def magnets_table_section(assembly_name, db_path=None):
    """Build a `DataTable` of an assembly's magnets, or a placeholder message.

    Parameters
    ----------
    assembly_name : str or None
        Assembly name from the page's selector. A placeholder is returned
        if this is ``None`` or :data:`ALL`.
    db_path : str, optional
        Path to the DuckDB database.

    Returns
    -------
    :class:`~dash.html.Div` or :class:`dash.dash_table.DataTable`
        Placeholder text if no assembly is selected, a "no magnets" message
        if the assembly has none, or a `DataTable` with Magnet / Description
        / Type / Composition / Status / Assembled columns. A magnet whose
        geometry cannot be rebuilt from its parts has its Magnet cell in
        :data:`GEOMETRY_PROBLEM_COLOR`, with the error as tooltip; an empty
        Assembled cell is in :data:`MISSING_DATE_COLOR`.
    """
    if not assembly_name or assembly_name == ALL:
        return html.Div(
            i18n._("Select an assembly above to see its magnets."),
            style={"color": "#888", "fontStyle": "italic"},
        )

    magnets = db.get_magnets_for_assembly(assembly_name, db_path)
    if not magnets:
        return html.Div(
            i18n._("No magnets found for {assembly}.").format(assembly=assembly_name),
            style={"color": "#888", "fontStyle": "italic"},
        )

    composition = db.get_magnet_part_composition([m["name"] for m in magnets], db_path)

    table_df = pd.DataFrame(magnets).rename(
        columns={
            "name": "Magnet",
            "type": "Type",
            "status": "Status",
            "description": "Description",
            "assembled_at": "Assembled",
        }
    )
    problems = dict(zip(table_df["Magnet"], table_df.pop("geometry_problem")))
    table_df["Composition"] = table_df["Magnet"].map(composition).fillna("")
    table_df["Description"] = table_df["Description"].fillna("")
    table_df["Magnet"] = table_df.apply(magnet_link, axis=1)
    table_df["Assembled"] = table_df["Assembled"].apply(i18n.format_date)

    return DataTable(
        columns=magnets_table_columns(),
        data=table_df.to_dict("records"),
        page_size=10,
        sort_action="native",
        style_table={"overflowX": "auto"},
        style_cell={"textAlign": "center", "padding": "6px"},
        style_header={"fontWeight": "bold"},
        style_data_conditional=[
            {
                "if": {"filter_query": f'{{Magnet}} contains "[{name}]"', "column_id": "Magnet"},
                "backgroundColor": GEOMETRY_PROBLEM_COLOR,
            }
            for name, problem in problems.items()
            if problem
        ]
        + missing_date_style("Assembled"),
        tooltip_data=[
            {"Magnet": {"value": problem, "type": "text"}} if problem else {}
            for problem in problems.values()
        ],
        tooltip_duration=None,
    )


def file_stats_banner(
    duration_seconds,
    field_stats,
    pupitre_files=None,
    assembly_name=None,
    energy_stats=None,
    zoomed=False,
):
    """Build a one-line duration + Field/Champ_magn stats + Energy + pupitre-sources summary.

    Parameters
    ----------
    duration_seconds : float or None
        Duration in seconds, or ``None`` if unavailable.
    field_stats : dict or None
        Result of :func:`magnetdb_analysis.get_field_column_stats`, or
        ``None`` if no Field/Champ_magn column was found.
    pupitre_files : list of str, optional
        ``overview_records.sources_pupitre`` filenames for this record.
        Omitted from the summary if ``None`` or empty.
    assembly_name : str, optional
        Assembly owning *pupitre_files*, used to link each filename to
        ``/file_viewer`` pre-loaded with that file (see
        :func:`experiment_links.file_viewer_href`). Filenames render as
        plain text (no link) when not given.
    energy_stats : dict, optional
        Result of :func:`magnetdb_analysis.get_energy_stats`, or ``None`` if
        no power channel was found. Omitted from the summary when ``None``.
    zoomed : bool, optional
        When ``True``, *duration_seconds*/*field_stats*/*energy_stats* are
        understood to cover the current graph zoom rather than the whole
        file/record, and the banner is suffixed accordingly.

    Returns
    -------
    :class:`~dash.html.Div`
        A styled one-line summary, or an empty ``Div`` if *duration_seconds*,
        *field_stats* and *energy_stats* are all ``None`` and *pupitre_files*
        is empty.
    """
    if (
        duration_seconds is None
        and field_stats is None
        and energy_stats is None
        and not pupitre_files
    ):
        return html.Div()

    segments = []
    if duration_seconds is not None:
        segments.append(i18n._("Duration: {value:.1f} s").format(value=duration_seconds))
    if field_stats is not None:
        unit_suffix = f" {field_stats['unit']}" if field_stats["unit"] else ""
        segments.append(
            f"{field_stats['column']}: "
            f"min={field_stats['min']:.3g}{unit_suffix}, "
            f"mean={field_stats['mean']:.3g}{unit_suffix}, "
            f"max={field_stats['max']:.3g}{unit_suffix}, "
            f"std={field_stats['std']:.3g}{unit_suffix}"
        )
    if energy_stats is not None:
        segments.append(
            i18n._("Energy: {value:.3g} MWh").format(value=energy_stats["energy_mwh"])
        )
    if zoomed:
        segments.append(i18n._("(zoomed range)"))
    if pupitre_files:
        pupitre_children = [i18n._("Pupitre sources: ")]
        for i, fname in enumerate(pupitre_files):
            if i:
                pupitre_children.append(", ")
            if assembly_name:
                pupitre_children.append(html.A(fname, href=file_viewer_href(assembly_name, fname)))
            else:
                pupitre_children.append(fname)
        segments.append(html.Span(pupitre_children))

    if len(segments) == 1 and isinstance(segments[0], str):
        content = segments[0]
    else:
        content = []
        for i, segment in enumerate(segments):
            if i:
                content.append(" | ")
            content.append(segment)

    return html.Div(
        content,
        style={"fontStyle": "italic", "color": "#333", "padding": "6px 0"},
    )


# ---------------------------------------------------------------------------
# File quality and ETL checks (PLAN_file_check_rules.md step 6)
# ---------------------------------------------------------------------------


def _json_value(value):
    """Parse a JSON column value (text or already parsed); None for missing values."""
    if isinstance(value, str):
        return json.loads(value)
    if isinstance(value, (list, dict)):
        return value
    return None


def file_integrity_label(file_integrity):
    """Return the ``File integrity`` cell text: ``ok`` / ``truncated`` / ``unreadable``, blank if not checked."""
    return file_integrity if isinstance(file_integrity, str) else ""


def etl_checks_label(etl_checks):
    """Return the ``ETL checks`` cell text.

    Parameters
    ----------
    etl_checks : str or list or None
        ``experiments.etl_checks`` (JSON text or parsed list).

    Returns
    -------
    str
        Blank when not checked or empty, ``load error`` when the file could
        not be loaded, ``N failed`` when N checks failed, else ``ok``.
        Checks that could not be evaluated (``ok: None``) do not count.
    """
    checks = _json_value(etl_checks) or []
    if not checks:
        return ""
    if any(c.get("kind") == "load" for c in checks):
        return i18n._("load error")
    n_failed = sum(c.get("ok") is False for c in checks)
    return i18n._("{n} failed").format(n=n_failed) if n_failed else "ok"


def _check_line(check):
    """One tooltip line for a failed or not evaluated ETL check."""
    kind = check.get("kind")
    if kind == "rule":
        if check.get("ok") is None:
            missing = ", ".join(check.get("missing") or [])
            if missing:
                return i18n._("{name}: not evaluated (missing {columns})").format(
                    name=check.get("name"), columns=missing
                )
            return i18n._("{name}: not evaluated").format(name=check.get("name"))
        unit = f" {check['unit']}" if check.get("unit") else ""
        value = check.get("value")
        value_text = f"{value:.4g}" if isinstance(value, (int, float)) else "?"
        tag = f" ({check['tag']})" if check.get("tag") else ""
        return (
            f"{check.get('name')}: {check.get('stat')} = {value_text}{unit} "
            f"> {check.get('tol'):g}{unit}{tag}"
        )
    if kind == "channel":
        fields = ", ".join(f"{k} = {v:.4g}" for k, v in (check.get("fields") or {}).items())
        return i18n._("channel {n} not empty: {fields}").format(n=check.get("channel"), fields=fields)
    if kind == "housing_version":
        return i18n._("housing version: spec {spec}, data {data}").format(
            spec=check.get("spec"), data=check.get("data")
        )
    if kind == "load":
        return i18n._("load error: {reason}").format(reason=check.get("reason", ""))
    return json.dumps(check)


def etl_checks_tooltip(etl_checks):
    """Return the ``ETL checks`` tooltip (markdown list): failed checks, then those not evaluated.

    Parameters
    ----------
    etl_checks : str or list or None
        ``experiments.etl_checks`` (JSON text or parsed list).

    Returns
    -------
    str
        Every failed check, tagged or not (rules, channels, housing version,
        load error), then the rules that could not be evaluated; blank when
        there is none.
    """
    checks = _json_value(etl_checks) or []
    shown = [c for c in checks if c.get("ok") is False or c.get("kind") == "load"]
    shown += [c for c in checks if c.get("ok") is None and c.get("kind") != "load"]
    return "\n".join(f"- {_check_line(c)}" for c in shown)


def file_integrity_tooltip(file_checks):
    """Return the ``File integrity`` tooltip (markdown list) from ``experiments.file_checks``; blank if none."""
    details = _json_value(file_checks) or {}
    labels = (
        ("reason", i18n._("reason")),
        ("rows_read", i18n._("rows read")),
        ("rows_dropped", i18n._("rows dropped")),
    )
    return "\n".join(f"- {label}: {details[key]}" for key, label in labels if key in details)


def tags_tooltip(tags):
    """Return the ``Experiment`` tooltip (markdown list): each tag with its rules and description."""
    by_tag = {}
    for tag in tags:
        by_tag.setdefault(tag["tag"], {"rules": [], "description": tag.get("description")})
        by_tag[tag["tag"]]["rules"].append(tag["rule"])
    lines = []
    for name, info in by_tag.items():
        description = f": {info['description']}" if info["description"] else ""
        lines.append(f"- {name} ({', '.join(info['rules'])}){description}")
    return "\n".join(lines)


def experiment_flag(file_integrity, etl_checks, tags):
    """Return the colour of an experiment row, and the cell that causes it.

    Parameters
    ----------
    file_integrity : str or None
        ``experiments.file_integrity``.
    etl_checks : str or list or None
        ``experiments.etl_checks``.
    tags : list of dict
        The file's tags (:func:`magnetdb_analysis.get_file_tags`).

    Returns
    -------
    dict or None
        ``{"key", "color", "column"}`` by precedence: ``unreadable``, an ETL
        ``load error`` (both :data:`UNREADABLE_COLOR`), ``truncated``
        (:data:`TRUNCATED_COLOR`), then the tag with the highest severity
        (ties by name); ``None`` for a clean or unchecked file.
    """
    if file_integrity == "unreadable":
        return {"key": "unreadable", "color": UNREADABLE_COLOR, "column": FILE_INTEGRITY_COLUMN}
    if any(c.get("kind") == "load" for c in _json_value(etl_checks) or []):
        return {"key": "load error", "color": UNREADABLE_COLOR, "column": ETL_CHECKS_COLUMN}
    if file_integrity == "truncated":
        return {"key": "truncated", "color": TRUNCATED_COLOR, "column": FILE_INTEGRITY_COLUMN}
    if tags:
        top = min(tags, key=lambda t: (-t["severity"], t["tag"]))
        return {"key": top["tag"], "color": top["color"], "column": ETL_CHECKS_COLUMN}
    return None


def _check_flag(check):
    """:func:`experiment_flag` of a :func:`magnetdb_analysis.get_file_checks_for_assembly` entry (or None)."""
    if not check:
        return None
    return experiment_flag(check.get("file_integrity"), check.get("etl_checks"), check.get("tags") or [])


def file_option(file, check):
    """Return the File viewer's ``dd-file`` option for *file*, coloured like its experiment row.

    Parameters
    ----------
    file : str
        ``experiments.file``.
    check : dict or None
        Its :func:`magnetdb_analysis.get_file_checks_for_assembly` entry.

    Returns
    -------
    dict
        ``{"label", "value"}``; for a flagged file (:func:`experiment_flag`)
        the label is a coloured ``Span`` and ``search`` keeps it searchable.
    """
    flag = _check_flag(check)
    if not flag:
        return {"label": file, "value": file}
    label = html.Span(file, style={"backgroundColor": flag["color"], "padding": "0 4px",
                                   "borderRadius": "3px"})
    return {"label": label, "value": file, "search": file}


def file_check_note(check):
    """Return the note shown under the File viewer's file selector.

    Parameters
    ----------
    check : dict or None
        The selected file's :func:`magnetdb_analysis.get_file_checks_for_assembly` entry.

    Returns
    -------
    :class:`~dash.html.Div` or str
        For a flagged file, a box in its colour with the file integrity, the
        tags and the failed or not evaluated ETL checks; ``""`` otherwise.
    """
    flag = _check_flag(check)
    if not flag:
        return ""
    lines = [
        f"**{i18n._('File integrity')}**: {file_integrity_label(check.get('file_integrity')) or '–'}"
        f" · **{i18n._('ETL checks')}**: {etl_checks_label(check.get('etl_checks')) or '–'}"
    ]
    for text in (
        tags_tooltip(check.get("tags") or []),
        file_integrity_tooltip(check.get("file_checks")),
        etl_checks_tooltip(check.get("etl_checks")),
    ):
        if text:
            lines.append(text)
    return html.Div(
        dcc.Markdown("\n\n".join(lines)),
        style={"backgroundColor": flag["color"], "padding": "6px 12px", "borderRadius": "6px",
               "marginTop": "6px"},
    )


def _legend_chip(text, color, title=None):
    return html.Span(
        text,
        title=title,
        style={"backgroundColor": color, "padding": "2px 6px", "marginLeft": "6px",
               "borderRadius": "4px", "whiteSpace": "nowrap"},
    )


def file_check_legend(tags):
    """Return the one-line colour legend: the two file-integrity colours, then *tags* (most severe first)."""
    distinct = {}
    for tag in tags:
        distinct.setdefault(tag["tag"], tag)
    chips = [
        _legend_chip(i18n._("truncated"), TRUNCATED_COLOR),
        _legend_chip(i18n._("unreadable / load error"), UNREADABLE_COLOR),
    ] + [
        _legend_chip(t["tag"], t["color"], t.get("description"))
        for t in sorted(distinct.values(), key=lambda t: (-t["severity"], t["tag"]))
    ]
    return html.Div(
        [html.Span(i18n._("Colours:"), style={"fontStyle": "italic"})] + chips,
        style={"marginBottom": "6px", "fontSize": "0.9em"},
    )


def experiment_table(
    table_df, columns, tags_by_id, id_column="ID", page_size=10, extra_style=None, table_id=None
):
    """Build an experiment `DataTable` with its file-check columns, colours, tooltips and legend.

    Parameters
    ----------
    table_df : :class:`~pandas.DataFrame`
        Rows to show, already formatted (links, dates), with an *id_column*
        (``experiments.id``) and the raw ``file_integrity``, ``file_checks``
        and ``etl_checks`` columns (missing values allowed).
    columns : list of dict
        `DataTable` columns for the page's own fields; ``File integrity``,
        ``ETL checks`` and the hidden flag column are appended.
    tags_by_id : dict[int, list[dict]]
        :func:`magnetdb_analysis.get_file_tags`.
    id_column : str, optional
        Column holding ``experiments.id``.
    page_size : int, optional
        Rows per page.
    extra_style : list of dict, optional
        Other ``style_data_conditional`` rules (e.g. :func:`missing_date_style`),
        kept first.
    table_id : str, optional
        Component id of the `DataTable`.

    Returns
    -------
    :class:`~dash.html.Div`
        The legend (:func:`file_check_legend`) above the `DataTable`. The
        ``Experiment`` cell and the cell causing it take the row's colour
        (:func:`experiment_flag`), keyed on a hidden column so it survives
        sorting; cells are not selectable (Dash's highlight of the clicked
        cell looked like a flag).
    """
    data, tooltips, flags, present_tags = [], [], {}, []
    for record in table_df.to_dict("records"):
        integrity = record.pop("file_integrity", None)
        integrity = integrity if isinstance(integrity, str) else None
        file_checks = record.pop("file_checks", None)
        etl_checks = record.pop("etl_checks", None)
        exp_id = record.get(id_column)
        tags = tags_by_id.get(int(exp_id), []) if pd.notna(exp_id) else []
        flag = experiment_flag(integrity, etl_checks, tags)

        record[FILE_INTEGRITY_COLUMN] = file_integrity_label(integrity)
        record[ETL_CHECKS_COLUMN] = etl_checks_label(etl_checks)
        record[_FLAG_COLUMN] = flag["key"] if flag else ""
        if flag:
            flags[flag["key"]] = flag
        present_tags += tags

        tooltip = {}
        for column, text in (
            ("Experiment", tags_tooltip(tags)),
            (FILE_INTEGRITY_COLUMN, file_integrity_tooltip(file_checks)),
            (ETL_CHECKS_COLUMN, etl_checks_tooltip(etl_checks)),
        ):
            if text:
                tooltip[column] = {"value": text, "type": "markdown"}
        data.append(record)
        tooltips.append(tooltip)

    flag_rules = [
        {"if": {"filter_query": f'{{{_FLAG_COLUMN}}} = "{key}"', "column_id": column},
         "backgroundColor": flag["color"]}
        for key, flag in flags.items()
        for column in ("Experiment", flag["column"])
    ]
    table_kwargs = {"id": table_id} if table_id else {}
    table = DataTable(
        columns=list(columns) + [
            {"name": i18n._("File integrity"), "id": FILE_INTEGRITY_COLUMN},
            {"name": i18n._("ETL checks"), "id": ETL_CHECKS_COLUMN},
            {"name": _FLAG_COLUMN, "id": _FLAG_COLUMN},
        ],
        data=data,
        page_size=page_size,
        sort_action="native",
        style_table={"overflowX": "auto"},
        style_cell={"textAlign": "center", "padding": "6px"},
        style_header={"fontWeight": "bold"},
        style_data_conditional=list(extra_style or []) + flag_rules,
        tooltip_data=tooltips,
        tooltip_duration=None,
        hidden_columns=[_FLAG_COLUMN],
        # no "Toggle columns" button for the hidden flag column
        css=[{"selector": ".show-hide", "rule": "display: none"}],
        cell_selectable=False,
        **table_kwargs,
    )
    return html.Div([file_check_legend(present_tags), table])
