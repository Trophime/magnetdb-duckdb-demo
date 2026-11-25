"""Tests for export_inductance_matrix.py.

The unit tests replace magnettools and the stress_map geometry chain with
fakes. The last test runs the real chain and is skipped without magnettools
or without ``test-magnetdb.duckdb``.
"""

import csv
import importlib.util
import sys
import types
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pytest

from export_inductance_matrix import build_label_rows, export_inductance_matrix, main
from schema import ensure_schema
from tests.test_compute_hoop_stats import _build_hoop_assembly

# HOOP_ASSEMBLY: H1_fast = H_NEW (MAG_NEW), B1_fast = B_ONE (MAG_B), H2_fast = H_OLD (MAG_OLD)
PART_MAP = {"H1_fast": "H_NEW", "B1_fast": "B_ONE", "H2_fast": "H_OLD"}
PART_MAGNETS = {"H_NEW": "MAG_NEW", "H_OLD": "MAG_OLD", "B_ONE": "MAG_B"}

TUBE_MATRIX = [
    [2.0e-4, 5.0e-5, 1.0e-4],
    [5.0e-5, 3.0e-4, 2.0e-4],
    [1.0e-4, 2.0e-4, 1.0e-2],
]


def _write_matrix(path, labels, matrix):
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([""] + labels)
        for label, row in zip(labels, matrix, strict=True):
            writer.writerow([label] + [f"{v:.6e}" for v in row])


def _fake_inductances(with_pairs: bool) -> types.ModuleType:
    """magnettools.inductances stand-in: 2 tubes + 1 Bitter, 1.2.6-style labels."""
    module = types.ModuleType("magnettools.inductances")
    module.__file__ = "/fake/magnettools/inductances.py"

    def compute_inductance_matrix(Tubes, Helices, BMagnets, UMagnets, csvfile=None, verbose=True):
        labels = [f"H_{i}" for i in range(len(Tubes))] + [f"B_{i}" for i in range(len(BMagnets))]
        if csvfile:
            _write_matrix(csvfile, labels, TUBE_MATRIX)
            Path(csvfile).with_name(Path(csvfile).stem + "_summary.csv").write_text("")
        return {"labels": labels, "matrix": TUBE_MATRIX}

    def pair_tube_inductances(result, csvfile=None, verbose=True):
        m = result["matrix"]
        labels = ["H1H2", "B1"]
        paired = [
            [m[0][0] + m[1][1] + 2 * m[0][1], m[0][2] + m[1][2]],
            [m[0][2] + m[1][2], m[2][2]],
        ]
        if csvfile:
            _write_matrix(csvfile, labels, paired)
        return {"labels": labels, "matrix": paired, "inductances": {}}

    module.compute_inductance_matrix = compute_inductance_matrix
    if with_pairs:
        module.pair_tube_inductances = pair_tube_inductances
    return module


@pytest.fixture
def assembly_db(tmp_path):
    """File-backed DB holding HOOP_ASSEMBLY."""
    db_path = tmp_path / "inductance.duckdb"
    con = duckdb.connect(str(db_path))
    ensure_schema(con)
    _build_hoop_assembly(con)
    con.close()
    return db_path


@pytest.fixture
def fake_pipeline(monkeypatch, tmp_path):
    """Fake the stress_map chain; return the geometry dir it creates and the calls made."""
    geom_dir = tmp_path / "geom"
    calls = []

    def fake_load_assembly_config_from_duckdb(assembly_name, db_path, con=None):
        calls.append("load_assembly_config_from_duckdb")
        assert con is not None
        return "M9", [("MAG_NEW", {"geom": "MAG_NEW.yaml"}, None)]

    def fake_prepare_geometry_directory(assembly_name, config, db_path, geometries_dir=None, con=None):
        calls.append("prepare_geometry_directory")
        assert set(config) == {"name", "magnets"}
        geom_dir.mkdir()
        return geom_dir

    def fake_load_magnettools(config, tempdir, debug=False):
        calls.append("load_magnettools")
        return ["tube1", "tube2"], ["h1", "h2"], [], ["bitter1"], [], []

    monkeypatch.setattr("stress_map.load_assembly_config_from_duckdb", fake_load_assembly_config_from_duckdb)
    monkeypatch.setattr("stress_map.prepare_geometry_directory", fake_prepare_geometry_directory)
    monkeypatch.setattr("stress_map.load_magnettools", fake_load_magnettools)
    return geom_dir, calls


# ---------------------------------------------------------------------------
# build_label_rows
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("labels", [["H_0", "H_1", "B_0"], ["H1", "H2", "B1"]])
def test_build_label_rows_matches_parts_in_group_order(labels):
    rows = build_label_rows(labels, PART_MAP, PART_MAGNETS)
    assert rows == [
        {"label": labels[0], "magnet": "MAG_NEW", "part": "H_NEW"},
        {"label": labels[1], "magnet": "MAG_OLD", "part": "H_OLD"},
        {"label": labels[2], "magnet": "MAG_B", "part": "B_ONE"},
    ]


def test_build_label_rows_count_mismatch_warns_and_returns_none(capsys):
    assert build_label_rows(["H1", "B1"], PART_MAP, PART_MAGNETS) is None
    assert "group H: 1 matrix labels but 2 DB parts" in capsys.readouterr().out


def test_build_label_rows_adds_one_row_per_helix_pair():
    rows = build_label_rows(["H1", "H2", "B1"], PART_MAP, PART_MAGNETS, ["H1H2", "B1"])
    assert rows[-1] == {"label": "H1H2", "magnet": "MAG_NEW;MAG_OLD", "part": "H_NEW;H_OLD"}
    assert len(rows) == 4


# ---------------------------------------------------------------------------
# export_inductance_matrix
# ---------------------------------------------------------------------------


def test_export_writes_matrix_pairs_and_labels(assembly_db, fake_pipeline, monkeypatch, tmp_path):
    geom_dir, calls = fake_pipeline
    monkeypatch.setitem(sys.modules, "magnettools.inductances", _fake_inductances(with_pairs=True))
    out = tmp_path / "out" / "M9.csv"
    out.parent.mkdir()

    exported = export_inductance_matrix("HOOP_ASSEMBLY", assembly_db, out, pair_tubes=True, verbose=False)

    assert calls == ["load_assembly_config_from_duckdb", "prepare_geometry_directory", "load_magnettools"]
    assert not geom_dir.exists()
    names = [p.name for p in exported["files"]]
    assert names == ["M9.csv", "M9_summary.csv", "M9_pairs.csv", "M9_labels.csv"]
    assert all(p.exists() for p in exported["files"])

    pairs = pd.read_csv(out.parent / "M9_pairs.csv", index_col=0)
    assert list(pairs.index) == ["H1H2", "B1"]
    assert pairs.loc["H1H2", "H1H2"] == pytest.approx(2.0e-4 + 3.0e-4 + 2 * 5.0e-5)

    labels = pd.read_csv(out.parent / "M9_labels.csv")
    assert list(labels["label"]) == ["H_0", "H_1", "B_0", "H1H2"]
    assert list(labels["part"]) == ["H_NEW", "H_OLD", "B_ONE", "H_NEW;H_OLD"]


def test_export_without_pair_tubes_writes_no_pairs_file(assembly_db, fake_pipeline, monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "magnettools.inductances", _fake_inductances(with_pairs=False))
    exported = export_inductance_matrix("HOOP_ASSEMBLY", assembly_db, tmp_path / "M9.csv", verbose=False)
    assert exported["pairs"] is None
    assert not (tmp_path / "M9_pairs.csv").exists()
    assert (tmp_path / "M9_labels.csv").exists()


def test_pair_tubes_without_binding_raises_before_any_work(assembly_db, fake_pipeline, monkeypatch, tmp_path):
    _geom_dir, calls = fake_pipeline
    monkeypatch.setitem(sys.modules, "magnettools.inductances", _fake_inductances(with_pairs=False))
    with pytest.raises(ImportError, match="pair_tube_inductances"):
        export_inductance_matrix("HOOP_ASSEMBLY", assembly_db, tmp_path / "M9.csv", pair_tubes=True)
    assert calls == []
    assert not (tmp_path / "M9.csv").exists()


def test_main_pair_tubes_without_binding_exits_with_error(assembly_db, fake_pipeline, monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "magnettools.inductances", _fake_inductances(with_pairs=False))
    argv = ["--db", str(assembly_db), "--assembly", "HOOP_ASSEMBLY",
            "--csv", str(tmp_path / "M9.csv"), "--pair-tubes", "--quiet"]
    with pytest.raises(SystemExit, match="error: .*pair_tube_inductances"):
        main(argv)


# ---------------------------------------------------------------------------
# Real magnettools (dev container only)
# ---------------------------------------------------------------------------

REAL_DB = Path(__file__).resolve().parents[1] / "test-magnetdb.duckdb"


def _has_magnettools() -> bool:
    try:
        return importlib.util.find_spec("magnettools.inductances") is not None
    except ModuleNotFoundError:
        return False


@pytest.mark.skipif(not _has_magnettools(), reason="magnettools not installed")
@pytest.mark.skipif(not REAL_DB.exists(), reason=f"{REAL_DB.name} not found")
def test_export_real_assembly(tmp_path):
    inductances = importlib.import_module("magnettools.inductances")
    pair_tubes = hasattr(inductances, "pair_tube_inductances")
    out = tmp_path / "M9.csv"

    exported = export_inductance_matrix("M9_A230801_00", REAL_DB, out, pair_tubes=pair_tubes, verbose=False)

    matrix = pd.read_csv(out, index_col=0)
    labels = list(matrix.index)
    assert labels == list(matrix.columns)
    prefixes = [label.rstrip("0123456789_")[:1] for label in labels]
    assert prefixes == sorted(prefixes, key="HBS".index)
    values = matrix.to_numpy()
    assert np.allclose(values, values.T)
    assert (np.diag(values) > 0).all()
    assert exported["labels"] is not None

    if pair_tubes:
        pairs = pd.read_csv(tmp_path / "M9_pairs.csv", index_col=0)
        n_pairs = sum(1 for label in pairs.index if label.count("H") == 2)
        l_h = exported["result"]["L_H"]
        assert pairs.iloc[:n_pairs, :n_pairs].to_numpy().sum() == pytest.approx(l_h, rel=1e-5)
