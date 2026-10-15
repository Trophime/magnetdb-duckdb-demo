import sys
from pathlib import Path

import dash
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# dash.register_page() (called at the page module's import) requires a
# pages-enabled app to exist first.
dash.Dash(__name__, use_pages=True, pages_folder="")

from pages import defaults_spikes as ds  # noqa: E402

_REGULAR = ["M10_Overview_260120-1345.tdms", "2026.01.20 - 13:45:55.txt"]
_EVENTS = [
    "M10_Default_260120-135125_DefautNums.tdms",
    "M10_Spikes_260120-142940.tdms",
]


def test_data_files_appends_selected_incident():
    assert ds._data_files(_REGULAR, _EVENTS, _EVENTS[0]) == _REGULAR + [_EVENTS[0]]


def test_data_files_ignores_missing_or_unknown_incident():
    assert ds._data_files(_REGULAR, _EVENTS, None) == _REGULAR
    assert ds._data_files(_REGULAR, _EVENTS, "M10_Default_other.tdms") == _REGULAR


def test_data_files_does_not_mutate_regular_files():
    regular = list(_REGULAR)
    ds._data_files(regular, _EVENTS, _EVENTS[0])
    assert regular == _REGULAR


def test_shift_incident_t_uses_record_reference():
    df = pd.DataFrame({
        "t": [0.0, 1.0],
        "timestamp": pd.to_datetime(["2026-01-20 12:50:24", "2026-01-20 12:50:25"]),
        "Champ_magn": [1.0, 2.0],
    })
    entry = {"file": _EVENTS[0], "df": df, "sensors": ["Champ_magn"]}
    shifted = ds._shift_incident_t(entry, pd.Timestamp("2026-01-20 12:45:00"))
    assert shifted["df"]["t"].tolist() == [324.0, 325.0]
    assert shifted["sensors"] == ["Champ_magn"]


def test_shift_incident_t_does_not_mutate_cached_dataframe():
    df = pd.DataFrame({
        "t": [0.0],
        "timestamp": pd.to_datetime(["2026-01-20 12:50:24"]),
    })
    entry = {"file": _EVENTS[0], "df": df, "sensors": []}
    ds._shift_incident_t(entry, pd.Timestamp("2026-01-20 12:45:00"))
    assert df["t"].tolist() == [0.0]
    assert entry["df"] is df
