"""Unit tests for populate.py's operationaldata path handling."""

from datetime import datetime
from pathlib import Path

import pytest

from populate import (
    _TDMS_SUBDIR_NAMES,
    FILE_TZ,
    TDMS_TYPES,
    _insert_operationaldata,
    parse_tdms_file_ts,
    resolve_operationaldata_path,
    scan_tdms_subdir,
)


# ---------------------------------------------------------------------------
# SignalStats / Trigger file types
# ---------------------------------------------------------------------------


def test_signal_stats_and_trigger_are_tdms_types():
    assert "SignalStats" in TDMS_TYPES
    assert "Trigger" in TDMS_TYPES
    assert _TDMS_SUBDIR_NAMES["SignalStats"] == "Fichiers_stats"
    assert _TDMS_SUBDIR_NAMES["Trigger"] == "Fichiers_Manuel_Trig"


@pytest.mark.parametrize("filename,file_type,expected", [
    ("M8_Stats_260226-094838.tdms", "SignalStats", datetime(2026, 2, 26, 9, 48, 38)),
    # legacy name: stray extra underscore, minute precision
    ("M9_Stats__190304-1459.tdms", "SignalStats", datetime(2019, 3, 4, 14, 59)),
    ("M10_ManuelTrig_240718-130540.tdms", "Trigger", datetime(2024, 7, 18, 13, 5, 40)),
    # existing types are unchanged
    ("M9_Overview_261006-0948.tdms", "Overview", datetime(2026, 10, 6, 9, 48)),
    ("M9_Spikes_261006-095523.tdms", "Spike", datetime(2026, 10, 6, 9, 55, 23)),
])
def test_parse_tdms_file_ts(filename, file_type, expected):
    assert parse_tdms_file_ts(filename, file_type) == expected.replace(tzinfo=FILE_TZ)


@pytest.mark.parametrize("filename,file_type", [
    ("M8_Overview_260226-0948.tdms", "SignalStats"),
    ("M8_Stats_260226-094838.tdms", "Trigger"),
])
def test_parse_tdms_file_ts_rejects_other_types(filename, file_type):
    assert parse_tdms_file_ts(filename, file_type) is None


def test_scan_tdms_subdir_finds_signal_stats(tmp_path):
    for name in ("M8_Stats_260226-094838.tdms", "M9_Stats__190304-1459.tdms", "notes.txt"):
        (tmp_path / name).touch()
    found = scan_tdms_subdir(tmp_path, "SignalStats", None, None)
    assert [(p.name, kind) for p, _, kind in found] == [
        ("M8_Stats_260226-094838.tdms", "SignalStats"),
        ("M9_Stats__190304-1459.tdms", "SignalStats"),
    ]


# ---------------------------------------------------------------------------
# resolve_operationaldata_path
# ---------------------------------------------------------------------------


def test_resolve_operationaldata_path_joins_records_base():
    path = resolve_operationaldata_path(
        "pbsurv/M10/Overview/250101-0000.tdms", records_base=Path("/records"),
    )
    assert path == Path("/records/pbsurv/M10/Overview/250101-0000.tdms")


def test_resolve_operationaldata_path_passes_through_absolute_legacy_value():
    legacy = "/mnt/LNCMIG-Data/records/pbsurv/M10/Overview/250101-0000.tdms"
    path = resolve_operationaldata_path(legacy, records_base=Path("/records"))
    assert path == Path(legacy)


# ---------------------------------------------------------------------------
# _insert_operationaldata
# ---------------------------------------------------------------------------


def test_insert_operationaldata_strips_records_base(con_populated):
    records_base = Path("/mnt/LNCMIG-Data/records")
    fpath = records_base / "pbsurv" / "M10" / "Overview" / "250101-0000.tdms"
    inserted = _insert_operationaldata(con_populated, "ASSEMBLY_01", fpath, "Overview", records_base)
    assert inserted
    row = con_populated.execute(
        "SELECT file FROM operationaldata WHERE assembly_name = 'ASSEMBLY_01'"
    ).fetchone()
    assert row[0] == "pbsurv/M10/Overview/250101-0000.tdms"


def test_insert_operationaldata_dedup(con_populated):
    records_base = Path("/mnt/LNCMIG-Data/records")
    fpath = records_base / "pbsurv" / "M10" / "Overview" / "250101-0000.tdms"
    assert _insert_operationaldata(con_populated, "ASSEMBLY_01", fpath, "Overview", records_base)
    assert not _insert_operationaldata(con_populated, "ASSEMBLY_01", fpath, "Overview", records_base)


# ---------------------------------------------------------------------------
# fill_operationaldata_metadata
# ---------------------------------------------------------------------------

RECORDS = Path("/records")


def _add_files(con, *files):
    """Register (relative path, type) pairs for ASSEMBLY_01 (housing M10)."""
    for rel, file_type in files:
        _insert_operationaldata(con, "ASSEMBLY_01", RECORDS / rel, file_type, RECORDS)


def _fake_extract_data(ranges):
    """extract_data stand-in returning *ranges[basename]* (local Paris times)."""
    calls = []

    def fake(file, housing, assembly="", key=None, dry_run=False):
        calls.append((Path(file).name, housing, key, dry_run))
        start, end = ranges[Path(file).name]
        return start, end, False

    return fake, calls


class _FakeMData:
    def __init__(self, df):
        self.Data = {"Courants_Alimentations": df}


@pytest.fixture
def ramp_overview(monkeypatch):
    """load_magnetdata returns an overview whose GR1 follows GR2 (NORMAL mode)."""
    import pandas as pd

    ib = [float(i) for i in range(0, 2000, 20)]
    df = pd.DataFrame({"Courant_GR1": ib, "Courant_GR2": ib})
    loaded = []

    def fake_load(path):
        loaded.append(Path(path).name)
        return _FakeMData(df)

    monkeypatch.setattr("python_magnetrun.magnetdata.load_magnetdata", fake_load)
    return loaded


def _metadata(con):
    return {
        Path(f).name: (s, e, m)
        for f, s, e, m in con.execute(
            "SELECT file, t_start, t_end, mode FROM operationaldata ORDER BY id"
        ).fetchall()
    }


def test_fill_operationaldata_metadata_stores_utc_times_and_overview_mode(
    con_populated, monkeypatch, ramp_overview
):
    from populate import fill_operationaldata_metadata

    _add_files(
        con_populated,
        ("pbsurv/M10/Overview/M10_Overview_250115-1200.tdms", "Overview"),
        ("srv-data-install/M10/2025.01.15 - 12:00:05.txt", "Pupitre"),
    )
    fake, calls = _fake_extract_data({
        "M10_Overview_250115-1200.tdms": ("2025-01-15 12:00:00", "2025-01-15 13:00:00"),
        "2025.01.15 - 12:00:05.txt": ("2025-01-15 12:00:05", "2025-01-15 12:59:00"),
    })
    monkeypatch.setattr("python_magnetrun.utils.files.extract_data", fake)

    counts = fill_operationaldata_metadata(
        con_populated, "ASSEMBLY_01", records_base=RECORDS, verbose=False
    )

    assert counts["filled"] == 2
    # metadata-only path: no key, no dry run; housing from the assembly
    assert all(c[1:] == ("M10", None, False) for c in calls)
    meta = _metadata(con_populated)
    # January: Europe/Paris = UTC+1
    assert meta["M10_Overview_250115-1200.tdms"] == (
        datetime(2025, 1, 15, 11, 0), datetime(2025, 1, 15, 12, 0), "NORMAL"
    )
    assert meta["2025.01.15 - 12:00:05.txt"] == (
        datetime(2025, 1, 15, 11, 0, 5), datetime(2025, 1, 15, 11, 59), None
    )
    assert ramp_overview == ["M10_Overview_250115-1200.tdms"]  # only Overview files loaded


def test_fill_operationaldata_metadata_skips_filled_rows_unless_reprocess(
    con_populated, monkeypatch, ramp_overview
):
    from populate import fill_operationaldata_metadata

    _add_files(con_populated, ("srv-data-install/M10/2025.01.15 - 12:00:05.txt", "Pupitre"))
    fake, calls = _fake_extract_data(
        {"2025.01.15 - 12:00:05.txt": ("2025-01-15 12:00:05", "2025-01-15 12:59:00")}
    )
    monkeypatch.setattr("python_magnetrun.utils.files.extract_data", fake)

    fill_operationaldata_metadata(con_populated, "ASSEMBLY_01", records_base=RECORDS, verbose=False)
    fill_operationaldata_metadata(con_populated, "ASSEMBLY_01", records_base=RECORDS, verbose=False)
    assert len(calls) == 1
    fill_operationaldata_metadata(
        con_populated, "ASSEMBLY_01", records_base=RECORDS, reprocess=True, verbose=False
    )
    assert len(calls) == 2


def test_fill_operationaldata_metadata_type_filter_and_dry_run(
    con_populated, monkeypatch, ramp_overview
):
    from populate import fill_operationaldata_metadata

    _add_files(
        con_populated,
        ("pbsurv/M10/Fichiers_stats/M10_Stats_250115-120005.tdms", "SignalStats"),
        ("pbsurv/M10/Fichiers_Spike/M10_Spikes_250115-120500.tdms", "Spike"),
    )
    fake, calls = _fake_extract_data({
        "M10_Stats_250115-120005.tdms": ("2025-01-15 12:00:05", "2025-01-15 13:00:00"),
        "M10_Spikes_250115-120500.tdms": ("2025-01-15 12:05:00", "2025-01-15 12:05:01"),
    })
    monkeypatch.setattr("python_magnetrun.utils.files.extract_data", fake)

    counts = fill_operationaldata_metadata(
        con_populated, "ASSEMBLY_01", types=["SignalStats"], records_base=RECORDS,
        dry_run=True, verbose=False,
    )
    assert counts["filled"] == 1
    assert [c[0] for c in calls] == ["M10_Stats_250115-120005.tdms"]
    assert all(v == (None, None, None) for v in _metadata(con_populated).values())


def test_fill_operationaldata_metadata_leaves_unreadable_rows_empty(
    con_populated, monkeypatch, ramp_overview
):
    from populate import fill_operationaldata_metadata

    _add_files(con_populated, ("pbsurv/M10/Fichiers_stats/M10_Stats_250115-120005.tdms", "SignalStats"))
    monkeypatch.setattr(
        "python_magnetrun.utils.files.extract_data",
        lambda file, housing, assembly="", key=None, dry_run=False: ("2025-01-15 12:00:05", "", False),
    )
    counts = fill_operationaldata_metadata(
        con_populated, "ASSEMBLY_01", records_base=RECORDS, verbose=False
    )
    assert counts["filled"] == 0
    assert counts["no_time_range"] == 1
    assert _metadata(con_populated)["M10_Stats_250115-120005.tdms"] == (None, None, None)


def test_fill_operationaldata_metadata_incident_files_from_name_only(
    con_populated, monkeypatch, ramp_overview
):
    """Spike/Default/Trigger files are not read: t_start = t_end = the time in their name."""
    from populate import fill_operationaldata_metadata

    _add_files(
        con_populated,
        ("pbsurv/M10/Fichiers_Spike/M10_Spikes_250115-120500.tdms", "Spike"),
        ("pbsurv/M10/Fichiers_Default/M10_Default_250115-120600_DefautNums.tdms", "Default"),
        ("pbsurv/M10/Fichiers_Manuel_Trig/M10_ManuelTrig_250115-120700.tdms", "Trigger"),
    )
    fake, calls = _fake_extract_data({})
    monkeypatch.setattr("python_magnetrun.utils.files.extract_data", fake)

    counts = fill_operationaldata_metadata(
        con_populated, "ASSEMBLY_01", records_base=RECORDS, verbose=False
    )

    assert counts["filled"] == 3
    assert calls == []
    meta = _metadata(con_populated)
    # January: Europe/Paris = UTC+1
    assert meta["M10_Spikes_250115-120500.tdms"] == (
        datetime(2025, 1, 15, 11, 5), datetime(2025, 1, 15, 11, 5), None
    )
    assert meta["M10_Default_250115-120600_DefautNums.tdms"] == (
        datetime(2025, 1, 15, 11, 6), datetime(2025, 1, 15, 11, 6), None
    )
    assert meta["M10_ManuelTrig_250115-120700.tdms"] == (
        datetime(2025, 1, 15, 11, 7), datetime(2025, 1, 15, 11, 7), None
    )
