"""Tests for stress_map.py."""

import argparse

import magnettools.magnettools as mt
import pandas as pd
import pytest

import stress_map
from python_magnetrun.magnetdata_base import _make_ureg
from stress_map import _assert_current_units, _section_index_at_z, compute_stress_stats


def test_assert_current_units_passes_for_ampere():
    ureg = _make_ureg()
    units = {"IH": ("I_H", ureg.ampere), "IB": ("I_B", ureg.ampere)}
    _assert_current_units(units, ["IH", "IB"], ureg)


def test_assert_current_units_skips_unknown_columns():
    ureg = _make_ureg()
    _assert_current_units({}, ["IH", "IB", "IS"], ureg)


def test_assert_current_units_rejects_incompatible_unit():
    ureg = _make_ureg()
    units = {"IH": ("T", ureg.tesla)}
    with pytest.raises(ValueError, match="IH"):
        _assert_current_units(units, ["IH"], ureg)


# ---------------------------------------------------------------------------
# _section_index_at_z
#
# Mirrors a real 3-section Bitter part layout (small/big/small, e.g. real
# turns=[6,158,6]): end sections at z=-0.279/+0.279 (halfheight 0.02), one
# big centered section spanning z=-0.259..0.259 (halfheight 0.259).
# ---------------------------------------------------------------------------


def _three_section_group():
    elements = mt.VectorOfBitters()
    elements.append(mt.BitterMagnet(0.34, 0.20, 0.04, 1000.0, -0.279))   # idx 0
    elements.append(mt.BitterMagnet(0.34, 0.20, 0.518, 2000.0, 0.0))     # idx 1 (centered)
    elements.append(mt.BitterMagnet(0.34, 0.20, 0.04, 1000.0, 0.279))    # idx 2
    return elements


def test_section_index_at_z_default_picks_centered_section():
    elements = _three_section_group()
    assert _section_index_at_z(elements, [0, 1, 2]) == 1


def test_section_index_at_z_nonzero_z0_picks_matching_end_section():
    elements = _three_section_group()
    assert _section_index_at_z(elements, [0, 1, 2], z0=0.279) == 2
    assert _section_index_at_z(elements, [0, 1, 2], z0=-0.279) == 0


def test_section_index_at_z_falls_back_to_closest_when_no_section_contains_z0():
    elements = mt.VectorOfBitters()
    elements.append(mt.BitterMagnet(0.34, 0.20, 0.02, 1000.0, -0.279))  # idx 0: [-0.289,-0.269]
    elements.append(mt.BitterMagnet(0.34, 0.20, 0.02, 1000.0, 0.279))   # idx 1: [0.269, 0.289]

    # z0=0.1 falls in the gap between the two sections -> closer to idx 1
    assert _section_index_at_z(elements, [0, 1], z0=0.1) == 1
    assert _section_index_at_z(elements, [0, 1], z0=-0.1) == 0


# ---------------------------------------------------------------------------
# compute_stress_stats()
# ---------------------------------------------------------------------------


def test_compute_stress_stats_includes_all_coil_types():
    df = pd.DataFrame({
        "t": [0.0, 1.0, 2.0],
        "IH": [100.0, 200.0, 300.0],
        "H1_fast": [10.0, 20.0, 30.0],
        "B1_fast": [5.0, 15.0, 25.0],
        "Supra1_fast": [1.0, 2.0, 3.0],
    })

    stats = compute_stress_stats(df)

    assert set(stats["coil"]) == {"H1_fast", "B1_fast", "Supra1_fast"}


def test_compute_stress_stats_values():
    df = pd.DataFrame({"H1_fast": [10.0, 20.0, 30.0]})

    row = compute_stress_stats(df).iloc[0]

    assert row["coil"] == "H1_fast"
    assert row["min"] == 10.0
    assert row["max"] == 30.0
    assert row["mean"] == pytest.approx(20.0)
    assert row["p50"] == pytest.approx(20.0)


def test_compute_stress_stats_empty_when_no_fast_columns():
    df = pd.DataFrame({"t": [0.0, 1.0], "IH": [100.0, 200.0]})

    assert compute_stress_stats(df).empty


# ---------------------------------------------------------------------------
# Bitter/Supra regex regression — plot_stress_history / _load_history /
# cmd_fatigue previously filtered on r"H\d+_fast" only, silently dropping
# Bitter/Supra columns. Now all three use r"(H|B|Supra)\d+_fast".
# ---------------------------------------------------------------------------


def test_plot_stress_history_includes_bitter_and_supra_columns(tmp_path, monkeypatch):
    df = pd.DataFrame({
        "t": [0.0, 1.0, 2.0],
        "H1_fast": [10.0, 20.0, 30.0],
        "B1_fast": [5.0, 15.0, 25.0],
        "Supra1_fast": [1.0, 2.0, 3.0],
    })
    plotted_labels = []
    real_plot = stress_map.plt.plot

    def recording_plot(*args, **kwargs):
        if "label" in kwargs:
            plotted_labels.append(kwargs["label"])
        return real_plot(*args, **kwargs)

    monkeypatch.setattr(stress_map.plt, "plot", recording_plot)

    stress_map.plot_stress_history(df, "TEST_MAGNET", output_png=str(tmp_path / "out.png"))

    assert any(label.startswith("B1_fast") for label in plotted_labels)
    assert any(label.startswith("Supra1_fast") for label in plotted_labels)


def test_load_history_preview_includes_bitter_and_supra_columns(monkeypatch, capsys):
    df = pd.DataFrame({
        "t": [0.0, 1.0],
        "H1_fast": [10.0, 20.0],
        "B1_fast": [5.0, 15.0],
        "Supra1_fast": [1.0, 2.0],
    })
    monkeypatch.setattr(stress_map, "resolve_pupitre_files", lambda *a, **k: ["fake_file.txt"])
    monkeypatch.setattr(stress_map, "validate_fast_from_pupitre", lambda *a, **k: df)
    monkeypatch.setattr(stress_map, "parse_filename_timestamp", lambda f: None)
    import compute_hoop_stats
    monkeypatch.setattr(compute_hoop_stats, "resolve_z0_by_type", lambda *a, **k: ([], []))

    args = argparse.Namespace(
        assembly_name="TEST_ASSEMBLY", db="unused.duckdb", pupitre=None,
        magnet_type="all", check=False, use_mrun=False,
    )

    stress_map._load_history(args, data=object(), housing="M9")
    captured = capsys.readouterr()

    assert "B1_fast" in captured.out
    assert "Supra1_fast" in captured.out


def test_cmd_fatigue_includes_bitter_and_supra_columns(monkeypatch, tmp_path):
    df = pd.DataFrame({
        "t": [0.0, 1.0, 2.0],
        "H1_fast": [10.0, 20.0, 30.0],
        "B1_fast": [5.0, 15.0, 25.0],
        "Supra1_fast": [1.0, 2.0, 3.0],
    })
    processed_cols = []

    def fake_compute_fatigue(df, col):
        processed_cols.append(col)
        return pd.DataFrame({"range": [1.0], "mean": [0.0], "count": [1], "i_start": [0], "i_end": [1]})

    monkeypatch.setattr(stress_map, "_load_assembly", lambda args: (str(tmp_path), object(), [], "M9"))
    monkeypatch.setattr(stress_map, "_load_history", lambda args, data, housing: df)
    monkeypatch.setattr(stress_map, "compute_fatigue", fake_compute_fatigue)
    monkeypatch.setattr(stress_map, "plot_fatigue", lambda *a, **k: None)

    args = argparse.Namespace(assembly_name="TEST_ASSEMBLY", bins=15)
    stress_map.cmd_fatigue(args)

    assert processed_cols == ["H1_fast", "B1_fast", "Supra1_fast"]
