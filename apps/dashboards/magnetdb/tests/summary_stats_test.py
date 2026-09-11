import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import magnetdb_analysis as db
import magnetdb_plot as plot

DB_PATH = str(Path(__file__).resolve().parents[4] / "to_duckdb" / "test-magnetdb.duckdb")

_PUPITRE_FILE = "2025.12.02 - 14:30:46.txt"
_TDMS_FILE = "M9_Overview_251202-1430.tdms"
_HOUSING = "M9"


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


def test_get_field_column_stats_returns_values_array_for_histogram(monkeypatch):
    monkeypatch.chdir(Path(__file__).resolve().parent)
    mrun = db.load_mrun_object(_PUPITRE_FILE, _HOUSING)
    stats = db.get_field_column_stats([mrun])
    assert stats["column"] == "Field"
    assert len(stats["values"]) > 0
    assert stats["values"].min() == stats["min"]
    assert stats["values"].max() == stats["max"]


def test_get_field_column_stats_overview_only_uses_champ_magn(monkeypatch):
    """No sources_pupitre for a record: overview_records.py already falls back
    to sources_overview alone (see _record_sources) — Field must resolve via
    the TDMS Courants_Alimentations/Champ_magn key in that case."""
    monkeypatch.chdir(Path(__file__).resolve().parent)
    mrun = db.load_mrun_object(_TDMS_FILE, _HOUSING)
    stats = db.get_field_column_stats([mrun])
    assert stats["column"] == "Champ_magn"
    assert stats["unit"] == "tesla"
    assert len(stats["values"]) > 0


def test_get_field_column_stats_time_range_narrows_sample_count(monkeypatch):
    monkeypatch.chdir(Path(__file__).resolve().parent)
    mrun = db.load_mrun_object(_TDMS_FILE, _HOUSING)
    full = db.get_field_column_stats([mrun])
    df = mrun.MagnetData.get_group_data("Courants_Alimentations")
    t_min, t_max = float(df["t"].min()), float(df["t"].max())
    half = t_min + (t_max - t_min) / 2
    zoomed = db.get_field_column_stats([mrun], x_range=[t_min, half], x_col="t")
    assert len(zoomed["values"]) < len(full["values"])


def test_get_energy_stats_pupitre_and_tdms(monkeypatch):
    monkeypatch.chdir(Path(__file__).resolve().parent)
    pupitre = db.load_mrun_object(_PUPITRE_FILE, _HOUSING)
    tdms = db.load_mrun_object(_TDMS_FILE, _HOUSING)
    assert db.get_energy_stats([pupitre])["n_included"] == 1
    assert db.get_energy_stats([tdms])["n_included"] == 1
    assert db.get_energy_stats([tdms])["energy_mwh"] > 0


def test_get_energy_stats_time_range_reduces_total(monkeypatch):
    monkeypatch.chdir(Path(__file__).resolve().parent)
    mrun = db.load_mrun_object(_TDMS_FILE, _HOUSING)
    full = db.get_energy_stats([mrun])
    df = mrun.MagnetData.get_group_data("Courants_Alimentations")
    t_min, t_max = float(df["t"].min()), float(df["t"].max())
    half = t_min + (t_max - t_min) / 2
    zoomed = db.get_energy_stats([mrun], x_range=[t_min, half], x_col="t")
    assert zoomed["energy_mwh"] <= full["energy_mwh"]


def test_field_histogram_figure_has_one_histogram_trace(monkeypatch):
    monkeypatch.chdir(Path(__file__).resolve().parent)
    mrun = db.load_mrun_object(_PUPITRE_FILE, _HOUSING)
    stats = db.get_field_column_stats([mrun])
    fig = plot.field_histogram_figure(stats)
    assert len(fig.data) == 1
    assert fig.data[0].type == "histogram"
    assert len(fig.data[0].x) == len(stats["values"])


def test_field_histogram_figure_empty_when_no_stats():
    fig = plot.field_histogram_figure(None)
    assert len(fig.data) == 0
