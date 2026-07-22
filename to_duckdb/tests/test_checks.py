"""Unit tests for checks.py — magnetdb.py's `check` command backend."""

import pytest

from checks import (
    check_experiments,
    check_magnets,
    check_operationaldata,
    check_parts,
    print_check_report,
    run_checks,
)
from crud import insert_experiments


def _result_for(results, name):
    for r in results:
        if r["name"] == name:
            return r
    raise AssertionError(f"no result for {name!r} in {results}")


# ---------------------------------------------------------------------------
# check_parts
# ---------------------------------------------------------------------------


def test_check_parts_reports_missing_geometry_and_geometry_data(con_populated):
    results = check_parts(con_populated)
    helix = _result_for(results, "HELIX_01")
    assert not helix["ok"]
    assert "geometry is not set" in helix["problems"]
    assert "geometry_data is not set" in helix["problems"]


def test_check_parts_name_filter(con_populated):
    results = check_parts(con_populated, name="HELIX_01")
    assert [r["name"] for r in results] == ["HELIX_01"]


def test_check_parts_ok_when_both_fields_set(con):
    from crud import insert_material, insert_part
    insert_material(con, {"name": "MAT_X"}, verbose=False)
    con.execute(
        "INSERT INTO parts (name, type, material_name, geometry, geometry_data) "
        "VALUES ('P_OK', 'helix', 'MAT_X', '/some/path.yaml', '{}')"
    )
    results = check_parts(con, name="P_OK")
    assert results[0]["ok"]
    assert results[0]["problems"] == []


# ---------------------------------------------------------------------------
# check_magnets
# ---------------------------------------------------------------------------


def test_check_magnets_reports_missing_geometry_data(con_populated):
    results = check_magnets(con_populated)
    mag = _result_for(results, "MAG_01")
    assert not mag["ok"]
    assert "geometry_data is not set" in mag["problems"]


def test_check_magnets_fix_reports_unfixable_when_parts_lack_geometry_data(con_populated):
    """MAG_01's parts have geometry_data=None, so reconstruction can't succeed —
    this must be reported as a problem, not raise."""
    results = check_magnets(con_populated, fix=True)
    mag = _result_for(results, "MAG_01")
    assert not mag["ok"]
    assert any("could not be auto-fixed" in p for p in mag["problems"])


def test_check_magnets_flags_invalid_type_without_raising(con_populated):
    con_populated.execute("UPDATE magnets SET type = 'hybrid' WHERE name = 'MAG_01'")
    results = check_magnets(con_populated)  # fix=False
    mag = _result_for(results, "MAG_01")
    assert not mag["ok"]
    assert any("not a valid MagnetType" in p for p in mag["problems"])


def test_check_magnets_fix_raises_for_invalid_type_missing_geometry_data(con_populated):
    con_populated.execute("UPDATE magnets SET type = 'hybrid' WHERE name = 'MAG_01'")
    with pytest.raises(ValueError):
        check_magnets(con_populated, fix=True)


def test_check_magnets_invalid_type_with_geometry_data_does_not_raise_on_fix(con_populated):
    """If geometry_data is already present, --fix has nothing to do for this
    magnet even if its type is bogus — only report the type problem."""
    con_populated.execute(
        "UPDATE magnets SET type = 'hybrid', geometry_data = '{}' WHERE name = 'MAG_01'"
    )
    results = check_magnets(con_populated, fix=True)
    mag = _result_for(results, "MAG_01")
    assert not mag["ok"]
    assert any("not a valid MagnetType" in p for p in mag["problems"])


def test_check_magnets_flags_part_type_not_valid_for_magnet_type(con_populated):
    """RING_01 is fine for an insert magnet; retype it to something invalid
    for INSERT (e.g. 'bitter') and expect a part/type-consistency problem."""
    con_populated.execute("UPDATE parts SET type = 'bitter' WHERE name = 'RING_01'")
    results = check_magnets(con_populated)
    mag = _result_for(results, "MAG_01")
    assert not mag["ok"]
    assert any("RING_01" in p and "not valid for a insert magnet" in p for p in mag["problems"])


# ---------------------------------------------------------------------------
# check_experiments / check_operationaldata
# ---------------------------------------------------------------------------


def test_check_experiments_missing_file_on_disk(con_populated, tmp_path):
    insert_experiments(con_populated, "SITE_01", [{"name": "exp1", "file": "/no/such/file.txt"}],
                        verbose=False)
    results = check_experiments(con_populated)
    assert len(results) == 1
    assert not results[0]["ok"]
    assert "does not exist on disk" in results[0]["problems"][0]


def test_check_experiments_ok_when_file_exists(con_populated, tmp_path):
    real_file = tmp_path / "real.txt"
    real_file.write_text("data")
    insert_experiments(con_populated, "SITE_01", [{"name": "exp1", "file": str(real_file)}],
                        verbose=False)
    results = check_experiments(con_populated)
    assert results[0]["ok"]


def test_check_operationaldata_missing_file_on_disk(con_populated):
    con_populated.execute(
        "INSERT INTO operationaldata (name, description, file, site_name) "
        "VALUES ('od1', '', '/no/such/file.txt', 'SITE_01')"
    )
    results = check_operationaldata(con_populated)
    assert not results[0]["ok"]
    assert "does not exist on disk" in results[0]["problems"][0]


def test_check_operationaldata_ok_when_file_exists(con_populated, tmp_path):
    real_file = tmp_path / "real.txt"
    real_file.write_text("data")
    con_populated.execute(
        "INSERT INTO operationaldata (name, description, file, site_name) "
        "VALUES ('od1', '', ?, 'SITE_01')",
        [str(real_file)],
    )
    results = check_operationaldata(con_populated)
    assert results[0]["ok"]


# ---------------------------------------------------------------------------
# run_checks / print_check_report
# ---------------------------------------------------------------------------


def test_run_checks_all_combines_every_entity(con_populated):
    insert_experiments(con_populated, "SITE_01", [{"name": "exp1", "file": "/no/such/file.txt"}],
                        verbose=False)
    con_populated.execute(
        "INSERT INTO operationaldata (name, description, file, site_name) "
        "VALUES ('od1', '', '/no/such/file.txt', 'SITE_01')"
    )
    results = run_checks(con_populated, entity="all")
    entities = {r["entity"] for r in results}
    assert entities == {"part", "magnet", "experiment", "operationaldata"}


def test_run_checks_name_with_all_entity_raises(con_populated):
    with pytest.raises(ValueError):
        run_checks(con_populated, entity="all", name="MAG_01")


def test_run_checks_unknown_entity_raises(con_populated):
    with pytest.raises(ValueError):
        run_checks(con_populated, entity="bogus")


def test_print_check_report_returns_false_on_problems(con_populated, capsys):
    results = check_parts(con_populated)
    ok = print_check_report(results)
    assert ok is False
    capsys.readouterr()


def test_print_check_report_returns_true_when_all_ok(capsys):
    ok = print_check_report([{"entity": "part", "name": "P1", "ok": True, "problems": []}])
    assert ok is True
    capsys.readouterr()
