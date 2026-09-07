import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import magnetdb_analysis as db
import magnetdb_plot as plot

_FILES = ["2025.12.02 - 14:30:46.txt", "M9_Overview_251202-1430.tdms"]
_HOUSING = "M9"


def test_matched_entry_records_pigbrothers_own_native_group(monkeypatch):
    """The pigbrother side of a cross-format match must not be assumed to
    live in the pupitre block's group ("Magnetic_Field" != "Courants_Alimentations"
    for Field/Champ_magn — see PLAN discussion)."""
    monkeypatch.chdir(Path(__file__).resolve().parent)
    group_entries = db.get_overview_group_entries(_FILES, _HOUSING)
    entry = next(
        e
        for e in group_entries["Magnetic_Field"]
        if e["channels"].get("pupitre", {}).get("channel") == "Field"
    )
    assert entry["channels"]["pupitre"] == {"group": "Magnetic_Field", "channel": "Field"}
    assert entry["channels"]["pigbrother"] == {
        "group": "Courants_Alimentations",
        "channel": "Champ_magn",
    }


def test_collect_group_files_data_includes_both_formats(monkeypatch):
    """Regression test: checking the Field/Champ_magn entry in the
    "Magnetic_Field" block must pull data from BOTH the pupitre file (Field)
    and the pigbrother overview file (Champ_magn, native group
    Courants_Alimentations), not just the pupitre one."""
    monkeypatch.chdir(Path(__file__).resolve().parent)
    group_entries = db.get_overview_group_entries(_FILES, _HOUSING)
    group_name = "Magnetic_Field"
    value = next(
        e["value"]
        for e in group_entries[group_name]
        if e["channels"].get("pupitre", {}).get("channel") == "Field"
    )

    mruns = {f: db.load_mrun_object(f, _HOUSING) for f in _FILES}
    files_data = db.collect_group_files_data(
        mruns, _HOUSING, group_name, [value], group_entries
    )

    all_sensors = {s for fd in files_data for s in fd["sensors"]}
    assert all_sensors == {"Field", "Champ_magn"}
    assert len(files_data) == 2

    native_group_by_sensor = {
        fd["sensors"][0]: fd["native_group"] for fd in files_data
    }
    assert native_group_by_sensor == {
        "Field": "Magnetic_Field",
        "Champ_magn": "Courants_Alimentations",
    }


def test_create_annotated_plot_converts_champ_magn_to_tesla(monkeypatch):
    """Regression test for the "0 to 30000 T" bug: create_annotated_plot must
    resolve Champ_magn's unit against its own native tdms group
    (Courants_Alimentations), not the "Magnetic_Field" display block name --
    otherwise resolve_sensor_unit silently fails, Champ_magn's raw
    millitesla-scale values pass through unconverted, and the plot ends up
    with an axis labeled "T" holding values ~1000x too large."""
    monkeypatch.chdir(Path(__file__).resolve().parent)
    group_entries = db.get_overview_group_entries(_FILES, _HOUSING)
    group_name = "Magnetic_Field"
    value = next(
        e["value"]
        for e in group_entries[group_name]
        if e["channels"].get("pupitre", {}).get("channel") == "Field"
    )

    mruns = {f: db.load_mrun_object(f, _HOUSING) for f in _FILES}
    files_data = db.collect_group_files_data(
        mruns, _HOUSING, group_name, [value], group_entries
    )

    fig = plot.create_annotated_plot(files_data, "t", "none", group_name=group_name)

    assert fig.layout.yaxis.title.text == "Bz [T]"
    traces_by_sensor = {tr.name.split(" - ")[-1]: tr for tr in fig.data}
    assert max(traces_by_sensor["Champ_magn"].y) == pytest.approx(0.4980357330322266)
    assert min(traces_by_sensor["Champ_magn"].y) == pytest.approx(-0.005575473914543788)


def test_collect_group_field_rows_includes_both_formats_and_nothing_else(monkeypatch):
    """The style editor's field list for the "Magnetic_Field" block must
    include Champ_magn (pigbrother) alongside Field (pupitre) — and nothing
    else. Champ_magn's native pigbrother group, Courants_Alimentations, also
    holds Courant_A1..A4/Référence_*/Courant_GR1..2 (sibling channels that
    belong to the separate "Courants_Alimentations" display block); those
    must not leak in just because they share that native group."""
    monkeypatch.chdir(Path(__file__).resolve().parent)
    group_entries = db.get_overview_group_entries(_FILES, _HOUSING)
    group_name = "Magnetic_Field"

    field_rows, _source_keys = db.collect_group_field_rows(
        _FILES, _HOUSING, group_name, group_entries
    )

    sensors = {sensor for sensor, _source_key in field_rows}
    assert sensors == {"Field", "Champ_magn"}


def test_get_field_column_stats_normalizes_to_tesla_regardless_of_order(monkeypatch):
    """Field (pupitre, native tesla) and Champ_magn (pigbrother, native
    millitesla, keyed as "Courants_Alimentations/Champ_magn" in getKeys())
    must both be picked up and converted to a common unit before combining
    -- otherwise Champ_magn is silently dropped (bare-key lookup misses its
    "Group/Channel" key) or, once found, its millitesla magnitudes get
    combined with Field's tesla ones as if they were the same unit."""
    monkeypatch.chdir(Path(__file__).resolve().parent)
    mruns = [db.load_mrun_object(f, _HOUSING) for f in _FILES]

    stats_forward = db.get_field_column_stats(mruns)
    stats_reversed = db.get_field_column_stats(list(reversed(mruns)))

    assert stats_forward["unit"] == "tesla"
    assert stats_reversed["unit"] == "tesla"
    for key in ("min", "mean", "max", "std"):
        assert stats_forward[key] == pytest.approx(stats_reversed[key])


def test_gr_current_folds_into_matched_entry_via_housing_config(monkeypatch):
    """IH has no static defs.json alias -- which GR role it plays (and hence
    which pigbrother channel it corresponds to) depends on the housing (see
    housing_config.py). For M9 (GR1 = IH), IH must still be folded into a
    matched entry with the pigbrother Courant_GR1 channel, resolved via
    get_housing_config(housing) rather than a fixed alias."""
    monkeypatch.chdir(Path(__file__).resolve().parent)
    group_entries = db.get_overview_group_entries(_FILES, _HOUSING)
    entry = next(
        e
        for e in group_entries["Courants_Alimentations"]
        if e["channels"].get("pupitre", {}).get("channel") == "IH"
    )
    assert entry["channels"]["pupitre"] == {
        "group": "Courants_Alimentations",
        "channel": "IH",
    }
    assert entry["channels"]["pigbrother"] == {
        "group": "Courants_Alimentations",
        "channel": "Courant_GR1",
    }


def test_collect_group_files_data_includes_ih_and_courant_gr1(monkeypatch):
    """Regression test: checking the IH/Courant_GR1 matched entry must pull
    data from BOTH the pupitre file (IH) and the pigbrother overview file
    (Courant_GR1), not just the pupitre one."""
    monkeypatch.chdir(Path(__file__).resolve().parent)
    group_entries = db.get_overview_group_entries(_FILES, _HOUSING)
    group_name = "Courants_Alimentations"
    value = next(
        e["value"]
        for e in group_entries[group_name]
        if e["channels"].get("pupitre", {}).get("channel") == "IH"
    )

    mruns = {f: db.load_mrun_object(f, _HOUSING) for f in _FILES}
    files_data = db.collect_group_files_data(
        mruns, _HOUSING, group_name, [value], group_entries
    )

    all_sensors = {s for fd in files_data for s in fd["sensors"]}
    assert {"IH", "Courant_GR1"} <= all_sensors


def test_collect_group_field_rows_courants_alimentations_unaffected(monkeypatch):
    """The sibling "Courants_Alimentations" block (pupitre Idcct1..4, matched
    to pigbrother Courant_A1..4, plus pigbrother-only Référence_*/Courant_GR*)
    must still see its own full sensor set, unaffected by the native-group
    name it happens to share with Magnetic_Field's pigbrother side."""
    monkeypatch.chdir(Path(__file__).resolve().parent)
    group_entries = db.get_overview_group_entries(_FILES, _HOUSING)

    field_rows, _source_keys = db.collect_group_field_rows(
        _FILES, _HOUSING, "Courants_Alimentations", group_entries
    )

    sensors = {sensor for sensor, _source_key in field_rows}
    assert {"Idcct1", "Idcct2", "Idcct3", "Idcct4", "Courant_A1", "Courant_GR1"} <= sensors
    assert "Champ_magn" not in sensors
