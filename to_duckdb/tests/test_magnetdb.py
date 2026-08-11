"""Integration tests for magnetdb.py — the unified CLI entry point."""

import json

import duckdb
import pytest

from magnetdb import main
from magnetdb import _add_magnet as add_magnet, _add_site as add_site
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


# ---------------------------------------------------------------------------
# populate overview-records-from-json
# ---------------------------------------------------------------------------


def _summary_json_record(filename, **extra):
    return {
        "filename": filename,
        "overview": f"/mnt/LNCMIG-Data/records/pbsurv/M10/Overview/{filename}.tdms",
        "archive": "",
        "pupitre": "",
        "default": "",
        "trigger": "",
        "spike": "",
        "hybrid_kHz": "",
        "hybrid_rms": "",
        "hybrid_trigger": "",
        "hybrid_vprocess": "",
        "pigbrother_runlog": "",
        "pupitre_runlog": "",
        **extra,
    }


def test_cli_populate_overview_records_from_json_auto_resolves_site(tmp_path, monkeypatch):
    db = _db_with_site(tmp_path)  # SITE_JSON_01, housing M10, commissioned 2025-01-01
    json_path = tmp_path / "M10_summary-2025.json"
    json_path.write_text(json.dumps([_summary_json_record("M10_Overview_250115-1200")]))

    _run(monkeypatch, "populate", "overview-records-from-json", str(json_path), "--db", str(db))

    row = _fetch_one(
        db, "SELECT housing, site_name, t0, sources_overview FROM overview_records "
        "WHERE filename = 'M10_Overview_250115-1200'"
    )
    assert row[0] == "M10"
    assert row[1] == "SITE_JSON_01"
    assert row[2] is not None
    assert row[3] == ["M10_Overview_250115-1200.tdms"]


def test_cli_populate_overview_records_from_json_unresolved_site_stays_null(tmp_path, monkeypatch):
    db = _db_with_site(tmp_path)  # only a M10 site exists
    json_path = tmp_path / "M9_summary-2025.json"
    json_path.write_text(json.dumps([_summary_json_record("M9_Overview_250115-1200")]))

    _run(monkeypatch, "populate", "overview-records-from-json", str(json_path), "--db", str(db))

    row = _fetch_one(
        db, "SELECT housing, site_name FROM overview_records "
        "WHERE filename = 'M9_Overview_250115-1200'"
    )
    assert row == ("M9", None)


def test_cli_populate_overview_records_from_json_unknown_site_exits(tmp_path, monkeypatch):
    db = _db_with_site(tmp_path)
    json_path = tmp_path / "M10_summary-2025.json"
    json_path.write_text(json.dumps([_summary_json_record("M10_Overview_250115-1200")]))

    with pytest.raises(SystemExit):
        _run(monkeypatch, "populate", "overview-records-from-json", str(json_path),
             "--db", str(db), "--site", "NoSuchSite")

    assert _count(db, "overview_records") == 0


def test_cli_populate_overview_records_from_json_site_override(tmp_path, monkeypatch):
    db = _db_with_site(tmp_path)
    json_path = tmp_path / "M10_summary-2025.json"
    json_path.write_text(json.dumps([_summary_json_record("M10_Overview_250115-1200")]))

    _run(monkeypatch, "populate", "overview-records-from-json", str(json_path),
         "--db", str(db), "--site", "SITE_JSON_01")

    row = _fetch_one(
        db, "SELECT housing, site_name FROM overview_records "
        "WHERE filename = 'M10_Overview_250115-1200'"
    )
    assert row == ("M10", "SITE_JSON_01")


# ---------------------------------------------------------------------------
# db drop-table
# ---------------------------------------------------------------------------


def _tables(db_path):
    with duckdb.connect(str(db_path), read_only=True) as con:
        return {r[0] for r in con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchall()}


def _add_junk_tables(db_path, *names):
    """Create standalone tables (no FK relationships) for drop-table tests."""
    with duckdb.connect(str(db_path)) as con:
        for name in names:
            con.execute(f"CREATE TABLE {name} (x INTEGER)")
            con.execute(f"INSERT INTO {name} VALUES (1), (2)")


def test_cli_db_drop_table_drops_existing_table(tmp_path, monkeypatch):
    db = _db_with_magnet(tmp_path)
    _add_junk_tables(db, "JUNK1")

    _run(monkeypatch, "db", "drop-table", "--db", str(db), "--table", "JUNK1", "--yes")

    assert "JUNK1" not in _tables(db)


def test_cli_db_drop_table_multiple_tables(tmp_path, monkeypatch):
    db = _db_with_magnet(tmp_path)
    _add_junk_tables(db, "JUNK1", "JUNK2")

    _run(monkeypatch, "db", "drop-table", "--db", str(db),
         "--table", "JUNK1", "JUNK2", "--yes")

    assert not ({"JUNK1", "JUNK2"} & _tables(db))


def test_cli_db_drop_table_skips_nonexistent_table(tmp_path, monkeypatch, capsys):
    db = _db_with_magnet(tmp_path)

    _run(monkeypatch, "db", "drop-table", "--db", str(db), "--table", "NOPE", "--yes")

    assert "does not exist" in capsys.readouterr().out


def test_cli_db_drop_table_dry_run_writes_nothing(tmp_path, monkeypatch):
    db = _db_with_magnet(tmp_path)
    _add_junk_tables(db, "JUNK1")

    _run(monkeypatch, "db", "drop-table", "--db", str(db), "--table", "JUNK1", "--dry-run")

    assert "JUNK1" in _tables(db)


def test_cli_db_drop_table_missing_db_exits(tmp_path, monkeypatch):
    with pytest.raises(SystemExit):
        _run(monkeypatch, "db", "drop-table",
             "--db", str(tmp_path / "nope.duckdb"), "--table", "materials", "--yes")
