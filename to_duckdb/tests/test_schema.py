"""Tests for schema.py — DDL creation and idempotency."""

import duckdb
import pytest

from schema import COIL_TYPES, ensure_schema

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
