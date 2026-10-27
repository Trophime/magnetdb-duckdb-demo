"""
Tests for demos/report_experiments_linking.py.
"""

from datetime import datetime

import pytest

from crud import insert_assembly
from demos.report_experiments_linking import report_clock_drift, report_unlinked_experiments
from tests.conftest import ASSEMBLY_DATA

FROM_TS = datetime(2018, 1, 1)


@pytest.fixture
def con_report(con):
    """One M10 session A (10:00-11:00) linked to file 1, plus files 2 and 3 left unlinked.

    File 2 starts 50 min before session B's hstart (looks like clock drift);
    file 3 starts 3 min after session A's hstop.
    """
    insert_assembly(con, {**ASSEMBLY_DATA, "name": "M10_A250101_00"}, verbose=False)
    files = [
        "2025.01.01 - 10:02:00.txt",
        "2025.01.02 - 09:10:00.txt",
        "2025.01.01 - 11:03:00.txt",
    ]
    for i, file in enumerate(files, start=1):
        con.execute(
            "INSERT INTO experiments (id, name, file, assembly_name) VALUES (?, ?, ?, ?)",
            [i, file, file, "M10_A250101_00"],
        )
    con.execute(
        "INSERT INTO users (acronym, housing, hstart, hstop, experiments_ids) VALUES "
        "('A', 'M10', '2025-01-01 10:00:00', '2025-01-01 11:00:00', [1]), "
        "('B', 'M10', '2025-01-02 10:00:00', '2025-01-02 12:00:00', NULL)"
    )
    return con


def test_unlinked_experiments_lists_nearest_session(con_report):
    df = report_unlinked_experiments(con_report, FROM_TS, show_rows=False)
    rows = {r.file: (r.nearest_acronym, r.nearest_distance_min) for r in df.itertuples()}
    assert rows == {
        "2025.01.02 - 09:10:00.txt": ("B", -50.0),
        "2025.01.01 - 11:03:00.txt": ("A", 3.0),
    }


def test_unlinked_experiments_respects_housing_filter(con_report):
    df = report_unlinked_experiments(con_report, FROM_TS, {"M9"}, show_rows=False)
    assert df.empty


def test_clock_drift_flags_file_starting_before_hstart(con_report):
    df = report_clock_drift(con_report, FROM_TS, threshold=5.0, show_rows=False)
    assert list(df["acronym"]) == ["B"]
    assert df["offset_min"].iloc[0] == -50.0
