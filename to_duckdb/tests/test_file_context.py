"""file_context.resolve_file_context: file → experiment → assembly → housing version."""

from datetime import datetime
from zoneinfo import ZoneInfo

import duckdb
import pytest

from crud import insert_housing_config_from_magnetrun
from file_context import resolve_file_context
from schema import ensure_schema

PARIS = ZoneInfo("Europe/Paris")

# (name, type)
MAGNETS = [
    ("M25032101", "insert"),
    ("M9Bi", "bitters"),
    ("MX", "insert"),
    ("M23012001", "insert"),
    ("M8Bi", "bitters"),
    ("Hybrid", "supras"),
    ("M10Bi", "bitters"),
]
# (name, housing, commissioned_at, decommissioned_at, magnets)
ASSEMBLIES = [
    ("M9_A260602_00", "M9", "2026-06-02 08:00:00", None, ["M25032101", "M9Bi"]),
    ("M9_B", "M9", "2025-01-01 08:00:00", "2026-06-01 07:00:00", ["MX", "M9Bi"]),
    ("M8_A230913_00", "M8", "2023-09-19 08:00:00", None, ["M23012001", "M8Bi", "Hybrid"]),
    ("M8_S", "M8", "2021-12-25 08:00:00", "2023-09-19 07:00:00", ["Hybrid"]),
    ("M10_B", "M10", "2025-01-01 08:00:00", None, ["M10Bi"]),
    ("M10_X", "M10", "2024-01-01 08:00:00", "2024-12-31 07:00:00", ["MX", "M10Bi"]),
]
REGISTERED = (1, "2026.06.10 - 10:00:00.txt", "M9_A260602_00")


def build_db(path: str = ":memory:") -> duckdb.DuckDBPyConnection:
    """DB (in memory by default): bundled M8/M9/M10 configs with versions, test magnets/assemblies, one experiment."""
    con = duckdb.connect(path)
    ensure_schema(con)
    for housing in ("M8", "M9", "M10"):
        insert_housing_config_from_magnetrun(con, housing, verbose=False)
    for name, mtype in MAGNETS:
        con.execute(
            "INSERT INTO magnets (name, type, status) VALUES (?, ?, 'in_operation')",
            [name, mtype],
        )
    for name, housing, start, end, magnets in ASSEMBLIES:
        con.execute(
            "INSERT INTO assemblies (name, housing, status, commissioned_at, decommissioned_at) "
            "VALUES (?, ?, 'in_operation', ?, ?)",
            [name, housing, start, end],
        )
        for magnet in magnets:
            con.execute(
                "INSERT INTO assembly_magnets (assembly_name, magnet_name, commissioned_at) "
                "VALUES (?, ?, ?)",
                [name, magnet, start],
            )
    con.execute(
        "INSERT INTO experiments (id, name, file, assembly_name) VALUES (?, ?, ?, ?)",
        [REGISTERED[0], REGISTERED[1], REGISTERED[1], REGISTERED[2]],
    )
    return con


def write_pupitre(directory, date: str, time: str = "10:00:00", columns=None):
    """Write a minimal pupitre file ``<date> - <time>.txt`` starting at *date* *time*."""
    columns = columns or {"Field": "1.0"}
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{date} - {time}.txt"
    header = "\t".join(["Date", "Time", *columns])
    row = "\t".join([date, time, *columns.values()])
    path.write_text(f"16\tM0\t1\t1\n{header}\n{row}\n")
    return path


@pytest.fixture()
def con():
    c = build_db()
    yield c
    c.close()


def test_registered_file(con, tmp_path):
    path = write_pupitre(tmp_path / "M9", "2026.06.10")
    ctx = resolve_file_context(con, path)
    assert ctx.experiment_id == 1
    assert (ctx.assembly, ctx.housing, ctx.housing_version) == ("M9_A260602_00", "M9", "M9-181109")
    assert ctx.t0 == datetime(2026, 6, 10, 10, 0, tzinfo=PARIS)


def test_unregistered_file_by_time_window(con, tmp_path):
    ctx = resolve_file_context(con, write_pupitre(tmp_path / "M9", "2026.07.01"))
    assert ctx.experiment_id is None
    assert ctx.assembly == "M9_A260602_00"


@pytest.mark.parametrize(
    "date, version", [("2026.03.06", "M8-260305"), ("2025.11.05", "M8-230913")]
)
def test_m8_housing_version(con, tmp_path, date, version):
    ctx = resolve_file_context(con, write_pupitre(tmp_path / "M8", date))
    assert (ctx.assembly, ctx.housing_version) == ("M8_A230913_00", version)


def test_no_assembly_covers_file(con, tmp_path):
    ctx = resolve_file_context(con, write_pupitre(tmp_path / "M9", "2020.01.01"))
    assert ctx.assembly is None
    assert (ctx.housing, ctx.housing_version) == ("M9", "M9-181109")


def test_explicit_housing(con, tmp_path):
    """Housing given explicitly when the parent directory is not a housing name."""
    ctx = resolve_file_context(con, write_pupitre(tmp_path / "other", "2026.03.06"), housing="M8")
    assert ctx.housing_version == "M8-260305"
