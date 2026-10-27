"""check_experiment_files.py — file quality columns on experiments."""

import json

import duckdb

import check_experiment_files
from magnetdb import _add_assembly as add_assembly, _add_magnet as add_magnet
from tests.conftest import ASSEMBLY_JSON, MAGNET_JSON

ASSEMBLY = ASSEMBLY_JSON["name"]
HOUSING = ASSEMBLY_JSON["housing"]

_FULL = "1\tM1\t100\t100\t0.1\t0\t0\t0.0035\n"
_HEADER = "Date\tTime\tField\tIcoil1\t\n"
_ROWS = (
    "2024.12.05\t12:15:30\t28.7457\t1000.0\t\n"
    "2024.12.05\t12:15:31\t28.7517\t1000.0\t\n"
    "2024.12.05\t12:15:32\t28.7578\t1000.0\t\n"
)
# Crash tail as in M10 "2024.12.05 - 11:16:02.txt": NUL padding, then older rows.
_STALE_TAIL = "\x00" * 64 + ".0\t20897.5\t182.4\n" + "2014.07.27\t22:38:31\t22.2053"

FILES = {
    "2024.12.05 - 12:15:30.txt": _FULL + _HEADER + _ROWS,
    "2024.12.05 - 12:15:31.txt": _FULL + _HEADER + _ROWS + _STALE_TAIL,
    "2024.12.05 - 12:15:32.txt": "2\n" + _HEADER,  # short header, no data rows
}
MISSING = "2024.12.05 - 12:15:33.txt"


def _setup(tmp_path):
    db = tmp_path / "test.duckdb"
    add_magnet(MAGNET_JSON, db)
    add_assembly(ASSEMBLY_JSON, db)
    records = tmp_path / "records"
    pupitre_dir = records / "srv-data-install" / HOUSING
    pupitre_dir.mkdir(parents=True)
    with duckdb.connect(str(db)) as con:
        con.execute("DELETE FROM experiments WHERE assembly_name = ?", [ASSEMBLY])
        for i, name in enumerate([*FILES, MISSING], start=1):
            con.execute(
                "INSERT INTO experiments (id, name, file, assembly_name) VALUES (?, ?, ?, ?)",
                [i, name, name, ASSEMBLY],
            )
    for name, content in FILES.items():
        (pupitre_dir / name).write_bytes(content.encode("utf-8"))
    return db, records


def _rows(db):
    with duckdb.connect(str(db)) as con:
        rows = con.execute(
            "SELECT file, header_class, file_integrity, file_checks, file_checked_at "
            "FROM experiments ORDER BY id"
        ).fetchall()
    return {r[0]: (r[1], r[2], json.loads(r[3]) if r[3] else None, r[4]) for r in rows}


def test_file_quality_recorded(tmp_path):
    db, records = _setup(tmp_path)
    results = check_experiment_files.check_experiments(
        str(db), records_base=str(records), verbose=False
    )
    rows = _rows(db)

    header, integrity, checks, checked_at = rows["2024.12.05 - 12:15:30.txt"]
    assert (header, integrity) == ("full", "ok")
    assert checks["rows_read"] == 3 and checks["rows_dropped"] == 0
    assert checked_at is not None

    header, integrity, checks, _ = rows["2024.12.05 - 12:15:31.txt"]
    assert (header, integrity) == ("full", "truncated")
    assert checks["rows_read"] == 3 and checks["rows_dropped"] == 2
    assert checks["reason"] == "corrupt_tail"

    header, integrity, checks, _ = rows["2024.12.05 - 12:15:32.txt"]
    assert (header, integrity) == ("short", "unreadable")
    assert "no data rows" in checks["reason"]

    # a missing file is not recorded: the records base may just be wrong
    assert rows[MISSING] == (None, None, {}, None)
    assert results == {"checked": 3, "skipped": 0, "missing": 1}


def test_already_checked_skipped_unless_recheck(tmp_path):
    db, records = _setup(tmp_path)
    check_experiment_files.check_experiments(str(db), records_base=str(records), verbose=False)

    again = check_experiment_files.check_experiments(
        str(db), records_base=str(records), verbose=False
    )
    assert again == {"checked": 0, "skipped": 3, "missing": 1}

    forced = check_experiment_files.check_experiments(
        str(db), records_base=str(records), recheck=True, verbose=False
    )
    assert forced == {"checked": 3, "skipped": 0, "missing": 1}


def test_assembly_filter(tmp_path):
    db, records = _setup(tmp_path)
    results = check_experiment_files.check_experiments(
        str(db), assembly="NO_SUCH_ASSEMBLY", records_base=str(records), verbose=False
    )
    assert results == {"checked": 0, "skipped": 0, "missing": 0}
