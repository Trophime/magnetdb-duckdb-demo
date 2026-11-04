import sys
from pathlib import Path

import dash
import duckdb
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# dash.register_page() (called at the page module's import) requires a
# pages-enabled app to exist first.
dash.Dash(__name__, use_pages=True, pages_folder="")

import dash_selectors as selectors  # noqa: E402
import magnetdb_analysis as db  # noqa: E402
from pages import operational_viewer as opv  # noqa: E402


@pytest.fixture
def op_db(tmp_path):
    """A minimal DuckDB file with two assemblies and mixed-type operationaldata rows."""
    db_path = tmp_path / "op_test.duckdb"
    con = duckdb.connect(str(db_path))
    con.execute("CREATE TABLE assemblies (name VARCHAR, commissioned_at TIMESTAMP)")
    con.execute(
        "CREATE TABLE operationaldata (file VARCHAR, assembly_name VARCHAR, type VARCHAR)"
    )
    con.execute(
        "INSERT INTO assemblies VALUES "
        "('M9_A250401_00', '2025-04-01'), ('M10_A201126_00', '2020-11-26')"
    )
    con.execute(
        "INSERT INTO operationaldata VALUES "
        "('pbsurv/M9/Overview/M9_Overview_250612-1611.tdms', 'M9_A250401_00', 'Overview'), "
        "('pbsurv/M9/Overview/M9_Overview_250410-0900.tdms', 'M9_A250401_00', 'Overview'), "
        "('pbsurv/M9/Fichiers_Archive/M9_Archive_250501-1200.tdms', 'M9_A250401_00', 'Archive'), "
        "('pbsurv/M9/Default/M9_Default_250501-1200.tdms', 'M9_A250401_00', 'Default'), "
        "('pbsurv/M10/Overview/M10_Overview_201211-1455.tdms', 'M10_A201126_00', 'Overview')"
    )
    con.close()
    return str(db_path)


def test_operational_files_filtered_by_type_basenamed_and_sorted(op_db):
    files = db.get_operational_files_for_assembly(
        "M9_A250401_00", ["Overview", "Archive"], db_path=op_db
    )
    assert files == [
        "M9_Overview_250410-0900.tdms",
        "M9_Archive_250501-1200.tdms",
        "M9_Overview_250612-1611.tdms",
    ]


def test_operational_files_single_type(op_db):
    files = db.get_operational_files_for_assembly(
        "M9_A250401_00", ["Archive"], db_path=op_db
    )
    assert files == ["M9_Archive_250501-1200.tdms"]


@pytest.mark.parametrize(
    "types, expected",
    [
        (["Overview"], ["M9_Overview_250612-1611.tdms", "M9_Overview_250410-0900.tdms"]),
        (["Archive"], ["M9_Archive_250501-1200.tdms"]),
        (
            ["Overview", "Archive"],
            [
                "M9_Overview_250612-1611.tdms",
                "M9_Archive_250501-1200.tdms",
                "M9_Overview_250410-0900.tdms",
            ],
        ),
        ([], []),
    ],
)
def test_file_dropdown_follows_type_selector(op_db, types, expected):
    options = opv.update_file_dropdown("M9_A250401_00", types, op_db)
    assert [o["value"] for o in options] == expected


def test_assembly_dropdown_housing_filter(op_db):
    options, value = opv.update_assembly_dropdown(
        op_db, "M9", selectors.ALL, selectors.ALL, None
    )
    assert options == ["M9_A250401_00"]
    assert value == "M9_A250401_00"
