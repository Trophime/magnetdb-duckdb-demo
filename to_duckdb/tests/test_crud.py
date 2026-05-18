"""Unit tests for crud.py — one function per concern."""

import pytest

from crud import (
    delete_magnet,
    delete_site,
    exists,
    infer_magnet_type,
    insert_experiments,
    insert_magnet,
    insert_magnet_part_row,
    insert_magnet_parts,
    insert_material,
    insert_part,
    insert_site,
    insert_site_magnets,
    parse_timestamp,
    update_site_magnet,
    view_magnet,
    view_magnets,
    view_site,
    view_sites,
)
from tests.conftest import (
    MAGNET_DATA,
    MATERIAL_COPPER,
    MATERIAL_STEEL,
    PART_HELIX,
    PART_RING,
    SITE_DATA,
)


# ---------------------------------------------------------------------------
# exists()
# ---------------------------------------------------------------------------


def test_exists_returns_false_before_insert(con):
    assert exists(con, "materials", "NONEXISTENT") is False


def test_exists_returns_true_after_insert(con):
    insert_material(con, MATERIAL_COPPER, verbose=False)
    assert exists(con, "materials", "MAT_COPPER") is True


# ---------------------------------------------------------------------------
# insert_material()
# ---------------------------------------------------------------------------


def test_insert_material_creates_row(con):
    insert_material(con, MATERIAL_COPPER, verbose=False)
    row = con.execute("SELECT nuance FROM materials WHERE name = 'MAT_COPPER'").fetchone()
    assert row is not None
    assert row[0] == "CuAg2.75"


def test_insert_material_skips_duplicate(con):
    insert_material(con, MATERIAL_COPPER, verbose=False)
    insert_material(con, MATERIAL_COPPER, verbose=False)
    count = con.execute("SELECT COUNT(*) FROM materials WHERE name = 'MAT_COPPER'").fetchone()[0]
    assert count == 1


def test_insert_material_stores_null_for_missing_optional_fields(con):
    minimal = {"name": "MAT_MINIMAL", "nuance": "Cu", "rpe": None}
    insert_material(con, minimal, verbose=False)
    row = con.execute("SELECT description FROM materials WHERE name = 'MAT_MINIMAL'").fetchone()
    assert row[0] is None


# ---------------------------------------------------------------------------
# insert_part()
# ---------------------------------------------------------------------------


def test_insert_part_creates_row(con):
    insert_material(con, MATERIAL_COPPER, verbose=False)
    insert_part(con, PART_HELIX, verbose=False)
    row = con.execute("SELECT type, material_name FROM parts WHERE name = 'HELIX_01'").fetchone()
    assert row == ("helix", "MAT_COPPER")


def test_insert_part_skips_duplicate(con):
    insert_material(con, MATERIAL_COPPER, verbose=False)
    insert_part(con, PART_HELIX, verbose=False)
    insert_part(con, PART_HELIX, verbose=False)
    count = con.execute("SELECT COUNT(*) FROM parts WHERE name = 'HELIX_01'").fetchone()[0]
    assert count == 1


def test_insert_part_accepts_nested_material_dict(con):
    """Part dict may carry the full material under 'material' instead of 'material_name'."""
    insert_material(con, MATERIAL_COPPER, verbose=False)
    part_with_nested = {**PART_HELIX, "name": "H_NESTED", "material_name": None,
                        "material": {"name": "MAT_COPPER"}}
    insert_part(con, part_with_nested, verbose=False)
    row = con.execute("SELECT material_name FROM parts WHERE name = 'H_NESTED'").fetchone()
    assert row[0] == "MAT_COPPER"


# ---------------------------------------------------------------------------
# infer_magnet_type()
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("parts,expected", [
    ([{"type": "helix"}, {"type": "helix"}, {"type": "ring"}], "insert"),
    ([{"type": "bitter"}, {"type": "bitter"}], "bitters"),
    ([{"type": "helix"}, {"type": "bitter"}], "hybrid"),
    ([{"type": "ring"}, {"type": "lead"}], "unknown"),
    ([], "unknown"),
])
def test_infer_magnet_type(parts, expected):
    assert infer_magnet_type(parts) == expected


# ---------------------------------------------------------------------------
# insert_magnet()
# ---------------------------------------------------------------------------


def test_insert_magnet_creates_row(con):
    insert_magnet(con, MAGNET_DATA, "insert", verbose=False)
    row = con.execute("SELECT type, status FROM magnets WHERE name = 'MAG_01'").fetchone()
    assert row == ("insert", "in_operation")


def test_insert_magnet_skips_duplicate(con):
    insert_magnet(con, MAGNET_DATA, "insert", verbose=False)
    insert_magnet(con, MAGNET_DATA, "insert", verbose=False)
    count = con.execute("SELECT COUNT(*) FROM magnets WHERE name = 'MAG_01'").fetchone()[0]
    assert count == 1


# ---------------------------------------------------------------------------
# insert_magnet_parts()
# ---------------------------------------------------------------------------


def test_insert_magnet_parts_assigns_coil_index(con):
    insert_material(con, MATERIAL_COPPER, verbose=False)
    insert_material(con, MATERIAL_STEEL, verbose=False)
    insert_part(con, PART_HELIX, verbose=False)
    insert_part(con, PART_RING, verbose=False)
    insert_magnet(con, MAGNET_DATA, "insert", verbose=False)

    parts = [{"name": "HELIX_01", "type": "helix"}, {"name": "RING_01", "type": "ring"}]
    insert_magnet_parts(con, "MAG_01", parts, verbose=False)

    rows = con.execute(
        "SELECT part_name, rank, coil_index FROM magnet_parts WHERE magnet_name = 'MAG_01' ORDER BY rank"
    ).fetchall()
    assert rows[0] == ("HELIX_01", 0, 1)   # helix → coil_index 1
    assert rows[1] == ("RING_01", 1, None)  # ring  → NULL


def test_insert_magnet_parts_skips_duplicate(con):
    insert_material(con, MATERIAL_COPPER, verbose=False)
    insert_part(con, PART_HELIX, verbose=False)
    insert_magnet(con, MAGNET_DATA, "insert", verbose=False)

    parts = [{"name": "HELIX_01", "type": "helix"}]
    insert_magnet_parts(con, "MAG_01", parts, verbose=False)
    insert_magnet_parts(con, "MAG_01", parts, verbose=False)

    count = con.execute("SELECT COUNT(*) FROM magnet_parts WHERE magnet_name = 'MAG_01'").fetchone()[0]
    assert count == 1


def test_insert_magnet_parts_multiple_coil_channels(con):
    """Three helices must get sequential coil_index 1, 2, 3."""
    mats = {**MATERIAL_COPPER}
    insert_material(con, mats, verbose=False)
    for i in range(1, 4):
        insert_part(con, {**PART_HELIX, "name": f"H_{i:02d}"}, verbose=False)
    insert_magnet(con, MAGNET_DATA, "insert", verbose=False)

    parts = [{"name": f"H_{i:02d}", "type": "helix"} for i in range(1, 4)]
    insert_magnet_parts(con, "MAG_01", parts, verbose=False)

    indexes = con.execute(
        "SELECT coil_index FROM magnet_parts WHERE magnet_name = 'MAG_01' ORDER BY rank"
    ).fetchall()
    assert [r[0] for r in indexes] == [1, 2, 3]


# ---------------------------------------------------------------------------
# insert_magnet_part_row()
# ---------------------------------------------------------------------------


def test_insert_magnet_part_row_inserts(con_populated):
    count = con_populated.execute(
        "SELECT COUNT(*) FROM magnet_parts WHERE magnet_name = 'MAG_01'"
    ).fetchone()[0]
    assert count == 2  # HELIX_01 + RING_01 from fixture


def test_insert_magnet_part_row_skips_duplicate(con_populated):
    insert_magnet_part_row(con_populated, "MAG_01", "HELIX_01", 0, 1)
    count = con_populated.execute(
        "SELECT COUNT(*) FROM magnet_parts WHERE magnet_name = 'MAG_01' AND part_name = 'HELIX_01'"
    ).fetchone()[0]
    assert count == 1


# ---------------------------------------------------------------------------
# parse_timestamp()
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value,expected", [
    (None, None),
    ("None", None),
    ("null", None),
    ("NULL", None),
    ("", None),
    ("2025-01-01 00:00:00", "2025-01-01 00:00:00"),
    ("2025-11-12", "2025-11-12"),
])
def test_parse_timestamp(value, expected):
    assert parse_timestamp(value) == expected


# ---------------------------------------------------------------------------
# insert_site()
# ---------------------------------------------------------------------------


def test_insert_site_creates_row(con):
    insert_site(con, SITE_DATA, verbose=False)
    row = con.execute(
        "SELECT housing, status FROM sites WHERE name = 'SITE_01'"
    ).fetchone()
    assert row == ("M10", "in_operation")


def test_insert_site_skips_duplicate(con):
    insert_site(con, SITE_DATA, verbose=False)
    insert_site(con, SITE_DATA, verbose=False)
    count = con.execute("SELECT COUNT(*) FROM sites WHERE name = 'SITE_01'").fetchone()[0]
    assert count == 1


def test_insert_site_null_decommissioned(con):
    insert_site(con, {**SITE_DATA, "decommissioned_at": None}, verbose=False)
    row = con.execute("SELECT decommissioned_at FROM sites WHERE name = 'SITE_01'").fetchone()
    assert row[0] is None


# ---------------------------------------------------------------------------
# insert_site_magnets()
# ---------------------------------------------------------------------------


def test_insert_site_magnets_creates_row(con_populated):
    insert_site_magnets(con_populated, "SITE_01", ["MAG_01"], verbose=False)
    row = con_populated.execute(
        "SELECT z_offset FROM site_magnets WHERE site_name = 'SITE_01' AND magnet_name = 'MAG_01'"
    ).fetchone()
    assert row is not None
    assert row[0] == 0.0


def test_insert_site_magnets_stores_offsets(con_populated):
    entry = {"name": "MAG_01", "z_offset": 1.5, "r_offset": 0.3, "parallax": 0.01}
    insert_site_magnets(con_populated, "SITE_01", [entry], verbose=False)
    row = con_populated.execute(
        "SELECT z_offset, r_offset, parallax FROM site_magnets "
        "WHERE site_name = 'SITE_01' AND magnet_name = 'MAG_01'"
    ).fetchone()
    assert row == (1.5, 0.3, 0.01)


def test_insert_site_magnets_skips_duplicate(con_populated):
    insert_site_magnets(con_populated, "SITE_01", ["MAG_01"], verbose=False)
    insert_site_magnets(con_populated, "SITE_01", ["MAG_01"], verbose=False)
    count = con_populated.execute(
        "SELECT COUNT(*) FROM site_magnets WHERE site_name = 'SITE_01' AND magnet_name = 'MAG_01'"
    ).fetchone()[0]
    assert count == 1


# ---------------------------------------------------------------------------
# insert_experiments()
# ---------------------------------------------------------------------------


def test_insert_experiments_creates_rows(con_populated):
    records = [
        {"name": "run_001.txt", "file": "run_001.txt", "description": ""},
        {"name": "run_002.txt", "file": "run_002.txt", "description": ""},
    ]
    insert_experiments(con_populated, "SITE_01", records, verbose=False)
    count = con_populated.execute(
        "SELECT COUNT(*) FROM experiments WHERE site_name = 'SITE_01'"
    ).fetchone()[0]
    assert count == 2


def test_insert_experiments_skips_duplicate_file(con_populated):
    records = [{"name": "run_001.txt", "file": "run_001.txt"}]
    insert_experiments(con_populated, "SITE_01", records, verbose=False)
    insert_experiments(con_populated, "SITE_01", records, verbose=False)
    count = con_populated.execute(
        "SELECT COUNT(*) FROM experiments WHERE file = 'run_001.txt'"
    ).fetchone()[0]
    assert count == 1


# ---------------------------------------------------------------------------
# update_site_magnet()
# ---------------------------------------------------------------------------


def test_update_site_magnet_updates_offset(con_populated):
    insert_site_magnets(con_populated, "SITE_01", ["MAG_01"], verbose=False)
    update_site_magnet(con_populated, "SITE_01", "MAG_01", z_offset=12.5)
    row = con_populated.execute(
        "SELECT z_offset FROM site_magnets WHERE site_name = 'SITE_01' AND magnet_name = 'MAG_01'"
    ).fetchone()
    assert row[0] == 12.5


def test_update_site_magnet_updates_only_passed_fields(con_populated):
    insert_site_magnets(con_populated, "SITE_01", [{"name": "MAG_01", "r_offset": 0.5}], verbose=False)
    update_site_magnet(con_populated, "SITE_01", "MAG_01", z_offset=3.0)
    row = con_populated.execute(
        "SELECT z_offset, r_offset FROM site_magnets WHERE site_name = 'SITE_01' AND magnet_name = 'MAG_01'"
    ).fetchone()
    assert row[0] == 3.0
    assert row[1] == 0.5  # unchanged


def test_update_site_magnet_raises_when_row_missing(con_populated):
    with pytest.raises(ValueError, match="No link"):
        update_site_magnet(con_populated, "SITE_01", "NONEXISTENT", z_offset=1.0)


def test_update_site_magnet_nothing_to_update(con_populated, capsys):
    insert_site_magnets(con_populated, "SITE_01", ["MAG_01"], verbose=False)
    update_site_magnet(con_populated, "SITE_01", "MAG_01")
    captured = capsys.readouterr()
    assert "Nothing to update" in captured.out


# ---------------------------------------------------------------------------
# view_magnets() / view_magnet()
# ---------------------------------------------------------------------------


def test_view_magnets_empty(con, capsys):
    view_magnets(con)
    assert "No magnets" in capsys.readouterr().out


def test_view_magnets_lists_row(con_populated, capsys):
    view_magnets(con_populated)
    out = capsys.readouterr().out
    assert "MAG_01" in out
    assert "insert" in out


def test_view_magnet_not_found(con, capsys):
    view_magnet(con, "NONEXISTENT")
    assert "not found" in capsys.readouterr().out


def test_view_magnet_shows_name_and_parts(con_populated, capsys):
    view_magnet(con_populated, "MAG_01")
    out = capsys.readouterr().out
    assert "MAG_01" in out
    assert "HELIX_01" in out
    assert "RING_01" in out


def test_view_magnet_shows_coil_index(con_populated, capsys):
    view_magnet(con_populated, "MAG_01")
    out = capsys.readouterr().out
    assert "coil#1" in out


# ---------------------------------------------------------------------------
# view_sites() / view_site()
# ---------------------------------------------------------------------------


def test_view_sites_empty(con, capsys):
    view_sites(con)
    assert "No sites" in capsys.readouterr().out


def test_view_sites_lists_row(con_populated, capsys):
    view_sites(con_populated)
    out = capsys.readouterr().out
    assert "SITE_01" in out
    assert "M10" in out


def test_view_site_not_found(con, capsys):
    view_site(con, "NONEXISTENT")
    assert "not found" in capsys.readouterr().out


def test_view_site_shows_detail(con_populated, capsys):
    insert_site_magnets(con_populated, "SITE_01", ["MAG_01"], verbose=False)
    records = [{"name": "run.txt", "file": "run.txt"}]
    insert_experiments(con_populated, "SITE_01", records, verbose=False)
    view_site(con_populated, "SITE_01")
    out = capsys.readouterr().out
    assert "SITE_01" in out
    assert "M10" in out
    assert "MAG_01" in out
    assert "experiments: 1" in out


# ---------------------------------------------------------------------------
# delete_magnet()
# ---------------------------------------------------------------------------


def test_delete_magnet_removes_magnet_row(con_populated):
    delete_magnet(con_populated, "MAG_01")
    assert not exists(con_populated, "magnets", "MAG_01")


def test_delete_magnet_removes_part_links(con_populated):
    delete_magnet(con_populated, "MAG_01")
    count = con_populated.execute(
        "SELECT COUNT(*) FROM magnet_parts WHERE magnet_name = 'MAG_01'"
    ).fetchone()[0]
    assert count == 0


def test_delete_magnet_not_found(con, capsys):
    delete_magnet(con, "NONEXISTENT")
    assert "not found" in capsys.readouterr().out


def test_delete_magnet_leaves_parts_table_intact(con_populated):
    """Deleting a magnet must not cascade-delete the parts themselves."""
    delete_magnet(con_populated, "MAG_01")
    assert exists(con_populated, "parts", "HELIX_01")
    assert exists(con_populated, "parts", "RING_01")


# ---------------------------------------------------------------------------
# delete_site()
# ---------------------------------------------------------------------------


def test_delete_site_removes_site_row(con_populated):
    delete_site(con_populated, "SITE_01")
    assert not exists(con_populated, "sites", "SITE_01")


def test_delete_site_removes_site_magnet_links(con_populated):
    insert_site_magnets(con_populated, "SITE_01", ["MAG_01"], verbose=False)
    delete_site(con_populated, "SITE_01")
    count = con_populated.execute(
        "SELECT COUNT(*) FROM site_magnets WHERE site_name = 'SITE_01'"
    ).fetchone()[0]
    assert count == 0


def test_delete_site_removes_experiments(con_populated):
    records = [{"name": "run.txt", "file": "run.txt"}]
    insert_experiments(con_populated, "SITE_01", records, verbose=False)
    delete_site(con_populated, "SITE_01")
    count = con_populated.execute(
        "SELECT COUNT(*) FROM experiments WHERE site_name = 'SITE_01'"
    ).fetchone()[0]
    assert count == 0


def test_delete_site_not_found(con, capsys):
    delete_site(con, "NONEXISTENT")
    assert "not found" in capsys.readouterr().out
