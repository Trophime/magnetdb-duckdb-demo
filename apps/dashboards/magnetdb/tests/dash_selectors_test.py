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
