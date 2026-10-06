import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import magnetdb_analysis as db  # noqa: E402


@pytest.fixture
def supra_db(tmp_path):
    """A minimal DuckDB file with one supra assembly and one plain assembly."""
    db_path = tmp_path / "supra_test.duckdb"
    con = duckdb.connect(str(db_path))
    con.execute("""
        CREATE TABLE assembly_magnets (assembly_name VARCHAR, magnet_name VARCHAR)
    """)
    con.execute("""
        CREATE TABLE magnet_parts (magnet_name VARCHAR, part_name VARCHAR)
    """)
    con.execute("CREATE TABLE parts (name VARCHAR, type VARCHAR)")
    con.execute("""
        CREATE TABLE overview_records (
            filename VARCHAR, housing VARCHAR, sources_pupitre VARCHAR[],
            sources_hybrid_kHz VARCHAR[]
        )
    """)
    con.execute("INSERT INTO parts VALUES ('Supra1', 'supra'), ('Bitter1', 'bitter')")
    con.execute("INSERT INTO magnet_parts VALUES ('M8Hybrid', 'Supra1'), ('M8Bitter', 'Bitter1')")
    con.execute(
        "INSERT INTO assembly_magnets VALUES "
        "('M8_2024.0.1', 'M8Hybrid'), ('M8_2024.0.2', 'M8Bitter')"
    )
    con.execute(
        "INSERT INTO overview_records VALUES "
        "('M8_2024-03-15T10-00-00', 'M8', ['2024.03.15 - 10:00:00.txt'], "
        "['/data/hybrid/kHz/2024-03-15/FEPC-LNCMI/09HOST_1_LIST_0.bin'])"
    )
    con.close()
    return str(db_path)


def test_assembly_has_supra_true_for_supra_assembly(supra_db):
    assert db.assembly_has_supra("M8_2024.0.1", db_path=supra_db) is True


def test_assembly_has_supra_false_for_non_supra_assembly(supra_db):
    assert db.assembly_has_supra("M8_2024.0.2", db_path=supra_db) is False


def test_get_hybrid_khz_source_matches_linked_pupitre_file(supra_db):
    source = db.get_hybrid_khz_source(
        "M8", "2024.03.15 - 10:00:00.txt", db_path=supra_db
    )
    assert source == "/data/hybrid/kHz/2024-03-15/FEPC-LNCMI/09HOST_1_LIST_0.bin"


def test_get_hybrid_khz_source_returns_none_when_unlinked(supra_db):
    assert db.get_hybrid_khz_source("M8", "no-such-file.txt", db_path=supra_db) is None


class _FakeHybridData:
    pass


class _FakeHybridRun:
    """Stands in for HybridRun: 1000 Hz sawtooth current over one hour."""

    def __init__(self, *, data, elapsed):
        self._data = data
        self._elapsed = elapsed

    def getData(self, key, hours=None):
        assert key == "kHz/FEPC-LNCMI/I_BOB"
        return self._data, self._elapsed


def test_load_hybrid_supra_current_downsamples_to_1hz(monkeypatch):
    """1000 Hz synthetic I_BOB, anchored at 10:00:00 UTC, must resample to
    one row per second with values close to each second's mean."""
    n_seconds = 5
    fs = 1000.0
    elapsed = np.arange(0, n_seconds * fs) / fs
    data = 10.0 + 0.01 * np.sin(2 * np.pi * 50 * elapsed)  # ~10 A + 50 Hz ripple

    fake_run = _FakeHybridRun(data=data, elapsed=elapsed)
    monkeypatch.setattr(
        db.HybridRun, "fromdir", staticmethod(lambda **kwargs: fake_run)
    )
    # Bypass the lru_cache from a prior call with the same args in this process.
    db.load_hybrid_supra_current.cache_clear()

    start = pd.Timestamp("2024-03-15 10:00:00")
    end = pd.Timestamp("2024-03-15 10:00:04")
    result = db.load_hybrid_supra_current(
        "kHz/2024-03-15/FEPC-LNCMI/09HOST_1_LIST_0.bin", "M8", "M8_2024.0.1", start, end
    )

    assert list(result.columns) == ["timestamp", "I_BOB"]
    assert len(result) == n_seconds
    assert result["timestamp"].iloc[0] == start
    np.testing.assert_allclose(result["I_BOB"], 10.0, atol=0.01)


def test_load_hybrid_supra_current_matches_pupitre_grid_via_merge_asof(monkeypatch):
    """The alignment step used in update_outputs (merge_asof onto the
    Pupitre file's own timestamps) must preserve Pupitre's exact grid,
    including an irregular/duplicate timestamp, and mark true gaps as NaN."""
    fs = 1000.0
    elapsed = np.arange(0, 3 * fs) / fs
    data = np.full_like(elapsed, 42.0)

    fake_run = _FakeHybridRun(data=data, elapsed=elapsed)
    monkeypatch.setattr(
        db.HybridRun, "fromdir", staticmethod(lambda **kwargs: fake_run)
    )
    db.load_hybrid_supra_current.cache_clear()

    start = pd.Timestamp("2024-03-15 10:00:00")
    end = pd.Timestamp("2024-03-15 10:00:02")
    hourly = db.load_hybrid_supra_current(
        "kHz/2024-03-15/FEPC-LNCMI/09HOST_1_LIST_0.bin", "M8", "M8_2024.0.1", start, end
    )

    # Pupitre grid: a duplicate timestamp and a 5s gap with no Hybrid coverage.
    pupitre_timestamps = pd.to_datetime(
        [
            "2024-03-15 10:00:00",
            "2024-03-15 10:00:00",
            "2024-03-15 10:00:01",
            "2024-03-15 10:00:10",
        ]
    )
    pupitre_df = pd.DataFrame({"t": [0, 0, 1, 10], "timestamp": pupitre_timestamps})

    aligned = pd.merge_asof(
        pupitre_df[["t", "timestamp"]],
        hourly.rename(columns={"I_BOB": "hybrid:I_BOB"}),
        on="timestamp",
        direction="nearest",
        tolerance=pd.Timedelta("0.5s"),
    )

    assert len(aligned) == len(pupitre_df)
    assert list(aligned["timestamp"]) == list(pupitre_df["timestamp"])
    assert aligned["hybrid:I_BOB"].iloc[:3].tolist() == [42.0, 42.0, 42.0]
    assert pd.isna(aligned["hybrid:I_BOB"].iloc[3])
