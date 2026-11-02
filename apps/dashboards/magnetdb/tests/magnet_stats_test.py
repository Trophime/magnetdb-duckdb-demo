import sys
from pathlib import Path

import dash
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# dash.register_page() (called at the page module's import) requires a
# pages-enabled app to exist first.
dash.Dash(__name__, use_pages=True, pages_folder="")

from pages import magnet_stats as ms  # noqa: E402


def test_assembly_history_section_newest_first_undated_last():
    # As returned by get_assembly_history_for_magnet: ascending, NULLs last.
    history = [
        {"assembly_name": name, "housing": name, "status": "disassembled",
         "commissioned_at": commissioned, "decommissioned_at": pd.NaT}
        for name, commissioned in [
            ("M10_A200101_00", pd.Timestamp("2020-01-01")),
            ("M10_A240101_00", pd.Timestamp("2024-01-01")),
            ("M10_UNDATED", pd.NaT),
        ]
    ]
    table = ms._assembly_history_section("M10Bitters", history)
    assert [r["housing"] for r in table.data] == ["M10_A240101_00", "M10_A200101_00", "M10_UNDATED"]
