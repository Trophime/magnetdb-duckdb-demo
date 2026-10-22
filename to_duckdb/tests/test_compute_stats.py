"""Tests for compute_scalars() / load_file() in compute_exp_stats.py / compute_op_stats.py."""

import pandas as pd
import polars as pl
import pytest
from pint import DimensionalityError

from compute_exp_stats import compute_scalars as compute_exp_scalars
from compute_exp_stats import load_file as load_exp_file
from compute_op_stats import compute_scalars as compute_op_scalars
from compute_op_stats import load_file as load_op_file
from python_magnetrun.magnetdata_base import _make_ureg

_SCALAR_FNS = [compute_exp_scalars, compute_op_scalars]
_LOAD_FNS = [load_exp_file, load_op_file]

_PUPITRE_BODY = (
    "Date\tTime\tField\n"
    "2018.02.21\t10:18:55\t0.0\n"
    "2018.02.21\t10:18:56\t1.5\n"
)


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


class _FakePolarsMagnetData:
    """Mimics PolarsMagnetData: ``.Data`` is a polars frame."""

    def __init__(self):
        self.Data = pl.DataFrame(
            {
                "Date": ["2018.02.21", "2018.02.21"],
                "Time": ["10:18:55", "10:18:56"],
                "Field": [0.0, 1.5],
            }
        )
        self.units = {}

    def Units(self):  # noqa: N802
        pass


def _failing_load(_filename):
    raise RuntimeError("reader unavailable")


@pytest.mark.parametrize("load_file", _LOAD_FNS)
def test_load_file_converts_polars_data(load_file, tmp_path, monkeypatch):
    # Content unreadable by the pandas fallback: only the fake reader yields Field.
    path = tmp_path / "2018.02.21 - 10:18:54.txt"
    path.write_text("not a pupitre file\n")
    monkeypatch.setattr(
        "python_magnetrun.magnetdata.load_magnetdata",
        lambda _filename: _FakePolarsMagnetData(),
    )
    result = load_file(path)
    assert result is not None
    df, _ = result
    assert isinstance(df, pd.DataFrame)
    assert df["Field"].tolist() == [0.0, 1.5]
    assert df["dt"].tolist() == [0.0, 1.0]


@pytest.mark.parametrize("load_file", _LOAD_FNS)
def test_load_file_fallback_skips_preamble(load_file, tmp_path, monkeypatch):
    path = tmp_path / "2018.02.21 - 10:18:54.txt"
    path.write_text("16\tM15061601\n" + _PUPITRE_BODY)
    monkeypatch.setattr("python_magnetrun.magnetdata.load_magnetdata", _failing_load)
    df, _ = load_file(path)
    assert df["Field"].tolist() == [0.0, 1.5]


@pytest.mark.parametrize("load_file", _LOAD_FNS)
def test_load_file_fallback_without_preamble(load_file, tmp_path, monkeypatch):
    path = tmp_path / "2018.02.21 - 10:18:54.txt"
    path.write_text(_PUPITRE_BODY)
    monkeypatch.setattr("python_magnetrun.magnetdata.load_magnetdata", _failing_load)
    df, _ = load_file(path)
    assert df["Field"].tolist() == [0.0, 1.5]


@pytest.mark.parametrize("load_file", _LOAD_FNS)
def test_load_file_fallback_drops_stale_tail(load_file, tmp_path, monkeypatch):
    # Crash tail as in M10 "2024.12.05 - 11:16:02.txt": NUL padding, then older rows.
    path = tmp_path / "2018.02.21 - 10:18:54.txt"
    path.write_bytes(
        (
            "16\tM15061601\n"
            + _PUPITRE_BODY
            + "\x00" * 64
            + ".0\t182.4\n"
            + "2014.07.27\t22:38:31\t22.2"
        ).encode("utf-8")
    )
    monkeypatch.setattr("python_magnetrun.magnetdata.load_magnetdata", _failing_load)
    df, _ = load_file(path)
    assert df["Field"].tolist() == [0.0, 1.5]


def test_get_experiments_skips_unreadable_and_single_row(tmp_path):
    import duckdb
    from compute_exp_stats import get_experiments
    from magnetdb import _add_assembly as add_assembly, _add_magnet as add_magnet
    from tests.conftest import ASSEMBLY_JSON, MAGNET_JSON

    db = tmp_path / "test.duckdb"
    add_magnet(MAGNET_JSON, db)
    add_assembly(ASSEMBLY_JSON, db)
    assembly = ASSEMBLY_JSON["name"]
    with duckdb.connect(str(db)) as con:
        con.execute("DELETE FROM experiments WHERE assembly_name = ?", [assembly])
        con.execute(
            "INSERT INTO experiments (id, name, file, assembly_name, file_integrity, file_checks) VALUES "
            "(1, 'a', 'a.txt', ?, 'ok', '{\"rows_read\": 10}'), "
            "(2, 'b', 'b.txt', ?, 'unreadable', '{\"reason\": \"no data rows\"}'), "
            "(3, 'c', 'c.txt', ?, NULL, '{}'), "
            "(4, 'd', 'd.txt', ?, 'truncated', '{\"rows_read\": 3}'), "
            "(5, 'e', 'e.txt', ?, 'ok', '{\"rows_read\": 1}'), "
            "(6, 'f', 'f.txt', ?, 'ok', '{\"rows_read\": 2}')",
            [assembly] * 6,
        )
        files = get_experiments(con, assembly)["file"].tolist()
    # unreadable (b) and single-row (e) files have no statistics to compute
    assert files == ["a.txt", "c.txt", "d.txt", "f.txt"]
