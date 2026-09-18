import sys
from pathlib import Path

import flask
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import i18n

_test_app = flask.Flask(__name__)


def test_current_language_falls_back_outside_request_context():
    assert i18n.current_language() == i18n.DEFAULT_LANGUAGE


def test_current_language_reads_flask_g_inside_request_context():
    with _test_app.test_request_context("/"):
        flask.g.language = "fr"
        assert i18n.current_language() == "fr"


def test_current_language_falls_back_when_flask_g_unset_in_request_context():
    with _test_app.test_request_context("/"):
        assert i18n.current_language() == i18n.DEFAULT_LANGUAGE


def test_default_language_for_new_visitors_uses_env_var(monkeypatch):
    monkeypatch.setenv("MAGNETDB_LANGUAGE", "de")
    assert i18n.default_language_for_new_visitors() == "de"


def test_default_language_for_new_visitors_ignores_unsupported_env_var(monkeypatch):
    monkeypatch.setenv("MAGNETDB_LANGUAGE", "es")
    assert i18n.default_language_for_new_visitors() == i18n.DEFAULT_LANGUAGE


def test_default_language_for_new_visitors_falls_back_with_no_env_var(monkeypatch):
    monkeypatch.delenv("MAGNETDB_LANGUAGE", raising=False)
    assert i18n.default_language_for_new_visitors() == i18n.DEFAULT_LANGUAGE


def test_translate_falls_back_to_source_text_when_untranslated():
    assert i18n._("some string with no catalog entry") == "some string with no catalog entry"


@pytest.mark.parametrize(
    ("language", "group", "decimal"),
    [
        ("en", ",", "."),
        ("fr", " ", ","),
        ("de", ".", ","),
        ("nl", ".", ","),
    ],
)
def test_localized_number_format_uses_language_separators(monkeypatch, language, group, decimal):
    monkeypatch.setattr(i18n, "current_language", lambda: language)
    fmt = i18n.localized_number_format(precision=1).to_plotly_json()
    assert fmt["locale"] == {"group": group, "decimal": decimal}


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        ("en", "1/15/24"),
        ("fr", "15/01/2024"),
        ("de", "15.01.24"),
        ("nl", "15-01-2024"),
    ],
)
def test_format_date_uses_language_short_format(monkeypatch, language, expected):
    monkeypatch.setattr(i18n, "current_language", lambda: language)
    assert i18n.format_date(pd.Timestamp("2024-01-15")) == expected


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        ("en", "1,234.50"),
        ("fr", "1 234,50"),
        ("de", "1.234,50"),
        ("nl", "1.234,50"),
    ],
)
def test_format_number_uses_language_separators(monkeypatch, language, expected):
    monkeypatch.setattr(i18n, "current_language", lambda: language)
    assert i18n.format_number(1234.5) == expected


def test_format_date_returns_empty_string_for_missing_values():
    assert i18n.format_date(None) == ""
    assert i18n.format_date(pd.NaT) == ""


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        ("en", "1/15/24, 2:30 PM"),
        ("fr", "15/01/2024 14:30"),
        ("de", "15.01.24, 14:30"),
        ("nl", "15-01-2024, 14:30"),
    ],
)
def test_format_datetime_uses_language_short_format(monkeypatch, language, expected):
    monkeypatch.setattr(i18n, "current_language", lambda: language)
    assert i18n.format_datetime(pd.Timestamp("2024-01-15 14:30:05")) == expected


def test_format_datetime_returns_empty_string_for_missing_values():
    assert i18n.format_datetime(None) == ""
    assert i18n.format_datetime(pd.NaT) == ""
