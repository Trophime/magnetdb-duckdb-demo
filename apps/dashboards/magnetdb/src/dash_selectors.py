import magnetdb_analysis as db
import pandas as pd
from dash import dcc, html
from dash.dash_table import DataTable
from experiment_links import file_viewer_href, magnet_link

ALL = "All"

MAGNETS_TABLE_COLUMNS = [
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
                placeholder=f"Choose a{'n' if label[0].lower() in 'aeiou' else ''} {label.lower()}...",
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
        / Type / Composition / Status / Assembled columns.
    """
    if not assembly_name or assembly_name == ALL:
        return html.Div(
            "Select an assembly above to see its magnets.",
            style={"color": "#888", "fontStyle": "italic"},
        )

    magnets = db.get_magnets_for_assembly(assembly_name, db_path)
    if not magnets:
        return html.Div(
            f"No magnets found for {assembly_name}.",
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
    table_df["Composition"] = table_df["Magnet"].map(composition).fillna("")
    table_df["Description"] = table_df["Description"].fillna("")
    table_df["Magnet"] = table_df.apply(magnet_link, axis=1)

    return DataTable(
        columns=MAGNETS_TABLE_COLUMNS,
        data=table_df.to_dict("records"),
        page_size=10,
        sort_action="native",
        style_table={"overflowX": "auto"},
        style_cell={"textAlign": "center", "padding": "6px"},
        style_header={"fontWeight": "bold"},
    )


def file_stats_banner(duration_seconds, field_stats, pupitre_files=None, assembly_name=None):
    """Build a one-line duration + Field/Champ_magn stats + pupitre-sources summary.

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

    Returns
    -------
    :class:`~dash.html.Div`
        A styled one-line summary, or an empty ``Div`` if *duration_seconds*
        and *field_stats* are ``None`` and *pupitre_files* is empty.
    """
    if duration_seconds is None and field_stats is None and not pupitre_files:
        return html.Div()

    segments = []
    if duration_seconds is not None:
        segments.append(f"Duration: {duration_seconds:.1f} s")
    if field_stats is not None:
        unit_suffix = f" {field_stats['unit']}" if field_stats["unit"] else ""
        segments.append(
            f"{field_stats['column']}: "
            f"min={field_stats['min']:.3g}{unit_suffix}, "
            f"mean={field_stats['mean']:.3g}{unit_suffix}, "
            f"max={field_stats['max']:.3g}{unit_suffix}, "
            f"std={field_stats['std']:.3g}{unit_suffix}"
        )
    if pupitre_files:
        pupitre_children = ["Pupitre sources: "]
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
