"""Tests for impact.py."""

import pytest

from crud import (
    insert_assembly,
    insert_assembly_magnets,
    insert_experiments,
    insert_magnet,
    insert_magnet_part_row,
    insert_material,
    insert_part,
)
from impact import (
    affected_assemblies,
    decommission_report,
    find_hoop_stale_impact,
    format_hoop_stale_report,
    hoop_stress_inputs_changed,
    mark_hoop_stale,
)
from tests.conftest import MATERIAL_COPPER, MATERIAL_STEEL


def _add_hoop_rows(con, exp_id: int, part_name: str) -> None:
    con.execute(
        "INSERT INTO hoop_stress_processed (experiment_id, bin_config, magnet_type) VALUES (?, 'k', 'all')",
        [exp_id],
    )
    con.execute(
        "INSERT INTO hoop_stress_bin_stats VALUES (?, ?, 0, 100, 1, 1, 1, 1, 1, 1)", [exp_id, part_name]
    )
    con.execute("INSERT INTO hoop_stress_fatigue VALUES (?, ?, 1, 1)", [exp_id, part_name])


@pytest.fixture
def two_assemblies(con):
    """Assembly A (MAG_A: H_A copper) and B (MAG_B: H_B steel); A has one
    processed and one unprocessed experiment, B one processed experiment."""
    insert_material(con, MATERIAL_COPPER, verbose=False)
    insert_material(con, MATERIAL_STEEL, verbose=False)
    insert_part(con, {"name": "H_A", "type": "helix", "material_name": "MAT_COPPER"}, verbose=False)
    insert_part(con, {"name": "H_B", "type": "helix", "material_name": "MAT_STEEL"}, verbose=False)
    insert_magnet(con, {"name": "MAG_A"}, "insert", verbose=False)
    insert_magnet(con, {"name": "MAG_B"}, "insert", verbose=False)
    insert_magnet_part_row(con, "MAG_A", "H_A", 0, 1)
    insert_magnet_part_row(con, "MAG_B", "H_B", 0, 1)
    for assembly, magnet in (("A", "MAG_A"), ("B", "MAG_B")):
        insert_assembly(con, {"name": assembly, "status": "in_operation"}, verbose=False)
        insert_assembly_magnets(con, assembly, [{"name": magnet}], verbose=False)
    insert_experiments(
        con, "A",
        [{"name": "a1", "file": "M9_2025.01.01 - 10:00:00.txt"},
         {"name": "a2", "file": "M9_2025.03.01 - 10:00:00.txt"}],
        verbose=False,
    )
    insert_experiments(con, "B", [{"name": "b1", "file": "M9_2025.02.01 - 10:00:00.txt"}], verbose=False)
    ids = dict(con.execute("SELECT name, id FROM experiments").fetchall())
    _add_hoop_rows(con, ids["a1"], "H_A")
    _add_hoop_rows(con, ids["b1"], "H_B")
    return con, ids


def _stale_ids(con) -> set[int]:
    return {
        r[0] for r in con.execute(
            "SELECT experiment_id FROM hoop_stress_processed WHERE stale_since IS NOT NULL"
        ).fetchall()
    }


def test_hoop_stress_inputs_changed_filters_to_dependency_map():
    assert hoop_stress_inputs_changed("parts", ["cad", "material_name"]) == ["material_name"]
    assert hoop_stress_inputs_changed("assembly_magnets", ["r_offset", "parallax"]) == []
    assert hoop_stress_inputs_changed("materials", ["description"]) == []
    assert hoop_stress_inputs_changed("materials", ["rpe"]) == ["rpe"]
    assert hoop_stress_inputs_changed("assemblies", ["description"]) == []


@pytest.mark.parametrize("table,key", [
    ("materials", "MAT_COPPER"),
    ("parts", "H_A"),
    ("magnets", "MAG_A"),
    ("assembly_magnets", ("A", "MAG_A")),
])
def test_affected_assemblies_finds_a_not_b(two_assemblies, table, key):
    con, _ids = two_assemblies
    assert affected_assemblies(con, table, key) == ["A"]


def test_affected_assemblies_unknown_table_raises(two_assemblies):
    con, _ids = two_assemblies
    with pytest.raises(ValueError):
        affected_assemblies(con, "housing_config", "M9")


def test_find_hoop_stale_impact_lists_processed_experiments_and_row_counts(two_assemblies):
    con, ids = two_assemblies
    impact = find_hoop_stale_impact(con, "parts", "H_A", ["material_name", "cad"])
    assert impact["inputs"] == ["material_name"]
    assert impact["assemblies"] == ["A"]
    assert impact["experiment_ids"] == [ids["a1"]]  # a2 is not processed
    assert impact["rows"] == {
        "hoop_stress_bin_stats": 1, "hoop_stress_fatigue": 1, "hoop_stress_fatigue_bins": 0,
    }


def test_find_hoop_stale_impact_none_for_non_input_change(two_assemblies):
    con, _ids = two_assemblies
    assert find_hoop_stale_impact(con, "parts", "H_A", ["cad"]) is None


def test_mark_hoop_stale_marks_only_given_experiments_and_keeps_first_reason(two_assemblies):
    con, ids = two_assemblies
    assert mark_hoop_stale(con, [ids["a1"]], op_id=7) == 1
    assert _stale_ids(con) == {ids["a1"]}

    assert mark_hoop_stale(con, [ids["a1"]], op_id=8) == 0  # already stale
    reason = con.execute(
        "SELECT stale_reason FROM hoop_stress_processed WHERE experiment_id = ?", [ids["a1"]]
    ).fetchone()[0]
    assert reason == 7


def test_mark_hoop_stale_empty_list_is_noop(two_assemblies):
    con, _ids = two_assemblies
    assert mark_hoop_stale(con, [], op_id=1) == 0
    assert _stale_ids(con) == set()


def test_format_hoop_stale_report_mentions_scope_and_command(two_assemblies):
    con, _ids = two_assemblies
    report = format_hoop_stale_report(find_hoop_stale_impact(con, "materials", "MAT_COPPER", ["rpe"]))
    assert "now stale (rpe changed)" in report
    assert "1 assembly, 1 experiment(s)" in report
    assert "hoop-stress compute --assembly A" in report
    assert format_hoop_stale_report(None) == ""


def test_decommission_report_lists_records_after_end_only(two_assemblies):
    con, _ids = two_assemblies
    con.execute(
        "INSERT INTO overview_records (filename, assembly_name, t0) VALUES "
        "('late.txt', 'A', '2025-03-01 09:00:00'), ('early.txt', 'A', '2025-01-01 09:00:00')"
    )
    report = decommission_report(con, "A", "2025-02-01 00:00:00")
    assert report == {"experiments": ["a2"], "operationaldata": [], "overview_records": ["late.txt"]}
