"""Tests for schema.py — DDL creation and idempotency."""

import duckdb
import pytest

from schema import COIL_TYPES, ensure_schema

EXPECTED_TABLES = {
    "materials",
    "parts",
    "magnets",
    "magnet_parts",
    "sites",
    "site_magnets",
    "experiments",
    "operationaldata",
    "overview_records",
    "housing_config",
    "op_run_scalars",
    "op_site_bin_stats",
    "op_part_bin_stats",
    "op_stats_processed",
    "exp_run_scalars",
    "exp_site_bin_stats",
    "exp_part_bin_stats",
    "exp_stats_processed",
    "hoop_stress_processed",
    "hoop_stress_bin_stats",
    "hoop_stress_fatigue",
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
    ("site_magnets", "site_name", "sites"),
    ("site_magnets", "magnet_name", "magnets"),
    ("experiments", "site_name", "sites"),
])
def test_foreign_key_columns_exist(con, table, fk_col, fk_table):
    """Spot-check that FK columns are present (via PRAGMA table_info)."""
    cols = {row[1] for row in con.execute(f"PRAGMA table_info({table})").fetchall()}
    assert fk_col in cols, f"{table}.{fk_col} missing"
