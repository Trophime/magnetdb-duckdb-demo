import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import dash_selectors as selectors


def test_newest_first_reverses_oldest_first_list():
    assert selectors.newest_first(["a", "b", "c"]) == ["c", "b", "a"]


def test_newest_first_handles_empty_list():
    assert selectors.newest_first([]) == []


def test_newest_first_does_not_mutate_input():
    items = ["a", "b", "c"]
    selectors.newest_first(items)
    assert items == ["a", "b", "c"]


def test_year_options_lists_years_newest_first_after_all():
    assert selectors.year_options((2018, 2020)) == [selectors.ALL, "2020", "2019", "2018"]


def test_year_options_without_range_is_all_only():
    assert selectors.year_options(None) == [selectors.ALL]


def _magnets_table(monkeypatch, problems):
    """Build the magnets table for magnets ``{name: geometry_problem}``."""
    magnets = [
        {"name": name, "type": "bitters", "status": "in_stock", "description": None,
         "assembled_at": None, "geometry_problem": problem}
        for name, problem in problems.items()
    ]
    monkeypatch.setattr(selectors.db, "get_magnets_for_assembly", lambda assembly, db_path=None: magnets)
    monkeypatch.setattr(selectors.db, "get_magnet_part_composition", lambda names, db_path=None: {})
    return selectors.magnets_table_section("M9_A260707_00")


def test_magnets_table_highlights_magnet_with_geometry_problem(monkeypatch):
    table = _magnets_table(monkeypatch, {"M9Bitters": "no parts", "M9Bitters-newBi08": None})
    rules = [r for r in table.style_data_conditional if r.get("backgroundColor") == selectors.GEOMETRY_PROBLEM_COLOR]
    assert [r["if"] for r in rules] == [{"filter_query": '{Magnet} contains "[M9Bitters]"', "column_id": "Magnet"}]
    assert table.tooltip_data == [{"Magnet": {"value": "no parts", "type": "text"}}, {}]


def test_magnets_table_without_geometry_problem_has_no_highlight(monkeypatch):
    table = _magnets_table(monkeypatch, {"M9Bitters": None})
    assert not [r for r in table.style_data_conditional if r.get("backgroundColor") == selectors.GEOMETRY_PROBLEM_COLOR]
    assert table.tooltip_data == [{}]
    assert "geometry_problem" not in table.data[0]


def test_missing_date_style_one_blank_rule_per_column():
    assert selectors.missing_date_style("t0", "Assembled") == [
        {"if": {"filter_query": "{t0} is blank", "column_id": "t0"},
         "backgroundColor": selectors.MISSING_DATE_COLOR},
        {"if": {"filter_query": "{Assembled} is blank", "column_id": "Assembled"},
         "backgroundColor": selectors.MISSING_DATE_COLOR},
    ]


def test_missing_date_style_experiment_column_matches_nat_label():
    (rule,) = selectors.missing_date_style("Experiment")
    assert rule["if"] == {"filter_query": '{Experiment} contains "NaT"', "column_id": "Experiment"}


def test_missing_date_style_exempts_in_study_rows():
    (rule,) = selectors.missing_date_style("Commissioned", status_column="Status")
    assert rule["if"] == {
        "filter_query": '{Commissioned} is blank && {Status} != "in_study"',
        "column_id": "Commissioned",
    }


def test_missing_date_color_differs_from_geometry_problem_color():
    assert selectors.MISSING_DATE_COLOR == "#fff3cd"
    assert selectors.MISSING_DATE_COLOR != selectors.GEOMETRY_PROBLEM_COLOR


def test_magnets_table_highlights_blank_assembled_and_keeps_geometry_rule(monkeypatch):
    table = _magnets_table(monkeypatch, {"M9Bitters": "no parts"})
    colors = [r["backgroundColor"] for r in table.style_data_conditional]
    assert colors == [selectors.GEOMETRY_PROBLEM_COLOR, selectors.MISSING_DATE_COLOR]
    assert table.style_data_conditional[1]["if"]["column_id"] == "Assembled"
