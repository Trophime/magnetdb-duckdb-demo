"""Per-request language resolution, gettext translation, and Babel-based
number/date formatting, shared by every page.

The active language is per-*request*, not a process-wide global: it's read
from a ``language`` cookie into ``flask.g.language`` by a
``server.before_request`` hook registered in ``magnetdb_app.py``, so
concurrent visitors on different gunicorn threads never see each other's
language (a plain module global would race under the Dockerfile's default
``THREADS=4``). Outside a request context (tests, scripts), functions here
fall back to :data:`DEFAULT_LANGUAGE`.
"""

import gettext
import logging
import os
from pathlib import Path

import flask
import pandas as pd
from babel.dates import format_date as _babel_format_date
from babel.dates import format_datetime as _babel_format_datetime
from babel.numbers import format_decimal, get_decimal_symbol, get_group_symbol

logger = logging.getLogger(__name__)

SUPPORTED_LANGUAGES = ("en", "fr", "de", "nl")
DEFAULT_LANGUAGE = "en"
COOKIE_NAME = "language"

_DOMAIN = "magnetdb"
_LOCALE_DIR = Path(__file__).parent / "locales"

# Loaded once at import — compiled catalogs are read-only after loading, so
# sharing them across threads/requests is safe (unlike a mutable "current
# language" global would be).
_TRANSLATIONS = {
    lang: gettext.translation(
        _DOMAIN, localedir=_LOCALE_DIR, languages=[lang], fallback=True
    )
    for lang in SUPPORTED_LANGUAGES
}


def default_language_for_new_visitors() -> str:
    """Language assigned to a visitor with no ``language`` cookie yet.

    Returns
    -------
    str
        ``$MAGNETDB_LANGUAGE`` if set and one of :data:`SUPPORTED_LANGUAGES`,
        else :data:`DEFAULT_LANGUAGE`.
    """
    env_language = os.environ.get("MAGNETDB_LANGUAGE")
    if env_language:
        if env_language in SUPPORTED_LANGUAGES:
            return env_language
        logger.warning(
            "Unsupported $MAGNETDB_LANGUAGE=%s — using %s", env_language, DEFAULT_LANGUAGE
        )
    return DEFAULT_LANGUAGE


def current_language() -> str:
    """Resolve the active request's language.

    Returns
    -------
    str
        ``flask.g.language``, set by the ``before_request`` hook from the
        visitor's ``language`` cookie. Falls back to :data:`DEFAULT_LANGUAGE`
        outside a request context (tests, scripts, CLI tools).
    """
    if flask.has_request_context():
        return getattr(flask.g, "language", DEFAULT_LANGUAGE)
    return DEFAULT_LANGUAGE


def _(text: str) -> str:
    """Translate *text* into :func:`current_language`.

    Falls back to *text* unchanged if no translation exists — same
    behavior gettext always has for an untranslated msgid.
    """
    return _TRANSLATIONS[current_language()].gettext(text)


def localized_number_format(precision: int = 1, group: bool = True) -> "Format":
    """Build a :class:`~dash.dash_table.Format.Format` for :func:`current_language`.

    ``dash.dash_table`` is imported locally here rather than at module level,
    so plain ``import i18n`` (for :func:`_`) stays usable from modules that
    deliberately have no Dash dependency, e.g. :mod:`magnetdb_plot`.

    Parameters
    ----------
    precision : int, optional
        Number of digits after the decimal point.
    group : bool, optional
        Whether to group digits with the locale's thousands separator.

    Returns
    -------
    :class:`~dash.dash_table.Format.Format`
        Configured with the current language's decimal/group symbols.
    """
    from dash.dash_table.Format import Format, Group, Scheme

    lang = current_language()
    fmt = Format(
        precision=precision, scheme=Scheme.fixed, group=Group.yes if group else Group.no
    )
    fmt.group_delimiter(get_group_symbol(lang))
    fmt.decimal_delimiter(get_decimal_symbol(lang))
    return fmt


def format_number(value, precision: int = 2) -> str:
    """Format a plain number as text for :func:`current_language`.

    For numbers embedded directly in HTML text (e.g. an ``html.Span``)
    rather than a `DataTable` column — see :func:`localized_number_format`
    for the latter.

    Parameters
    ----------
    value : int or float
        Value to format.
    precision : int, optional
        Number of digits after the decimal point.

    Returns
    -------
    str
        Locale-formatted number, grouped by thousands.
    """
    pattern = "#,##0" + ("." + "0" * precision if precision else "")
    return format_decimal(value, format=pattern, locale=current_language())


def format_date(value, format: str = "short") -> str:
    """Format a date/datetime value for :func:`current_language`.

    Parameters
    ----------
    value : :class:`~datetime.date`, :class:`~datetime.datetime`, or :class:`~pandas.Timestamp`
        Value to format; ``None``/``NaT`` returns ``""``.
    format : str, optional
        Babel date format: ``"short"``, ``"medium"``, or ``"long"``.

    Returns
    -------
    str
        Locale-formatted date string.
    """
    if value is None or pd.isna(value):
        return ""
    return _babel_format_date(value, format=format, locale=current_language())


def format_datetime(value, format: str = "short") -> str:
    """Format a datetime value (date + time of day) for :func:`current_language`.

    Use this instead of :func:`format_date` where the time of day matters
    (e.g. an audit-log timestamp) — :func:`format_date` drops it.

    Parameters
    ----------
    value : :class:`~datetime.datetime` or :class:`~pandas.Timestamp`
        Value to format; ``None``/``NaT`` returns ``""``.
    format : str, optional
        Babel datetime format: ``"short"``, ``"medium"``, or ``"long"``.

    Returns
    -------
    str
        Locale-formatted date + time string.
    """
    if value is None or pd.isna(value):
        return ""
    return _babel_format_datetime(value, format=format, locale=current_language())
