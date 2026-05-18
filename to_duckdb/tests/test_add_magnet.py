"""Integration tests for add_magnet.py."""

import json
import copy

import duckdb
import pytest

import add_magnet as am_module
from add_magnet import add_magnet
from schema import ensure_schema
from tests.conftest import MAGNET_JSON


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _count(db_path, table):
    with duckdb.connect(str(db_path), read_only=True) as con:
        return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _fetch_one(db_path, sql, params=None):
    with duckdb.connect(str(db_path), read_only=True) as con:
        return con.execute(sql, params or []).fetchone()


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_add_magnet_creates_magnet_row(tmp_path):
    db = tmp_path / "test.duckdb"
    add_magnet(MAGNET_JSON, db)
    row = _fetch_one(db, "SELECT name, type, status FROM magnets WHERE name = 'MAG_JSON'")
    assert row == ("MAG_JSON", "insert", "in_operation")


def test_add_magnet_creates_all_parts(tmp_path):
    db = tmp_path / "test.duckdb"
    add_magnet(MAGNET_JSON, db)
    count = _count(db, "parts")
    assert count == len(MAGNET_JSON["parts"])


def test_add_magnet_creates_all_materials(tmp_path):
    db = tmp_path / "test.duckdb"
    add_magnet(MAGNET_JSON, db)
    assert _count(db, "materials") == 2  # one per part (CU + SS)


def test_add_magnet_links_parts_to_magnet(tmp_path):
    db = tmp_path / "test.duckdb"
    add_magnet(MAGNET_JSON, db)
    count = _fetch_one(
        db,
        "SELECT COUNT(*) FROM magnet_parts WHERE magnet_name = 'MAG_JSON'",
    )[0]
    assert count == 2


def test_add_magnet_assigns_coil_index_to_helix_only(tmp_path):
    db = tmp_path / "test.duckdb"
    add_magnet(MAGNET_JSON, db)
    rows = duckdb.connect(str(db), read_only=True).execute(
        "SELECT p.type, mp.coil_index FROM magnet_parts mp "
        "JOIN parts p ON p.name = mp.part_name "
        "WHERE mp.magnet_name = 'MAG_JSON' ORDER BY mp.rank"
    ).fetchall()
    assert rows[0] == ("helix", 1)   # first part is a helix → coil_index 1
    assert rows[1] == ("ring", None)  # second part is a ring → NULL


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_add_magnet_is_idempotent(tmp_path):
    db = tmp_path / "test.duckdb"
    add_magnet(MAGNET_JSON, db)
    add_magnet(MAGNET_JSON, db)  # second call must not raise or duplicate rows
    assert _count(db, "magnets") == 1
    assert _count(db, "parts") == 2
    assert _count(db, "materials") == 2


def test_add_magnet_shared_material_inserted_once(tmp_path):
    """Two parts referencing the same material must not cause a duplicate key error."""
    data = copy.deepcopy(MAGNET_JSON)
    # Make both parts share the same material
    data["parts"][1]["material"] = copy.deepcopy(data["parts"][0]["material"])
    data["parts"][1]["material"]["name"] = "MAT_JSON_CU"  # same as part 0

    db = tmp_path / "test.duckdb"
    add_magnet(data, db)
    assert _count(db, "materials") == 1


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------


def test_add_magnet_dry_run_writes_nothing(tmp_path):
    db = tmp_path / "test.duckdb"
    add_magnet(MAGNET_JSON, db, dry_run=True)
    assert not db.exists()


def test_add_magnet_dry_run_prints_summary(tmp_path, capsys):
    db = tmp_path / "test.duckdb"
    add_magnet(MAGNET_JSON, db, dry_run=True)
    out = capsys.readouterr().out
    assert "[dry-run]" in out
    assert "MAG_JSON" in out


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_add_magnet_validate_missing_name(tmp_path):
    data = {**MAGNET_JSON, "name": ""}
    with pytest.raises(SystemExit):
        add_magnet(data, tmp_path / "test.duckdb")


def test_add_magnet_validate_missing_parts(tmp_path):
    data = {**MAGNET_JSON, "parts": []}
    with pytest.raises(SystemExit):
        add_magnet(data, tmp_path / "test.duckdb")


def test_add_magnet_validate_part_missing_type(tmp_path):
    data = copy.deepcopy(MAGNET_JSON)
    del data["parts"][0]["type"]
    errors = am_module._validate(data)
    assert any("type" in e for e in errors)


def test_add_magnet_validate_part_missing_material(tmp_path):
    data = copy.deepcopy(MAGNET_JSON)
    data["parts"][0]["material"] = {}
    errors = am_module._validate(data)
    assert any("material" in e for e in errors)


# ---------------------------------------------------------------------------
# Type inference
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("part_types,expected_magnet_type", [
    (["helix", "ring"], "insert"),
    (["bitter", "bitter"], "bitters"),
    (["helix", "bitter"], "hybrid"),
])
def test_add_magnet_infers_type(tmp_path, part_types, expected_magnet_type):
    data = copy.deepcopy(MAGNET_JSON)
    # Rebuild parts list with the desired types, reusing the first material
    template_part = data["parts"][0]
    data["parts"] = [
        {**template_part, "name": f"P_{i:02d}", "type": t}
        for i, t in enumerate(part_types)
    ]
    db = tmp_path / "test.duckdb"
    add_magnet(data, db)
    row = _fetch_one(db, "SELECT type FROM magnets WHERE name = 'MAG_JSON'")
    assert row[0] == expected_magnet_type


# ---------------------------------------------------------------------------
# CLI entry point smoke test
# ---------------------------------------------------------------------------


def test_add_magnet_cli(tmp_path, monkeypatch, capsys):
    json_path = tmp_path / "MAG_JSON.json"
    json_path.write_text(json.dumps(MAGNET_JSON))
    db_path = tmp_path / "cli.duckdb"

    monkeypatch.setattr("sys.argv", ["add_magnet.py", str(json_path), "--db", str(db_path)])
    am_module.main()

    assert _count(db_path, "magnets") == 1
