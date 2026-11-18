import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import magnetdb_analysis


def test_available_databases_newest_first(tmp_path):
    names = [
        "magnetdb.duckdb",
        "magnetdb-2026-10-08.duckdb",
        "test-magnetdb.duckdb",
        "magnetdb-2026-11-10.mode17.duckdb",
        "magnetdb-2026-11-16.duckdb",
        "magnetdb-2026-11-10.duckdb",
        "notes.txt",
    ]
    for name in names:
        (tmp_path / name).touch()

    options = magnetdb_analysis.get_available_databases(str(tmp_path))

    assert [o["label"] for o in options] == [
        "magnetdb-2026-11-16.duckdb",
        "magnetdb-2026-11-10.duckdb",
        "magnetdb-2026-11-10.mode17.duckdb",
        "magnetdb-2026-10-08.duckdb",
        "magnetdb.duckdb",
        "test-magnetdb.duckdb",
    ]
    assert options[0]["value"] == str(tmp_path / "magnetdb-2026-11-16.duckdb")


def test_available_databases_missing_dir(tmp_path):
    assert magnetdb_analysis.get_available_databases(str(tmp_path / "absent")) == []
