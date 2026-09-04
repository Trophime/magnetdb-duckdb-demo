"""Unit tests for crud.py — one function per concern."""

import json
from datetime import datetime

import pytest

from crud import (
    _find_assembly_for_timestamp,
    _parse_overview_filename,
    _postprocess_overview_record,
    assembled_at_from_name,
    decommission_assembly,
    delete_magnet,
    delete_assembly,
    exists,
    infer_magnet_type,
    infer_operating_mode,
    infer_overview_record_fields,
    insert_experiments,
    insert_magnet,
    insert_magnet_part_row,
    insert_magnet_parts,
    insert_material,
    insert_overview_record_from_dict,
    insert_part,
    insert_assembly,
    insert_assembly_magnets,
    manufactured_at_from_name,
    merge_duplicate_pupitre_records,
    parse_timestamp,
    resolve_overview_assembly,
    update_assembly_from_json,
    update_assembly_magnet,
    update_magnet_from_json,
    update_magnet_status,
    update_part_from_json,
    update_part_status,
    view_magnet,
    view_magnets,
    view_overview_records,
    view_assembly,
    view_assemblies,
)
from populate import FILE_TZ
from tests.conftest import (
    MAGNET_DATA,
    MATERIAL_COPPER,
    MATERIAL_STEEL,
    PART_HELIX,
    PART_RING,
    ASSEMBLY_DATA,
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


def test_insert_part_defaults_status_to_in_stock(con):
    insert_material(con, MATERIAL_COPPER, verbose=False)
    part = {k: v for k, v in PART_HELIX.items() if k != "status"}
    insert_part(con, part, verbose=False)
    row = con.execute("SELECT status FROM parts WHERE name = 'HELIX_01'").fetchone()
    assert row[0] == "in_stock"


def test_insert_part_honors_explicit_status(con):
    insert_material(con, MATERIAL_COPPER, verbose=False)
    insert_part(con, {**PART_HELIX, "status": "in_study"}, verbose=False)
    row = con.execute("SELECT status FROM parts WHERE name = 'HELIX_01'").fetchone()
    assert row[0] == "in_study"


def test_insert_part_rejects_invalid_status(con):
    insert_material(con, MATERIAL_COPPER, verbose=False)
    with pytest.raises(ValueError):
        insert_part(con, {**PART_HELIX, "status": "bogus"}, verbose=False)


def test_insert_part_sets_manufactured_at_from_conforming_name(con):
    insert_material(con, MATERIAL_COPPER, verbose=False)
    insert_part(con, {**PART_HELIX, "name": "H23012001"}, verbose=False)
    row = con.execute("SELECT manufactured_at FROM parts WHERE name = 'H23012001'").fetchone()
    assert str(row[0]) == "2023-01-20 00:00:00"


def test_insert_part_leaves_manufactured_at_null_for_non_conforming_name(con):
    insert_material(con, MATERIAL_COPPER, verbose=False)
    insert_part(con, {**PART_HELIX, "name": "M9Bi"}, verbose=False)
    row = con.execute("SELECT manufactured_at FROM parts WHERE name = 'M9Bi'").fetchone()
    assert row[0] is None


def test_insert_part_ignores_created_at_for_manufactured_at(con):
    """The JSON export's own created_at must not influence manufactured_at."""
    insert_material(con, MATERIAL_COPPER, verbose=False)
    insert_part(
        con,
        {**PART_HELIX, "name": "H23012001", "created_at": "1999-01-01T00:00:00Z"},
        verbose=False,
    )
    row = con.execute("SELECT manufactured_at FROM parts WHERE name = 'H23012001'").fetchone()
    assert str(row[0]) == "2023-01-20 00:00:00"


# ---------------------------------------------------------------------------
# infer_magnet_type()
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("parts,expected", [
    ([{"type": "helix"}, {"type": "helix"}, {"type": "ring"}], "insert"),
    ([{"type": "bitter"}, {"type": "bitter"}], "bitters"),
    ([{"type": "supra"}, {"type": "supra"}], "supras"),
])
def test_infer_magnet_type(parts, expected):
    assert infer_magnet_type(parts) == expected


@pytest.mark.parametrize("parts", [
    [{"type": "helix"}, {"type": "bitter"}],  # mixed/hybrid — unsupported
    [{"type": "ring"}, {"type": "lead"}],     # no coil part at all
    [],
])
def test_infer_magnet_type_raises_for_invalid_coil_types(parts):
    with pytest.raises(ValueError):
        infer_magnet_type(parts)


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


def test_insert_magnet_defaults_status_to_in_stock(con):
    data = {k: v for k, v in MAGNET_DATA.items() if k != "status"}
    insert_magnet(con, data, "insert", verbose=False)
    row = con.execute("SELECT status FROM magnets WHERE name = 'MAG_01'").fetchone()
    assert row[0] == "in_stock"


def test_insert_magnet_rejects_invalid_status(con):
    with pytest.raises(ValueError):
        insert_magnet(con, {**MAGNET_DATA, "status": "bogus"}, "insert", verbose=False)


def test_insert_magnet_sets_assembled_at_from_conforming_name(con):
    insert_magnet(con, {**MAGNET_DATA, "name": "M23012001"}, "insert", verbose=False)
    row = con.execute("SELECT assembled_at FROM magnets WHERE name = 'M23012001'").fetchone()
    assert str(row[0]) == "2023-01-20 00:00:00"


def test_insert_magnet_leaves_assembled_at_null_for_non_conforming_name(con):
    insert_magnet(con, {**MAGNET_DATA, "name": "M9Bitters"}, "insert", verbose=False)
    row = con.execute("SELECT assembled_at FROM magnets WHERE name = 'M9Bitters'").fetchone()
    assert row[0] is None


def test_insert_magnet_ignores_created_at_for_assembled_at(con):
    """The JSON export's own created_at must not influence assembled_at."""
    insert_magnet(
        con,
        {**MAGNET_DATA, "name": "M23012001", "created_at": "1999-01-01T00:00:00Z"},
        "insert",
        verbose=False,
    )
    row = con.execute("SELECT assembled_at FROM magnets WHERE name = 'M23012001'").fetchone()
    assert str(row[0]) == "2023-01-20 00:00:00"


# ---------------------------------------------------------------------------
# insert_magnet_parts()
# ---------------------------------------------------------------------------


def test_insert_magnet_parts_assigns_coil_index(con):
    insert_material(con, MATERIAL_COPPER, verbose=False)
    insert_material(con, MATERIAL_STEEL, verbose=False)
    insert_part(con, {**PART_HELIX, "status": "in_stock"}, verbose=False)
    insert_part(con, {**PART_RING, "status": "in_stock"}, verbose=False)
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
    insert_part(con, {**PART_HELIX, "status": "in_stock"}, verbose=False)
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
        insert_part(con, {**PART_HELIX, "name": f"H_{i:02d}", "status": "in_stock"}, verbose=False)
    insert_magnet(con, MAGNET_DATA, "insert", verbose=False)

    parts = [{"name": f"H_{i:02d}", "type": "helix"} for i in range(1, 4)]
    insert_magnet_parts(con, "MAG_01", parts, verbose=False)

    indexes = con.execute(
        "SELECT coil_index FROM magnet_parts WHERE magnet_name = 'MAG_01' ORDER BY rank"
    ).fetchall()
    assert [r[0] for r in indexes] == [1, 2, 3]


def test_insert_magnet_parts_promotes_part_to_in_operation(con):
    """A part is promoted to in_operation as soon as it's attached to a
    magnet — no assembly involved at all."""
    insert_material(con, MATERIAL_COPPER, verbose=False)
    insert_material(con, MATERIAL_STEEL, verbose=False)
    insert_part(con, {**PART_HELIX, "status": "in_stock"}, verbose=False)
    insert_part(con, {**PART_RING, "status": "in_stock"}, verbose=False)
    insert_magnet(con, MAGNET_DATA, "insert", verbose=False)

    parts = [{"name": "HELIX_01", "type": "helix"}, {"name": "RING_01", "type": "ring"}]
    insert_magnet_parts(con, "MAG_01", parts, verbose=False)

    assert con.execute("SELECT status FROM parts WHERE name = 'HELIX_01'").fetchone()[0] == "in_operation"
    assert con.execute("SELECT status FROM parts WHERE name = 'RING_01'").fetchone()[0] == "in_operation"


def test_insert_magnet_parts_rejects_non_in_stock_part(con):
    insert_material(con, MATERIAL_COPPER, verbose=False)
    insert_part(con, {**PART_HELIX, "status": "in_operation"}, verbose=False)
    insert_magnet(con, MAGNET_DATA, "insert", verbose=False)
    with pytest.raises(ValueError, match="not 'in_stock'"):
        insert_magnet_parts(con, "MAG_01", [{"name": "HELIX_01", "type": "helix"}], verbose=False)


def test_insert_magnet_parts_reuse_retires_old_magnet_and_closes_its_assembly(con):
    """A part already held by another still-active magnet is reclaimed: the
    old magnet is retired, its open assembly link is auto-closed (fallback
    07:00 same day as the new magnet's assembled_at), and the part links to
    the new magnet."""
    insert_material(con, MATERIAL_COPPER, verbose=False)
    insert_part(con, {**PART_HELIX, "status": "in_stock"}, verbose=False)
    insert_magnet(con, {**MAGNET_DATA, "name": "M19061901", "status": "in_stock"}, "insert", verbose=False)
    insert_magnet_parts(con, "M19061901", [{"name": "HELIX_01", "type": "helix"}], verbose=False)
    insert_assembly(con, {
        "name": "OLD_A", "housing": "M9",
        "commissioned_at": "2019-06-19 08:00:00", "decommissioned_at": None,
    }, verbose=False)
    insert_assembly_magnets(con, "OLD_A", ["M19061901"], verbose=False)
    assert con.execute("SELECT status FROM parts WHERE name = 'HELIX_01'").fetchone()[0] == "in_operation"

    insert_magnet(con, {**MAGNET_DATA, "name": "M20022001", "status": "in_stock"}, "insert", verbose=False)
    insert_magnet_parts(con, "M20022001", [{"name": "HELIX_01", "type": "helix"}], verbose=False)

    assert con.execute("SELECT status FROM magnets WHERE name = 'M19061901'").fetchone()[0] == "retired"
    a_status, a_decommissioned_at = con.execute(
        "SELECT status, decommissioned_at FROM assemblies WHERE name = 'OLD_A'"
    ).fetchone()
    assert a_status == "disassembled"
    assert a_decommissioned_at.isoformat() == "2020-02-20T07:00:00"
    assert con.execute(
        "SELECT 1 FROM magnet_parts WHERE magnet_name = 'M20022001' AND part_name = 'HELIX_01'"
    ).fetchone() is not None
    assert con.execute("SELECT status FROM parts WHERE name = 'HELIX_01'").fetchone()[0] == "in_operation"


def test_insert_magnet_parts_reuse_does_not_override_explicit_decommissioned_at(con):
    """If the old assembly link already carries an explicit decommissioned_at,
    reclaiming the part must not touch it."""
    insert_material(con, MATERIAL_COPPER, verbose=False)
    insert_part(con, {**PART_HELIX, "status": "in_stock"}, verbose=False)
    insert_magnet(con, {**MAGNET_DATA, "name": "M19061901", "status": "in_stock"}, "insert", verbose=False)
    insert_magnet_parts(con, "M19061901", [{"name": "HELIX_01", "type": "helix"}], verbose=False)
    insert_assembly(con, {
        "name": "OLD_A", "housing": "M9",
        "commissioned_at": "2019-06-19 08:00:00", "decommissioned_at": None,
    }, verbose=False)
    insert_assembly_magnets(con, "OLD_A", ["M19061901"], verbose=False)
    con.execute(
        "UPDATE assembly_magnets SET decommissioned_at = '2019-12-31 07:00:00' "
        "WHERE assembly_name = 'OLD_A' AND magnet_name = 'M19061901'"
    )

    insert_magnet(con, {**MAGNET_DATA, "name": "M20022001", "status": "in_stock"}, "insert", verbose=False)
    insert_magnet_parts(con, "M20022001", [{"name": "HELIX_01", "type": "helix"}], verbose=False)

    assert con.execute("SELECT status FROM magnets WHERE name = 'M19061901'").fetchone()[0] == "retired"
    assembly_decommissioned_at = con.execute(
        "SELECT decommissioned_at FROM assemblies WHERE name = 'OLD_A'"
    ).fetchone()[0]
    assert assembly_decommissioned_at is None


def test_insert_magnet_parts_rejects_unknown_part(con):
    insert_magnet(con, MAGNET_DATA, "insert", verbose=False)
    with pytest.raises(ValueError, match="not found"):
        insert_magnet_parts(con, "MAG_01", [{"name": "NOPE", "type": "helix"}], verbose=False)


def test_insert_magnet_parts_rejection_writes_zero_rows(con):
    """A rejected call must leave zero magnet_parts rows — validated up front,
    before any row is inserted, so a bad part later in the list doesn't leave
    a partial set from the good parts earlier in the list."""
    insert_material(con, MATERIAL_COPPER, verbose=False)
    insert_material(con, MATERIAL_STEEL, verbose=False)
    insert_part(con, {**PART_HELIX, "status": "in_stock"}, verbose=False)
    insert_part(con, {**PART_RING, "status": "in_operation"}, verbose=False)
    insert_magnet(con, MAGNET_DATA, "insert", verbose=False)
    parts = [{"name": "HELIX_01", "type": "helix"}, {"name": "RING_01", "type": "ring"}]
    with pytest.raises(ValueError):
        insert_magnet_parts(con, "MAG_01", parts, verbose=False)
    count = con.execute("SELECT COUNT(*) FROM magnet_parts WHERE magnet_name = 'MAG_01'").fetchone()[0]
    assert count == 0


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
# assembled_at_from_name() / manufactured_at_from_name()
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name,expected", [
    ("M23012001", "2023-01-20"),
    ("M09052601", "2009-05-26"),
    ("M9Bitters", None),
    ("M10Bitters", None),
    ("H23012001", None),  # wrong prefix for a magnet
    ("M231301", None),  # too short to carry a 2-digit serial
    ("M23132001", None),  # month 13 is invalid
])
def test_assembled_at_from_name(name, expected):
    assert assembled_at_from_name(name) == expected


@pytest.mark.parametrize("name,expected", [
    ("H23012001", "2023-01-20"),
    ("R09052601", "2009-05-26"),
    ("M9Bi", None),
    ("M9_newBi08", None),
    ("M23012001", None),  # wrong prefix for a part
])
def test_manufactured_at_from_name(name, expected):
    assert manufactured_at_from_name(name) == expected


# ---------------------------------------------------------------------------
# insert_assembly()
# ---------------------------------------------------------------------------


def test_insert_assembly_creates_row(con):
    insert_assembly(con, ASSEMBLY_DATA, verbose=False)
    row = con.execute(
        "SELECT housing, status FROM assemblies WHERE name = 'ASSEMBLY_01'"
    ).fetchone()
    assert row == ("M10", "in_operation")


def test_insert_assembly_skips_duplicate(con):
    insert_assembly(con, ASSEMBLY_DATA, verbose=False)
    insert_assembly(con, ASSEMBLY_DATA, verbose=False)
    count = con.execute("SELECT COUNT(*) FROM assemblies WHERE name = 'ASSEMBLY_01'").fetchone()[0]
    assert count == 1


def test_insert_assembly_null_decommissioned(con):
    insert_assembly(con, {**ASSEMBLY_DATA, "decommissioned_at": None}, verbose=False)
    row = con.execute("SELECT decommissioned_at FROM assemblies WHERE name = 'ASSEMBLY_01'").fetchone()
    assert row[0] is None


def test_insert_assembly_derives_disassembled_status(con):
    insert_assembly(con, {
        "name": "A1", "housing": "M10",
        "commissioned_at": "2025-01-01 00:00:00", "decommissioned_at": "2025-02-01 00:00:00",
    }, verbose=False)
    row = con.execute("SELECT status FROM assemblies WHERE name = 'A1'").fetchone()
    assert row[0] == "disassembled"


def test_insert_assembly_overrides_contradicting_status(con):
    insert_assembly(con, {
        "name": "A1", "housing": "M10", "status": "disassembled",
        "commissioned_at": "2025-01-01 00:00:00", "decommissioned_at": None,
    }, verbose=False)
    row = con.execute("SELECT status FROM assemblies WHERE name = 'A1'").fetchone()
    assert row[0] == "in_operation"


def test_insert_assembly_in_study_exempt_from_derivation(con):
    insert_assembly(con, {
        "name": "A1", "housing": "M10", "status": "in_study",
        "commissioned_at": "2025-01-01 00:00:00", "decommissioned_at": None,
    }, verbose=False)
    row = con.execute("SELECT status FROM assemblies WHERE name = 'A1'").fetchone()
    assert row[0] == "in_study"


def test_insert_assembly_in_study_exempt_from_overlap(con):
    insert_assembly(con, {
        "name": "A1", "housing": "M10",
        "commissioned_at": "2025-01-01 00:00:00", "decommissioned_at": None,
    }, verbose=False)
    insert_assembly(con, {
        "name": "A2", "housing": "M10", "status": "in_study",
        "commissioned_at": "2025-01-01 00:00:00", "decommissioned_at": None,
    }, verbose=False)
    row = con.execute("SELECT status FROM assemblies WHERE name = 'A2'").fetchone()
    assert row[0] == "in_study"


def test_insert_assembly_rejects_overlap_with_closed_assembly(con):
    insert_assembly(con, {
        "name": "A1", "housing": "M10",
        "commissioned_at": "2025-01-01 00:00:00", "decommissioned_at": "2025-02-01 00:00:00",
    }, verbose=False)
    with pytest.raises(ValueError, match="overlaps"):
        insert_assembly(con, {
            "name": "A2", "housing": "M10",
            "commissioned_at": "2025-01-15 00:00:00", "decommissioned_at": "2025-03-01 00:00:00",
        }, verbose=False)


def test_insert_assembly_rejects_starting_before_open_predecessor(con):
    insert_assembly(con, {
        "name": "A1", "housing": "M10",
        "commissioned_at": "2025-02-01 00:00:00", "decommissioned_at": None,
    }, verbose=False)
    with pytest.raises(ValueError, match="before"):
        insert_assembly(con, {
            "name": "A2", "housing": "M10",
            "commissioned_at": "2025-01-01 00:00:00", "decommissioned_at": None,
        }, verbose=False)


def test_insert_assembly_auto_closes_open_predecessor(con):
    insert_assembly(con, {
        "name": "A1", "housing": "M10",
        "commissioned_at": "2025-01-01 00:00:00", "decommissioned_at": None,
    }, verbose=False)
    insert_assembly(con, {
        "name": "A2", "housing": "M10",
        "commissioned_at": "2025-02-01 00:00:00", "decommissioned_at": None,
    }, verbose=False)
    row = con.execute(
        "SELECT status, decommissioned_at FROM assemblies WHERE name = 'A1'"
    ).fetchone()
    assert row[0] == "disassembled"
    assert row[1] is not None


def test_insert_assembly_auto_close_cascades_magnets_to_in_stock(con):
    insert_material(con, MATERIAL_COPPER, verbose=False)
    insert_part(con, {**PART_HELIX, "status": "in_stock"}, verbose=False)
    insert_magnet(con, {k: v for k, v in MAGNET_DATA.items() if k != "status"}, "insert", verbose=False)
    insert_magnet_parts(con, "MAG_01", [{"name": "HELIX_01", "type": "helix"}], verbose=False)
    insert_assembly(con, {
        "name": "A1", "housing": "M10",
        "commissioned_at": "2025-01-01 00:00:00", "decommissioned_at": None,
    }, verbose=False)
    insert_assembly_magnets(con, "A1", ["MAG_01"], verbose=False)
    assert con.execute("SELECT status FROM magnets WHERE name = 'MAG_01'").fetchone()[0] == "in_operation"
    assert con.execute("SELECT status FROM parts WHERE name = 'HELIX_01'").fetchone()[0] == "in_operation"

    insert_assembly(con, {
        "name": "A2", "housing": "M10",
        "commissioned_at": "2025-02-01 00:00:00", "decommissioned_at": None,
    }, verbose=False)

    assert con.execute("SELECT status FROM magnets WHERE name = 'MAG_01'").fetchone()[0] == "in_stock"
    assert con.execute("SELECT status FROM parts WHERE name = 'HELIX_01'").fetchone()[0] == "in_operation"
    row = con.execute(
        "SELECT decommissioned_at FROM assembly_magnets WHERE assembly_name = 'A1' AND magnet_name = 'MAG_01'"
    ).fetchone()
    assert row[0] is not None


# ---------------------------------------------------------------------------
# decommission_assembly()
# ---------------------------------------------------------------------------


def test_decommission_assembly_sets_status_and_timestamp(con):
    insert_assembly(con, {
        "name": "A1", "housing": "M10",
        "commissioned_at": "2025-01-01 00:00:00", "decommissioned_at": None,
    }, verbose=False)
    decommission_assembly(con, "A1", decommissioned_at="2025-06-01 00:00:00", verbose=False)
    row = con.execute("SELECT status, decommissioned_at FROM assemblies WHERE name = 'A1'").fetchone()
    assert row[0] == "disassembled"
    assert row[1] is not None


def test_decommission_assembly_cascades_magnet_to_in_stock(con):
    insert_material(con, MATERIAL_COPPER, verbose=False)
    insert_part(con, {**PART_HELIX, "status": "in_stock"}, verbose=False)
    insert_magnet(con, {k: v for k, v in MAGNET_DATA.items() if k != "status"}, "insert", verbose=False)
    insert_magnet_parts(con, "MAG_01", [{"name": "HELIX_01", "type": "helix"}], verbose=False)
    insert_assembly(con, {
        "name": "A1", "housing": "M10",
        "commissioned_at": "2025-01-01 00:00:00", "decommissioned_at": None,
    }, verbose=False)
    insert_assembly_magnets(con, "A1", ["MAG_01"], verbose=False)
    assert con.execute("SELECT status FROM magnets WHERE name = 'MAG_01'").fetchone()[0] == "in_operation"
    assert con.execute("SELECT status FROM parts WHERE name = 'HELIX_01'").fetchone()[0] == "in_operation"

    decommission_assembly(con, "A1", verbose=False)

    assert con.execute("SELECT status FROM magnets WHERE name = 'MAG_01'").fetchone()[0] == "in_stock"
    assert con.execute("SELECT status FROM parts WHERE name = 'HELIX_01'").fetchone()[0] == "in_operation"


def test_decommission_assembly_leaves_retired_magnet_untouched(con):
    insert_material(con, MATERIAL_COPPER, verbose=False)
    insert_part(con, {**PART_HELIX, "status": "in_stock"}, verbose=False)
    insert_magnet(con, {k: v for k, v in MAGNET_DATA.items() if k != "status"}, "insert", verbose=False)
    insert_assembly(con, {
        "name": "A1", "housing": "M10",
        "commissioned_at": "2025-01-01 00:00:00", "decommissioned_at": None,
    }, verbose=False)
    insert_assembly_magnets(con, "A1", ["MAG_01"], verbose=False)
    update_magnet_status(con, "MAG_01", "retired", verbose=False)

    decommission_assembly(con, "A1", verbose=False)

    assert con.execute("SELECT status FROM magnets WHERE name = 'MAG_01'").fetchone()[0] == "retired"


def test_decommission_assembly_backfills_orphaned_link_with_assemblys_own_date(con):
    """An assembly already closed from creation (explicit decommissioned_at)
    can still have an open assembly_magnets link (insert_assembly_magnets
    doesn't read the assembly's own decommissioned_at for plain-string
    magnet entries). Re-calling decommission_assembly on it — e.g. via the
    auto-close paths, with no date of its own to pass in — must backfill
    that link (and log status_history) with the assembly's own true date,
    not a fresh now()/passed-in fallback."""
    insert_material(con, MATERIAL_COPPER, verbose=False)
    insert_part(con, {**PART_HELIX, "status": "in_stock"}, verbose=False)
    insert_magnet(con, {k: v for k, v in MAGNET_DATA.items() if k != "status"}, "insert", verbose=False)
    insert_magnet_parts(con, "MAG_01", [{"name": "HELIX_01", "type": "helix"}], verbose=False)
    insert_assembly(con, {
        "name": "A1", "housing": "M10",
        "commissioned_at": "2025-01-01 00:00:00", "decommissioned_at": "2025-06-01 07:00:00",
    }, verbose=False)
    insert_assembly_magnets(con, "A1", ["MAG_01"], verbose=False)
    assert con.execute(
        "SELECT decommissioned_at FROM assembly_magnets WHERE assembly_name = 'A1' AND magnet_name = 'MAG_01'"
    ).fetchone()[0] is None

    decommission_assembly(con, "A1", verbose=False)  # no decommissioned_at passed -> would default to now()

    link_at, assembly_at = con.execute(
        "SELECT am.decommissioned_at, a.decommissioned_at FROM assembly_magnets am "
        "JOIN assemblies a ON a.name = am.assembly_name "
        "WHERE am.assembly_name = 'A1' AND am.magnet_name = 'MAG_01'"
    ).fetchone()
    assert assembly_at.isoformat() == "2025-06-01T07:00:00"
    assert link_at == assembly_at

    latest_event = json.loads(
        con.execute("SELECT status_history FROM assemblies WHERE name = 'A1'").fetchone()[0]
    )[-1]
    assert latest_event["date"] == "2025-06-01 07:00:00"


def test_decommission_assembly_raises_for_unknown(con):
    with pytest.raises(ValueError):
        decommission_assembly(con, "NOPE", verbose=False)


# ---------------------------------------------------------------------------
# insert_assembly_magnets()
# ---------------------------------------------------------------------------


def test_insert_assembly_magnets_creates_row(con_populated):
    insert_assembly_magnets(con_populated, "ASSEMBLY_01", ["MAG_01"], verbose=False)
    row = con_populated.execute(
        "SELECT z_offset FROM assembly_magnets WHERE assembly_name = 'ASSEMBLY_01' AND magnet_name = 'MAG_01'"
    ).fetchone()
    assert row is not None
    assert row[0] == 0.0


def test_insert_assembly_magnets_stores_offsets(con_populated):
    entry = {"name": "MAG_01", "z_offset": 1.5, "r_offset": 0.3, "parallax": 0.01}
    insert_assembly_magnets(con_populated, "ASSEMBLY_01", [entry], verbose=False)
    row = con_populated.execute(
        "SELECT z_offset, r_offset, parallax FROM assembly_magnets "
        "WHERE assembly_name = 'ASSEMBLY_01' AND magnet_name = 'MAG_01'"
    ).fetchone()
    assert row == (1.5, 0.3, 0.01)


def test_insert_assembly_magnets_skips_duplicate(con_populated):
    insert_assembly_magnets(con_populated, "ASSEMBLY_01", ["MAG_01"], verbose=False)
    insert_assembly_magnets(con_populated, "ASSEMBLY_01", ["MAG_01"], verbose=False)
    count = con_populated.execute(
        "SELECT COUNT(*) FROM assembly_magnets WHERE assembly_name = 'ASSEMBLY_01' AND magnet_name = 'MAG_01'"
    ).fetchone()[0]
    assert count == 1


def test_insert_assembly_magnets_commissions_magnet_and_parts(con):
    insert_material(con, MATERIAL_COPPER, verbose=False)
    insert_part(con, {**PART_HELIX, "status": "in_stock"}, verbose=False)
    insert_magnet(con, {k: v for k, v in MAGNET_DATA.items() if k != "status"}, "insert", verbose=False)
    insert_magnet_part_row(con, "MAG_01", "HELIX_01", 0, 1)
    insert_assembly(con, {
        "name": "A1", "housing": "M10",
        "commissioned_at": "2025-01-01 00:00:00", "decommissioned_at": None,
    }, verbose=False)

    insert_assembly_magnets(con, "A1", ["MAG_01"], verbose=False)

    assert con.execute("SELECT status FROM magnets WHERE name = 'MAG_01'").fetchone()[0] == "in_operation"
    assert con.execute("SELECT status FROM parts WHERE name = 'HELIX_01'").fetchone()[0] == "in_operation"


def test_insert_assembly_magnets_no_cascade_when_assembly_not_active(con):
    insert_magnet(con, {k: v for k, v in MAGNET_DATA.items() if k != "status"}, "insert", verbose=False)
    insert_assembly(con, {
        "name": "A1", "housing": "M10", "status": "in_study",
        "commissioned_at": "2025-01-01 00:00:00", "decommissioned_at": None,
    }, verbose=False)

    insert_assembly_magnets(con, "A1", ["MAG_01"], verbose=False)

    assert con.execute("SELECT status FROM magnets WHERE name = 'MAG_01'").fetchone()[0] == "in_stock"


def test_insert_assembly_magnets_auto_closes_predecessor_on_different_housing(con):
    """A magnet moved to a new housing auto-closes its still-open assembly
    link elsewhere (fallback 07:00 same day as the new commissioned_at),
    instead of being rejected."""
    insert_magnet(con, {k: v for k, v in MAGNET_DATA.items() if k != "status"}, "insert", verbose=False)
    insert_assembly(con, {
        "name": "A1", "housing": "M10",
        "commissioned_at": "2025-01-01 00:00:00", "decommissioned_at": None,
    }, verbose=False)
    insert_assembly_magnets(con, "A1", ["MAG_01"], verbose=False)

    insert_assembly(con, {
        "name": "A2", "housing": "M9",
        "commissioned_at": "2025-06-15 08:00:00", "decommissioned_at": None,
    }, verbose=False)
    insert_assembly_magnets(con, "A2", ["MAG_01"], verbose=False)

    a1_status, a1_decommissioned_at = con.execute(
        "SELECT status, decommissioned_at FROM assemblies WHERE name = 'A1'"
    ).fetchone()
    assert a1_status == "disassembled"
    assert a1_decommissioned_at.isoformat() == "2025-06-15T07:00:00"
    assert con.execute(
        "SELECT 1 FROM assembly_magnets WHERE assembly_name = 'A2' AND magnet_name = 'MAG_01'"
    ).fetchone() is not None


# ---------------------------------------------------------------------------
# insert_experiments()
# ---------------------------------------------------------------------------


def test_insert_experiments_creates_rows(con_populated):
    records = [
        {"name": "run_001.txt", "file": "run_001.txt", "description": ""},
        {"name": "run_002.txt", "file": "run_002.txt", "description": ""},
    ]
    insert_experiments(con_populated, "ASSEMBLY_01", records, verbose=False)
    count = con_populated.execute(
        "SELECT COUNT(*) FROM experiments WHERE assembly_name = 'ASSEMBLY_01'"
    ).fetchone()[0]
    assert count == 2


def test_insert_experiments_skips_duplicate_file(con_populated):
    records = [{"name": "run_001.txt", "file": "run_001.txt"}]
    insert_experiments(con_populated, "ASSEMBLY_01", records, verbose=False)
    insert_experiments(con_populated, "ASSEMBLY_01", records, verbose=False)
    count = con_populated.execute(
        "SELECT COUNT(*) FROM experiments WHERE file = 'run_001.txt'"
    ).fetchone()[0]
    assert count == 1


# ---------------------------------------------------------------------------
# update_part_from_json()
# ---------------------------------------------------------------------------


def test_update_part_from_json_updates_only_present_fields(con):
    insert_material(con, MATERIAL_COPPER, verbose=False)
    insert_part(con, PART_HELIX, verbose=False)
    update_part_from_json(con, {"name": "HELIX_01", "cad": "/new/cad.step"}, verbose=False)
    row = con.execute(
        "SELECT cad, geometry, design_office_reference FROM parts WHERE name = 'HELIX_01'"
    ).fetchone()
    assert row == ("/new/cad.step", None, "HL-TEST")


def test_update_part_from_json_leaves_status_and_type_untouched(con):
    insert_material(con, MATERIAL_COPPER, verbose=False)
    insert_part(con, PART_HELIX, verbose=False)
    update_part_from_json(
        con, {"name": "HELIX_01", "type": "ring", "status": "dead", "cad": "/x.step"},
        verbose=False,
    )
    row = con.execute("SELECT type, status FROM parts WHERE name = 'HELIX_01'").fetchone()
    assert row == ("helix", "in_operation")


def test_update_part_from_json_recomputes_geometry_data_when_geometry_changes(con, monkeypatch):
    insert_material(con, MATERIAL_COPPER, verbose=False)
    insert_part(con, PART_HELIX, verbose=False)
    monkeypatch.setattr("crud.load_geometry_json", lambda path: '{"__classname__": "Helix"}')
    update_part_from_json(con, {"name": "HELIX_01", "geometry": "/new/HELIX_01.yaml"}, verbose=False)
    row = con.execute("SELECT geometry, geometry_data FROM parts WHERE name = 'HELIX_01'").fetchone()
    assert row[0] == "/new/HELIX_01.yaml"
    assert row[1] is not None


def test_update_part_from_json_uses_explicit_geometry_data_over_recompute(con, monkeypatch):
    insert_material(con, MATERIAL_COPPER, verbose=False)
    insert_part(con, PART_HELIX, verbose=False)
    monkeypatch.setattr(
        "crud.load_geometry_json",
        lambda path: (_ for _ in ()).throw(AssertionError("should not be called")),
    )
    update_part_from_json(
        con, {"name": "HELIX_01", "geometry_data": '{"__classname__": "Helix"}'}, verbose=False,
    )
    row = con.execute("SELECT geometry_data FROM parts WHERE name = 'HELIX_01'").fetchone()
    assert row[0] is not None


def test_update_part_from_json_raises_for_unknown_material(con):
    insert_material(con, MATERIAL_COPPER, verbose=False)
    insert_part(con, PART_HELIX, verbose=False)
    with pytest.raises(ValueError):
        update_part_from_json(con, {"name": "HELIX_01", "material_name": "NOPE"}, verbose=False)


def test_update_part_from_json_raises_for_unknown_part(con):
    with pytest.raises(ValueError):
        update_part_from_json(con, {"name": "NOPE", "cad": "/x.step"}, verbose=False)


def test_update_part_from_json_nothing_to_update(con, capsys):
    insert_material(con, MATERIAL_COPPER, verbose=False)
    insert_part(con, PART_HELIX, verbose=False)
    update_part_from_json(con, {"name": "HELIX_01"}, verbose=True)
    row = con.execute("SELECT cad FROM parts WHERE name = 'HELIX_01'").fetchone()
    assert row[0] is None
    assert "nothing to update" in capsys.readouterr().out


def test_update_part_from_json_dry_run_does_not_write(con, capsys):
    insert_material(con, MATERIAL_COPPER, verbose=False)
    insert_part(con, PART_HELIX, verbose=False)
    update_part_from_json(con, {"name": "HELIX_01", "cad": "/new/cad.step"}, dry_run=True, verbose=True)
    row = con.execute("SELECT cad FROM parts WHERE name = 'HELIX_01'").fetchone()
    assert row[0] is None
    assert "dry-run" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# update_part_status()
# ---------------------------------------------------------------------------


def test_update_part_status_appends_history(con):
    insert_material(con, MATERIAL_COPPER, verbose=False)
    insert_part(con, PART_HELIX, verbose=False)
    update_part_status(con, "HELIX_01", "retired", description="worn out", verbose=False)
    row = con.execute("SELECT status, status_history FROM parts WHERE name = 'HELIX_01'").fetchone()
    assert row[0] == "retired"
    history = json.loads(row[1])
    assert history[-1]["status"] == "retired"
    assert history[-1]["description"] == "worn out"


def test_update_part_status_raises_for_unknown_part(con):
    with pytest.raises(ValueError):
        update_part_status(con, "NOPE", "retired", verbose=False)


def test_update_part_status_raises_for_invalid_status(con):
    insert_material(con, MATERIAL_COPPER, verbose=False)
    insert_part(con, PART_HELIX, verbose=False)
    with pytest.raises(ValueError):
        update_part_status(con, "HELIX_01", "bogus", verbose=False)


# ---------------------------------------------------------------------------
# update_magnet_from_json()
# ---------------------------------------------------------------------------


def test_update_magnet_from_json_updates_only_present_fields(con_populated):
    update_magnet_from_json(
        con_populated, {"name": "MAG_01", "design_office_reference": "MAG-NEW"}, verbose=False,
    )
    row = con_populated.execute(
        "SELECT design_office_reference, geometry FROM magnets WHERE name = 'MAG_01'"
    ).fetchone()
    assert row == ("MAG-NEW", None)


def test_update_magnet_from_json_leaves_status_type_and_parts_untouched(con_populated):
    before_parts = con_populated.execute(
        "SELECT part_name FROM magnet_parts WHERE magnet_name = 'MAG_01' ORDER BY part_name"
    ).fetchall()
    update_magnet_from_json(
        con_populated,
        {"name": "MAG_01", "type": "bitters", "status": "dead", "design_office_reference": "X"},
        verbose=False,
    )
    row = con_populated.execute("SELECT type, status FROM magnets WHERE name = 'MAG_01'").fetchone()
    assert row == ("insert", "in_operation")
    after_parts = con_populated.execute(
        "SELECT part_name FROM magnet_parts WHERE magnet_name = 'MAG_01' ORDER BY part_name"
    ).fetchall()
    assert after_parts == before_parts


def test_update_magnet_from_json_recomputes_geometry_data_when_geometry_changes(con_populated, monkeypatch):
    monkeypatch.setattr("crud.load_geometry_json", lambda path: '{"__classname__": "Insert"}')
    update_magnet_from_json(con_populated, {"name": "MAG_01", "geometry": "/new/MAG_01.yaml"}, verbose=False)
    row = con_populated.execute(
        "SELECT geometry, geometry_data FROM magnets WHERE name = 'MAG_01'"
    ).fetchone()
    assert row[0] == "/new/MAG_01.yaml"
    assert row[1] is not None


def test_update_magnet_from_json_raises_for_unknown_magnet(con):
    with pytest.raises(ValueError):
        update_magnet_from_json(con, {"name": "NOPE", "design_office_reference": "X"}, verbose=False)


def test_update_magnet_from_json_nothing_to_update(con_populated, capsys):
    update_magnet_from_json(con_populated, {"name": "MAG_01"}, verbose=True)
    assert "nothing to update" in capsys.readouterr().out


def test_update_magnet_from_json_dry_run_does_not_write(con_populated, capsys):
    update_magnet_from_json(
        con_populated, {"name": "MAG_01", "design_office_reference": "MAG-NEW"},
        dry_run=True, verbose=True,
    )
    row = con_populated.execute(
        "SELECT design_office_reference FROM magnets WHERE name = 'MAG_01'"
    ).fetchone()
    assert row[0] == "MAG-TEST-001"
    assert "dry-run" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# update_magnet_status()
# ---------------------------------------------------------------------------


def test_update_magnet_status_in_stock_leaves_parts_untouched(con_populated):
    update_magnet_status(con_populated, "MAG_01", "in_stock", verbose=False)
    assert con_populated.execute(
        "SELECT status FROM magnets WHERE name = 'MAG_01'"
    ).fetchone()[0] == "in_stock"
    assert con_populated.execute(
        "SELECT status FROM parts WHERE name = 'HELIX_01'"
    ).fetchone()[0] == "in_operation"
    assert con_populated.execute(
        "SELECT status FROM parts WHERE name = 'RING_01'"
    ).fetchone()[0] == "in_operation"


def test_update_magnet_status_retired_cascades_parts_to_in_stock(con_populated):
    update_magnet_status(con_populated, "MAG_01", "retired", verbose=False)
    assert con_populated.execute(
        "SELECT status FROM magnets WHERE name = 'MAG_01'"
    ).fetchone()[0] == "retired"
    assert con_populated.execute(
        "SELECT status FROM parts WHERE name = 'HELIX_01'"
    ).fetchone()[0] == "in_stock"
    assert con_populated.execute(
        "SELECT status FROM parts WHERE name = 'RING_01'"
    ).fetchone()[0] == "in_stock"


def test_update_magnet_status_raises_for_unknown_magnet(con):
    with pytest.raises(ValueError):
        update_magnet_status(con, "NOPE", "in_stock", verbose=False)


def test_update_magnet_status_dead_requires_dead_parts(con_populated):
    with pytest.raises(ValueError, match="at least one dead part"):
        update_magnet_status(con_populated, "MAG_01", "dead", verbose=False)


def test_update_magnet_status_dead_rejects_unknown_dead_part(con_populated):
    with pytest.raises(ValueError, match="do not belong"):
        update_magnet_status(con_populated, "MAG_01", "dead", dead_parts=["NOT_A_PART"], verbose=False)


def test_update_magnet_status_dead_succeeds_with_valid_dead_parts(con_populated):
    update_magnet_status(con_populated, "MAG_01", "dead", dead_parts=["HELIX_01"],
                         description="burst", verbose=False)
    assert con_populated.execute(
        "SELECT status FROM magnets WHERE name = 'MAG_01'"
    ).fetchone()[0] == "dead"
    assert con_populated.execute(
        "SELECT status FROM parts WHERE name = 'HELIX_01'"
    ).fetchone()[0] == "dead"
    # RING_01 wasn't named dead — the ordinary downward cascade still applies to it
    assert con_populated.execute(
        "SELECT status FROM parts WHERE name = 'RING_01'"
    ).fetchone()[0] == "in_stock"


def test_update_magnet_status_dead_parts_rejected_with_non_dead_status(con_populated):
    with pytest.raises(ValueError, match="only valid with"):
        update_magnet_status(con_populated, "MAG_01", "in_stock", dead_parts=["HELIX_01"], verbose=False)


def test_update_magnet_status_same_status_recall_logs_without_recascading(con_populated):
    update_magnet_status(con_populated, "MAG_01", "retired", verbose=False)
    history_1 = json.loads(
        con_populated.execute("SELECT status_history FROM magnets WHERE name = 'MAG_01'").fetchone()[0]
    )
    update_magnet_status(con_populated, "MAG_01", "retired", verbose=False)
    row = con_populated.execute(
        "SELECT status, status_history FROM magnets WHERE name = 'MAG_01'"
    ).fetchone()
    assert row[0] == "retired"
    history_2 = json.loads(row[1])
    assert len(history_2) == len(history_1) + 1
    assert con_populated.execute(
        "SELECT status FROM parts WHERE name = 'HELIX_01'"
    ).fetchone()[0] == "in_stock"


def test_update_magnet_status_dead_warns_without_description_or_attachment(con_populated, capsys):
    update_magnet_status(con_populated, "MAG_01", "dead", dead_parts=["HELIX_01"], verbose=False)
    assert "WARNING" in capsys.readouterr().out


def test_update_magnet_status_dead_no_warning_with_description(con_populated, capsys):
    update_magnet_status(con_populated, "MAG_01", "dead", dead_parts=["HELIX_01"],
                         description="incident report attached", verbose=False)
    assert "WARNING" not in capsys.readouterr().out


# ---------------------------------------------------------------------------
# update_assembly_magnet()
# ---------------------------------------------------------------------------


def test_update_assembly_magnet_updates_offset(con_populated):
    insert_assembly_magnets(con_populated, "ASSEMBLY_01", ["MAG_01"], verbose=False)
    update_assembly_magnet(con_populated, "ASSEMBLY_01", "MAG_01", z_offset=12.5)
    row = con_populated.execute(
        "SELECT z_offset FROM assembly_magnets WHERE assembly_name = 'ASSEMBLY_01' AND magnet_name = 'MAG_01'"
    ).fetchone()
    assert row[0] == 12.5


def test_update_assembly_magnet_updates_only_passed_fields(con_populated):
    insert_assembly_magnets(con_populated, "ASSEMBLY_01", [{"name": "MAG_01", "r_offset": 0.5}], verbose=False)
    update_assembly_magnet(con_populated, "ASSEMBLY_01", "MAG_01", z_offset=3.0)
    row = con_populated.execute(
        "SELECT z_offset, r_offset FROM assembly_magnets WHERE assembly_name = 'ASSEMBLY_01' AND magnet_name = 'MAG_01'"
    ).fetchone()
    assert row[0] == 3.0
    assert row[1] == 0.5  # unchanged


def test_update_assembly_magnet_raises_when_row_missing(con_populated):
    with pytest.raises(ValueError, match="No link"):
        update_assembly_magnet(con_populated, "ASSEMBLY_01", "NONEXISTENT", z_offset=1.0)


def test_update_assembly_magnet_nothing_to_update(con_populated, capsys):
    insert_assembly_magnets(con_populated, "ASSEMBLY_01", ["MAG_01"], verbose=False)
    update_assembly_magnet(con_populated, "ASSEMBLY_01", "MAG_01")
    captured = capsys.readouterr()
    assert "Nothing to update" in captured.out


# ---------------------------------------------------------------------------
# update_assembly_from_json()
# ---------------------------------------------------------------------------


def test_update_assembly_from_json_updates_description(con_populated):
    update_assembly_from_json(con_populated, {"name": "ASSEMBLY_01", "description": "new note"}, verbose=False)
    row = con_populated.execute(
        "SELECT description FROM assemblies WHERE name = 'ASSEMBLY_01'"
    ).fetchone()
    assert row[0] == "new note"


def test_update_assembly_from_json_leaves_status_and_housing_untouched(con_populated):
    update_assembly_from_json(
        con_populated,
        {"name": "ASSEMBLY_01", "description": "x", "status": "disassembled", "housing": "M99"},
        verbose=False,
    )
    row = con_populated.execute(
        "SELECT status, housing FROM assemblies WHERE name = 'ASSEMBLY_01'"
    ).fetchone()
    assert row == ("in_operation", "M10")


def test_update_assembly_from_json_raises_for_unknown_assembly(con):
    with pytest.raises(ValueError):
        update_assembly_from_json(con, {"name": "NOPE", "description": "x"}, verbose=False)


def test_update_assembly_from_json_nothing_to_update(con_populated, capsys):
    update_assembly_from_json(con_populated, {"name": "ASSEMBLY_01"}, verbose=True)
    assert "nothing to update" in capsys.readouterr().out


def test_update_assembly_from_json_dry_run_does_not_write(con_populated, capsys):
    update_assembly_from_json(
        con_populated, {"name": "ASSEMBLY_01", "description": "new note"}, dry_run=True, verbose=True,
    )
    row = con_populated.execute(
        "SELECT description FROM assemblies WHERE name = 'ASSEMBLY_01'"
    ).fetchone()
    assert row[0] == "Test assembly"
    assert "dry-run" in capsys.readouterr().out


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
# view_assemblies() / view_assembly()
# ---------------------------------------------------------------------------


def test_view_assemblies_empty(con, capsys):
    view_assemblies(con)
    assert "No assemblies" in capsys.readouterr().out


def test_view_assemblies_lists_row(con_populated, capsys):
    view_assemblies(con_populated)
    out = capsys.readouterr().out
    assert "ASSEMBLY_01" in out
    assert "M10" in out


def test_view_assembly_not_found(con, capsys):
    view_assembly(con, "NONEXISTENT")
    assert "not found" in capsys.readouterr().out


def test_view_assembly_shows_detail(con_populated, capsys):
    insert_assembly_magnets(con_populated, "ASSEMBLY_01", ["MAG_01"], verbose=False)
    records = [{"name": "run.txt", "file": "run.txt"}]
    insert_experiments(con_populated, "ASSEMBLY_01", records, verbose=False)
    view_assembly(con_populated, "ASSEMBLY_01")
    out = capsys.readouterr().out
    assert "ASSEMBLY_01" in out
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
# delete_assembly()
# ---------------------------------------------------------------------------


def test_delete_assembly_removes_assembly_row(con_populated):
    delete_assembly(con_populated, "ASSEMBLY_01")
    assert not exists(con_populated, "assemblies", "ASSEMBLY_01")


def test_delete_assembly_removes_assembly_magnet_links(con_populated):
    insert_assembly_magnets(con_populated, "ASSEMBLY_01", ["MAG_01"], verbose=False)
    delete_assembly(con_populated, "ASSEMBLY_01")
    count = con_populated.execute(
        "SELECT COUNT(*) FROM assembly_magnets WHERE assembly_name = 'ASSEMBLY_01'"
    ).fetchone()[0]
    assert count == 0


def test_delete_assembly_removes_experiments(con_populated):
    records = [{"name": "run.txt", "file": "run.txt"}]
    insert_experiments(con_populated, "ASSEMBLY_01", records, verbose=False)
    delete_assembly(con_populated, "ASSEMBLY_01")
    count = con_populated.execute(
        "SELECT COUNT(*) FROM experiments WHERE assembly_name = 'ASSEMBLY_01'"
    ).fetchone()[0]
    assert count == 0


def test_delete_assembly_not_found(con, capsys):
    delete_assembly(con, "NONEXISTENT")
    assert "not found" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# _parse_overview_filename()
# ---------------------------------------------------------------------------


def test_parse_overview_filename_valid():
    housing, t0 = _parse_overview_filename("M9_Overview_220127-1756")
    assert housing == "M9"
    assert t0 == datetime(2022, 1, 27, 17, 56, tzinfo=FILE_TZ)


def test_parse_overview_filename_bad_timestamp():
    housing, t0 = _parse_overview_filename("M9_Overview_notatimestamp")
    assert housing == "M9"
    assert t0 is None


# ---------------------------------------------------------------------------
# _find_assembly_for_timestamp()
# ---------------------------------------------------------------------------


def _insert_m9_assemblies(con):
    """Two consecutive M9 operational windows, with a gap in between."""
    insert_assembly(con, {
        "name": "M9_ASSEMBLY_A", "housing": "M9",
        "commissioned_at": "2022-01-01 00:00:00",
        "decommissioned_at": "2022-01-10 00:00:00",
    }, verbose=False)
    insert_assembly(con, {
        "name": "M9_ASSEMBLY_B", "housing": "M9",
        "commissioned_at": "2022-01-18 00:00:00",
        "decommissioned_at": None,
    }, verbose=False)


def test_find_assembly_for_timestamp_matches_unique_assembly(con):
    _insert_m9_assemblies(con)
    t0 = datetime(2022, 1, 27, 17, 56, tzinfo=FILE_TZ)
    assert _find_assembly_for_timestamp(con, "M9", t0, FILE_TZ) == "M9_ASSEMBLY_B"


def test_find_assembly_for_timestamp_matches_open_ended_window(con):
    _insert_m9_assemblies(con)
    t0 = datetime(2022, 1, 5, 12, 0, tzinfo=FILE_TZ)
    assert _find_assembly_for_timestamp(con, "M9", t0, FILE_TZ) == "M9_ASSEMBLY_A"


def test_find_assembly_for_timestamp_no_match_in_gap(con):
    _insert_m9_assemblies(con)
    t0 = datetime(2022, 1, 14, 0, 0, tzinfo=FILE_TZ)
    assert _find_assembly_for_timestamp(con, "M9", t0, FILE_TZ) is None


def test_find_assembly_for_timestamp_ambiguous_match(con):
    _insert_m9_assemblies(con)
    # insert_assembly() now rejects/auto-closes overlapping windows (the new
    # no-overlap invariant), so this deliberately-ambiguous fixture — two
    # open windows on the same housing — is inserted directly to simulate
    # legacy data that predates the invariant.
    con.execute(
        "INSERT INTO assemblies (name, status, housing, commissioned_at, decommissioned_at) "
        "VALUES (?,?,?,?,?)",
        ["M9_ASSEMBLY_OVERLAP", "in_operation", "M9", "2022-01-20 00:00:00", None],
    )
    t0 = datetime(2022, 1, 27, 17, 56, tzinfo=FILE_TZ)
    assert _find_assembly_for_timestamp(con, "M9", t0, FILE_TZ) is None


def test_find_assembly_for_timestamp_no_housing_match(con):
    _insert_m9_assemblies(con)
    t0 = datetime(2022, 1, 27, 17, 56, tzinfo=FILE_TZ)
    assert _find_assembly_for_timestamp(con, "M10", t0, FILE_TZ) is None


# ---------------------------------------------------------------------------
# resolve_overview_assembly()
# ---------------------------------------------------------------------------


def test_resolve_overview_assembly_matches_unique_assembly(con):
    _insert_m9_assemblies(con)
    housing, t0, assembly_name = resolve_overview_assembly(con, "M9_Overview_220127-1756", FILE_TZ)
    assert housing == "M9"
    assert t0 == datetime(2022, 1, 27, 17, 56)
    assert assembly_name == "M9_ASSEMBLY_B"


def test_resolve_overview_assembly_bad_filename_returns_housing_only(con):
    _insert_m9_assemblies(con)
    housing, t0, assembly_name = resolve_overview_assembly(con, "M9_Overview_notatimestamp", FILE_TZ)
    assert housing == "M9"
    assert t0 is None
    assert assembly_name is None


def test_resolve_overview_assembly_no_assembly_match_still_returns_housing_and_t0(con):
    _insert_m9_assemblies(con)
    housing, t0, assembly_name = resolve_overview_assembly(con, "M9_Overview_220114-0000", FILE_TZ)
    assert housing == "M9"
    assert t0 == datetime(2022, 1, 14, 0, 0)
    assert assembly_name is None


# ---------------------------------------------------------------------------
# insert_overview_record_from_dict()
# ---------------------------------------------------------------------------


def test_insert_overview_record_from_dict_reduces_sources_to_basename(con):
    insert_overview_record_from_dict(
        con,
        {
            "filename": "M10_Overview_250127-1605",
            "overview": "/mnt/LNCMIG-Data/records/pbsurv/M10/Overview/M10_Overview_250127-1605.tdms",
            "archive": (
                "/mnt/LNCMIG-Data/records/pbsurv/M10/Fichiers_Archive/M10_Archive_250127-1605.tdms, "
                "/mnt/LNCMIG-Data/records/pbsurv/M10/Fichiers_Archive/M10_Archive_250127-2105.tdms"
            ),
            "pupitre": ["/mnt/LNCMIG-Data/records/srv-data-install/M10/2025.01.27 - 15:39:29.txt"],
        },
        verbose=False,
    )
    row = con.execute(
        "SELECT sources_overview, sources_archive, sources_pupitre FROM overview_records "
        "WHERE filename = 'M10_Overview_250127-1605'"
    ).fetchone()
    assert row == (
        ["M10_Overview_250127-1605.tdms"],
        ["M10_Archive_250127-1605.tdms", "M10_Archive_250127-2105.tdms"],
        ["2025.01.27 - 15:39:29.txt"],
    )


# ---------------------------------------------------------------------------
# merge_duplicate_pupitre_records()
# ---------------------------------------------------------------------------


def _overview_dict(filename, t0, duration, teb, bp, pupitre, housing="M9", **extra):
    return {
        "filename": filename,
        "housing": housing,
        "t0": t0,
        "duration": duration,
        "teb": teb,
        "bp": bp,
        "sources_pupitre": pupitre,
        **extra,
    }


def _ensure_assembly(con, assembly_name, housing):
    """Insert a minimal housing_config + assemblies row, satisfying overview_records's FK."""
    if con.execute("SELECT 1 FROM housing_config WHERE name = ?", [housing]).fetchone() is None:
        con.execute(
            "INSERT INTO housing_config (name, coil_assignment, formats) VALUES (?, MAP{}, [])",
            [housing],
        )
    if con.execute("SELECT 1 FROM assemblies WHERE name = ?", [assembly_name]).fetchone() is None:
        con.execute(
            "INSERT INTO assemblies (name, housing, status, commissioned_at, decommissioned_at) "
            "VALUES (?, ?, 'active', '2022-01-01 00:00:00', NULL)",
            [assembly_name, housing],
        )


def _insert_overview(con, *args, **kwargs):
    data = _overview_dict(*args, **kwargs)
    if data.get("assembly_name"):
        _ensure_assembly(con, data["assembly_name"], data["housing"])
    insert_overview_record_from_dict(con, data, verbose=False)


def test_merge_duplicate_pupitre_records_merges_shared_pupitre_lower_t0_first(con):
    # 1700 ends at 17:01:40 (duration=100s); 1702 starts 20s later — within
    # the default 60s adjacency threshold.
    _insert_overview(
        con, "M9_Overview_220127-1700", "2022-01-27 17:00:00", 100.0, 10.0, 1.0,
        ["p1.tdms", "p2.tdms"], assembly_name="M9_ASSEMBLY_A",
        signatures={"sigA": {"min": 0, "max": 1}},
    )
    _insert_overview(
        con, "M9_Overview_220127-1702", "2022-01-27 17:02:00", 200.0, 20.0, 2.0,
        ["p2.tdms", "p3.tdms"], assembly_name="M9_ASSEMBLY_A",
        signatures={"sigB": {"min": 2, "max": 3}},
    )

    result = merge_duplicate_pupitre_records(con, verbose=False)
    assert result == {"groups_checked": 1, "merges": 1}

    rows = con.execute("SELECT filename FROM overview_records ORDER BY filename").fetchall()
    assert rows == [("M9_Overview_220127-1700",), ("M9_Overview_220127-1702",)]

    sources_pupitre, duration, teb, bp, signatures, merged_into = con.execute(
        "SELECT sources_pupitre, duration, teb, bp, signatures, merged_into "
        "FROM overview_records WHERE filename = 'M9_Overview_220127-1700'"
    ).fetchone()
    assert sources_pupitre == ["p1.tdms", "p2.tdms", "p3.tdms"]
    # 320s span (17:00:00 -> 17:05:20), not the 300s sum: includes the 20s
    # real gap between the first row's end (17:01:40) and the second's t0.
    assert duration == pytest.approx(320.0)
    assert teb == pytest.approx((10.0 * 100.0 + 20.0 * 200.0) / 300.0)
    assert bp == pytest.approx((1.0 * 100.0 + 2.0 * 200.0) / 300.0)
    assert json.loads(signatures) == {
        "sigA": {"min": 0, "max": 1},
        "sigB": {"min": 2, "max": 3},
    }
    assert merged_into is None

    absorbed_merged_into = con.execute(
        "SELECT merged_into FROM overview_records WHERE filename = 'M9_Overview_220127-1702'"
    ).fetchone()[0]
    assert absorbed_merged_into == "M9_Overview_220127-1700"


def test_merge_duplicate_pupitre_records_merges_shared_pupitre_higher_t0_first(con):
    _insert_overview(
        con, "M9_Overview_220127-1702", "2022-01-27 17:02:00", 200.0, 20.0, 2.0,
        ["p2.tdms", "p3.tdms"], assembly_name="M9_ASSEMBLY_A",
    )
    _insert_overview(
        con, "M9_Overview_220127-1700", "2022-01-27 17:00:00", 100.0, 10.0, 1.0,
        ["p1.tdms", "p2.tdms"], assembly_name="M9_ASSEMBLY_A",
    )

    merge_duplicate_pupitre_records(con, verbose=False)

    sources_pupitre, duration, merged_into = con.execute(
        "SELECT sources_pupitre, duration, merged_into FROM overview_records "
        "WHERE filename = 'M9_Overview_220127-1700'"
    ).fetchone()
    assert sources_pupitre == ["p1.tdms", "p2.tdms", "p3.tdms"]
    assert duration == pytest.approx(320.0)
    assert merged_into is None

    assert con.execute(
        "SELECT merged_into FROM overview_records WHERE filename = 'M9_Overview_220127-1702'"
    ).fetchone()[0] == "M9_Overview_220127-1700"


def test_merge_duplicate_pupitre_records_no_merge_when_gap_too_large(con):
    """Regression test: a shared pupitre file alone must not trigger a merge.

    Real data shows one pupitre log can legitimately span several genuinely
    distinct Overview captures hours apart (pupitre rotates on a much
    coarser cadence than pigbrother TDMS captures) — sharing a
    sources_pupitre entry is not sufficient on its own.
    """
    _insert_overview(
        con, "M9_Overview_220127-1700", "2022-01-27 17:00:00", 100.0, 10.0, 1.0,
        ["p1.tdms", "p2.tdms"], assembly_name="M9_ASSEMBLY_A",
    )
    _insert_overview(
        con, "M9_Overview_220127-1800", "2022-01-27 18:00:00", 200.0, 20.0, 2.0,
        ["p2.tdms", "p3.tdms"], assembly_name="M9_ASSEMBLY_A",
    )

    result = merge_duplicate_pupitre_records(con, verbose=False)
    assert result == {"groups_checked": 1, "merges": 0}

    rows = con.execute(
        "SELECT filename, merged_into FROM overview_records ORDER BY filename"
    ).fetchall()
    assert rows == [
        ("M9_Overview_220127-1700", None),
        ("M9_Overview_220127-1800", None),
    ]

    # Widening the threshold enough (~58 minutes here) makes it merge after all.
    result = merge_duplicate_pupitre_records(con, verbose=False, max_gap_seconds=3600.0)
    assert result == {"groups_checked": 1, "merges": 1}
    assert con.execute(
        "SELECT merged_into FROM overview_records WHERE filename = 'M9_Overview_220127-1800'"
    ).fetchone()[0] == "M9_Overview_220127-1700"


def test_merge_duplicate_pupitre_records_no_merge_when_housing_differs(con):
    _insert_overview(
        con, "M9_Overview_220127-1700", "2022-01-27 17:00:00", 100.0, 10.0, 1.0,
        ["shared.tdms"], housing="M9", assembly_name="M9_ASSEMBLY_A",
    )
    _insert_overview(
        con, "M10_Overview_220127-1800", "2022-01-27 18:00:00", 200.0, 20.0, 2.0,
        ["shared.tdms"], housing="M10", assembly_name="M10_ASSEMBLY_A",
    )

    result = merge_duplicate_pupitre_records(con, verbose=False)
    assert result == {"groups_checked": 2, "merges": 0}

    rows = con.execute(
        "SELECT filename, merged_into FROM overview_records ORDER BY filename"
    ).fetchall()
    assert rows == [
        ("M10_Overview_220127-1800", None),
        ("M9_Overview_220127-1700", None),
    ]


def test_merge_duplicate_pupitre_records_no_merge_when_assembly_name_differs(con):
    _insert_overview(
        con, "M9_Overview_220127-1700", "2022-01-27 17:00:00", 100.0, 10.0, 1.0,
        ["shared.tdms"], assembly_name="M9_ASSEMBLY_A",
    )
    _insert_overview(
        con, "M9_Overview_220127-1800", "2022-01-27 18:00:00", 200.0, 20.0, 2.0,
        ["shared.tdms"], assembly_name="M9_ASSEMBLY_B",
    )

    result = merge_duplicate_pupitre_records(con, verbose=False)
    assert result == {"groups_checked": 2, "merges": 0}

    rows = con.execute(
        "SELECT filename, merged_into FROM overview_records ORDER BY filename"
    ).fetchall()
    assert rows == [
        ("M9_Overview_220127-1700", None),
        ("M9_Overview_220127-1800", None),
    ]


def test_merge_duplicate_pupitre_records_no_merge_without_shared_pupitre(con):
    _insert_overview(
        con, "M9_Overview_220127-1700", "2022-01-27 17:00:00", 100.0, 10.0, 1.0,
        ["p1.tdms"], assembly_name="M9_ASSEMBLY_A",
    )
    _insert_overview(
        con, "M9_Overview_220127-1800", "2022-01-27 18:00:00", 200.0, 20.0, 2.0,
        ["p2.tdms"], assembly_name="M9_ASSEMBLY_A",
    )

    result = merge_duplicate_pupitre_records(con, verbose=False)
    assert result == {"groups_checked": 1, "merges": 0}

    rows = con.execute(
        "SELECT filename, merged_into FROM overview_records ORDER BY filename"
    ).fetchall()
    assert rows == [
        ("M9_Overview_220127-1700", None),
        ("M9_Overview_220127-1800", None),
    ]


def test_merge_duplicate_pupitre_records_chains_three_way(con):
    # Each record ends 100s after its t0 and the next starts 20s later —
    # all three gaps (20s) are within the default 60s threshold.
    _insert_overview(
        con, "M9_Overview_220127-1700", "2022-01-27 17:00:00", 100.0, 10.0, 1.0,
        ["p1.tdms", "p2.tdms"], assembly_name="M9_ASSEMBLY_A",
    )
    _insert_overview(
        con, "M9_Overview_220127-1702", "2022-01-27 17:02:00", 100.0, 10.0, 1.0,
        ["p2.tdms", "p3.tdms"], assembly_name="M9_ASSEMBLY_A",
    )
    _insert_overview(
        con, "M9_Overview_220127-1704", "2022-01-27 17:04:00", 100.0, 10.0, 1.0,
        ["p3.tdms", "p4.tdms"], assembly_name="M9_ASSEMBLY_A",
    )

    result = merge_duplicate_pupitre_records(con, verbose=False)
    assert result == {"groups_checked": 1, "merges": 2}

    rows = con.execute(
        "SELECT filename, merged_into FROM overview_records ORDER BY filename"
    ).fetchall()
    assert rows == [
        ("M9_Overview_220127-1700", None),
        ("M9_Overview_220127-1702", "M9_Overview_220127-1700"),
        ("M9_Overview_220127-1704", "M9_Overview_220127-1700"),
    ]
    sources_pupitre, duration = con.execute(
        "SELECT sources_pupitre, duration FROM overview_records "
        "WHERE filename = 'M9_Overview_220127-1700'"
    ).fetchone()
    assert sources_pupitre == ["p1.tdms", "p2.tdms", "p3.tdms", "p4.tdms"]
    # 340s span (17:00:00 -> 17:05:40): the 300s sum plus the two 20s real
    # gaps between consecutive captures.
    assert duration == pytest.approx(340.0)


def test_merge_duplicate_pupitre_records_chain_does_not_drift_with_summed_duration(con):
    """Regression test: a long chain must compare against each survivor's real
    last end, not against t0 + cumulative summed duration.

    Summing durations across merges silently swallows the small real
    dead-time gaps already absorbed into earlier links of the chain. Four
    records here each have a real 25s gap to the next — well within the
    default 60s threshold — but the two internal gaps (25s + 25s = 50s)
    would inflate the *naive* t0+duration comparison for the last link to
    75s (over threshold) if the survivor's true last end weren't tracked
    separately. This mirrors what real M9 December 2025 data showed.
    """
    _insert_overview(
        con, "M9_Overview_220127-1700", "2022-01-27 17:00:00", 100.0, 10.0, 1.0,
        ["p1.tdms", "p2.tdms"], assembly_name="M9_ASSEMBLY_A",
    )
    _insert_overview(
        con, "M9_Overview_220127-1702", "2022-01-27 17:02:05", 100.0, 10.0, 1.0,
        ["p2.tdms", "p3.tdms"], assembly_name="M9_ASSEMBLY_A",
    )
    _insert_overview(
        con, "M9_Overview_220127-1704", "2022-01-27 17:04:10", 100.0, 10.0, 1.0,
        ["p3.tdms", "p4.tdms"], assembly_name="M9_ASSEMBLY_A",
    )
    _insert_overview(
        con, "M9_Overview_220127-1706", "2022-01-27 17:06:15", 100.0, 10.0, 1.0,
        ["p4.tdms", "p5.tdms"], assembly_name="M9_ASSEMBLY_A",
    )

    result = merge_duplicate_pupitre_records(con, verbose=False)
    assert result == {"groups_checked": 1, "merges": 3}

    rows = con.execute(
        "SELECT filename, merged_into FROM overview_records ORDER BY filename"
    ).fetchall()
    assert rows == [
        ("M9_Overview_220127-1700", None),
        ("M9_Overview_220127-1702", "M9_Overview_220127-1700"),
        ("M9_Overview_220127-1704", "M9_Overview_220127-1700"),
        ("M9_Overview_220127-1706", "M9_Overview_220127-1700"),
    ]
    duration = con.execute(
        "SELECT duration FROM overview_records WHERE filename = 'M9_Overview_220127-1700'"
    ).fetchone()[0]
    # 475s span (17:00:00 -> 17:07:55): the 400s sum plus the three internal
    # real gaps (25s + 25s + 25s) now included instead of swallowed.
    assert duration == pytest.approx(475.0)


def test_merge_duplicate_pupitre_records_flattens_pointer_on_re_merge(con):
    _insert_overview(
        con, "M9_Overview_220127-1700", "2022-01-27 17:00:00", 100.0, 10.0, 1.0,
        ["p1.tdms", "p2.tdms"], assembly_name="M9_ASSEMBLY_A",
    )
    _insert_overview(
        con, "M9_Overview_220127-1702", "2022-01-27 17:02:00", 100.0, 10.0, 1.0,
        ["p2.tdms"], assembly_name="M9_ASSEMBLY_A",
    )
    merge_duplicate_pupitre_records(con, verbose=False)
    assert con.execute(
        "SELECT merged_into FROM overview_records WHERE filename = 'M9_Overview_220127-1702'"
    ).fetchone()[0] == "M9_Overview_220127-1700"

    # An even-earlier row sharing p2.tdms (now carried by the 17:00 survivor)
    # becomes the new survivor; the 17:02 row's pointer must flatten onto it.
    # Ends at 16:59:50 (duration=50s) — 10s before the 17:00 survivor's t0.
    _insert_overview(
        con, "M9_Overview_220127-1659", "2022-01-27 16:59:00", 50.0, 5.0, 0.5,
        ["p2.tdms"], assembly_name="M9_ASSEMBLY_A",
    )
    merge_duplicate_pupitre_records(con, verbose=False)

    rows = con.execute(
        "SELECT filename, merged_into FROM overview_records ORDER BY filename"
    ).fetchall()
    assert rows == [
        ("M9_Overview_220127-1659", None),
        ("M9_Overview_220127-1700", "M9_Overview_220127-1659"),
        ("M9_Overview_220127-1702", "M9_Overview_220127-1659"),
    ]


def test_merge_duplicate_pupitre_records_idempotent_on_rerun(con):
    _insert_overview(
        con, "M9_Overview_220127-1700", "2022-01-27 17:00:00", 100.0, 10.0, 1.0,
        ["p1.tdms", "p2.tdms"], assembly_name="M9_ASSEMBLY_A",
    )
    _insert_overview(
        con, "M9_Overview_220127-1702", "2022-01-27 17:02:00", 200.0, 20.0, 2.0,
        ["p2.tdms", "p3.tdms"], assembly_name="M9_ASSEMBLY_A",
    )

    first = merge_duplicate_pupitre_records(con, verbose=False)
    assert first["merges"] == 1
    before = con.execute(
        "SELECT filename, duration, merged_into FROM overview_records ORDER BY filename"
    ).fetchall()

    second = merge_duplicate_pupitre_records(con, verbose=False)
    assert second["merges"] == 0
    after = con.execute(
        "SELECT filename, duration, merged_into FROM overview_records ORDER BY filename"
    ).fetchall()
    assert before == after


def test_view_overview_records_excludes_merged_rows(con, capsys):
    _insert_overview(
        con, "M9_Overview_220127-1700", "2022-01-27 17:00:00", 100.0, 10.0, 1.0,
        ["p1.tdms", "p2.tdms"], assembly_name="M9_ASSEMBLY_A",
    )
    _insert_overview(
        con, "M9_Overview_220127-1702", "2022-01-27 17:02:00", 200.0, 20.0, 2.0,
        ["p2.tdms", "p3.tdms"], assembly_name="M9_ASSEMBLY_A",
    )
    merge_duplicate_pupitre_records(con, verbose=False)

    view_overview_records(con)
    out = capsys.readouterr().out
    assert "M9_Overview_220127-1700" in out
    assert "M9_Overview_220127-1702" not in out


# ---------------------------------------------------------------------------
# infer_overview_record_fields()
# ---------------------------------------------------------------------------


def test_infer_overview_record_fields_resolves_assembly_and_t0(con):
    _insert_m9_assemblies(con)
    insert_overview_record_from_dict(con, {"filename": "M9_Overview_220127-1756"}, verbose=False)

    status = infer_overview_record_fields(con, "M9_Overview_220127-1756", FILE_TZ, verbose=False)

    assert status == "resolved"
    row = con.execute(
        "SELECT assembly_name, housing, t0, duration, teb, bp FROM overview_records "
        "WHERE filename = 'M9_Overview_220127-1756'"
    ).fetchone()
    assert row == ("M9_ASSEMBLY_B", "M9", datetime(2022, 1, 27, 17, 56), 0.0, 0.0, 0.0)


def test_infer_overview_record_fields_no_assembly_match_leaves_assembly_name_null(con):
    _insert_m9_assemblies(con)
    insert_overview_record_from_dict(con, {"filename": "M9_Overview_220114-0000"}, verbose=False)

    status = infer_overview_record_fields(con, "M9_Overview_220114-0000", FILE_TZ, verbose=False)

    assert status == "no_assembly_match"
    row = con.execute(
        "SELECT assembly_name FROM overview_records WHERE filename = 'M9_Overview_220114-0000'"
    ).fetchone()
    assert row == (None,)


def test_infer_overview_record_fields_bad_filename(con):
    insert_overview_record_from_dict(con, {"filename": "not_a_valid_filename"}, verbose=False)
    status = infer_overview_record_fields(con, "not_a_valid_filename", FILE_TZ, verbose=False)
    assert status == "bad_filename"


def test_infer_overview_record_fields_not_found(con):
    status = infer_overview_record_fields(con, "does_not_exist", FILE_TZ, verbose=False)
    assert status == "not_found"


def test_infer_overview_record_fields_resolves_source_basenames(con, monkeypatch, tmp_path):
    """sources_overview/sources_pupitre store basenames only; both must be
    re-expanded against PIGBROTHER_DATA_DIR/PUPITRE_DATA_DIR before loading."""
    overview_dir = tmp_path / "pigbrother" / "M9" / "Overview"
    overview_dir.mkdir(parents=True)
    (overview_dir / "M9_Overview_220127-1756.tdms").touch()
    pupitre_dir = tmp_path / "pupitre" / "M9"
    pupitre_dir.mkdir(parents=True)
    (pupitre_dir / "pupitre1.txt").touch()
    monkeypatch.setattr(
        "python_magnetrun.data_dirs.PIGBROTHER_DATA_DIR", str(tmp_path / "pigbrother")
    )
    monkeypatch.setattr(
        "python_magnetrun.data_dirs.PUPITRE_DATA_DIR", str(tmp_path / "pupitre")
    )

    _insert_m9_assemblies(con)
    insert_overview_record_from_dict(
        con,
        {
            "filename": "M9_Overview_220127-1756",
            "sources_overview": ["M9_Overview_220127-1756.tdms"],
            "sources_pupitre": ["pupitre1.txt"],
        },
        verbose=False,
    )

    seen_paths = []

    def _fake_load(path):
        seen_paths.append(path)
        raise RuntimeError("stub load — only path resolution is under test")

    monkeypatch.setattr("python_magnetrun.magnetdata.load_magnetdata", _fake_load)

    status = infer_overview_record_fields(con, "M9_Overview_220127-1756", FILE_TZ, verbose=False)

    assert status == "resolved"
    # The overview file is loaded twice: once here for duration, once more
    # by the _postprocess_overview_record() call this function makes on
    # success (mode inference) — both must resolve to the same real path.
    assert seen_paths == [
        str(overview_dir / "M9_Overview_220127-1756.tdms"),
        str(pupitre_dir / "pupitre1.txt"),
        str(overview_dir / "M9_Overview_220127-1756.tdms"),
    ]


# ---------------------------------------------------------------------------
# infer_operating_mode()
# ---------------------------------------------------------------------------


def test_infer_operating_mode_normal_when_ih_near_zero():
    df = {"Courant_GR1": [0.0, 1.0, 2.0, 0.5], "Courant_GR2": [100.0, 200.0, 300.0, 400.0]}
    assert infer_operating_mode(df) == "NORMAL"


def test_infer_operating_mode_normal_when_ib_near_zero():
    df = {"Courant_GR1": [100.0, 200.0, 300.0], "Courant_GR2": [0.0, 1.0, 2.0]}
    assert infer_operating_mode(df) == "NORMAL"


def test_infer_operating_mode_normal_from_slope_fit():
    ib = list(range(60, 1060, 10))
    df = {"Courant_GR1": ib, "Courant_GR2": ib}  # slope == 1.0
    assert infer_operating_mode(df) == "NORMAL"


def test_infer_operating_mode_eco_from_slope_fit():
    ib = list(range(60, 1060, 10))
    df = {"Courant_GR1": [2.0 * v for v in ib], "Courant_GR2": ib}  # slope == 2.0
    assert infer_operating_mode(df) == "ECO"


def test_infer_operating_mode_unknown_when_insufficient_points():
    df = {"Courant_GR1": [100.0], "Courant_GR2": [100.0]}
    assert infer_operating_mode(df) == "UNKNOWN"


def test_infer_operating_mode_unknown_when_all_nan():
    nan = float("nan")
    df = {"Courant_GR1": [nan, nan], "Courant_GR2": [nan, nan]}
    assert infer_operating_mode(df) == "UNKNOWN"


def test_infer_operating_mode_raises_when_both_columns_missing():
    with pytest.raises(ValueError):
        infer_operating_mode({})


def test_infer_operating_mode_normal_when_only_ih_present():
    df = {"Courant_GR1": [100.0, 200.0, 300.0]}
    assert infer_operating_mode(df) == "NORMAL"


def test_infer_operating_mode_normal_when_only_ib_present():
    df = {"Courant_GR2": [100.0, 200.0, 300.0]}
    assert infer_operating_mode(df) == "NORMAL"


# ---------------------------------------------------------------------------
# _postprocess_overview_record()
# ---------------------------------------------------------------------------


class _FakeTdmsData:
    """Stand-in for a loaded TdmsMagnetData: exposes just the .Data dict."""

    def __init__(self, df):
        self.Data = {"Courants_Alimentations": df}


def test_postprocess_overview_record_not_found(con):
    status = _postprocess_overview_record(con, "does_not_exist", verbose=False)
    assert status == "not_found"


def test_postprocess_overview_record_skipped_no_assembly(con):
    insert_overview_record_from_dict(con, {"filename": "M9_Overview_220127-1756"}, verbose=False)

    status = _postprocess_overview_record(con, "M9_Overview_220127-1756", verbose=False)

    assert status == "skipped_no_assembly"


def test_postprocess_overview_record_skipped_no_sources(con):
    _insert_m9_assemblies(con)
    insert_overview_record_from_dict(
        con,
        {"filename": "M9_Overview_220127-1756", "assembly_name": "M9_ASSEMBLY_B"},
        verbose=False,
    )

    status = _postprocess_overview_record(con, "M9_Overview_220127-1756", verbose=False)

    assert status == "skipped_no_sources"


def test_postprocess_overview_record_applied_sets_mode(con, monkeypatch):
    _insert_m9_assemblies(con)
    insert_overview_record_from_dict(
        con,
        {
            "filename": "M9_Overview_220127-1756",
            "assembly_name": "M9_ASSEMBLY_B",
            "sources_overview": ["M9_Overview_220127-1756.tdms"],
        },
        verbose=False,
    )

    ib = list(range(60, 1060, 10))
    fake_df = {"Courant_GR1": ib, "Courant_GR2": ib}  # slope == 1.0 -> NORMAL
    monkeypatch.setattr(
        "python_magnetrun.magnetdata.load_magnetdata",
        lambda path: _FakeTdmsData(fake_df),
    )

    status = _postprocess_overview_record(con, "M9_Overview_220127-1756", verbose=False)

    assert status == "applied"
    row = con.execute(
        "SELECT mode FROM overview_records WHERE filename = 'M9_Overview_220127-1756'"
    ).fetchone()
    assert row == ("NORMAL",)


def test_postprocess_overview_record_skipped_no_mode_data(con, monkeypatch):
    # Uses a filename distinct from the other tests' "M9_Overview_220127-1756":
    # that name matches a real .tdms file on some dev machines' mounted
    # PIGBROTHER_DATA_DIR, whose insert-time internal postprocess call would
    # load real data and set mode before this test's monkeypatch is installed.
    _insert_m9_assemblies(con)
    insert_overview_record_from_dict(
        con,
        {
            "filename": "M9_Overview_010101-0101",
            "assembly_name": "M9_ASSEMBLY_B",
            "sources_overview": ["M9_Overview_010101-0101.tdms"],
        },
        verbose=False,
    )

    fake_df = {}  # neither Courant_GR1 nor Courant_GR2 -> malformed source file
    monkeypatch.setattr(
        "python_magnetrun.magnetdata.load_magnetdata",
        lambda path: _FakeTdmsData(fake_df),
    )

    status = _postprocess_overview_record(con, "M9_Overview_010101-0101", verbose=False)

    assert status == "skipped_no_mode_data"
    row = con.execute(
        "SELECT mode FROM overview_records WHERE filename = 'M9_Overview_010101-0101'"
    ).fetchone()
    assert row == (None,)


def test_postprocess_overview_record_resolves_bare_basename(con, monkeypatch, tmp_path):
    """sources_overview stores a basename only; it must be re-expanded against
    PIGBROTHER_DATA_DIR/<housing>/Overview/ before being handed to load_magnetdata."""
    overview_dir = tmp_path / "M9" / "Overview"
    overview_dir.mkdir(parents=True)
    (overview_dir / "M9_Overview_220127-1756.tdms").touch()
    monkeypatch.setattr("python_magnetrun.data_dirs.PIGBROTHER_DATA_DIR", str(tmp_path))

    _insert_m9_assemblies(con)
    insert_overview_record_from_dict(
        con,
        {
            "filename": "M9_Overview_220127-1756",
            "assembly_name": "M9_ASSEMBLY_B",
            "sources_overview": ["M9_Overview_220127-1756.tdms"],
        },
        verbose=False,
    )

    ib = list(range(60, 1060, 10))
    fake_df = {"Courant_GR1": ib, "Courant_GR2": ib}  # slope == 1.0 -> NORMAL
    seen_paths = []

    def _fake_load(path):
        seen_paths.append(path)
        return _FakeTdmsData(fake_df)

    monkeypatch.setattr("python_magnetrun.magnetdata.load_magnetdata", _fake_load)

    status = _postprocess_overview_record(con, "M9_Overview_220127-1756", verbose=False)

    assert status == "applied"
    assert seen_paths == [str(overview_dir / "M9_Overview_220127-1756.tdms")]
