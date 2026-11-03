"""etl_spec: Pupitre ETL spec per (assembly, housing version) built from DuckDB."""

import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import duckdb
import pytest

from etl_spec import build_pupitre_etl_spec, export_pupitre_etl_spec, set_magnet_part
from python_magnetrun.runetl import PupitreEtlSpec, load_pupitre_etl_spec
from tests.test_file_context import build_db

PARIS = ZoneInfo("Europe/Paris")
INSERT_UCOILS = [f"Ucoil{n}" for n in range(2, 8)]


def _fd(formula: str) -> dict:
    key = formula.split("=")[0].strip()
    return {"formula": formula, "symbol": key, "unit": "volt", "label": key, "description": key}


INSERT_PART = {
    "channels": INSERT_UCOILS,
    "remove": ["Ucoil1", "Ucoil(8|9|1[0-4])"],
    "add": {"UH": _fd("UH = " + " + ".join(INSERT_UCOILS))},
    "current": {"source": "Icoil2", "check": "IH"},
}


@pytest.fixture()
def con():
    c = build_db()
    yield c
    c.close()


def _spec(con, assembly, *when) -> PupitreEtlSpec:
    return PupitreEtlSpec.from_dict(build_pupitre_etl_spec(con, assembly, datetime(*when, tzinfo=PARIS)))


def test_m9_without_magnet_parts(con):
    spec = _spec(con, "M9_A260602_00", 2026, 6, 10, 10)
    assert spec.housing["version"] == "M9-181109"
    assert r"Icoil\d+" in spec.remove
    assert spec.rename["Flow1"] == "FlowH"
    assert {"IH", "IB", "UH", "UB"} <= set(spec.add)
    assert spec.magnets == {}


def test_m9_with_insert_part(con):
    set_magnet_part(con, "M9_A260602_00", "M25032101", "M9-181109", INSERT_PART)
    spec = _spec(con, "M9_A260602_00", 2026, 6, 10, 10)
    assert spec.add["UH"]["formula"] == "UH = Ucoil2 + Ucoil3 + Ucoil4 + Ucoil5 + Ucoil6 + Ucoil7"
    assert spec.checks == [{"magnet": "M25032101", "source": "Icoil2", "check": "IH"}]


def test_m8_spec_follows_wiring_change(con):
    part = {"channels": ["Ucoil15", "Ucoil16"], "current": {"source": "Icoil15", "check": "IB"}}
    set_magnet_part(con, "M8_A230919_00", "M8Bi", "M8-211225", part)
    before = _spec(con, "M8_A230919_00", 2026, 3, 5, 15, 56)
    after = _spec(con, "M8_A230919_00", 2026, 3, 5, 17, 22)
    assert before.housing["version"] == "M8-211225"
    assert before.add["UB"]["formula"] == "UB = Ucoil15 + Ucoil16"
    assert "M8Bi" in before.magnets
    assert after.housing["version"] == "M8-260305"
    assert after.add["UB"]["formula"] == "UB = Ucoil14"
    assert "M8Bi" not in after.magnets


def test_export_one_file_per_version(con, tmp_path):
    paths = export_pupitre_etl_spec(con, "M8_A230919_00", tmp_path)
    assert sorted(p.name for p in paths) == [
        "M8_A230919_00.M8-211225.pupitre-etl.json",
        "M8_A230919_00.M8-260305.pupitre-etl.json",
    ]
    loaded = load_pupitre_etl_spec(tmp_path / "M8_A230919_00.M8-260305.pupitre-etl.json")
    assert loaded == _spec(con, "M8_A230919_00", 2026, 3, 6)


def test_export_one_version(con, tmp_path):
    paths = export_pupitre_etl_spec(con, "M8_A230919_00", tmp_path, version="M8-260305")
    assert [p.name for p in paths] == ["M8_A230919_00.M8-260305.pupitre-etl.json"]


def test_part_for_magnet_outside_assembly_refused(con):
    with pytest.raises(duckdb.ConstraintException):
        set_magnet_part(con, "M9_A260602_00", "M8Bi", "M9-181109", {"channels": ["Ucoil15"]})


def test_part_for_unknown_version_refused(con):
    with pytest.raises((duckdb.ConstraintException, ValueError)):
        set_magnet_part(con, "M9_A260602_00", "M25032101", "M9-999999", INSERT_PART)


def test_part_for_other_housing_version_refused(con):
    with pytest.raises(ValueError, match="M8"):
        set_magnet_part(con, "M9_A260602_00", "M25032101", "M8-260305", INSERT_PART)


def test_part_for_version_outside_assembly_refused(con):
    with pytest.raises(ValueError, match="overlap"):
        set_magnet_part(con, "M8_S", "Hybrid", "M8-260305", {})


def test_invalid_part_refused(con):
    with pytest.raises(ValueError, match="rename"):
        set_magnet_part(con, "M9_A260602_00", "M25032101", "M9-181109", {"rename": {"A": "B"}})


def test_set_magnet_part_upserts(con):
    set_magnet_part(con, "M9_A260602_00", "M25032101", "M9-181109", {"channels": ["Ucoil2"]})
    set_magnet_part(con, "M9_A260602_00", "M25032101", "M9-181109", INSERT_PART)
    assert _spec(con, "M9_A260602_00", 2026, 6, 10).magnets["M25032101"] == INSERT_PART


def test_m10_bitters_only(con):
    spec = _spec(con, "M10_B", 2026, 1, 1)
    assert "IH" not in spec.add and "UH" not in spec.add
    assert {"IH", "UH", "Idcct3", "Idcct4"} <= set(spec.remove)
    assert {f"Ucoil{n}" for n in range(1, 15)} <= set(spec.remove)
    assert {"IB", "UB"} <= set(spec.add)
    assert spec.rename["Flow2"] == "FlowH"  # hydraulics kept


def test_supras_only(con):
    spec = _spec(con, "M8_S", 2022, 6, 1)
    assert not {"IH", "IB", "UH", "UB"} & set(spec.add)
    assert {"IH", "UH", "IB", "UB"} <= set(spec.remove)
    assert {"Flow1", "Flow2", "Tin1", "Tin2"} <= set(spec.rename)


def test_same_magnet_in_m9_and_m10(con):
    part = {"channels": ["Ucoil3"]}
    set_magnet_part(con, "M9_B", "MX", "M9-181109", part)
    set_magnet_part(con, "M10_X", "MX", "M10-180220", part)
    m9 = _spec(con, "M9_B", 2025, 6, 1)
    m10 = _spec(con, "M10_X", 2024, 6, 1)
    assert m9.rename["Flow1"] == "FlowH" and m10.rename["Flow1"] == "FlowB"
    assert m9.magnets["MX"] == m10.magnets["MX"] == part


def test_etl_cli_export(tmp_path, monkeypatch, capsys):
    """`magnetdb.py etl export` on a DuckDB file writes the spec files."""
    import magnetdb

    db = tmp_path / "test.duckdb"
    build_db(str(db)).close()
    out = tmp_path / "specs"
    monkeypatch.setattr(sys, "argv", ["magnetdb", "etl", "export", "M9_A260602_00", "--db", str(db), "-o", str(out)])
    magnetdb.main()
    assert (out / "M9_A260602_00.M9-181109.pupitre-etl.json").exists()


def _log(con):
    return con.execute(
        "SELECT operation, table_name, record_name, status FROM operation_log "
        "WHERE table_name = 'pupitre_etl_magnet' ORDER BY id"
    ).fetchall()


def test_set_magnet_part_logged(con):
    set_magnet_part(con, "M9_A260602_00", "M25032101", "M9-181109", INSERT_PART)
    assert _log(con) == [("upsert", "pupitre_etl_magnet", "M9_A260602_00/M25032101/M9-181109", "ok")]


def test_set_magnet_part_error_logged(con):
    with pytest.raises(ValueError):
        set_magnet_part(con, "M9_A260602_00", "M25032101", "M8-260305", INSERT_PART)
    assert _log(con) == [("upsert", "pupitre_etl_magnet", "M9_A260602_00/M25032101/M8-260305", "error")]
