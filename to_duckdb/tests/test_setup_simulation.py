"""Tests for setup_simulation.py.

The unit tests replace the stress_map geometry chain and
``python_magnetsetup.setup.setup`` with fakes. The integration test at the end
runs the real ``setup()`` and is skipped without ``test-magnetdb.duckdb``.
"""

import hashlib
import json
import os
import uuid
from pathlib import Path

import duckdb
import pytest

import setup_simulation as ss
from schema import ensure_schema
from setup_simulation import _parse_current, main, setup_simulation
from tests.test_compute_hoop_stats import _build_hoop_assembly

# HOOP_ASSEMBLY: MAG_NEW (insert), MAG_OLD (insert), MAG_B (bitters)
CONFIGS = {
    "MAG_NEW": {"geom": "MAG_NEW.yaml", "Helix": [{"geom": "H_NEW.yaml"}]},
    "MAG_OLD": {"geom": "MAG_OLD.yaml", "Helix": [{"geom": "H_OLD.yaml"}]},
    "MAG_B": {"geom": "MAG_B.yaml", "Bitter": [{"geom": "B_ONE.yaml"}]},
}
ALL_CURRENTS = {"MAG_NEW": 31000.0, "MAG_OLD": 30000.0, "MAG_B": 33000.0}
SETUP_STATE_KEYS = {"yamlfile", "cfgfile", "jsonfile", "xaofile", "meshfile", "csvfiles"}


@pytest.fixture
def assembly_db(tmp_path):
    """File-backed DB holding HOOP_ASSEMBLY."""
    db_path = tmp_path / "setup.duckdb"
    con = duckdb.connect(str(db_path))
    ensure_schema(con)
    _build_hoop_assembly(con)
    con.close()
    return db_path


@pytest.fixture
def fake_chain(monkeypatch, tmp_path):
    """Fake the stress_map chain, the YAML order and ``setup()``; return the recorded state."""
    state = {"calls": [], "setup_args": None, "geom_dir": tmp_path / "geomtmp",
             "yaml_order": ["MAG_NEW", "MAG_OLD", "MAG_B"], "raise": None}

    def fake_load(assembly_name, db_path, magnet_override=None, con=None):
        state["calls"].append("load")
        assert con is not None
        return "M9", [(name, CONFIGS[name], None) for name in ("MAG_NEW", "MAG_OLD", "MAG_B")]

    def fake_prepare(assembly_name, config, db_path, geometries_dir=None, con=None):
        state["calls"].append("prepare")
        assert con is not None
        geom = state["geom_dir"] / "data" / "geometries"
        geom.mkdir(parents=True)
        (state["geom_dir"] / "data" / "cad").mkdir()
        for name in ("HOOP_ASSEMBLY", *CONFIGS):
            (geom / f"{name}.yaml").write_text(f"name: {name}\n")
        return state["geom_dir"]

    def fake_order(yaml_path):
        state["calls"].append("order")
        assert Path(yaml_path).name == "HOOP_ASSEMBLY.yaml"
        return list(state["yaml_order"])

    def fake_setup(env, args, confdata, jsonfile, currents, session=None):
        state["calls"].append("setup")
        state["setup_args"] = {"env": env, "args": args, "confdata": confdata,
                               "jsonfile": jsonfile, "currents": currents}
        os.chdir(args.wd)  # like the real setup(): never changed back
        if state["raise"] is not None:
            raise state["raise"]
        base = f"{jsonfile}-{args.method}-{args.model}-{args.geom}-sim"
        Path(f"{base}.json").write_text("{}")
        Path(f"{base}.cfg").write_text("")
        Path("conductor.json").write_text("{}")
        Path("R.csv").write_text("")
        yamlfile = confdata["geom"] if "geom" in confdata else f"{confdata['name']}.yaml"
        return (yamlfile, f"{base}.cfg", f"{base}.json", "x-Axi.xao", "x-Axi.msh", ["./R.csv"])

    monkeypatch.setattr("stress_map.load_assembly_config_from_duckdb", fake_load)
    monkeypatch.setattr("stress_map.prepare_geometry_directory", fake_prepare)
    monkeypatch.setattr(ss, "_assembly_magnet_order", fake_order)
    monkeypatch.setattr("python_magnetsetup.setup.setup", fake_setup)
    return state


def _run(db, wd, **kwargs):
    kwargs.setdefault("currents", dict(ALL_CURRENTS))
    kwargs.setdefault("model", "thelec")
    return setup_simulation("HOOP_ASSEMBLY", wd, db_path=db, **kwargs)


# ---------------------------------------------------------------------------
# Target and currents
# ---------------------------------------------------------------------------


def test_magnet_setup_passes_flat_config_and_one_current(assembly_db, fake_chain, tmp_path):
    _run(assembly_db, tmp_path / "wd", magnet="MAG_B", currents={"MAG_B": 33000.0})

    called = fake_chain["setup_args"]
    assert called["confdata"] == CONFIGS["MAG_B"]
    assert called["currents"] == {"MAG_B": {"value": 33000.0, "type": "bitters"}}
    assert called["jsonfile"] == "MAG_B"
    assert "order" not in fake_chain["calls"]


def test_assembly_setup_orders_magnets_as_the_yaml(assembly_db, fake_chain, tmp_path):
    fake_chain["yaml_order"] = ["MAG_B", "MAG_NEW", "MAG_OLD"]
    _run(assembly_db, tmp_path / "wd")

    confdata = fake_chain["setup_args"]["confdata"]
    assert confdata["name"] == "HOOP_ASSEMBLY"
    assert [list(m) for m in confdata["magnets"]] == [["MAG_B"], ["MAG_NEW"], ["MAG_OLD"]]
    assert confdata["magnets"][0]["MAG_B"] == CONFIGS["MAG_B"]
    assert fake_chain["setup_args"]["currents"]["MAG_NEW"] == {"value": 31000.0, "type": "insert"}
    assert fake_chain["setup_args"]["jsonfile"] == "HOOP_ASSEMBLY"


def test_assembly_yaml_order_mismatch_is_refused(assembly_db, fake_chain, tmp_path):
    fake_chain["yaml_order"] = ["MAG_NEW", "MAG_B"]
    with pytest.raises(ValueError, match="MAG_OLD"):
        _run(assembly_db, tmp_path / "wd")
    assert "setup" not in fake_chain["calls"]
    assert not fake_chain["geom_dir"].exists()


def test_missing_current_is_refused(assembly_db, fake_chain, tmp_path):
    with pytest.raises(ValueError, match="MAG_OLD"):
        _run(assembly_db, tmp_path / "wd", currents={"MAG_NEW": 1.0, "MAG_B": 1.0})
    assert "setup" not in fake_chain["calls"]


def test_current_for_an_unknown_magnet_is_refused(assembly_db, fake_chain, tmp_path):
    with pytest.raises(ValueError, match="NOPE"):
        _run(assembly_db, tmp_path / "wd", magnet="MAG_B", currents={"MAG_B": 1.0, "NOPE": 2.0})


def test_magnet_not_in_assembly_is_refused(assembly_db, fake_chain, tmp_path):
    with pytest.raises(ValueError, match="NOPE"):
        _run(assembly_db, tmp_path / "wd", magnet="NOPE", currents={"NOPE": 1.0})
    assert "setup" not in fake_chain["calls"]


@pytest.mark.parametrize("text, expected", [("M23072801=31000", ("M23072801", 31000.0)),
                                            ("M9Bitters-newBi08=3.3e4", ("M9Bitters-newBi08", 33000.0))])
def test_parse_current(text, expected):
    assert _parse_current(text) == expected


@pytest.mark.parametrize("text", ["M23072801", "=31000", "M=abc", "M="])
def test_parse_current_rejects_bad_values(text):
    with pytest.raises(ValueError):
        _parse_current(text)


# ---------------------------------------------------------------------------
# Working directory, temporary tree, DB connection
# ---------------------------------------------------------------------------


def test_non_empty_wd_is_refused_without_force(assembly_db, fake_chain, tmp_path):
    wd = tmp_path / "wd"
    wd.mkdir()
    (wd / "old.txt").write_text("x")
    with pytest.raises(ValueError, match="not empty"):
        _run(assembly_db, wd)
    assert fake_chain["calls"] == []

    _run(assembly_db, wd, force=True)
    assert (wd / "setup.json").exists()


def test_cwd_restored_and_tree_removed_when_setup_raises(assembly_db, fake_chain, tmp_path):
    fake_chain["raise"] = RuntimeError("template missing")
    cwd = os.getcwd()
    with pytest.raises(RuntimeError, match="template missing"):
        _run(assembly_db, tmp_path / "wd")
    assert os.getcwd() == cwd
    assert not fake_chain["geom_dir"].exists()


def test_cwd_restored_and_tree_removed_on_success(assembly_db, fake_chain, tmp_path):
    cwd = os.getcwd()
    _run(assembly_db, tmp_path / "wd")
    assert os.getcwd() == cwd
    assert not fake_chain["geom_dir"].exists()


def test_db_path_is_opened_read_only(assembly_db, fake_chain, tmp_path, monkeypatch):
    seen = []
    real_connect = duckdb.connect

    def spy(*args, **kwargs):
        seen.append(kwargs.get("read_only"))
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(ss.duckdb, "connect", spy)
    _run(assembly_db, tmp_path / "wd")
    assert seen == [True]


def test_callers_connection_is_used_and_left_open(assembly_db, fake_chain, tmp_path):
    con = duckdb.connect(str(assembly_db), read_only=True)
    try:
        setup_simulation("HOOP_ASSEMBLY", tmp_path / "wd", con=con,
                         currents=dict(ALL_CURRENTS), model="thelec")
        assert con.execute("SELECT 1").fetchone() == (1,)
    finally:
        con.close()
    record = json.loads((tmp_path / "wd" / "setup.json").read_text())
    assert record["provenance"]["db_path"] is None
    assert record["provenance"]["db_sha256"] is None


@pytest.mark.parametrize("use_path, use_con", [(False, False), (True, True)])
def test_exactly_one_of_db_path_and_con(assembly_db, fake_chain, tmp_path, use_path, use_con):
    con = duckdb.connect(str(assembly_db), read_only=True) if use_con else None
    try:
        with pytest.raises(ValueError, match="db_path or con"):
            setup_simulation("HOOP_ASSEMBLY", tmp_path / "wd", currents=dict(ALL_CURRENTS),
                             model="thelec", db_path=assembly_db if use_path else None, con=con)
    finally:
        if con is not None:
            con.close()


# ---------------------------------------------------------------------------
# Output: returned dict, geometry copy, setup.json
# ---------------------------------------------------------------------------


def test_returns_setup_state_keys_relative_to_wd(assembly_db, fake_chain, tmp_path):
    wd = tmp_path / "wd"
    state = _run(assembly_db, wd)

    assert set(state) == SETUP_STATE_KEYS
    assert state["cfgfile"] == "HOOP_ASSEMBLY-cfpdes-thelec-Axi-sim.cfg"
    assert state["jsonfile"] == "HOOP_ASSEMBLY-cfpdes-thelec-Axi-sim.json"
    assert state["yamlfile"] == "HOOP_ASSEMBLY.yaml"
    assert state["csvfiles"] == ["R.csv"]
    assert (wd / state["cfgfile"]).exists()


def test_geometry_yamls_copied_to_wd(assembly_db, fake_chain, tmp_path):
    wd = tmp_path / "wd"
    _run(assembly_db, wd)
    assert sorted(p.name for p in (wd / "geometries").iterdir()) == [
        "HOOP_ASSEMBLY.yaml", "MAG_B.yaml", "MAG_NEW.yaml", "MAG_OLD.yaml"]


def test_setup_args_and_env(assembly_db, fake_chain, tmp_path):
    wd = tmp_path / "wd"
    _run(assembly_db, wd, model="thmag_hcurl", cooling="gradHZ", static=False, nonlinear=True)
    args = fake_chain["setup_args"]["args"]
    assert (args.method, args.time, args.geom, args.model, args.cooling, args.nonlinear) == (
        "cfpdes", "transient", "Axi", "thmag_hcurl", "gradHZ", True)
    assert Path(args.wd) == wd.resolve()
    env = fake_chain["setup_args"]["env"]
    assert env.yaml_repo == str(fake_chain["geom_dir"] / "data" / "geometries")


def test_setup_json_content(assembly_db, fake_chain, tmp_path):
    wd = tmp_path / "wd"
    state = _run(assembly_db, wd, model="thmag_hcurl", cooling="gradHZ")
    record = json.loads((wd / "setup.json").read_text())

    assert uuid.UUID(record["uid"]).version == 4
    assert record["kind"] == "fem"
    assert record["target_type"] == "assembly"
    assert record["target_name"] == "HOOP_ASSEMBLY"
    assert (record["method"], record["model"], record["geometry"], record["cooling"]) == (
        "cfpdes", "thmag_hcurl", "Axi", "gradHZ")
    assert record["static"] is True
    assert record["non_linear"] is False
    assert record["currents"] == ALL_CURRENTS
    assert record["setup_state"] == state

    provenance = record["provenance"]
    assert provenance["db_path"] == str(assembly_db)
    assert provenance["db_sha256"] == hashlib.sha256(assembly_db.read_bytes()).hexdigest()
    assert set(provenance["versions"]) == {"python_magnetsetup", "python_magnetgeo"}
    assert provenance["created_at"]
    assert len(record["geometry_fingerprint"]) == 64


def test_magnet_target_type_in_setup_json(assembly_db, fake_chain, tmp_path):
    wd = tmp_path / "wd"
    _run(assembly_db, wd, magnet="MAG_NEW", currents={"MAG_NEW": 31000.0})
    record = json.loads((wd / "setup.json").read_text())
    assert (record["target_type"], record["target_name"]) == ("magnet", "MAG_NEW")
    assert record["currents"] == {"MAG_NEW": 31000.0}


def test_geometry_fingerprint_is_stable_and_uid_is_new(assembly_db, fake_chain, tmp_path):
    _run(assembly_db, tmp_path / "wd1")
    _run(assembly_db, tmp_path / "wd2")
    first = json.loads((tmp_path / "wd1" / "setup.json").read_text())
    second = json.loads((tmp_path / "wd2" / "setup.json").read_text())
    assert first["geometry_fingerprint"] == second["geometry_fingerprint"]
    assert first["uid"] != second["uid"]


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def test_main_writes_the_setup(assembly_db, fake_chain, tmp_path):
    wd = tmp_path / "wd"
    main(["--db", str(assembly_db), "--assembly", "HOOP_ASSEMBLY", "--magnet", "MAG_B",
          "--current", "MAG_B=33000", "--model", "thelec", "--wd", str(wd)])
    assert fake_chain["setup_args"]["currents"] == {"MAG_B": {"value": 33000.0, "type": "bitters"}}
    assert (wd / "setup.json").exists()


def test_main_reports_errors_and_exits(assembly_db, fake_chain, tmp_path):
    argv = ["--db", str(assembly_db), "--assembly", "HOOP_ASSEMBLY", "--current", "MAG_B=1",
            "--model", "thelec", "--wd", str(tmp_path / "wd")]
    with pytest.raises(SystemExit, match="error: .*MAG_NEW"):
        main(argv)


# ---------------------------------------------------------------------------
# Real setup() on the latest database
# ---------------------------------------------------------------------------


def _latest_db() -> Path | None:
    """Newest ``to_duckdb/magnetdb-*.duckdb`` by modification time, or ``None``."""
    dbs = sorted(Path(__file__).resolve().parents[1].glob("magnetdb-*.duckdb"),
                 key=lambda p: p.stat().st_mtime)
    return dbs[-1] if dbs else None


LATEST_DB = _latest_db()


@pytest.mark.skipif(LATEST_DB is None, reason="no magnetdb-*.duckdb in to_duckdb/")
def test_real_insert_setup_on_latest_db(tmp_path):
    from stress_map import load_assembly_config_from_duckdb

    wd = tmp_path / "wd"
    state = setup_simulation("M9_A230801_00", wd, {"M23072801": 31000.0},
                             model="thelec", magnet="M23072801", db_path=LATEST_DB)

    assert (wd / state["cfgfile"]).exists()
    params = json.loads((wd / state["jsonfile"]).read_text())["Parameters"]
    _housing, magnets = load_assembly_config_from_duckdb("M9_A230801_00", str(LATEST_DB))
    n_helices = len(dict((name, config) for name, config, _ in magnets)["M23072801"]["Helix"])
    assert n_helices > 0
    for i in range(1, n_helices + 1):
        assert f"Area_H{i}" in params
        assert any(k.startswith(f"U_H{i}_") for k in params)
        assert any(k.startswith(f"N_H{i}_") for k in params)
    record = json.loads((wd / "setup.json").read_text())
    assert record["provenance"]["db_path"] == str(LATEST_DB)


@pytest.mark.skipif(LATEST_DB is None, reason="no magnetdb-*.duckdb in to_duckdb/")
def test_real_bitters_setup_keeps_every_part(tmp_path):
    from stress_map import load_assembly_config_from_duckdb

    wd = tmp_path / "wd"
    state = setup_simulation("M9_A230801_00", wd, {"M9Bitters-newBi08": 33000.0},
                             model="thelec", magnet="M9Bitters-newBi08", db_path=LATEST_DB)

    model = json.loads((wd / state["jsonfile"]).read_text())
    _housing, magnets = load_assembly_config_from_duckdb("M9_A230801_00", str(LATEST_DB))
    config = dict((name, cfg) for name, cfg, _ in magnets)["M9Bitters-newBi08"]
    parts = [Path(item["geom"]).stem for item in config["Bitter"]]
    assert len(parts) > 1
    for part in parts:
        assert f"Conductor_{part}" in model["Materials"]
        assert any(k.startswith(f"U_{part}_") for k in model["Parameters"])
        assert any(k.startswith(f"N_{part}_") for k in model["Parameters"])
