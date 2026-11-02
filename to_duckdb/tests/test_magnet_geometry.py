"""Unit tests for magnet_geometry.py — rebuilding a magnet's geometry from its parts."""

from crud import insert_magnet, insert_magnet_part_row, insert_material, insert_part
from magnet_geometry import geometry_problem, refresh_geometry_problem
from tests.conftest import MATERIAL_COPPER

SUPRA_GEOMETRY = (
    '{"__classname__": "Supra", "name": "Hybrid", "r": [550, 913], "z": [-700, 700], '
    '"n": 1924, "struct": "", "detail": "NONE"}'
)


def add_supras_magnet(con, geometry_data=SUPRA_GEOMETRY):
    """Load magnet SUP_01 holding one supra part SUPRA_01 with *geometry_data*."""
    insert_material(con, MATERIAL_COPPER, verbose=False)
    insert_part(
        con,
        {"name": "SUPRA_01", "type": "supra", "status": "in_stock", "material_name": "MAT_COPPER",
         "geometry": None, "geometry_data": geometry_data, "manufactured_at": "2020-01-01"},
        verbose=False,
    )
    insert_magnet(con, {"name": "SUP_01", "status": "in_stock", "assembled_at": "2020-01-01"}, "supras", verbose=False)
    insert_magnet_part_row(con, "SUP_01", "SUPRA_01", 0, 1)


def _stored(con, name):
    return con.execute("SELECT geometry_problem FROM magnets WHERE name = ?", [name]).fetchone()[0]


def _log_rows(con, name):
    return con.execute(
        "SELECT operation, details FROM operation_log WHERE table_name = 'magnets' "
        "AND record_name = ? AND details LIKE '%geometry_problem%'",
        [name],
    ).fetchall()


def test_geometry_problem_none_when_parts_rebuild(con):
    add_supras_magnet(con)
    assert geometry_problem(con, "SUP_01") is None


def test_geometry_problem_names_part_without_geometry_data(con_populated):
    problem = geometry_problem(con_populated, "MAG_01")
    assert problem is not None
    assert "HELIX_01" in problem


def test_geometry_problem_reports_unbuildable_part_geometry(con):
    add_supras_magnet(con, geometry_data='{"__classname__": "Supra", "name": "broken"}')
    assert geometry_problem(con, "SUP_01")


def test_refresh_stores_problem_and_logs_change_once(con_populated):
    problem = refresh_geometry_problem(con_populated, "MAG_01")
    assert problem and _stored(con_populated, "MAG_01") == problem
    assert len(_log_rows(con_populated, "MAG_01")) == 1

    refresh_geometry_problem(con_populated, "MAG_01")
    assert len(_log_rows(con_populated, "MAG_01")) == 1


def test_refresh_clears_problem_once_parts_fixed(con):
    add_supras_magnet(con, geometry_data=None)
    assert refresh_geometry_problem(con, "SUP_01")

    con.execute("UPDATE parts SET geometry_data = ? WHERE name = 'SUPRA_01'", [SUPRA_GEOMETRY])
    assert refresh_geometry_problem(con, "SUP_01") is None
    assert _stored(con, "SUP_01") is None
    assert len(_log_rows(con, "SUP_01")) == 2
