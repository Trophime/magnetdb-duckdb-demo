import pandas as pd
from dash import dcc, html

ALL = "All"


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
