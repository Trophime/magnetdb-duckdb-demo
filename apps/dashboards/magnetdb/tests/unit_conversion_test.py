import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pint

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import magnetdb_plot as plot


class _FakeMrun:
    """Minimal getUnit()-only stand-in for MagnetRun, for unit-conversion tests."""

    def __init__(self, units):
        self._units = units

    def getUnit(self, key):
        if key not in self._units:
            raise RuntimeError(f"no unit for {key!r}")
        return self._units[key]


def test_convert_values_to_unit_compatible():
    ureg = pint.UnitRegistry()
    from_unit = ureg.Unit("meter ** 3 / hour")
    to_unit = ureg.Unit("liter / second")
    values = np.array([3.6, 7.2])
    result = plot.convert_values_to_unit(values, from_unit, to_unit)
    np.testing.assert_allclose(result, [1.0, 2.0])


def test_convert_values_to_unit_incompatible_returns_unchanged():
    ureg = pint.UnitRegistry()
    from_unit = ureg.Unit("meter")
    to_unit = ureg.Unit("second")
    values = np.array([1.0, 2.0])
    result = plot.convert_values_to_unit(values, from_unit, to_unit)
    np.testing.assert_array_equal(result, values)


def test_convert_values_to_unit_none_is_noop():
    values = np.array([1.0, 2.0])
    assert plot.convert_values_to_unit(values, None, None) is values


def test_group_display_unit_applies_override():
    ureg = pint.UnitRegistry()
    mrun = _FakeMrun({"debitbrut": ("Q", ureg.Unit("meter ** 3 / hour"))})
    symbol, unit = plot.group_display_unit(mrun, "Hydraulics", "debitbrut")
    assert symbol == "Q"
    assert unit == ureg.Unit("liter / second")


def test_group_display_unit_no_override_keeps_native_unit():
    ureg = pint.UnitRegistry()
    native_unit = ureg.Unit("bar")
    mrun = _FakeMrun({"Pcoil1": ("P", native_unit)})
    symbol, unit = plot.group_display_unit(mrun, "Pressures_Hydraulics", "Pcoil1")
    assert symbol == "P"
    assert unit == native_unit


def test_format_sensor_label_with_symbol_and_unit():
    ureg = pint.UnitRegistry()
    label = plot.format_sensor_label("debitbrut", "Q", ureg.Unit("liter / second"))
    assert label == "debitbrut (Q [l/s])"


def test_format_sensor_label_symbol_only():
    assert plot.format_sensor_label("debitbrut", "Q", None) == "debitbrut (Q)"


def test_format_sensor_label_no_symbol():
    assert plot.format_sensor_label("debitbrut", None, None) == "debitbrut"


def test_create_annotated_plot_forces_group_unit():
    ureg = pint.UnitRegistry()
    mrun_a = _FakeMrun({"debitbrut": ("Q", ureg.Unit("meter ** 3 / hour"))})
    mrun_b = _FakeMrun({"FlowH": ("Q", ureg.Unit("liter / second"))})

    df_a = pd.DataFrame({"t": [0.0, 1.0], "debitbrut": [3.6, 7.2]})
    df_b = pd.DataFrame({"t": [0.0, 1.0], "FlowH": [1.0, 2.0]})

    files_data = [
        {"file": "a.txt", "df": df_a, "sensors": ["debitbrut"], "mrun": mrun_a},
        {"file": "b.txt", "df": df_b, "sensors": ["FlowH"], "mrun": mrun_b},
    ]

    fig = plot.create_annotated_plot(files_data, "t", "none", group_name="Hydraulics")
    assert fig.layout.yaxis.title.text == "Q [l/s]"

    traces_by_name = {tr.name: tr for tr in fig.data}
    np.testing.assert_allclose(traces_by_name["a.txt - debitbrut"].y, [1.0, 2.0])
    np.testing.assert_allclose(traces_by_name["b.txt - FlowH"].y, [1.0, 2.0])


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"{name}: OK")
