import sys
from pathlib import Path

import dash
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# dash.register_page() (called at the page module's import) requires a
# pages-enabled app to exist first.
dash.Dash(__name__, use_pages=True, pages_folder="")

from pages import part_stats as ps  # noqa: E402

# As returned by the data helpers: ascending, NULLs last.
_DATES = [
    ("A2020", pd.Timestamp("2020-01-01")),
    ("A2024", pd.Timestamp("2024-01-01")),
    ("UNDATED", pd.NaT),
]


def test_magnet_history_section_newest_first_undated_last(monkeypatch):
    history = [
        {"magnet_name": name, "type": name, "status": "in_stock", "assembled_at": assembled,
         "rank": 0, "coil_index": None}
        for name, assembled in _DATES
    ]
    monkeypatch.setattr(ps.db, "get_magnet_history_for_part", lambda part, db_path=None: history)
    table = ps._magnet_history_section("M10Be", None)
    assert [r["type"] for r in table.data] == ["A2024", "A2020", "UNDATED"]


def test_assembly_history_section_newest_first_undated_last():
    history = [
        {"assembly_name": name, "housing": name, "status": "disassembled",
         "commissioned_at": commissioned, "decommissioned_at": pd.NaT}
        for name, commissioned in _DATES
    ]
    table = ps._assembly_history_section("M10Be", history)
    assert [r["housing"] for r in table.data] == ["A2024", "A2020", "UNDATED"]
