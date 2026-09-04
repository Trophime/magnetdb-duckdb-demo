"""Unit tests for checks.py — magnetdb.py's `check` command backend."""

import pytest

from checks import (
    _ENTITY_CHECKS,
    check_assemblies,
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
    assert any("geometry_data is not set" in p for p in helix["problems"])


def test_check_parts_name_filter(con_populated):
    results = check_parts(con_populated, name="HELIX_01")
    assert [r["name"] for r in results] == ["HELIX_01"]


def test_check_parts_ok_when_both_fields_set(con):
    from crud import insert_material
    insert_material(con, {"name": "MAT_X"}, verbose=False)
    con.execute(
        "INSERT INTO parts (name, type, material_name, geometry, geometry_data) "
        "VALUES ('P_OK', 'helix', 'MAT_X', '/some/path.yaml', '{}')"
    )
    results = check_parts(con, name="P_OK")
    assert results[0]["ok"]
    assert results[0]["problems"] == []


def test_check_parts_fix_loads_geometry_data_from_file(con_populated, monkeypatch):
    monkeypatch.setattr("checks.load_geometry_json", lambda path: '{"__classname__": "Helix"}')
    con_populated.execute("UPDATE parts SET geometry = '/fake/HELIX_01.yaml' WHERE name = 'HELIX_01'")
    results = check_parts(con_populated, name="HELIX_01", fix=True)
    helix = _result_for(results, "HELIX_01")
    assert helix["ok"]
    assert helix["problems"] == []
    stored = con_populated.execute(
        "SELECT geometry_data FROM parts WHERE name = 'HELIX_01'"
    ).fetchone()[0]
    assert stored is not None


def test_check_parts_fix_reports_unfixable_when_load_fails(con_populated, monkeypatch):
    monkeypatch.setattr("checks.load_geometry_json", lambda path: None)
    con_populated.execute("UPDATE parts SET geometry = '/fake/missing.yaml' WHERE name = 'HELIX_01'")
    results = check_parts(con_populated, name="HELIX_01", fix=True)
    helix = _result_for(results, "HELIX_01")
    assert not helix["ok"]
    assert any("could not be auto-fixed" in p for p in helix["problems"])


def test_check_parts_fix_no_geometry_path_is_unfixable(con_populated):
    """HELIX_01 has geometry=None in con_populated — there's no file to load
    from, so --fix must report it as an ordinary problem, not attempt a load."""
    results = check_parts(con_populated, name="HELIX_01", fix=True)
    helix = _result_for(results, "HELIX_01")
    assert not helix["ok"]
    assert any("cannot auto-fix" in p for p in helix["problems"])


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


def test_check_magnets_flags_invalid_status(con_populated):
    con_populated.execute("UPDATE magnets SET status = 'bogus' WHERE name = 'MAG_01'")
    results = check_magnets(con_populated)
    mag = _result_for(results, "MAG_01")
    assert not mag["ok"]
    assert any("not a valid LifecycleStatus" in p for p in mag["problems"])


def test_check_magnets_flags_dead_magnet_with_no_dead_parts(con_populated):
    """MAG_01 marked dead directly (bypassing update_magnet_status) with both
    parts still in_operation must fail the dead-part invariant audit."""
    con_populated.execute("UPDATE magnets SET status = 'dead' WHERE name = 'MAG_01'")
    results = check_magnets(con_populated)
    mag = _result_for(results, "MAG_01")
    assert not mag["ok"]
    assert any("dead-part invariant" in p for p in mag["problems"])


def test_check_magnets_dead_with_one_dead_part_satisfies_invariant(con_populated):
    con_populated.execute("UPDATE magnets SET status = 'dead' WHERE name = 'MAG_01'")
    con_populated.execute("UPDATE parts SET status = 'dead' WHERE name = 'HELIX_01'")
    results = check_magnets(con_populated)
    mag = _result_for(results, "MAG_01")
    assert not any("dead-part invariant" in p for p in mag["problems"])


# ---------------------------------------------------------------------------
# check_assemblies
# ---------------------------------------------------------------------------


def test_check_assemblies_ok_for_consistent_assembly(con_populated):
    results = check_assemblies(con_populated)
    a = _result_for(results, "ASSEMBLY_01")
    assert a["ok"]
    assert a["problems"] == []


def test_check_assemblies_flags_status_inconsistent_with_decommissioned_at(con_populated):
    """ASSEMBLY_01 is in_operation (decommissioned_at IS NULL); force-set it
    to 'disassembled' directly and expect the consistency check to flag it."""
    con_populated.execute("UPDATE assemblies SET status = 'disassembled' WHERE name = 'ASSEMBLY_01'")
    results = check_assemblies(con_populated)
    a = _result_for(results, "ASSEMBLY_01")
    assert not a["ok"]
    assert any("inconsistent with decommissioned_at" in p for p in a["problems"])


def test_check_assemblies_flags_invalid_status(con_populated):
    con_populated.execute("UPDATE assemblies SET status = 'bogus' WHERE name = 'ASSEMBLY_01'")
    results = check_assemblies(con_populated)
    a = _result_for(results, "ASSEMBLY_01")
    assert not a["ok"]
    assert any("not a valid AssemblyStatus" in p for p in a["problems"])


def test_check_assemblies_in_study_exempt_from_consistency_check(con_populated):
    con_populated.execute("UPDATE assemblies SET status = 'in_study' WHERE name = 'ASSEMBLY_01'")
    results = check_assemblies(con_populated)
    a = _result_for(results, "ASSEMBLY_01")
    assert a["ok"]


def test_check_assemblies_flags_residual_overlap(con_populated):
    """insert_assembly() prevents new overlaps, so simulate legacy data by
    inserting the overlapping row directly."""
    con_populated.execute(
        "INSERT INTO assemblies (name, status, housing, commissioned_at, decommissioned_at) "
        "VALUES ('ASSEMBLY_OVERLAP', 'in_operation', 'M10', '2025-01-15 00:00:00', NULL)"
    )
    results = check_assemblies(con_populated)
    a1 = _result_for(results, "ASSEMBLY_01")
    a2 = _result_for(results, "ASSEMBLY_OVERLAP")
    assert not a1["ok"]
    assert not a2["ok"]
    assert any("overlaps assembly" in p for p in a1["problems"])
    assert any("overlaps assembly" in p for p in a2["problems"])


def test_check_assemblies_name_filter(con_populated):
    results = check_assemblies(con_populated, name="ASSEMBLY_01")
    assert [r["name"] for r in results] == ["ASSEMBLY_01"]


# ---------------------------------------------------------------------------
# check_experiments / check_operationaldata
# ---------------------------------------------------------------------------


def test_check_experiments_missing_file_on_disk(con_populated, tmp_path):
    insert_experiments(con_populated, "ASSEMBLY_01", [{"name": "exp1", "file": "/no/such/file.txt"}],
                        verbose=False)
    results = check_experiments(con_populated)
    assert len(results) == 1
    assert not results[0]["ok"]
    assert "does not exist on disk" in results[0]["problems"][0]


def test_check_experiments_ok_when_file_exists(con_populated, tmp_path):
    real_file = tmp_path / "real.txt"
    real_file.write_text("data")
    insert_experiments(con_populated, "ASSEMBLY_01", [{"name": "exp1", "file": str(real_file)}],
                        verbose=False)
    results = check_experiments(con_populated)
    assert results[0]["ok"]


def test_check_operationaldata_missing_file_on_disk(con_populated):
    con_populated.execute(
        "INSERT INTO operationaldata (name, description, file, assembly_name) "
        "VALUES ('od1', '', '/no/such/file.txt', 'ASSEMBLY_01')"
    )
    results = check_operationaldata(con_populated)
    assert not results[0]["ok"]
    assert "does not exist on disk" in results[0]["problems"][0]


def test_check_operationaldata_ok_when_file_exists(con_populated, tmp_path):
    real_file = tmp_path / "real.txt"
    real_file.write_text("data")
    con_populated.execute(
        "INSERT INTO operationaldata (name, description, file, assembly_name) "
        "VALUES ('od1', '', ?, 'ASSEMBLY_01')",
        [str(real_file)],
    )
    results = check_operationaldata(con_populated)
    assert results[0]["ok"]


def test_check_experiments_resolves_relative_file_against_records_base(con_populated, tmp_path):
    """experiments.file is a bare filename; it must be resolved as
    records_base/srv_subdir/housing/file (ASSEMBLY_01's housing is 'M10')."""
    real_file = tmp_path / "srv-data-install" / "M10" / "2018.02.21 - 10:18:54.txt"
    real_file.parent.mkdir(parents=True)
    real_file.write_text("data")
    insert_experiments(
        con_populated, "ASSEMBLY_01",
        [{"name": "exp1", "file": "2018.02.21 - 10:18:54.txt"}],
        verbose=False,
    )
    results = check_experiments(con_populated, records_base=tmp_path)
    assert results[0]["ok"]


def test_check_experiments_relative_file_missing_reports_problem(con_populated, tmp_path):
    insert_experiments(
        con_populated, "ASSEMBLY_01",
        [{"name": "exp1", "file": "2018.02.21 - 10:18:54.txt"}],
        verbose=False,
    )
    results = check_experiments(con_populated, records_base=tmp_path)
    assert not results[0]["ok"]
    assert "does not exist on disk" in results[0]["problems"][0]


def test_check_operationaldata_resolves_relative_file_against_records_base(con_populated, tmp_path):
    """operationaldata.file is stored relative to records_base (e.g.
    'pbsurv/<housing>/Fichiers_Spike/<file>.tdms')."""
    relpath = "pbsurv/M10/Fichiers_Spike/M10_Spikes_260509-153823.tdms"
    real_file = tmp_path / relpath
    real_file.parent.mkdir(parents=True)
    real_file.write_text("data")
    con_populated.execute(
        "INSERT INTO operationaldata (name, description, file, assembly_name) "
        "VALUES ('od1', '', ?, 'ASSEMBLY_01')",
        [relpath],
    )
    results = check_operationaldata(con_populated, records_base=tmp_path)
    assert results[0]["ok"]


def test_check_operationaldata_relative_file_missing_reports_problem(con_populated, tmp_path):
    relpath = "pbsurv/M10/Fichiers_Spike/M10_Spikes_260509-153823.tdms"
    con_populated.execute(
        "INSERT INTO operationaldata (name, description, file, assembly_name) "
        "VALUES ('od1', '', ?, 'ASSEMBLY_01')",
        [relpath],
    )
    results = check_operationaldata(con_populated, records_base=tmp_path)
    assert not results[0]["ok"]
    assert "does not exist on disk" in results[0]["problems"][0]


# ---------------------------------------------------------------------------
# run_checks / print_check_report
# ---------------------------------------------------------------------------


def test_run_checks_all_combines_every_entity(con_populated):
    insert_experiments(con_populated, "ASSEMBLY_01", [{"name": "exp1", "file": "/no/such/file.txt"}],
                        verbose=False)
    con_populated.execute(
        "INSERT INTO operationaldata (name, description, file, assembly_name) "
        "VALUES ('od1', '', '/no/such/file.txt', 'ASSEMBLY_01')"
    )
    results = run_checks(con_populated, entity="all")
    entities = {r["entity"] for r in results}
    assert entities == {"part", "magnet", "assembly", "experiment", "operationaldata"}


def test_run_checks_name_with_all_entity_raises(con_populated):
    with pytest.raises(ValueError):
        run_checks(con_populated, entity="all", name="MAG_01")


def test_run_checks_unknown_entity_raises(con_populated):
    with pytest.raises(ValueError):
        run_checks(con_populated, entity="bogus")


def test_entity_checks_fixes_parts_before_magnets(con_populated):
    """entity='all' --fix must reconstruct parts' geometry_data before
    attempting magnet reconstruction, since magnets depend on it."""
    assert list(_ENTITY_CHECKS)[:2] == ["part", "magnet"]


def test_print_check_report_returns_false_on_problems(con_populated, capsys):
    results = check_parts(con_populated)
    ok = print_check_report(results)
    assert ok is False
    capsys.readouterr()


def test_print_check_report_returns_true_when_all_ok(capsys):
    ok = print_check_report([{"entity": "part", "name": "P1", "ok": True, "problems": []}])
    assert ok is True
    capsys.readouterr()
