"""Integration tests for add_assembly.py."""

import copy
import json

import duckdb
import pytest

import magnetdb
from magnetdb import _add_magnet as add_magnet, _add_assembly as add_assembly, _validate_assembly
from schema import ensure_schema
from tests.conftest import MAGNET_JSON, ASSEMBLY_JSON


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
    """Return a db_path that already contains MAG_JSON."""
    db = tmp_path / "test.duckdb"
    add_magnet(MAGNET_JSON, db)
    return db


def _empty_db(tmp_path):
    """Return a db_path for an empty but schema-initialised database."""
    db = tmp_path / "test.duckdb"
    with duckdb.connect(str(db)) as con:
        ensure_schema(con)
    return db


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_add_assembly_creates_assembly_row(tmp_path):
    db = _db_with_magnet(tmp_path)
    add_assembly(ASSEMBLY_JSON, db)
    row = _fetch_one(db, "SELECT name, housing, status FROM assemblies WHERE name = 'ASSEMBLY_JSON_01'")
    assert row == ("ASSEMBLY_JSON_01", "M10", "in_operation")


def test_add_assembly_links_magnets(tmp_path):
    db = _db_with_magnet(tmp_path)
    add_assembly(ASSEMBLY_JSON, db)
    count = _fetch_one(
        db,
        "SELECT COUNT(*) FROM assembly_magnets WHERE assembly_name = 'ASSEMBLY_JSON_01'",
    )[0]
    assert count == 1


def test_add_assembly_creates_experiments(tmp_path):
    db = _db_with_magnet(tmp_path)
    add_assembly(ASSEMBLY_JSON, db)
    count = _count(db, "experiments")
    assert count == len(ASSEMBLY_JSON["records"])


def test_add_assembly_string_magnet_entry_uses_default_offsets(tmp_path):
    db = _db_with_magnet(tmp_path)
    add_assembly(ASSEMBLY_JSON, db)
    row = _fetch_one(
        db,
        "SELECT z_offset, r_offset, parallax FROM assembly_magnets WHERE magnet_name = 'MAG_JSON'",
    )
    assert row == (0.0, 0.0, 0.0)


def test_add_assembly_dict_magnet_entry_stores_offsets(tmp_path):
    db = _db_with_magnet(tmp_path)
    data = copy.deepcopy(ASSEMBLY_JSON)
    data["magnets"] = [{"name": "MAG_JSON", "z_offset": 12.5, "r_offset": 0.3, "parallax": 0.1}]
    add_assembly(data, db)
    row = _fetch_one(
        db,
        "SELECT z_offset, r_offset, parallax FROM assembly_magnets WHERE magnet_name = 'MAG_JSON'",
    )
    assert row == (12.5, 0.3, 0.1)


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_add_assembly_is_idempotent(tmp_path):
    db = _db_with_magnet(tmp_path)
    add_assembly(ASSEMBLY_JSON, db)
    add_assembly(ASSEMBLY_JSON, db)  # second call must not raise or duplicate rows
    assert _count(db, "assemblies") == 1
    assert _count(db, "assembly_magnets") == 1
    assert _count(db, "experiments") == len(ASSEMBLY_JSON["records"])


# ---------------------------------------------------------------------------
# Auto-load missing magnets
# ---------------------------------------------------------------------------


def test_add_assembly_auto_loads_magnet_from_json(tmp_path):
    """add_assembly must load a missing magnet from a JSON file in magnet_dir."""
    db = _empty_db(tmp_path)
    (tmp_path / "MAG_JSON.json").write_text(json.dumps(MAGNET_JSON))

    add_assembly(ASSEMBLY_JSON, db, magnet_dir=tmp_path)

    assert _count(db, "magnets") == 1
    assert _count(db, "assemblies") == 1


def test_add_assembly_fails_when_magnet_json_missing(tmp_path):
    """add_assembly must exit when a referenced magnet is absent from DB and disk."""
    db = _empty_db(tmp_path)
    # No magnet JSON file placed in tmp_path
    with pytest.raises(SystemExit):
        add_assembly(ASSEMBLY_JSON, db, magnet_dir=tmp_path)


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------


def test_add_assembly_dry_run_writes_nothing(tmp_path):
    db = _db_with_magnet(tmp_path)
    assemblies_before = _count(db, "assemblies")
    add_assembly(ASSEMBLY_JSON, db, dry_run=True)
    assert _count(db, "assemblies") == assemblies_before


def test_add_assembly_dry_run_prints_summary(tmp_path, capsys):
    db = _db_with_magnet(tmp_path)
    add_assembly(ASSEMBLY_JSON, db, dry_run=True)
    out = capsys.readouterr().out
    assert "[dry-run]" in out
    assert "ASSEMBLY_JSON_01" in out


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_add_assembly_fails_when_db_missing(tmp_path):
    db = tmp_path / "nonexistent.duckdb"
    with pytest.raises(SystemExit):
        add_assembly(ASSEMBLY_JSON, db)


def test_add_assembly_validate_missing_name(tmp_path):
    errors = _validate_assembly({**ASSEMBLY_JSON, "name": ""})
    assert any("name" in e.lower() for e in errors)


def test_add_assembly_validate_missing_magnets(tmp_path):
    errors = _validate_assembly({**ASSEMBLY_JSON, "magnets": []})
    assert any("magnet" in e.lower() for e in errors)


# ---------------------------------------------------------------------------
# CLI: update-magnet subcommand
# ---------------------------------------------------------------------------


def test_update_magnet_cli(tmp_path, monkeypatch):
    db = _db_with_magnet(tmp_path)
    add_assembly(ASSEMBLY_JSON, db)

    monkeypatch.setattr(
        "sys.argv",
        [
            "magnetdb.py",
            "assembly", "update-magnet",
            "ASSEMBLY_JSON_01",
            "MAG_JSON",
            "--db", str(db),
            "--z-offset", "7.5",
        ],
    )
    magnetdb.main()

    row = _fetch_one(db, "SELECT z_offset FROM assembly_magnets WHERE magnet_name = 'MAG_JSON'")
    assert row[0] == 7.5


def test_update_magnet_cli_missing_row_exits(tmp_path, monkeypatch):
    db = _db_with_magnet(tmp_path)  # assembly not added → no assembly_magnets row

    monkeypatch.setattr(
        "sys.argv",
        [
            "magnetdb.py",
            "assembly", "update-magnet",
            "NONEXISTENT_ASSEMBLY",
            "MAG_JSON",
            "--db", str(db),
            "--z-offset", "1.0",
        ],
    )
    with pytest.raises(SystemExit):
        magnetdb.main()
