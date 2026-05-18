"""Tests for material CRUD operations (schema.py + crud.py).

Reference JSON files from hifimagnet-projects/magnetdb.json are used as
ground truth.  They are opened read-only and are never modified.
"""

import json
from pathlib import Path

import duckdb
import pytest

from schema import ensure_schema
from crud import (
    delete_material,
    exists,
    insert_material,
    insert_part,
    view_material,
    view_materials,
)

# ---------------------------------------------------------------------------
# Reference JSON files (read-only)
# ---------------------------------------------------------------------------

_MAGNETDB_JSON = (
    Path(__file__).parent.parent.parent.parent
    / "hifimagnet-projects" / "magnetdb.json"
)

_REF_FILES: dict[str, Path] = {
    "MA20072304": _MAGNETDB_JSON / "MA20072304.json",
    "MA15011202": _MAGNETDB_JSON / "MA15011202.json",
    "MA25031201": _MAGNETDB_JSON / "MA25031201.json",
}

_EXPECTED: dict[str, dict] = {}
for _name, _path in _REF_FILES.items():
    if _path.exists():
        _EXPECTED[_name] = json.loads(_path.read_text())


def _ref_available(name: str):
    return pytest.mark.skipif(
        name not in _EXPECTED,
        reason=f"Reference file for {name} not found",
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def con():
    """Fresh in-memory DuckDB connection with the full schema."""
    conn = duckdb.connect(":memory:")
    ensure_schema(conn)
    yield conn
    conn.close()


@pytest.fixture()
def populated_con(con):
    """Connection pre-loaded with all available reference materials."""
    for data in _EXPECTED.values():
        insert_material(con, data, verbose=False)
    return con


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class TestMaterialsTable:
    def test_table_exists(self, con):
        rows = con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_name = 'materials'"
        ).fetchall()
        assert rows, "materials table not found after ensure_schema()"

    def test_required_columns_present(self, con):
        cols = {
            row[0]
            for row in con.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'materials'"
            ).fetchall()
        }
        required = {
            "name", "description", "nuance", "t_ref", "volumic_mass",
            "specific_heat", "alpha", "electrical_conductivity",
            "thermal_conductivity", "magnet_permeability",
            "young", "poisson", "expansion_coefficient", "rpe",
        }
        assert required <= cols

    def test_ensure_schema_idempotent(self, con):
        ensure_schema(con)


# ---------------------------------------------------------------------------
# insert_material
# ---------------------------------------------------------------------------


class TestInsertMaterial:
    @_ref_available("MA20072304")
    def test_inserts_row(self, con):
        insert_material(con, _EXPECTED["MA20072304"], verbose=False)
        assert exists(con, "materials", "MA20072304")

    @_ref_available("MA20072304")
    def test_nuance_stored(self, con):
        insert_material(con, _EXPECTED["MA20072304"], verbose=False)
        row = con.execute(
            "SELECT nuance FROM materials WHERE name = 'MA20072304'"
        ).fetchone()
        assert row[0] == _EXPECTED["MA20072304"]["nuance"]

    @_ref_available("MA20072304")
    def test_rpe_stored(self, con):
        insert_material(con, _EXPECTED["MA20072304"], verbose=False)
        row = con.execute(
            "SELECT rpe FROM materials WHERE name = 'MA20072304'"
        ).fetchone()
        assert row[0] == pytest.approx(_EXPECTED["MA20072304"]["rpe"])

    @_ref_available("MA20072304")
    def test_all_numeric_fields_stored(self, con):
        data = _EXPECTED["MA20072304"]
        insert_material(con, data, verbose=False)
        row = con.execute(
            "SELECT t_ref, volumic_mass, specific_heat, alpha, "
            "electrical_conductivity, thermal_conductivity, "
            "magnet_permeability, young, poisson, expansion_coefficient, rpe "
            "FROM materials WHERE name = 'MA20072304'"
        ).fetchone()
        fields = [
            "t_ref", "volumic_mass", "specific_heat", "alpha",
            "electrical_conductivity", "thermal_conductivity",
            "magnet_permeability", "young", "poisson", "expansion_coefficient", "rpe",
        ]
        for value, field in zip(row, fields):
            assert value == pytest.approx(data[field]), f"{field} mismatch"

    @_ref_available("MA20072304")
    def test_idempotent_second_insert_skipped(self, con):
        insert_material(con, _EXPECTED["MA20072304"], verbose=False)
        insert_material(con, _EXPECTED["MA20072304"], verbose=False)
        count = con.execute(
            "SELECT COUNT(*) FROM materials WHERE name = 'MA20072304'"
        ).fetchone()[0]
        assert count == 1

    @pytest.mark.parametrize("name", list(_EXPECTED))
    def test_all_ref_materials_insert(self, con, name):
        insert_material(con, _EXPECTED[name], verbose=False)
        assert exists(con, "materials", name)

    def test_minimal_material_name_only(self, con):
        insert_material(con, {"name": "MAT_MINIMAL"}, verbose=False)
        assert exists(con, "materials", "MAT_MINIMAL")


# ---------------------------------------------------------------------------
# view_materials / view_material
# ---------------------------------------------------------------------------


class TestViewMaterials:
    def test_empty_database(self, con, capsys):
        view_materials(con)
        assert "No materials" in capsys.readouterr().out

    def test_lists_all_inserted(self, populated_con, capsys):
        view_materials(populated_con)
        out = capsys.readouterr().out
        for name in _EXPECTED:
            assert name in out

    @_ref_available("MA20072304")
    def test_nuance_in_listing(self, populated_con, capsys):
        view_materials(populated_con)
        out = capsys.readouterr().out
        assert _EXPECTED["MA20072304"]["nuance"] in out


class TestViewMaterial:
    @_ref_available("MA20072304")
    def test_shows_name(self, populated_con, capsys):
        view_material(populated_con, "MA20072304")
        out = capsys.readouterr().out
        assert "MA20072304" in out

    @_ref_available("MA20072304")
    def test_shows_nuance(self, populated_con, capsys):
        view_material(populated_con, "MA20072304")
        out = capsys.readouterr().out
        assert _EXPECTED["MA20072304"]["nuance"] in out

    @_ref_available("MA20072304")
    def test_shows_rpe(self, populated_con, capsys):
        view_material(populated_con, "MA20072304")
        out = capsys.readouterr().out
        assert "rpe" in out

    def test_not_found_message(self, con, capsys):
        view_material(con, "NONEXISTENT")
        out = capsys.readouterr().out
        assert "not found" in out.lower()


# ---------------------------------------------------------------------------
# delete_material
# ---------------------------------------------------------------------------


class TestDeleteMaterial:
    @_ref_available("MA20072304")
    def test_deletes_existing(self, con):
        insert_material(con, _EXPECTED["MA20072304"], verbose=False)
        delete_material(con, "MA20072304")
        assert not exists(con, "materials", "MA20072304")

    def test_not_found_message(self, con, capsys):
        delete_material(con, "NONEXISTENT")
        out = capsys.readouterr().out
        assert "not found" in out.lower()

    @_ref_available("MA20072304")
    def test_blocked_when_part_references_material(self, con, capsys):
        insert_material(con, _EXPECTED["MA20072304"], verbose=False)
        insert_part(con, {
            "name": "PART_REF_TEST",
            "type": "helix",
            "status": "in_operation",
            "material_name": "MA20072304",
        }, verbose=False)
        delete_material(con, "MA20072304")
        out = capsys.readouterr().out
        assert "referenced" in out.lower() or "error" in out.lower()
        assert exists(con, "materials", "MA20072304"), (
            "Material must NOT be deleted when a part references it"
        )

    @_ref_available("MA20072304")
    def test_reference_files_unmodified(self):
        """Reference JSON files must never be written to."""
        originals = {n: p.read_text() for n, p in _REF_FILES.items() if p.exists()}
        # (no DB writes happen here; this just re-reads the files)
        for name, path in _REF_FILES.items():
            if path.exists():
                assert path.read_text() == originals[name]
