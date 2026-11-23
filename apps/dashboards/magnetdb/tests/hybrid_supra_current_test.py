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


@pytest.fixture
def hybrid_sources_db(tmp_path):
    """overview_records with the four hybrid source lists (one row with NULLs)."""
    db_path = tmp_path / "hybrid_sources.duckdb"
    con = duckdb.connect(str(db_path))
    con.execute("""
        CREATE TABLE overview_records (
            filename VARCHAR, housing VARCHAR, sources_pupitre VARCHAR[],
            sources_hybrid_kHz VARCHAR[], sources_hybrid_rms VARCHAR[],
            sources_hybrid_trigger VARCHAR[], sources_hybrid_vprocess VARCHAR[]
        )
    """)
    con.execute("""
        INSERT INTO overview_records VALUES
        ('M8_Overview_260415-1348', 'M8', ['a.txt', 'b.txt'],
         ['k1.bin', 'k2.bin'], ['r1.rms'], [], ['v1.vprocess']),
        ('M8_Overview_261113-0813', 'M8', ['c.txt'], NULL, NULL, NULL, NULL)
    """)
    con.close()
    return str(db_path)


def test_get_hybrid_sources_for_pupitre_returns_the_four_lists(hybrid_sources_db):
    sources = db.get_hybrid_sources_for_pupitre("M8", "b.txt", db_path=hybrid_sources_db)
    assert sources == {
        "kHz": ["k1.bin", "k2.bin"],
        "RMS": ["r1.rms"],
        "trigger": [],
        "vprocess": ["v1.vprocess"],
    }


def test_get_hybrid_sources_for_pupitre_null_lists_are_empty(hybrid_sources_db):
    sources = db.get_hybrid_sources_for_pupitre("M8", "c.txt", db_path=hybrid_sources_db)
    assert sources == {"kHz": [], "RMS": [], "trigger": [], "vprocess": []}


def test_get_hybrid_sources_for_pupitre_none_without_record(hybrid_sources_db):
    assert db.get_hybrid_sources_for_pupitre("M8", "z.txt", db_path=hybrid_sources_db) is None


@pytest.fixture
def signal_stats_db(tmp_path):
    """overview_records listing pigbrother Stats files (one merged row)."""
    db_path = tmp_path / "signal_stats.duckdb"
    con = duckdb.connect(str(db_path))
    con.execute("""
        CREATE TABLE overview_records (
            filename VARCHAR, assembly_name VARCHAR, t0 TIMESTAMP,
            sources_signal_stats VARCHAR[], merged_into VARCHAR
        )
    """)
    con.execute("""
        INSERT INTO overview_records VALUES
        ('rec_b', 'M8_A1', '2026-11-13 12:00', ['s1.tdms', 's2.tdms'], NULL),
        ('rec_a', 'M8_A1', '2026-11-13 08:00', ['s1.tdms'], NULL),
        ('rec_merged', 'M8_A1', '2026-11-13 09:00', ['s1.tdms'], 'rec_a'),
        ('rec_other', 'M9_A1', '2026-11-13 08:00', ['s1.tdms'], NULL)
    """)
    con.close()
    return str(db_path)


def test_get_overview_records_for_signal_stats(signal_stats_db):
    assert db.get_overview_records_for_signal_stats(
        "M8_A1", "s1.tdms", db_path=signal_stats_db
    ) == ["rec_a", "rec_b"]
    assert db.get_overview_records_for_signal_stats(
        "M8_A1", "s2.tdms", db_path=signal_stats_db
    ) == ["rec_b"]
    assert db.get_overview_records_for_signal_stats(
        "M8_A1", "none.tdms", db_path=signal_stats_db
    ) == []


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


def test_load_hybrid_supra_current_takes_date_from_start(monkeypatch):
    """overview_records stores kHz basenames (no date): the day comes from `start` (UTC)."""
    fs = 1000.0
    elapsed = np.arange(0, 2 * fs) / fs
    fake_run = _FakeHybridRun(data=np.full_like(elapsed, 5.0), elapsed=elapsed)
    calls = []

    def fake_fromdir(**kwargs):
        calls.append(kwargs)
        return fake_run

    monkeypatch.setattr(db.HybridRun, "fromdir", staticmethod(fake_fromdir))
    db.load_hybrid_supra_current.cache_clear()

    result = db.load_hybrid_supra_current(
        "13HOST_1_LIST_0.bin", "M8", "M8_A230913_00",
        pd.Timestamp("2026-03-05 13:42:13"), pd.Timestamp("2026-03-05 13:42:14"),
    )

    assert [c["date_str"] for c in calls] == ["2026-03-05"]
    assert len(result) == 2


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

    aligned = db.align_hybrid_to_pupitre(pupitre_df, hourly)

    assert len(aligned) == len(pupitre_df)
    assert list(aligned["timestamp"]) == list(pupitre_df["timestamp"])
    assert aligned["hybrid:I_BOB"].iloc[:3].tolist() == [42.0, 42.0, 42.0]
    assert pd.isna(aligned["hybrid:I_BOB"].iloc[3])


def test_align_hybrid_to_pupitre_accepts_microsecond_pupitre_timestamps():
    """Pupitre timestamps can be datetime64[us] while Hybrid ones are
    datetime64[ns]; the alignment must not raise a MergeError."""
    pupitre_df = pd.DataFrame({
        "t": [0, 1],
        "timestamp": pd.to_datetime(["2026-11-13 07:12:02", "2026-11-13 07:12:03"]).astype("datetime64[us]"),
    })
    hourly = pd.DataFrame({
        "timestamp": pd.to_datetime(["2026-11-13 07:12:02", "2026-11-13 07:12:03"]).astype("datetime64[ns]"),
        "I_BOB": [7180.0, 7181.0],
    })

    aligned = db.align_hybrid_to_pupitre(pupitre_df, hourly)

    assert aligned["timestamp"].dtype == pupitre_df["timestamp"].dtype
    assert aligned["hybrid:I_BOB"].tolist() == [7180.0, 7181.0]
