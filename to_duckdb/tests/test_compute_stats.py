"""Tests for compute_scalars() in compute_exp_stats.py / compute_op_stats.py."""

import pandas as pd
import pytest
from pint import DimensionalityError

from compute_exp_stats import compute_scalars as compute_exp_scalars
from compute_op_stats import compute_scalars as compute_op_scalars
from python_magnetrun.magnetdata_base import _make_ureg

_SCALAR_FNS = [compute_exp_scalars, compute_op_scalars]


def _make_df() -> pd.DataFrame:
    # 1 MW held constant for 10 s of dt → 1e7 J of true energy.
    return pd.DataFrame(
        {
            "Field": [0.0, 0.0],
            "Ptot": [1.0, 1.0],
            "dt": [10.0, 10.0],
        }
    )


@pytest.mark.parametrize("compute_scalars", _SCALAR_FNS)
def test_energy_j_is_joules_with_unknown_units(compute_scalars):
    scalars = compute_scalars(_make_df())
    assert scalars["energy_j"] == 2.0e7


@pytest.mark.parametrize("compute_scalars", _SCALAR_FNS)
def test_energy_j_uses_declared_field_unit(compute_scalars):
    # Same "1.0" Ptot values, but now declared as kW instead of the assumed
    # MW fallback → energy should come out 1000x smaller.
    ureg = _make_ureg()
    units = {"Ptot": ("Power", ureg.kilowatt)}
    scalars = compute_scalars(_make_df(), units=units)
    assert scalars["energy_j"] == pytest.approx(2.0e7 / 1000)


@pytest.mark.parametrize("compute_scalars", _SCALAR_FNS)
def test_energy_j_rejects_incompatible_declared_unit(compute_scalars):
    ureg = _make_ureg()
    units = {"Ptot": ("I", ureg.ampere)}
    with pytest.raises(DimensionalityError):
        compute_scalars(_make_df(), units=units)
