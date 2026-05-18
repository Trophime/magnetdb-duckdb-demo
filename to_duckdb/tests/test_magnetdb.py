"""Integration tests for magnetdb.py — the unified CLI entry point."""

import json

import duckdb
import pytest

import magnetdb as cli_module
from magnetdb import main
from add_magnet import add_magnet
from add_site import add_site
from schema import ensure_schema
from tests.conftest import MAGNET_JSON, SITE_JSON


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _count(db_path, table):
    with duckdb.connect(str(db_path), read_only=True) as con:
        return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _fetch_one(db_path, sql, params=None):
    with duckdb.connect(str(db_path), read_only=True) as con:
        return con.execute(sql, params or []).fetchone()


def _db_with_magnet(tmp_path):
    db = tmp_path / "test.duckdb"
    add_magnet(MAGNET_JSON, db)
    return db


def _db_with_site(tmp_path):
    db = _db_with_magnet(tmp_path)
    add_site(SITE_JSON, db)
    return db


def _run(monkeypatch, *argv):
    monkeypatch.setattr("sys.argv", ["magnetdb", *argv])
    main()


# ---------------------------------------------------------------------------
# magnet add
# ---------------------------------------------------------------------------


def test_cli_magnet_add_creates_magnet(tmp_path, monkeypatch):
    json_path = tmp_path / "MAG_JSON.json"
    json_path.write_text(json.dumps(MAGNET_JSON))
    db_path = tmp_path / "test.duckdb"

    _run(monkeypatch, "magnet", "add", str(json_path), "--db", str(db_path))

    assert _count(db_path, "magnets") == 1
    assert _count(db_path, "parts") == 2
    assert _count(db_path, "materials") == 2


def test_cli_magnet_add_dry_run_writes_nothing(tmp_path, monkeypatch):
    json_path = tmp_path / "MAG_JSON.json"
    json_path.write_text(json.dumps(MAGNET_JSON))
    db_path = tmp_path / "test.duckdb"

    _run(monkeypatch, "magnet", "add", str(json_path), "--db", str(db_path), "--dry-run")

    assert not db_path.exists()


def test_cli_magnet_add_missing_json_exits(tmp_path, monkeypatch):
    with pytest.raises(SystemExit):
        _run(monkeypatch, "magnet", "add", str(tmp_path / "NOPE.json"),
             "--db", str(tmp_path / "test.duckdb"))


# ---------------------------------------------------------------------------
# magnet view
# ---------------------------------------------------------------------------


def test_cli_magnet_view_list_all(tmp_path, monkeypatch, capsys):
    db = _db_with_magnet(tmp_path)
    _run(monkeypatch, "magnet", "view", "--db", str(db))
    assert "MAG_JSON" in capsys.readouterr().out


def test_cli_magnet_view_one(tmp_path, monkeypatch, capsys):
    db = _db_with_magnet(tmp_path)
    _run(monkeypatch, "magnet", "view", "MAG_JSON", "--db", str(db))
    out = capsys.readouterr().out
    assert "MAG_JSON" in out
    assert "H_JSON_01" in out


def test_cli_magnet_view_missing_db_exits(tmp_path, monkeypatch):
    with pytest.raises(SystemExit):
        _run(monkeypatch, "magnet", "view", "--db", str(tmp_path / "nope.duckdb"))


# ---------------------------------------------------------------------------
# magnet delete
# ---------------------------------------------------------------------------


def test_cli_magnet_delete_removes_magnet(tmp_path, monkeypatch):
    db = _db_with_magnet(tmp_path)
    _run(monkeypatch, "magnet", "delete", "MAG_JSON", "--db", str(db))
    assert _count(db, "magnets") == 0
    assert _count(db, "magnet_parts") == 0


def test_cli_magnet_delete_missing_db_exits(tmp_path, monkeypatch):
    with pytest.raises(SystemExit):
        _run(monkeypatch, "magnet", "delete", "MAG_JSON",
             "--db", str(tmp_path / "nope.duckdb"))


# ---------------------------------------------------------------------------
# site add
# ---------------------------------------------------------------------------


def test_cli_site_add_creates_site(tmp_path, monkeypatch):
    db = _db_with_magnet(tmp_path)
    json_path = tmp_path / "SITE_JSON_01.json"
    json_path.write_text(json.dumps(SITE_JSON))

    _run(monkeypatch, "site", "add", str(json_path), "--db", str(db))

    assert _count(db, "sites") == 1
    assert _count(db, "site_magnets") == 1
    assert _count(db, "experiments") == len(SITE_JSON["records"])


def test_cli_site_add_dry_run_writes_nothing(tmp_path, monkeypatch):
    db = _db_with_magnet(tmp_path)
    json_path = tmp_path / "SITE_JSON_01.json"
    json_path.write_text(json.dumps(SITE_JSON))

    _run(monkeypatch, "site", "add", str(json_path), "--db", str(db), "--dry-run")

    assert _count(db, "sites") == 0


def test_cli_site_add_missing_json_exits(tmp_path, monkeypatch):
    db = _db_with_magnet(tmp_path)
    with pytest.raises(SystemExit):
        _run(monkeypatch, "site", "add", str(tmp_path / "NOPE.json"), "--db", str(db))


# ---------------------------------------------------------------------------
# site view
# ---------------------------------------------------------------------------


def test_cli_site_view_list_all(tmp_path, monkeypatch, capsys):
    db = _db_with_site(tmp_path)
    _run(monkeypatch, "site", "view", "--db", str(db))
    assert "SITE_JSON_01" in capsys.readouterr().out


def test_cli_site_view_one(tmp_path, monkeypatch, capsys):
    db = _db_with_site(tmp_path)
    _run(monkeypatch, "site", "view", "SITE_JSON_01", "--db", str(db))
    out = capsys.readouterr().out
    assert "SITE_JSON_01" in out
    assert "M10" in out


def test_cli_site_view_missing_db_exits(tmp_path, monkeypatch):
    with pytest.raises(SystemExit):
        _run(monkeypatch, "site", "view", "--db", str(tmp_path / "nope.duckdb"))


# ---------------------------------------------------------------------------
# site delete
# ---------------------------------------------------------------------------


def test_cli_site_delete_removes_site_and_related(tmp_path, monkeypatch):
    db = _db_with_site(tmp_path)
    _run(monkeypatch, "site", "delete", "SITE_JSON_01", "--db", str(db))
    assert _count(db, "sites") == 0
    assert _count(db, "site_magnets") == 0
    assert _count(db, "experiments") == 0


def test_cli_site_delete_missing_db_exits(tmp_path, monkeypatch):
    with pytest.raises(SystemExit):
        _run(monkeypatch, "site", "delete", "SITE_JSON_01",
             "--db", str(tmp_path / "nope.duckdb"))


# ---------------------------------------------------------------------------
# site update-magnet
# ---------------------------------------------------------------------------


def test_cli_site_update_magnet_changes_offset(tmp_path, monkeypatch):
    db = _db_with_site(tmp_path)

    _run(monkeypatch, "site", "update-magnet",
         "SITE_JSON_01", "MAG_JSON",
         "--db", str(db),
         "--z-offset", "9.5")

    row = _fetch_one(db, "SELECT z_offset FROM site_magnets WHERE magnet_name = 'MAG_JSON'")
    assert row[0] == 9.5


def test_cli_site_update_magnet_invalid_metadata_exits(tmp_path, monkeypatch):
    db = _db_with_site(tmp_path)
    with pytest.raises(SystemExit):
        _run(monkeypatch, "site", "update-magnet",
             "SITE_JSON_01", "MAG_JSON",
             "--db", str(db),
             "--metadata", "NOT_JSON")


def test_cli_site_update_magnet_missing_row_exits(tmp_path, monkeypatch):
    db = _db_with_magnet(tmp_path)  # site not added → no site_magnets row
    with pytest.raises(SystemExit):
        _run(monkeypatch, "site", "update-magnet",
             "NONEXISTENT_SITE", "MAG_JSON",
             "--db", str(db),
             "--z-offset", "1.0")


def test_cli_site_update_magnet_missing_db_exits(tmp_path, monkeypatch):
    with pytest.raises(SystemExit):
        _run(monkeypatch, "site", "update-magnet",
             "SITE_JSON_01", "MAG_JSON",
             "--db", str(tmp_path / "nope.duckdb"),
             "--z-offset", "1.0")
