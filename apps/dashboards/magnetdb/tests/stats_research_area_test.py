import sys
from pathlib import Path

import dash
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# dash.register_page() (called at the page module's import) requires a
# pages-enabled app to exist first.
dash.Dash(__name__, use_pages=True, pages_folder="")

from pages import stats_research_area as ra  # noqa: E402


def test_experiments_section_newest_first():
    exp_df = pd.DataFrame({
        "name": ["2024.01.10 - 10:00:00", "2025.03.05 - 12:00:00", "2026.06.20 - 08:00:00"],
        "file": ["a.txt", "b.txt", "c.txt"],
        "assembly_name": ["M9_A1", "M9_A2", "M10_A3"],
        "status": ["old", "mid", "new"],
    })
    table = ra._experiments_section(exp_df)
    assert [r["Status"] for r in table.data] == ["new", "mid", "old"]


def test_overview_records_section_newest_first():
    ov_df = pd.DataFrame({
        "filename": ["M9_Overview_a.tdms", "M9_Overview_b.tdms", "M10_Overview_c.tdms"],
        "assembly_name": ["M9_A1", "M9_A2", "M10_A3"],
        "housing": ["M9", "M9", "M10"],
        "mode": ["old", "mid", "new"],
        "t0": pd.to_datetime(["2024-01-10", "2025-03-05", "2026-06-20"]),
        "stats": ["", "", ""],
    })
    table = ra._overview_records_section(ov_df)
    assert [r["Mode"] for r in table.data] == ["new", "mid", "old"]
