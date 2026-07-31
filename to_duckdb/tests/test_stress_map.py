"""Tests for _assert_current_units() in stress_map.py."""

import pytest

from python_magnetrun.magnetdata_base import _make_ureg
from stress_map import _assert_current_units


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
