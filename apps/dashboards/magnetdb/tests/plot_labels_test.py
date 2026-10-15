import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import magnetdb_plot as plot

_ARCHIVE = "M10_Archive_250127-1605.tdms"
_PUPITRE = "M10_2025.01.27---15:39:29.txt"


def test_short_file_label():
    assert plot._short_file_label(_ARCHIVE) == "Archive 27/01 16:05"
    assert plot._short_file_label(_PUPITRE) == "Pupitre 27/01 15:39"
    assert plot._short_file_label("M9_Overview_240716-1634.tdms") == "Overview 16/07 16:34"
    assert plot._short_file_label("SUPERVISION") == "SUPERVISION"
    assert plot._short_file_label("Hybrid") == "Hybrid"
    # Unparseable timestamp falls back to the bare stem.
    assert plot._short_file_label("a.txt") == "a"


def test_create_plot_short_legend_and_title():
    df = pd.DataFrame({"t": [0.0, 1.0], "Courant_A1": [1.0, 2.0]})
    group = "Courants_Alimentations"

    fig = plot.create_plot(df, "t", [f"{group}/Courant_A1"], "none", filename=_ARCHIVE, group_name=group)

    assert [tr.name for tr in fig.data] == ["Courant_A1"]
    assert fig.layout.title.text == f"{plot.i18n._(group)} — Archive 27/01 16:05"


def test_create_plot_keeps_supervision_prefix_for_page_cleanup():
    df = pd.DataFrame({"t": [0.0, 1.0], "supervision:teb": [1.0, 2.0]})

    fig = plot.create_plot(df, "t", ["supervision:teb"], "none", filename="SUPERVISION", group_name="Hydraulics")

    assert fig.data[0].name == "supervision:teb"


def test_create_annotated_plot_groups_legend_by_file():
    df = pd.DataFrame({"t": [0.0, 1.0], "Courant_A1": [1.0, 2.0]})
    sensors = ["Courants_Alimentations/Courant_A1"]
    files_data = [
        {"file": _ARCHIVE, "df": df, "sensors": sensors, "mrun": None},
        {"file": _PUPITRE, "df": df, "sensors": sensors, "mrun": None},
    ]

    fig = plot.create_annotated_plot(files_data, "t", "none", group_name="Courants_Alimentations")

    assert [tr.name for tr in fig.data] == ["Courant_A1", "Courant_A1"]
    assert [tr.legendgroup for tr in fig.data] == [_ARCHIVE, _PUPITRE]
    assert [tr.legendgrouptitle.text for tr in fig.data] == ["Archive 27/01 16:05", "Pupitre 27/01 15:39"]
    # Unified hover must still tell the two files apart.
    assert "Archive 27/01 16:05" in fig.data[0].hovertemplate
    assert "Pupitre 27/01 15:39" in fig.data[1].hovertemplate
