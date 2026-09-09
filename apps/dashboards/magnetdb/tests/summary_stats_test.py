import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import magnetdb_analysis as db

DB_PATH = str(Path(__file__).resolve().parents[4] / "to_duckdb" / "test-magnetdb.duckdb")


def test_get_status_counts_assemblies_db_wide():
    assert db.get_status_counts("assemblies", DB_PATH) == {
        "in_operation": 2,
        "disassembled": 47,
    }


def test_get_status_counts_restricts_to_names():
    assert db.get_status_counts(
        "assemblies", DB_PATH, names=["M10_A180220_00"]
    ) == {"disassembled": 1}


def test_get_status_counts_empty_names_returns_empty_dict():
    assert db.get_status_counts("assemblies", DB_PATH, names=[]) == {}


def test_get_distinct_statuses_assemblies():
    assert db.get_distinct_statuses("assemblies") == [
        "in_operation",
        "disassembled",
        "in_study",
    ]


def test_get_distinct_statuses_magnets():
    assert db.get_distinct_statuses("magnets") == [
        "in_operation",
        "in_stock",
        "retired",
        "dead",
        "in_study",
    ]


def test_get_distinct_statuses_parts():
    assert db.get_distinct_statuses("parts") == [
        "in_operation",
        "in_stock",
        "retired",
        "dead",
        "in_study",
    ]


def test_get_housing_file_summary_unfiltered_covers_all_housings():
    summary_df = db.get_housing_file_summary(DB_PATH)
    assert set(summary_df["housing"]) == {"M9", "M10"}
    assert summary_df["n_experiments"].sum() == 5419


def test_get_housing_file_summary_assembly_names_restricts_counts():
    summary_df = db.get_housing_file_summary(
        DB_PATH, assembly_names=["M9_A181109_00"]
    )
    by_housing = summary_df.set_index("housing")
    assert by_housing.loc["M9", "n_experiments"] == 103
    assert by_housing.loc["M10", "n_experiments"] == 0
