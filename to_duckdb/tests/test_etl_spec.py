"""etl_spec: Pupitre ETL spec per (assembly, housing version) built from DuckDB."""

import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import duckdb
import pytest

from etl_spec import build_pupitre_etl_spec, export_pupitre_etl_spec, set_magnet_wiring
from python_magnetrun.runetl import PupitreEtlSpec, load_pupitre_etl_spec
from tests.test_file_context import build_db

PARIS = ZoneInfo("Europe/Paris")
INSERT_UCOILS = [f"Ucoil{n}" for n in range(2, 8)]


def _fd(formula: str) -> dict:
    key = formula.split("=")[0].strip()
    return {"formula": formula, "symbol": key, "unit": "volt", "label": key, "description": key}


INSERT_WIRING = {
    "channels": INSERT_UCOILS,
    "remove": ["Ucoil1", "Ucoil(8|9|1[0-4])"],
    "add": {"UH": _fd("UH = " + " + ".join(INSERT_UCOILS))},
}


@pytest.fixture()
def con():
    c = build_db()
    yield c
    c.close()


def _spec(con, assembly, *when) -> PupitreEtlSpec:
    return PupitreEtlSpec.from_dict(build_pupitre_etl_spec(con, assembly, datetime(*when, tzinfo=PARIS)))


def test_m9_without_magnet_wiring(con):
    spec = _spec(con, "M9_A260602_00", 2026, 6, 10, 10)
    assert spec.housing["version"] == "M9-181109"
    assert r"Icoil\d+" in spec.remove
    assert spec.rename["Flow1"] == "FlowH"
    assert {"IH", "IB", "UH", "UB"} <= set(spec.add)
    assert spec.magnets == {}


def test_m9_with_insert_wiring(con):
    set_magnet_wiring(con, "M9_A260602_00", "M25032101", "M9-181109", INSERT_WIRING)
    spec = _spec(con, "M9_A260602_00", 2026, 6, 10, 10)
    assert spec.add["UH"]["formula"] == "UH = Ucoil2 + Ucoil3 + Ucoil4 + Ucoil5 + Ucoil6 + Ucoil7"
    assert spec.magnets["M25032101"] == INSERT_WIRING
    assert spec.rules == []


def test_m8_spec_follows_wiring_change(con):
    wiring = {"channels": ["Ucoil15", "Ucoil16"]}
    set_magnet_wiring(con, "M8_A230919_00", "M8Bi", "M8-230913", wiring)
    before = _spec(con, "M8_A230919_00", 2026, 3, 5, 15, 56)
    after = _spec(con, "M8_A230919_00", 2026, 3, 5, 17, 22)
    assert before.housing["version"] == "M8-230913"
    assert before.add["UB"]["formula"] == "UB = Ucoil15 + Ucoil16"
    assert "M8Bi" in before.magnets
    assert after.housing["version"] == "M8-260305"
    assert after.add["UB"]["formula"] == "UB = Ucoil14"
    assert "M8Bi" not in after.magnets


def test_export_one_file_per_version(con, tmp_path):
    paths = export_pupitre_etl_spec(con, "M8_A230919_00", tmp_path)
    assert sorted(p.name for p in paths) == [
        "M8_A230919_00.M8-230913.pupitre-etl.json",
        "M8_A230919_00.M8-260305.pupitre-etl.json",
    ]
    loaded = load_pupitre_etl_spec(tmp_path / "M8_A230919_00.M8-260305.pupitre-etl.json")
    assert loaded == _spec(con, "M8_A230919_00", 2026, 3, 6)


def test_export_one_version(con, tmp_path):
    paths = export_pupitre_etl_spec(con, "M8_A230919_00", tmp_path, version="M8-260305")
    assert [p.name for p in paths] == ["M8_A230919_00.M8-260305.pupitre-etl.json"]


def test_wiring_for_magnet_outside_assembly_refused(con):
    with pytest.raises(duckdb.ConstraintException):
        set_magnet_wiring(con, "M9_A260602_00", "M8Bi", "M9-181109", {"channels": ["Ucoil15"]})


def test_wiring_for_unknown_version_refused(con):
    with pytest.raises((duckdb.ConstraintException, ValueError)):
        set_magnet_wiring(con, "M9_A260602_00", "M25032101", "M9-999999", INSERT_WIRING)


def test_wiring_for_other_housing_version_refused(con):
    with pytest.raises(ValueError, match="M8"):
        set_magnet_wiring(con, "M9_A260602_00", "M25032101", "M8-260305", INSERT_WIRING)


def test_wiring_for_version_outside_assembly_refused(con):
    with pytest.raises(ValueError, match="overlap"):
        set_magnet_wiring(con, "M8_S", "Hybrid", "M8-260305", {})


def test_invalid_wiring_refused(con):
    with pytest.raises(ValueError, match="rename"):
        set_magnet_wiring(con, "M9_A260602_00", "M25032101", "M9-181109", {"rename": {"A": "B"}})


def test_wiring_with_current_refused(con):
    """The current check is a rule now (`rule add`), not part of the wiring."""
    with pytest.raises(ValueError, match="current"):
        set_magnet_wiring(
            con, "M9_A260602_00", "M25032101", "M9-181109",
            {"channels": ["Ucoil2"], "current": {"source": "Icoil2", "check": "IH"}},
        )


def test_set_magnet_wiring_upserts(con):
    set_magnet_wiring(con, "M9_A260602_00", "M25032101", "M9-181109", {"channels": ["Ucoil2"]})
    set_magnet_wiring(con, "M9_A260602_00", "M25032101", "M9-181109", INSERT_WIRING)
    assert _spec(con, "M9_A260602_00", 2026, 6, 10).magnets["M25032101"] == INSERT_WIRING


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
    wiring = {"channels": ["Ucoil3"]}
    set_magnet_wiring(con, "M9_B", "MX", "M9-181109", wiring)
    set_magnet_wiring(con, "M10_X", "MX", "M10-210929", wiring)  # 2024: base wiring again since 2021-09-29
    m9 = _spec(con, "M9_B", 2025, 6, 1)
    m10 = _spec(con, "M10_X", 2024, 6, 1)
    assert m9.rename["Flow1"] == "FlowH" and m10.rename["Flow1"] == "FlowB"
    assert m9.magnets["MX"] == m10.magnets["MX"] == wiring


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


def test_set_magnet_wiring_logged(con):
    set_magnet_wiring(con, "M9_A260602_00", "M25032101", "M9-181109", INSERT_WIRING)
    assert _log(con) == [("upsert", "pupitre_etl_magnet", "M9_A260602_00/M25032101/M9-181109", "ok")]


def test_set_magnet_wiring_error_logged(con):
    with pytest.raises(ValueError):
        set_magnet_wiring(con, "M9_A260602_00", "M25032101", "M8-260305", INSERT_WIRING)
    assert _log(con) == [("upsert", "pupitre_etl_magnet", "M9_A260602_00/M25032101/M8-260305", "error")]


# ---------------------------------------------------------------------------
# insert wiring derived from the helix count (PLAN_pupitre_checks_file.md, revision 2)
# ---------------------------------------------------------------------------


def _helices(con, magnet: str, n: int) -> None:
    """Give *magnet* *n* helix parts (the fixture's magnets have no parts)."""
    for i in range(1, n + 1):
        con.execute("INSERT INTO parts (name, type, status) VALUES (?, 'helix', 'in_operation')",
                    [f"{magnet}_H{i}"])
        con.execute("INSERT INTO magnet_parts (magnet_name, part_name, rank) VALUES (?, ?, ?)",
                    [magnet, f"{magnet}_H{i}", i])


def _ucoils(numbers) -> list[str]:
    return [f"Ucoil{n}" for n in numbers]


@pytest.mark.parametrize("helices, first", [(14, 1), (12, 2), (6, 5), (2, 7)])
def test_derived_insert_wiring(con, helices, first):
    _helices(con, "M25032101", helices)
    spec = _spec(con, "M9_A260602_00", 2026, 6, 10, 10)
    taps = _ucoils(range(first, 8))
    wiring = spec.magnets["M25032101"]
    assert wiring["channels"] == taps
    assert wiring["remove"] == [c for c in _ucoils(range(1, 15)) if c not in taps]
    assert spec.add["UH"]["formula"] == "UH = " + " + ".join(taps)
    assert spec.add["UH"]["label"] == "GR1 Voltage (UH)"
    assert {"Ucoil15", "Ucoil16"}.isdisjoint(wiring["remove"])  # Bitters untouched


def test_derived_wiring_label_follows_housing(con):
    _helices(con, "MX", 6)
    spec = _spec(con, "M10_X", 2024, 6, 1)
    assert spec.magnets["MX"]["channels"] == _ucoils(range(5, 8))
    assert spec.add["UH"]["label"] == "GR2 Voltage (UH)"


def test_derived_wiring_follows_housing_version(con):
    """M8-260305 reads the Bitters on Ucoil14: the insert wiring must not remove it."""
    _helices(con, "M23012001", 12)
    before = _spec(con, "M8_A230919_00", 2026, 3, 5, 15, 56)  # M8-230913
    after = _spec(con, "M8_A230919_00", 2026, 3, 5, 17, 22)  # M8-260305
    assert before.magnets["M23012001"]["remove"] == _ucoils([1, *range(8, 15)])
    assert after.magnets["M23012001"]["remove"] == _ucoils([1, *range(8, 14)])
    assert after.add["UB"]["formula"] == "UB = Ucoil14"
    assert "Ucoil14" not in after.remove


def test_explicit_wiring_overrides_derived(con):
    _helices(con, "M25032101", 14)
    set_magnet_wiring(con, "M9_A260602_00", "M25032101", "M9-181109", INSERT_WIRING)
    assert _spec(con, "M9_A260602_00", 2026, 6, 10).magnets["M25032101"] == INSERT_WIRING


@pytest.mark.parametrize("helices", [0, 7, 16])
def test_no_derived_wiring_without_usable_helix_count(con, helices):
    _helices(con, "M25032101", helices)
    spec = _spec(con, "M9_A260602_00", 2026, 6, 10)
    assert spec.magnets == {}
    assert spec.add["UH"]["formula"] == "UH = " + " + ".join(_ucoils(range(1, 15)))
