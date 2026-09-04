"""Integration tests for magnetdb.py — the unified CLI entry point."""

import json
from datetime import datetime

import duckdb
import pytest

from magnetdb import main
from magnetdb import _add_magnet as add_magnet, _add_assembly as add_assembly
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
    db = tmp_path / "test.duckdb"
    add_magnet(MAGNET_JSON, db)
    return db


def _db_with_assembly(tmp_path):
    db = _db_with_magnet(tmp_path)
    add_assembly(ASSEMBLY_JSON, db)
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


def test_cli_magnet_add_rejects_non_in_stock_part(tmp_path, monkeypatch, capsys):
    bad_json = {**MAGNET_JSON, "parts": [
        {**MAGNET_JSON["parts"][0], "status": "in_operation"},
        MAGNET_JSON["parts"][1],
    ]}
    json_path = tmp_path / "MAG_JSON.json"
    json_path.write_text(json.dumps(bad_json))
    db_path = tmp_path / "test.duckdb"

    with pytest.raises(SystemExit):
        _run(monkeypatch, "magnet", "add", str(json_path), "--db", str(db_path))

    assert "not 'in_stock'" in capsys.readouterr().out
    assert not db_path.exists()


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
# magnet update
# ---------------------------------------------------------------------------


def test_cli_magnet_update_writes_descriptive_fields(tmp_path, monkeypatch):
    db = _db_with_magnet(tmp_path)
    json_path = tmp_path / "MAG_JSON_update.json"
    json_path.write_text(json.dumps({"name": "MAG_JSON", "design_office_reference": "NEW-REF"}))

    _run(monkeypatch, "magnet", "update", str(json_path), "--db", str(db))

    row = _fetch_one(db, "SELECT design_office_reference FROM magnets WHERE name = 'MAG_JSON'")
    assert row[0] == "NEW-REF"


def test_cli_magnet_update_dry_run_writes_nothing(tmp_path, monkeypatch):
    db = _db_with_magnet(tmp_path)
    json_path = tmp_path / "MAG_JSON_update.json"
    json_path.write_text(json.dumps({"name": "MAG_JSON", "design_office_reference": "NEW-REF"}))

    _run(monkeypatch, "magnet", "update", str(json_path), "--db", str(db), "--dry-run")

    row = _fetch_one(db, "SELECT design_office_reference FROM magnets WHERE name = 'MAG_JSON'")
    assert row[0] is None


def test_cli_magnet_update_missing_magnet_exits(tmp_path, monkeypatch):
    db = _db_with_magnet(tmp_path)
    json_path = tmp_path / "nope_update.json"
    json_path.write_text(json.dumps({"name": "NOPE", "design_office_reference": "X"}))

    with pytest.raises(SystemExit):
        _run(monkeypatch, "magnet", "update", str(json_path), "--db", str(db))


def test_cli_magnet_update_missing_json_exits(tmp_path, monkeypatch):
    db = _db_with_magnet(tmp_path)
    with pytest.raises(SystemExit):
        _run(monkeypatch, "magnet", "update", str(tmp_path / "NOPE.json"), "--db", str(db))


# ---------------------------------------------------------------------------
# assembly add
# ---------------------------------------------------------------------------


def test_cli_assembly_add_creates_assembly(tmp_path, monkeypatch):
    db = _db_with_magnet(tmp_path)
    json_path = tmp_path / "ASSEMBLY_JSON_01.json"
    json_path.write_text(json.dumps(ASSEMBLY_JSON))

    _run(monkeypatch, "assembly", "add", str(json_path), "--db", str(db))

    assert _count(db, "assemblies") == 1
    assert _count(db, "assembly_magnets") == 1
    assert _count(db, "experiments") == len(ASSEMBLY_JSON["records"])


def test_cli_assembly_add_dry_run_writes_nothing(tmp_path, monkeypatch):
    db = _db_with_magnet(tmp_path)
    json_path = tmp_path / "ASSEMBLY_JSON_01.json"
    json_path.write_text(json.dumps(ASSEMBLY_JSON))

    _run(monkeypatch, "assembly", "add", str(json_path), "--db", str(db), "--dry-run")

    assert _count(db, "assemblies") == 0


def test_cli_assembly_add_missing_json_exits(tmp_path, monkeypatch):
    db = _db_with_magnet(tmp_path)
    with pytest.raises(SystemExit):
        _run(monkeypatch, "assembly", "add", str(tmp_path / "NOPE.json"), "--db", str(db))


# ---------------------------------------------------------------------------
# assembly view
# ---------------------------------------------------------------------------


def test_cli_assembly_view_list_all(tmp_path, monkeypatch, capsys):
    db = _db_with_assembly(tmp_path)
    _run(monkeypatch, "assembly", "view", "--db", str(db))
    assert "ASSEMBLY_JSON_01" in capsys.readouterr().out


def test_cli_assembly_view_one(tmp_path, monkeypatch, capsys):
    db = _db_with_assembly(tmp_path)
    _run(monkeypatch, "assembly", "view", "ASSEMBLY_JSON_01", "--db", str(db))
    out = capsys.readouterr().out
    assert "ASSEMBLY_JSON_01" in out
    assert "M10" in out


def test_cli_assembly_view_missing_db_exits(tmp_path, monkeypatch):
    with pytest.raises(SystemExit):
        _run(monkeypatch, "assembly", "view", "--db", str(tmp_path / "nope.duckdb"))


# ---------------------------------------------------------------------------
# assembly delete
# ---------------------------------------------------------------------------


def test_cli_assembly_delete_removes_assembly_and_related(tmp_path, monkeypatch):
    db = _db_with_assembly(tmp_path)
    _run(monkeypatch, "assembly", "delete", "ASSEMBLY_JSON_01", "--db", str(db))
    assert _count(db, "assemblies") == 0
    assert _count(db, "assembly_magnets") == 0
    assert _count(db, "experiments") == 0


def test_cli_assembly_delete_missing_db_exits(tmp_path, monkeypatch):
    with pytest.raises(SystemExit):
        _run(monkeypatch, "assembly", "delete", "ASSEMBLY_JSON_01",
             "--db", str(tmp_path / "nope.duckdb"))


# ---------------------------------------------------------------------------
# assembly update
# ---------------------------------------------------------------------------


def test_cli_assembly_update_writes_description(tmp_path, monkeypatch):
    db = _db_with_assembly(tmp_path)
    json_path = tmp_path / "ASSEMBLY_JSON_01_update.json"
    json_path.write_text(json.dumps({"name": "ASSEMBLY_JSON_01", "description": "new note"}))

    _run(monkeypatch, "assembly", "update", str(json_path), "--db", str(db))

    row = _fetch_one(db, "SELECT description FROM assemblies WHERE name = 'ASSEMBLY_JSON_01'")
    assert row[0] == "new note"


def test_cli_assembly_update_dry_run_writes_nothing(tmp_path, monkeypatch):
    db = _db_with_assembly(tmp_path)
    json_path = tmp_path / "ASSEMBLY_JSON_01_update.json"
    json_path.write_text(json.dumps({"name": "ASSEMBLY_JSON_01", "description": "new note"}))

    _run(monkeypatch, "assembly", "update", str(json_path), "--db", str(db), "--dry-run")

    row = _fetch_one(db, "SELECT description FROM assemblies WHERE name = 'ASSEMBLY_JSON_01'")
    assert row[0] is None


def test_cli_assembly_update_missing_assembly_exits(tmp_path, monkeypatch):
    db = _db_with_assembly(tmp_path)
    json_path = tmp_path / "nope_update.json"
    json_path.write_text(json.dumps({"name": "NOPE", "description": "x"}))

    with pytest.raises(SystemExit):
        _run(monkeypatch, "assembly", "update", str(json_path), "--db", str(db))


# ---------------------------------------------------------------------------
# assembly update-magnet
# ---------------------------------------------------------------------------


def test_cli_assembly_update_magnet_changes_offset(tmp_path, monkeypatch):
    db = _db_with_assembly(tmp_path)

    _run(monkeypatch, "assembly", "update-magnet",
         "ASSEMBLY_JSON_01", "MAG_JSON",
         "--db", str(db),
         "--z-offset", "9.5")

    row = _fetch_one(db, "SELECT z_offset FROM assembly_magnets WHERE magnet_name = 'MAG_JSON'")
    assert row[0] == 9.5


def test_cli_assembly_update_magnet_invalid_metadata_exits(tmp_path, monkeypatch):
    db = _db_with_assembly(tmp_path)
    with pytest.raises(SystemExit):
        _run(monkeypatch, "assembly", "update-magnet",
             "ASSEMBLY_JSON_01", "MAG_JSON",
             "--db", str(db),
             "--metadata", "NOT_JSON")


def test_cli_assembly_update_magnet_missing_row_exits(tmp_path, monkeypatch):
    db = _db_with_magnet(tmp_path)  # assembly not added → no assembly_magnets row
    with pytest.raises(SystemExit):
        _run(monkeypatch, "assembly", "update-magnet",
             "NONEXISTENT_ASSEMBLY", "MAG_JSON",
             "--db", str(db),
             "--z-offset", "1.0")


def test_cli_assembly_update_magnet_missing_db_exits(tmp_path, monkeypatch):
    with pytest.raises(SystemExit):
        _run(monkeypatch, "assembly", "update-magnet",
             "ASSEMBLY_JSON_01", "MAG_JSON",
             "--db", str(tmp_path / "nope.duckdb"),
             "--z-offset", "1.0")


# ---------------------------------------------------------------------------
# assembly decommission
# ---------------------------------------------------------------------------


def test_cli_assembly_decommission_disassembles_and_cascades_magnet(tmp_path, monkeypatch):
    db = _db_with_assembly(tmp_path)  # ASSEMBLY_JSON_01 → MAG_JSON, commissioning cascades MAG_JSON in_operation

    _run(monkeypatch, "assembly", "decommission", "ASSEMBLY_JSON_01", "--db", str(db),
         "--decommissioned-at", "2025-06-01 00:00:00", "--description", "end of campaign")

    row = _fetch_one(db, "SELECT status, decommissioned_at FROM assemblies WHERE name = 'ASSEMBLY_JSON_01'")
    assert row[0] == "disassembled"
    assert row[1] is not None
    magnet_status = _fetch_one(db, "SELECT status FROM magnets WHERE name = 'MAG_JSON'")
    assert magnet_status[0] == "in_stock"


def test_cli_assembly_decommission_unknown_name_exits(tmp_path, monkeypatch):
    db = _db_with_assembly(tmp_path)
    with pytest.raises(SystemExit):
        _run(monkeypatch, "assembly", "decommission", "NOPE", "--db", str(db))


def test_cli_assembly_decommission_missing_db_exits(tmp_path, monkeypatch):
    with pytest.raises(SystemExit):
        _run(monkeypatch, "assembly", "decommission", "ASSEMBLY_JSON_01",
             "--db", str(tmp_path / "nope.duckdb"))


# ---------------------------------------------------------------------------
# part view / update-status
# ---------------------------------------------------------------------------


def test_cli_part_view_list_all(tmp_path, monkeypatch, capsys):
    db = _db_with_magnet(tmp_path)
    _run(monkeypatch, "part", "view", "--db", str(db))
    assert "H_JSON_01" in capsys.readouterr().out


def test_cli_part_view_one(tmp_path, monkeypatch, capsys):
    db = _db_with_magnet(tmp_path)
    _run(monkeypatch, "part", "view", "H_JSON_01", "--db", str(db))
    out = capsys.readouterr().out
    assert "H_JSON_01" in out
    assert "in_stock" in out


def test_cli_part_update_status_changes_status(tmp_path, monkeypatch):
    db = _db_with_magnet(tmp_path)
    _run(monkeypatch, "part", "update-status", "H_JSON_01", "--status", "retired",
         "--db", str(db), "--description", "worn out")
    row = _fetch_one(db, "SELECT status FROM parts WHERE name = 'H_JSON_01'")
    assert row[0] == "retired"


def test_cli_part_update_status_invalid_status_exits(tmp_path, monkeypatch):
    db = _db_with_magnet(tmp_path)
    with pytest.raises(SystemExit):
        _run(monkeypatch, "part", "update-status", "H_JSON_01", "--status", "bogus", "--db", str(db))


def test_cli_part_update_status_missing_db_exits(tmp_path, monkeypatch):
    with pytest.raises(SystemExit):
        _run(monkeypatch, "part", "update-status", "H_JSON_01", "--status", "retired",
             "--db", str(tmp_path / "nope.duckdb"))


# ---------------------------------------------------------------------------
# part update
# ---------------------------------------------------------------------------


def test_cli_part_update_writes_descriptive_fields(tmp_path, monkeypatch):
    db = _db_with_magnet(tmp_path)
    json_path = tmp_path / "H_JSON_01_update.json"
    json_path.write_text(json.dumps({"name": "H_JSON_01", "design_office_reference": "HL-NEW"}))

    _run(monkeypatch, "part", "update", str(json_path), "--db", str(db))

    row = _fetch_one(db, "SELECT design_office_reference FROM parts WHERE name = 'H_JSON_01'")
    assert row[0] == "HL-NEW"


def test_cli_part_update_dry_run_writes_nothing(tmp_path, monkeypatch):
    db = _db_with_magnet(tmp_path)
    json_path = tmp_path / "H_JSON_01_update.json"
    json_path.write_text(json.dumps({"name": "H_JSON_01", "design_office_reference": "HL-NEW"}))

    _run(monkeypatch, "part", "update", str(json_path), "--db", str(db), "--dry-run")

    row = _fetch_one(db, "SELECT design_office_reference FROM parts WHERE name = 'H_JSON_01'")
    assert row[0] is None


def test_cli_part_update_unknown_material_exits(tmp_path, monkeypatch):
    db = _db_with_magnet(tmp_path)
    json_path = tmp_path / "H_JSON_01_update.json"
    json_path.write_text(json.dumps({"name": "H_JSON_01", "material_name": "NOPE"}))

    with pytest.raises(SystemExit):
        _run(monkeypatch, "part", "update", str(json_path), "--db", str(db))


def test_cli_part_update_missing_part_exits(tmp_path, monkeypatch):
    db = _db_with_magnet(tmp_path)
    json_path = tmp_path / "nope_update.json"
    json_path.write_text(json.dumps({"name": "NOPE", "design_office_reference": "X"}))

    with pytest.raises(SystemExit):
        _run(monkeypatch, "part", "update", str(json_path), "--db", str(db))


# ---------------------------------------------------------------------------
# magnet update-status
# ---------------------------------------------------------------------------


def test_cli_magnet_update_status_changes_status(tmp_path, monkeypatch):
    db = _db_with_magnet(tmp_path)
    _run(monkeypatch, "magnet", "update-status", "MAG_JSON", "--status", "in_stock", "--db", str(db))
    row = _fetch_one(db, "SELECT status FROM magnets WHERE name = 'MAG_JSON'")
    assert row[0] == "in_stock"


def test_cli_magnet_update_status_dead_requires_dead_part(tmp_path, monkeypatch):
    db = _db_with_magnet(tmp_path)
    with pytest.raises(SystemExit):
        _run(monkeypatch, "magnet", "update-status", "MAG_JSON", "--status", "dead", "--db", str(db))


def test_cli_magnet_update_status_dead_with_dead_part(tmp_path, monkeypatch, capsys):
    db = _db_with_magnet(tmp_path)
    _run(monkeypatch, "magnet", "update-status", "MAG_JSON", "--status", "dead",
         "--dead-part", "H_JSON_01", "--db", str(db))
    row = _fetch_one(db, "SELECT status FROM magnets WHERE name = 'MAG_JSON'")
    assert row[0] == "dead"
    part_row = _fetch_one(db, "SELECT status FROM parts WHERE name = 'H_JSON_01'")
    assert part_row[0] == "dead"
    assert "WARNING" in capsys.readouterr().out


def test_cli_magnet_update_status_dead_all_marks_every_part(tmp_path, monkeypatch):
    db = _db_with_magnet(tmp_path)
    _run(monkeypatch, "magnet", "update-status", "MAG_JSON", "--status", "dead",
         "--dead-part", "ALL", "--db", str(db))
    row = _fetch_one(db, "SELECT status FROM magnets WHERE name = 'MAG_JSON'")
    assert row[0] == "dead"
    for part_name in ("H_JSON_01", "R_JSON_01"):
        part_row = _fetch_one(db, "SELECT status FROM parts WHERE name = ?", [part_name])
        assert part_row[0] == "dead"


def test_cli_magnet_update_status_dead_all_combined_with_part_fails(tmp_path, monkeypatch):
    db = _db_with_magnet(tmp_path)
    with pytest.raises(SystemExit):
        _run(monkeypatch, "magnet", "update-status", "MAG_JSON", "--status", "dead",
             "--dead-part", "ALL", "--dead-part", "H_JSON_01", "--db", str(db))


def test_cli_magnet_update_status_dead_repeat_dead_part_warns(tmp_path, monkeypatch, capsys):
    db = _db_with_magnet(tmp_path)
    _run(monkeypatch, "magnet", "update-status", "MAG_JSON", "--status", "dead",
         "--dead-part", "H_JSON_01", "--db", str(db))
    capsys.readouterr()
    _run(monkeypatch, "magnet", "update-status", "MAG_JSON", "--status", "dead",
         "--dead-part", "H_JSON_01", "--db", str(db))
    out = capsys.readouterr().out
    assert "already dead" in out


def test_cli_magnet_update_status_missing_db_exits(tmp_path, monkeypatch):
    with pytest.raises(SystemExit):
        _run(monkeypatch, "magnet", "update-status", "MAG_JSON", "--status", "in_stock",
             "--db", str(tmp_path / "nope.duckdb"))


# ---------------------------------------------------------------------------
# log view
# ---------------------------------------------------------------------------


def test_cli_log_view_shows_ok_row_after_magnet_add(tmp_path, monkeypatch, capsys):
    db = _db_with_magnet(tmp_path)
    capsys.readouterr()
    _run(monkeypatch, "log", "view", "--table", "magnets", "--db", str(db))
    out = capsys.readouterr().out
    assert "MAG_JSON" in out
    assert "ok" in out


def test_cli_log_view_status_error_after_failed_update_status(tmp_path, monkeypatch, capsys):
    db = _db_with_magnet(tmp_path)
    with pytest.raises(SystemExit):
        _run(monkeypatch, "magnet", "update-status", "MAG_JSON", "--status", "dead", "--db", str(db))
    capsys.readouterr()
    _run(monkeypatch, "log", "view", "--status", "error", "--db", str(db))
    out = capsys.readouterr().out
    assert "MAG_JSON" in out
    assert "error" in out


# ---------------------------------------------------------------------------
# populate overview-records
# ---------------------------------------------------------------------------


def test_cli_populate_overview_records_logs_operation_log_row(tmp_path, monkeypatch):
    """populate overview-records writes one operation_log row per processed file."""
    db = _db_with_assembly(tmp_path)  # ASSEMBLY_JSON_01, housing M10, commissioned 2025-01-01

    from python_magnetrun.analysis.loaders import FileSet
    from python_magnetrun.analysis.processing import OverviewRecord

    overview_path = tmp_path / "M10_Overview_250115-1200.tdms"

    def fake_find_and_register(assembly, db_path, db_tz, dry_run, type_filter, records_base, pbsurv):
        assert type_filter == ["Overview"]
        return [(overview_path, datetime(2025, 1, 15, 12, 0, 0), "Overview")]

    def fake_process_overview_file(path, config):
        return OverviewRecord(
            filename="M10_Overview_250115-1200",
            housing="M10",
            mode="Overview",
            t0=datetime(2025, 1, 15, 12, 0, 0),
            duration=1800.0,
            sources=FileSet(overview=[str(path)]),
        )

    monkeypatch.setattr("magnetdb._tdms_find_and_register", fake_find_and_register)
    monkeypatch.setattr(
        "python_magnetrun.analysis.processing.process_overview_file", fake_process_overview_file
    )

    _run(monkeypatch, "populate", "overview-records",
         "--assembly", "ASSEMBLY_JSON_01", "--db", str(db))

    row = _fetch_one(
        db, "SELECT operation, status FROM operation_log "
        "WHERE table_name = 'overview_records' AND record_name = ?",
        [overview_path.name],
    )
    assert row == ("populate", "ok")


# ---------------------------------------------------------------------------
# populate overview-records-from-archive
# ---------------------------------------------------------------------------


def test_cli_populate_overview_records_from_archive_writes_thin_row(tmp_path, monkeypatch):
    """CLI plumbing test: python_magnetrun's own file discovery/processing is
    mocked out (it's covered by python_magnetrun's own test suite); this checks
    that the new subcommand wires assembly resolution, type_filter=["Archive"],
    and the record into a row with sources_overview empty."""
    db = _db_with_assembly(tmp_path)  # ASSEMBLY_JSON_01, housing M10, commissioned 2025-01-01

    from python_magnetrun.analysis.loaders import FileSet
    from python_magnetrun.analysis.processing import OverviewRecord

    archive_path = tmp_path / "M10_Archive_250115-1200.tdms"

    def fake_find_and_register(assembly, db_path, db_tz, dry_run, type_filter, records_base, pbsurv):
        assert type_filter == ["Archive"]
        return [(archive_path, datetime(2025, 1, 15, 12, 0, 0), "Archive")]

    def fake_process_archive_file(path, config):
        return OverviewRecord(
            filename="M10_Archive_250115-1200",
            housing="M10",
            mode="Archive",
            t0=datetime(2025, 1, 15, 12, 0, 0),
            duration=1800.0,
            sources=FileSet(archive=[str(path)], pupitre=["2025.01.15 - 12:00:00.txt"]),
        )

    monkeypatch.setattr("magnetdb._tdms_find_and_register", fake_find_and_register)
    monkeypatch.setattr(
        "python_magnetrun.analysis.processing.process_archive_file", fake_process_archive_file
    )

    _run(monkeypatch, "populate", "overview-records-from-archive",
         "--assembly", "ASSEMBLY_JSON_01", "--db", str(db))

    row = _fetch_one(
        db, "SELECT housing, assembly_name, sources_overview, sources_archive, sources_pupitre, "
        "duration FROM overview_records WHERE filename = 'M10_Archive_250115-1200'"
    )
    assert row[0] == "M10"
    assert row[1] == "ASSEMBLY_JSON_01"
    assert row[2] == []
    assert row[3] == [str(archive_path)]
    assert row[4] == ["2025.01.15 - 12:00:00.txt"]
    assert row[5] == 1800.0


def test_cli_populate_overview_records_from_archive_skips_already_covered(tmp_path, monkeypatch):
    """An archive file already referenced in some existing row's sources_archive
    (e.g. a genuine Overview-anchored session) should be skipped, not duplicated."""
    db = _db_with_assembly(tmp_path)  # ASSEMBLY_JSON_01, housing M10, commissioned 2025-01-01

    from schema import ensure_schema

    with duckdb.connect(str(db)) as con:
        ensure_schema(con)
        con.execute(
            "INSERT INTO overview_records (filename, sources_archive) VALUES (?, ?)",
            [
                "M10_Overview_250115-1200",
                ["/data/M10/Fichiers_Archive/M10_Archive_250115-1200.tdms"],
            ],
        )

    # Same basename as the row seeded above, but discovered under a different path.
    archive_path = tmp_path / "M10_Archive_250115-1200.tdms"

    def fake_find_and_register(assembly, db_path, db_tz, dry_run, type_filter, records_base, pbsurv):
        return [(archive_path, datetime(2025, 1, 15, 12, 0, 0), "Archive")]

    def fake_process_archive_file(path, config):
        raise AssertionError(
            "process_archive_file should not be called for an already-covered archive file"
        )

    monkeypatch.setattr("magnetdb._tdms_find_and_register", fake_find_and_register)
    monkeypatch.setattr(
        "python_magnetrun.analysis.processing.process_archive_file", fake_process_archive_file
    )

    _run(monkeypatch, "populate", "overview-records-from-archive",
         "--assembly", "ASSEMBLY_JSON_01", "--db", str(db))

    assert _count(db, "overview_records") == 1


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


def test_cli_populate_overview_records_from_json_auto_resolves_assembly(tmp_path, monkeypatch):
    db = _db_with_assembly(tmp_path)  # ASSEMBLY_JSON_01, housing M10, commissioned 2025-01-01
    json_path = tmp_path / "M10_summary-2025.json"
    json_path.write_text(json.dumps([_summary_json_record("M10_Overview_250115-1200")]))

    _run(monkeypatch, "populate", "overview-records-from-json", str(json_path), "--db", str(db))

    row = _fetch_one(
        db, "SELECT housing, assembly_name, t0, sources_overview FROM overview_records "
        "WHERE filename = 'M10_Overview_250115-1200'"
    )
    assert row[0] == "M10"
    assert row[1] == "ASSEMBLY_JSON_01"
    assert row[2] is not None
    assert row[3] == ["M10_Overview_250115-1200.tdms"]


def test_cli_populate_overview_records_from_json_unresolved_assembly_stays_null(tmp_path, monkeypatch):
    db = _db_with_assembly(tmp_path)  # only a M10 assembly exists
    json_path = tmp_path / "M9_summary-2025.json"
    json_path.write_text(json.dumps([_summary_json_record("M9_Overview_250115-1200")]))

    _run(monkeypatch, "populate", "overview-records-from-json", str(json_path), "--db", str(db))

    row = _fetch_one(
        db, "SELECT housing, assembly_name FROM overview_records "
        "WHERE filename = 'M9_Overview_250115-1200'"
    )
    assert row == ("M9", None)


def test_cli_populate_overview_records_from_json_unknown_assembly_exits(tmp_path, monkeypatch):
    db = _db_with_assembly(tmp_path)
    json_path = tmp_path / "M10_summary-2025.json"
    json_path.write_text(json.dumps([_summary_json_record("M10_Overview_250115-1200")]))

    with pytest.raises(SystemExit):
        _run(monkeypatch, "populate", "overview-records-from-json", str(json_path),
             "--db", str(db), "--assembly", "NoSuchAssembly")

    assert _count(db, "overview_records") == 0


def test_cli_populate_overview_records_from_json_assembly_override(tmp_path, monkeypatch):
    db = _db_with_assembly(tmp_path)
    json_path = tmp_path / "M10_summary-2025.json"
    json_path.write_text(json.dumps([_summary_json_record("M10_Overview_250115-1200")]))

    _run(monkeypatch, "populate", "overview-records-from-json", str(json_path),
         "--db", str(db), "--assembly", "ASSEMBLY_JSON_01")

    row = _fetch_one(
        db, "SELECT housing, assembly_name FROM overview_records "
        "WHERE filename = 'M10_Overview_250115-1200'"
    )
    assert row == ("M10", "ASSEMBLY_JSON_01")


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
