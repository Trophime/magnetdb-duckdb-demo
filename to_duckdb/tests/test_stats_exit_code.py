"""Exit code of compute_op_stats.py / compute_exp_stats.py when record files are missing or unreadable."""

import errno

import duckdb
import pandas as pd
import pytest

import compute_exp_stats
import compute_op_stats
import record_io
from magnetdb import _add_assembly as add_assembly, _add_magnet as add_magnet
from tests.conftest import ASSEMBLY_JSON, MAGNET_JSON

ASSEMBLY = ASSEMBLY_JSON["name"]
HOUSING = ASSEMBLY_JSON["housing"]

# module, extra CLI arguments, ingest_assembly(db, records) call
SCRIPTS = {
    "op": (
        compute_op_stats,
        ["--type", "Pupitre"],
        lambda db, records: compute_op_stats.ingest_assembly(
            ASSEMBLY, str(db), records_dir=str(records), od_type="Pupitre", verbose=False
        ),
    ),
    "exp": (
        compute_exp_stats,
        [],
        lambda db, records: compute_exp_stats.ingest_assembly(
            ASSEMBLY, str(db), records_base=str(records), verbose=False
        ),
    ),
}


@pytest.fixture(params=sorted(SCRIPTS))
def script(request):
    return SCRIPTS[request.param]


def _db(tmp_path, files):
    """DB with the fixture assembly and, per file, one experiments + one Pupitre operationaldata row."""
    db = tmp_path / "test.duckdb"
    add_magnet(MAGNET_JSON, db)
    add_assembly(ASSEMBLY_JSON, db)
    with duckdb.connect(str(db)) as con:
        # drop the experiment row that comes with the fixture assembly
        con.execute("DELETE FROM experiments WHERE assembly_name = ?", [ASSEMBLY])
        for i, name in enumerate(files, start=1):
            con.execute(
                "INSERT INTO experiments (id, name, file, assembly_name) VALUES (?, ?, ?, ?)",
                [i, name, name, ASSEMBLY],
            )
            con.execute(
                "INSERT INTO operationaldata (name, file, assembly_name, type) VALUES (?, ?, ?, 'Pupitre')",
                [name, f"srv-data-install/{HOUSING}/{name}", ASSEMBLY],
            )
    return db


def _records(tmp_path, unreadable=()):
    """Records tree holding only the given files, filled with undecodable bytes."""
    records = tmp_path / "records"
    pupitre_dir = records / "srv-data-install" / HOUSING
    pupitre_dir.mkdir(parents=True)
    for name in unreadable:
        (pupitre_dir / name).write_bytes(b"\x9b\xff\x00\x9b not a pupitre file \x9b")
    return records


def _main(monkeypatch, script, db, records):
    module, extra, _ = script
    monkeypatch.setattr("sys.argv", [
        module.__name__, "--db", str(db), "--assembly", ASSEMBLY,
        "--records-base", str(records), "--quiet", *extra,
    ])
    module.main()


def test_all_files_missing_exits_1(tmp_path, monkeypatch, capsys, script):
    db = _db(tmp_path, ["a.txt", "b.txt"])
    records = _records(tmp_path)

    with pytest.raises(SystemExit) as exc:
        _main(monkeypatch, script, db, records)
    assert exc.value.code == 1

    out = capsys.readouterr().out
    assert "none of the 2 file(s) were found" in out
    assert str(records) in out


def test_some_files_missing_exits_0(tmp_path, monkeypatch, script):
    db = _db(tmp_path, ["a.txt", "b.txt"])
    records = _records(tmp_path, unreadable=["b.txt"])

    _main(monkeypatch, script, db, records)  # no SystemExit


def test_no_files_exits_0(tmp_path, monkeypatch, script):
    db = _db(tmp_path, [])
    records = _records(tmp_path)

    _main(monkeypatch, script, db, records)  # no SystemExit


def test_ingest_assembly_counts_missing(tmp_path, script):
    db = _db(tmp_path, ["a.txt", "b.txt"])
    records = _records(tmp_path, unreadable=["b.txt"])

    results = script[2](db, records)

    assert results["missing"] == 1
    assert len(results["errors"]) == 2


# --- I/O errors (rclone mount drops) -----------------------------------------


@pytest.fixture
def no_wait(monkeypatch):
    """Make load_with_retry's waits instant."""
    monkeypatch.setattr(record_io.time, "sleep", lambda _seconds: None)


def _readable():
    """What load_file returns for a readable record file."""
    return pd.DataFrame({"Field": [0.0, 1.5], "dt": [0.0, 1.0]}), {}


def _fake_load(monkeypatch, script, fail):
    """Replace the script's load_file; raise ``fail(path, n)`` (n = call number for that file) when not None."""
    calls = {}

    def load(path):
        calls[path.name] = calls.get(path.name, 0) + 1
        exc = fail(path, calls[path.name])
        if exc is not None:
            raise exc
        return _readable()

    monkeypatch.setattr(script[0], "load_file", load)
    return calls


def _eio():
    return OSError(errno.EIO, "Input/output error")


def test_transient_io_error_is_retried(tmp_path, monkeypatch, no_wait, script):
    db = _db(tmp_path, ["a.txt"])
    records = _records(tmp_path)
    calls = _fake_load(monkeypatch, script, lambda _path, n: _eio() if n == 1 else None)

    results = script[2](db, records)

    assert calls == {"a.txt": 2}
    assert results["new"] == 1
    assert results["errors"] == []
    assert results["io_errors"] == 0
    assert not results["aborted"]


def test_persistent_io_error_on_one_file_is_left_for_next_run(tmp_path, monkeypatch, no_wait, script):
    db = _db(tmp_path, ["a.txt", "b.txt"])
    records = _records(tmp_path)
    calls = _fake_load(
        monkeypatch, script, lambda path, _n: _eio() if path.name == "b.txt" else None
    )

    results = script[2](db, records)

    assert calls["b.txt"] == len(record_io.IO_RETRY_WAITS) + 1
    assert results["new"] == 1
    assert len(results["errors"]) == 1
    assert results["io_errors"] == 1
    assert not results["aborted"]
    _main(monkeypatch, script, db, records)  # no SystemExit: b.txt failed alone

    # b.txt was not marked processed: the next run (mount back) picks it up.
    _fake_load(monkeypatch, script, lambda _path, _n: None)
    rerun = script[2](db, records)
    assert (rerun["new"], rerun["skipped"]) == (1, 1)


def test_mount_down_aborts_and_exits_1(tmp_path, monkeypatch, capsys, no_wait, script):
    db = _db(tmp_path, ["a.txt", "b.txt", "c.txt", "d.txt"])
    records = _records(tmp_path)
    calls = _fake_load(monkeypatch, script, lambda _path, _n: _eio())

    results = script[2](db, records)

    assert len(calls) == record_io.MAX_CONSECUTIVE_IO_FAILURES
    assert results["io_errors"] == record_io.MAX_CONSECUTIVE_IO_FAILURES
    assert results["aborted"]

    with pytest.raises(SystemExit) as exc:
        _main(monkeypatch, script, db, records)
    assert exc.value.code == 1
    assert "mount looks down" in capsys.readouterr().out


def test_non_io_os_error_is_not_retried(tmp_path, monkeypatch, no_wait, script):
    db = _db(tmp_path, ["a.txt"])
    records = _records(tmp_path)
    calls = _fake_load(
        monkeypatch, script, lambda _path, _n: OSError(errno.EACCES, "Permission denied")
    )

    with pytest.raises(OSError) as exc:
        script[2](db, records)

    assert exc.value.errno == errno.EACCES
    assert calls == {"a.txt": 1}
