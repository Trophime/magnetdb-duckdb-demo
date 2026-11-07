"""Tests for schema.py — DDL creation and idempotency."""

import subprocess
import sys
from pathlib import Path

import duckdb
import pytest

from schema import COIL_TYPES, ensure_schema

TO_DUCKDB_DIR = Path(__file__).resolve().parent.parent

EXPECTED_TABLES = {
    "materials",
    "parts",
    "magnets",
    "magnet_parts",
    "assemblies",
    "assembly_magnets",
    "experiments",
    "operationaldata",
    "overview_records",
    "housing_config",
    "housing_config_versions",
    "pupitre_etl_magnet",
    "tags",
    "check_rules",
    "record_tags",
    "op_run_scalars",
    "op_assembly_bin_stats",
    "op_part_bin_stats",
    "op_stats_processed",
    "exp_run_scalars",
    "exp_assembly_bin_stats",
    "exp_part_bin_stats",
    "exp_stats_processed",
    "hoop_stress_processed",
    "hoop_stress_bin_stats",
    "hoop_stress_fatigue",
    "hoop_stress_fatigue_bins",
    "users",
    "operation_log",
}


def _table_names(con) -> set[str]:
    return {row[0] for row in con.execute("SHOW TABLES").fetchall()}


def test_ensure_schema_creates_all_tables():
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    assert _table_names(con) == EXPECTED_TABLES
    con.close()


def test_ensure_schema_is_idempotent():
    """Calling ensure_schema twice on the same connection must not raise."""
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    ensure_schema(con)
    assert _table_names(con) == EXPECTED_TABLES
    con.close()


def test_ensure_schema_on_empty_file(tmp_path):
    """ensure_schema must work on a freshly created file-backed database."""
    db_path = tmp_path / "new.duckdb"
    con = duckdb.connect(str(db_path))
    ensure_schema(con)
    assert _table_names(con) == EXPECTED_TABLES
    con.close()


def _run_child(code: str) -> subprocess.CompletedProcess:
    """Run *code* in a fresh Python process with ``to_duckdb/`` importable."""
    return subprocess.run(
        [sys.executable, "-c", code], cwd=TO_DUCKDB_DIR, capture_output=True, text=True
    )


def test_killed_writer_leaves_openable_db(tmp_path):
    """A process killed after ensure_schema() (no close, no checkpoint) must
    leave a WAL that DuckDB can replay, so the database still opens."""
    db_path = tmp_path / "killed.duckdb"
    con = duckdb.connect(str(db_path))
    ensure_schema(con)
    con.close()

    killed = _run_child(
        "import os, duckdb\n"
        "from schema import ensure_schema\n"
        f"con = duckdb.connect({str(db_path)!r})\n"
        "ensure_schema(con)\n"
        "os._exit(0)\n"
    )
    assert killed.returncode == 0, killed.stderr
    assert db_path.with_name(db_path.name + ".wal").exists()

    reopened = _run_child(
        "import duckdb\n"
        f"con = duckdb.connect({str(db_path)!r}, read_only=True)\n"
        "print(con.execute('SELECT count(*) FROM operationaldata').fetchone()[0])\n"
    )
    assert reopened.returncode == 0, reopened.stderr
    assert reopened.stdout.strip() == "0"


def test_ensure_schema_sets_missing_operationaldata_id_default():
    """An old database whose operationaldata.id has no default gets the sequence default."""
    con = duckdb.connect(":memory:")
    con.execute("CREATE SEQUENCE operationaldata_id_seq START 1")
    con.execute("CREATE TABLE operationaldata (id INTEGER PRIMARY KEY, file VARCHAR UNIQUE)")
    ensure_schema(con)
    default = con.execute(
        "SELECT column_default FROM information_schema.columns "
        "WHERE table_name = 'operationaldata' AND column_name = 'id'"
    ).fetchone()[0]
    assert default == "nextval('operationaldata_id_seq')"
    con.close()


def test_coil_types_contains_expected_values():
    assert "helix" in COIL_TYPES
    assert "bitter" in COIL_TYPES
    assert "ring" not in COIL_TYPES
    assert "lead" not in COIL_TYPES


@pytest.mark.parametrize("table,fk_col,fk_table", [
    ("parts", "material_name", "materials"),
    ("magnet_parts", "magnet_name", "magnets"),
    ("magnet_parts", "part_name", "parts"),
    ("assembly_magnets", "assembly_name", "assemblies"),
    ("assembly_magnets", "magnet_name", "magnets"),
    ("experiments", "assembly_name", "assemblies"),
])
def test_foreign_key_columns_exist(con, table, fk_col, fk_table):
    """Spot-check that FK columns are present (via PRAGMA table_info)."""
    cols = {row[1] for row in con.execute(f"PRAGMA table_info({table})").fetchall()}
    assert fk_col in cols, f"{table}.{fk_col} missing"


@pytest.mark.parametrize("table", ["assemblies", "parts", "magnets"])
def test_status_history_column_exists(con, table):
    cols = {row[1] for row in con.execute(f"PRAGMA table_info({table})").fetchall()}
    assert "status_history" in cols


@pytest.mark.parametrize(
    "column", ["header_class", "file_integrity", "file_checks", "file_checked_at"]
)
def test_experiments_file_quality_columns_exist(con, column):
    cols = {row[1] for row in con.execute("PRAGMA table_info(experiments)").fetchall()}
    assert column in cols


def _columns(con, table: str) -> set[str]:
    return {row[1] for row in con.execute(f"PRAGMA table_info({table})").fetchall()}


@pytest.mark.parametrize("column", ["t_start", "t_end", "mode"])
def test_operationaldata_metadata_columns_exist(con, column):
    assert column in _columns(con, "operationaldata")


def test_overview_records_has_sources_signal_stats(con):
    cols = _columns(con, "overview_records")
    assert "sources_signal_stats" in cols
    assert "sources_stats" not in cols


def test_sources_stats_renamed_to_sources_signal_stats_keeps_data(con):
    """A pre-rename DB keeps its Stats file lists under sources_signal_stats."""
    con.execute(
        "ALTER TABLE overview_records RENAME COLUMN sources_signal_stats TO sources_stats"
    )
    con.execute(
        "INSERT INTO overview_records (filename, sources_stats) "
        "VALUES ('M8_Overview_260226-0948', ['M8_Stats_260226-094838.tdms'])"
    )
    ensure_schema(con)
    ensure_schema(con)  # a second run must be a no-op
    cols = _columns(con, "overview_records")
    assert "sources_stats" not in cols
    row = con.execute(
        "SELECT sources_signal_stats FROM overview_records "
        "WHERE filename = 'M8_Overview_260226-0948'"
    ).fetchone()
    assert row[0] == ["M8_Stats_260226-094838.tdms"]


def test_decommisioned_typo_migrated_to_disassembled(con):
    """A row seeded with the legacy 'decommisioned' (typo) status value must
    be rewritten to 'disassembled' the next time ensure_schema() runs."""
    con.execute(
        "INSERT INTO assemblies (name, status, housing, commissioned_at, decommissioned_at) "
        "VALUES ('A_LEGACY', 'decommisioned', NULL, '2020-01-01', '2020-06-01')"
    )
    ensure_schema(con)
    row = con.execute("SELECT status FROM assemblies WHERE name = 'A_LEGACY'").fetchone()
    assert row[0] == "disassembled"
