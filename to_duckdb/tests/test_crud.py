"""Unit tests for crud.py — one function per concern."""

import json
from datetime import datetime

import pytest

from crud import (
    _find_site_for_timestamp,
    _parse_overview_filename,
    _postprocess_overview_record,
    delete_magnet,
    delete_site,
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
    insert_site,
    insert_site_magnets,
    merge_duplicate_pupitre_records,
    parse_timestamp,
    resolve_overview_site,
    update_site_magnet,
    view_magnet,
    view_magnets,
    view_overview_records,
    view_site,
    view_sites,
)
from populate import FILE_TZ
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
# _find_site_for_timestamp()
# ---------------------------------------------------------------------------


def _insert_m9_sites(con):
    """Two consecutive M9 operational windows, with a gap in between."""
    insert_site(con, {
        "name": "M9_SITE_A", "housing": "M9",
        "commissioned_at": "2022-01-01 00:00:00",
        "decommissioned_at": "2022-01-10 00:00:00",
    }, verbose=False)
    insert_site(con, {
        "name": "M9_SITE_B", "housing": "M9",
        "commissioned_at": "2022-01-18 00:00:00",
        "decommissioned_at": None,
    }, verbose=False)


def test_find_site_for_timestamp_matches_unique_site(con):
    _insert_m9_sites(con)
    t0 = datetime(2022, 1, 27, 17, 56, tzinfo=FILE_TZ)
    assert _find_site_for_timestamp(con, "M9", t0, FILE_TZ) == "M9_SITE_B"


def test_find_site_for_timestamp_matches_open_ended_window(con):
    _insert_m9_sites(con)
    t0 = datetime(2022, 1, 5, 12, 0, tzinfo=FILE_TZ)
    assert _find_site_for_timestamp(con, "M9", t0, FILE_TZ) == "M9_SITE_A"


def test_find_site_for_timestamp_no_match_in_gap(con):
    _insert_m9_sites(con)
    t0 = datetime(2022, 1, 14, 0, 0, tzinfo=FILE_TZ)
    assert _find_site_for_timestamp(con, "M9", t0, FILE_TZ) is None


def test_find_site_for_timestamp_ambiguous_match(con):
    _insert_m9_sites(con)
    insert_site(con, {
        "name": "M9_SITE_OVERLAP", "housing": "M9",
        "commissioned_at": "2022-01-20 00:00:00",
        "decommissioned_at": None,
    }, verbose=False)
    t0 = datetime(2022, 1, 27, 17, 56, tzinfo=FILE_TZ)
    assert _find_site_for_timestamp(con, "M9", t0, FILE_TZ) is None


def test_find_site_for_timestamp_no_housing_match(con):
    _insert_m9_sites(con)
    t0 = datetime(2022, 1, 27, 17, 56, tzinfo=FILE_TZ)
    assert _find_site_for_timestamp(con, "M10", t0, FILE_TZ) is None


# ---------------------------------------------------------------------------
# resolve_overview_site()
# ---------------------------------------------------------------------------


def test_resolve_overview_site_matches_unique_site(con):
    _insert_m9_sites(con)
    housing, t0, site_name = resolve_overview_site(con, "M9_Overview_220127-1756", FILE_TZ)
    assert housing == "M9"
    assert t0 == datetime(2022, 1, 27, 17, 56)
    assert site_name == "M9_SITE_B"


def test_resolve_overview_site_bad_filename_returns_housing_only(con):
    _insert_m9_sites(con)
    housing, t0, site_name = resolve_overview_site(con, "M9_Overview_notatimestamp", FILE_TZ)
    assert housing == "M9"
    assert t0 is None
    assert site_name is None


def test_resolve_overview_site_no_site_match_still_returns_housing_and_t0(con):
    _insert_m9_sites(con)
    housing, t0, site_name = resolve_overview_site(con, "M9_Overview_220114-0000", FILE_TZ)
    assert housing == "M9"
    assert t0 == datetime(2022, 1, 14, 0, 0)
    assert site_name is None


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


def _ensure_site(con, site_name, housing):
    """Insert a minimal housing_config + sites row, satisfying overview_records's FK."""
    if con.execute("SELECT 1 FROM housing_config WHERE name = ?", [housing]).fetchone() is None:
        con.execute(
            "INSERT INTO housing_config (name, coil_assignment, formats) VALUES (?, MAP{}, [])",
            [housing],
        )
    if con.execute("SELECT 1 FROM sites WHERE name = ?", [site_name]).fetchone() is None:
        con.execute(
            "INSERT INTO sites (name, housing, status, commissioned_at, decommissioned_at) "
            "VALUES (?, ?, 'active', '2022-01-01 00:00:00', NULL)",
            [site_name, housing],
        )


def _insert_overview(con, *args, **kwargs):
    data = _overview_dict(*args, **kwargs)
    if data.get("site_name"):
        _ensure_site(con, data["site_name"], data["housing"])
    insert_overview_record_from_dict(con, data, verbose=False)


def test_merge_duplicate_pupitre_records_merges_shared_pupitre_lower_t0_first(con):
    # 1700 ends at 17:01:40 (duration=100s); 1702 starts 20s later — within
    # the default 60s adjacency threshold.
    _insert_overview(
        con, "M9_Overview_220127-1700", "2022-01-27 17:00:00", 100.0, 10.0, 1.0,
        ["p1.tdms", "p2.tdms"], site_name="M9_SITE_A",
        signatures={"sigA": {"min": 0, "max": 1}},
    )
    _insert_overview(
        con, "M9_Overview_220127-1702", "2022-01-27 17:02:00", 200.0, 20.0, 2.0,
        ["p2.tdms", "p3.tdms"], site_name="M9_SITE_A",
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
        ["p2.tdms", "p3.tdms"], site_name="M9_SITE_A",
    )
    _insert_overview(
        con, "M9_Overview_220127-1700", "2022-01-27 17:00:00", 100.0, 10.0, 1.0,
        ["p1.tdms", "p2.tdms"], site_name="M9_SITE_A",
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
        ["p1.tdms", "p2.tdms"], site_name="M9_SITE_A",
    )
    _insert_overview(
        con, "M9_Overview_220127-1800", "2022-01-27 18:00:00", 200.0, 20.0, 2.0,
        ["p2.tdms", "p3.tdms"], site_name="M9_SITE_A",
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
        ["shared.tdms"], housing="M9", site_name="M9_SITE_A",
    )
    _insert_overview(
        con, "M10_Overview_220127-1800", "2022-01-27 18:00:00", 200.0, 20.0, 2.0,
        ["shared.tdms"], housing="M10", site_name="M10_SITE_A",
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


def test_merge_duplicate_pupitre_records_no_merge_when_site_name_differs(con):
    _insert_overview(
        con, "M9_Overview_220127-1700", "2022-01-27 17:00:00", 100.0, 10.0, 1.0,
        ["shared.tdms"], site_name="M9_SITE_A",
    )
    _insert_overview(
        con, "M9_Overview_220127-1800", "2022-01-27 18:00:00", 200.0, 20.0, 2.0,
        ["shared.tdms"], site_name="M9_SITE_B",
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
        ["p1.tdms"], site_name="M9_SITE_A",
    )
    _insert_overview(
        con, "M9_Overview_220127-1800", "2022-01-27 18:00:00", 200.0, 20.0, 2.0,
        ["p2.tdms"], site_name="M9_SITE_A",
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
        ["p1.tdms", "p2.tdms"], site_name="M9_SITE_A",
    )
    _insert_overview(
        con, "M9_Overview_220127-1702", "2022-01-27 17:02:00", 100.0, 10.0, 1.0,
        ["p2.tdms", "p3.tdms"], site_name="M9_SITE_A",
    )
    _insert_overview(
        con, "M9_Overview_220127-1704", "2022-01-27 17:04:00", 100.0, 10.0, 1.0,
        ["p3.tdms", "p4.tdms"], site_name="M9_SITE_A",
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
        ["p1.tdms", "p2.tdms"], site_name="M9_SITE_A",
    )
    _insert_overview(
        con, "M9_Overview_220127-1702", "2022-01-27 17:02:05", 100.0, 10.0, 1.0,
        ["p2.tdms", "p3.tdms"], site_name="M9_SITE_A",
    )
    _insert_overview(
        con, "M9_Overview_220127-1704", "2022-01-27 17:04:10", 100.0, 10.0, 1.0,
        ["p3.tdms", "p4.tdms"], site_name="M9_SITE_A",
    )
    _insert_overview(
        con, "M9_Overview_220127-1706", "2022-01-27 17:06:15", 100.0, 10.0, 1.0,
        ["p4.tdms", "p5.tdms"], site_name="M9_SITE_A",
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
        ["p1.tdms", "p2.tdms"], site_name="M9_SITE_A",
    )
    _insert_overview(
        con, "M9_Overview_220127-1702", "2022-01-27 17:02:00", 100.0, 10.0, 1.0,
        ["p2.tdms"], site_name="M9_SITE_A",
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
        ["p2.tdms"], site_name="M9_SITE_A",
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
        ["p1.tdms", "p2.tdms"], site_name="M9_SITE_A",
    )
    _insert_overview(
        con, "M9_Overview_220127-1702", "2022-01-27 17:02:00", 200.0, 20.0, 2.0,
        ["p2.tdms", "p3.tdms"], site_name="M9_SITE_A",
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
        ["p1.tdms", "p2.tdms"], site_name="M9_SITE_A",
    )
    _insert_overview(
        con, "M9_Overview_220127-1702", "2022-01-27 17:02:00", 200.0, 20.0, 2.0,
        ["p2.tdms", "p3.tdms"], site_name="M9_SITE_A",
    )
    merge_duplicate_pupitre_records(con, verbose=False)

    view_overview_records(con)
    out = capsys.readouterr().out
    assert "M9_Overview_220127-1700" in out
    assert "M9_Overview_220127-1702" not in out


# ---------------------------------------------------------------------------
# infer_overview_record_fields()
# ---------------------------------------------------------------------------


def test_infer_overview_record_fields_resolves_site_and_t0(con):
    _insert_m9_sites(con)
    insert_overview_record_from_dict(con, {"filename": "M9_Overview_220127-1756"}, verbose=False)

    status = infer_overview_record_fields(con, "M9_Overview_220127-1756", FILE_TZ, verbose=False)

    assert status == "resolved"
    row = con.execute(
        "SELECT site_name, housing, t0, duration, teb, bp FROM overview_records "
        "WHERE filename = 'M9_Overview_220127-1756'"
    ).fetchone()
    assert row == ("M9_SITE_B", "M9", datetime(2022, 1, 27, 17, 56), 0.0, 0.0, 0.0)


def test_infer_overview_record_fields_no_site_match_leaves_site_name_null(con):
    _insert_m9_sites(con)
    insert_overview_record_from_dict(con, {"filename": "M9_Overview_220114-0000"}, verbose=False)

    status = infer_overview_record_fields(con, "M9_Overview_220114-0000", FILE_TZ, verbose=False)

    assert status == "no_site_match"
    row = con.execute(
        "SELECT site_name FROM overview_records WHERE filename = 'M9_Overview_220114-0000'"
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

    _insert_m9_sites(con)
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


def test_postprocess_overview_record_skipped_no_site(con):
    insert_overview_record_from_dict(con, {"filename": "M9_Overview_220127-1756"}, verbose=False)

    status = _postprocess_overview_record(con, "M9_Overview_220127-1756", verbose=False)

    assert status == "skipped_no_site"


def test_postprocess_overview_record_skipped_no_sources(con):
    _insert_m9_sites(con)
    insert_overview_record_from_dict(
        con,
        {"filename": "M9_Overview_220127-1756", "site_name": "M9_SITE_B"},
        verbose=False,
    )

    status = _postprocess_overview_record(con, "M9_Overview_220127-1756", verbose=False)

    assert status == "skipped_no_sources"


def test_postprocess_overview_record_applied_sets_mode(con, monkeypatch):
    _insert_m9_sites(con)
    insert_overview_record_from_dict(
        con,
        {
            "filename": "M9_Overview_220127-1756",
            "site_name": "M9_SITE_B",
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
    _insert_m9_sites(con)
    insert_overview_record_from_dict(
        con,
        {
            "filename": "M9_Overview_010101-0101",
            "site_name": "M9_SITE_B",
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

    _insert_m9_sites(con)
    insert_overview_record_from_dict(
        con,
        {
            "filename": "M9_Overview_220127-1756",
            "site_name": "M9_SITE_B",
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
