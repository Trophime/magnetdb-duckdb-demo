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
