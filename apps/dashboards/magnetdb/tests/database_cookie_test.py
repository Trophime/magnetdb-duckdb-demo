import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import magnetdb_app

_DB_A = "/data/a.duckdb"
_DB_B = "/data/b.duckdb"


def _find_component(node, component_id):
    """Return the props of the component with ``component_id`` in a layout JSON tree."""
    if isinstance(node, dict):
        props = node.get("props", {})
        if props.get("id") == component_id:
            return props
        for value in props.values():
            found = _find_component(value, component_id)
            if found is not None:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _find_component(item, component_id)
            if found is not None:
                return found
    return None


@pytest.fixture
def client(monkeypatch):
    options = [{"label": "a.duckdb", "value": _DB_A}, {"label": "b.duckdb", "value": _DB_B}]
    monkeypatch.setattr(magnetdb_app, "_db_options", options)
    monkeypatch.setattr(magnetdb_app, "_default_db_values", [_DB_A, _DB_B])
    monkeypatch.setattr(magnetdb_app, "_default_db", _DB_A)
    return magnetdb_app.server.test_client()


def _selected_db(client):
    layout = client.get("/_dash-layout").get_json()
    return _find_component(layout, "dd-database")["value"]


def test_database_defaults_without_cookie(client):
    assert _selected_db(client) == _DB_A


def test_database_restored_from_cookie(client):
    client.set_cookie(magnetdb_app._DB_COOKIE_NAME, _DB_B)
    assert _selected_db(client) == _DB_B


def test_database_cookie_ignored_when_not_available(client):
    client.set_cookie(magnetdb_app._DB_COOKIE_NAME, "/data/gone.duckdb")
    assert _selected_db(client) == _DB_A
