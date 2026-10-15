import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import magnetdb_analysis as db
import pandas as pd
import pytest

_HOUSING = "M9"
_FILES_AND_GROUPS = [
    ("2025.12.02 - 14:30:46.txt", "Magnetic_Field"),
    ("M9_Overview_251202-1430.tdms", "Courants_Alimentations"),
]


@pytest.mark.parametrize("filename, group", _FILES_AND_GROUPS)
def test_group_data_pandas_returns_pandas(monkeypatch, filename, group):
    """python_magnetrun's get_group_data() now returns polars for both
    pupitre and TDMS runs; the dashboard's plotting/stats code needs pandas."""
    monkeypatch.chdir(Path(__file__).resolve().parent)
    mrun = db.load_mrun_object(filename, _HOUSING)
    df = db.group_data_pandas(mrun, group)
    assert isinstance(df, pd.DataFrame)
    assert {"t", "timestamp"} <= set(df.columns)


@pytest.mark.parametrize("filename, group", _FILES_AND_GROUPS)
def test_get_group_dataframe_returns_pandas(monkeypatch, filename, group):
    monkeypatch.chdir(Path(__file__).resolve().parent)
    df = db.get_group_dataframe(filename, _HOUSING, group)
    assert isinstance(df, pd.DataFrame)


def test_get_column_with_time_returns_pandas_for_pupitre(monkeypatch):
    """Pupitre getData() returns a narwhals DataFrame."""
    monkeypatch.chdir(Path(__file__).resolve().parent)
    mrun = db.load_mrun_object("2025.12.02 - 14:30:46.txt", _HOUSING)
    df = db._get_column_with_time(mrun, "Field")
    assert isinstance(df, pd.DataFrame)
    assert {"Field", "t", "timestamp"} <= set(df.columns)
