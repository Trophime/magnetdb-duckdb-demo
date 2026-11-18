import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from experiment_links import overview_record_href, signal_stats_links  # noqa: E402


def _row(stats, assembly="M9_A1"):
    return pd.Series({"Assembly": assembly, "Signal stats": stats})


def test_single_stats_file():
    assert signal_stats_links(_row("M9_Stats_a.tdms")) == (
        "[M9_Stats_a.tdms](/stats_viewer?assembly=M9_A1&file=M9_Stats_a.tdms)"
    )


def test_multiple_stats_files():
    assert signal_stats_links(_row("a.tdms, b.tdms")) == (
        "[a.tdms](/stats_viewer?assembly=M9_A1&file=a.tdms), "
        "[b.tdms](/stats_viewer?assembly=M9_A1&file=b.tdms)"
    )


def test_empty_cell_left_plain():
    assert signal_stats_links(_row("")) == ""
    assert signal_stats_links(_row(None)) == ""


def test_query_values_escaped():
    assert signal_stats_links(_row("x y&z.tdms", assembly="M9 A/1")) == (
        "[x y&z.tdms](/stats_viewer?assembly=M9%20A%2F1&file=x%20y%26z.tdms)"
    )


def test_overview_record_href():
    assert overview_record_href("M8_A230913_00", "M8_Overview_261113-0813") == (
        "/overview-records?assembly=M8_A230913_00&record=M8_Overview_261113-0813"
    )
    assert overview_record_href("M9 A/1", "r&1") == (
        "/overview-records?assembly=M9%20A%2F1&record=r%261"
    )
