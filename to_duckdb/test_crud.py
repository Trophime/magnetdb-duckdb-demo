"""Tests for CRUD helpers in crud.py.

Covers: material, part, magnet, site (with housing FK), and overview_record.
All tests use an in-memory DuckDB connection so they leave no files on disk.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime

import duckdb
import pytest

from schema import ensure_schema
from crud import (
    exists,
    infer_magnet_type,
    insert_material,
    insert_part,
    insert_magnet,
    insert_magnet_parts,
    insert_magnet_part_row,
    insert_housing_config,
    insert_housing_config_from_magnetrun,
    insert_site,
    insert_site_magnets,
    insert_experiments,
    insert_overview_record,
    upsert_overview_record,
    attach_site_to_overview_record,
    delete_magnet,
    delete_site,
)

# ---------------------------------------------------------------------------
# Minimal stub for OverviewRecord / FileSet (avoids python_magnetrun import)
# ---------------------------------------------------------------------------


@dataclass
class _FakeFileSet:
    overview: list = field(default_factory=list)
    archive: list = field(default_factory=list)
    pupitre: list = field(default_factory=list)
    default: list = field(default_factory=list)
    trigger: list = field(default_factory=list)
    spike: list = field(default_factory=list)
    hybrid_kHz: list = field(default_factory=list)
    hybrid_rms: list = field(default_factory=list)
    hybrid_trigger: list = field(default_factory=list)
    hybrid_vprocess: list = field(default_factory=list)
    pigbrother_runlog: list = field(default_factory=list)
    pupitre_runlog: list = field(default_factory=list)


@dataclass
class _FakeOverviewRecord:
    filename: str
    housing: str
    mode: str = ""
    t0: datetime | None = None
    duration: float = 0.0
    teb: float = 0.0
    BP: float = 0.0
    sources: _FakeFileSet | None = None
    signatures: dict = field(default_factory=dict)
    sync_info: dict = field(default_factory=dict)
    flow_params: dict = field(default_factory=dict)
    metrics: dict = field(default_factory=dict)
    debitbrut: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Shared fixture data
# ---------------------------------------------------------------------------

_HOUSING_M9 = {
    "name": "M9",
    "coil_assignment": {"Insert": "GR1", "Bitter": "GR2"},
    "formats": ["pupitre", "pigbrother"],
    "extra_config": None,
}

_MATERIAL_MINIMAL = {"name": "Cu"}

_MATERIAL_FULL = {
    "name": "CuBe",
    "description": "Copper-Beryllium alloy",
    "nuance": "CuBe2",
    "t_ref": 293.0,
    "volumic_mass": 8250.0,
    "specific_heat": 380.0,
    "alpha": 0.0039,
    "electrical_conductivity": 2.5e7,
    "thermal_conductivity": 200.0,
    "magnet_permeability": 1.0,
    "young": 1.28e11,
    "poisson": 0.34,
    "expansion_coefficient": 17e-6,
    "rpe": 300.0,
}

_PART_HELIX = {"name": "H1", "type": "helix", "status": "in_use"}
_PART_BITTER = {"name": "B1", "type": "bitter", "status": "in_use"}
_PART_SUPPORT = {"name": "Support1", "type": "support", "status": "in_use"}

_MAGNET_INSERT = {"name": "MAG_INSERT", "status": "in_study"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def con():
    """In-memory DuckDB connection with full schema."""
    conn = duckdb.connect(":memory:")
    ensure_schema(conn)
    yield conn
    conn.close()


@pytest.fixture()
def con_with_housing(con):
    """Connection with M9 housing config pre-loaded."""
    insert_housing_config(con, _HOUSING_M9, verbose=False)
    return con


@pytest.fixture()
def con_with_site(con_with_housing):
    """Connection with M9 housing + LNCMI-M9 site pre-loaded."""
    insert_site(
        con_with_housing,
        {"name": "LNCMI-M9", "housing": "M9", "status": "in_study"},
        verbose=False,
        create_housing=False,
    )
    return con_with_housing


# ---------------------------------------------------------------------------
# exists()
# ---------------------------------------------------------------------------


class TestExists:
    def test_false_for_missing(self, con):
        assert exists(con, "materials", "nonexistent") is False

    def test_true_after_insert(self, con):
        insert_material(con, _MATERIAL_MINIMAL, verbose=False)
        assert exists(con, "materials", "Cu") is True

    def test_false_after_delete_magnet(self, con):
        insert_magnet(con, _MAGNET_INSERT, "insert", verbose=False)
        delete_magnet(con, "MAG_INSERT")
        assert exists(con, "magnets", "MAG_INSERT") is False


# ---------------------------------------------------------------------------
# Material
# ---------------------------------------------------------------------------


class TestMaterialCRUD:
    def test_insert_minimal_creates_row(self, con):
        insert_material(con, _MATERIAL_MINIMAL, verbose=False)
        row = con.execute(
            "SELECT name FROM materials WHERE name = 'Cu'"
        ).fetchone()
        assert row is not None and row[0] == "Cu"

    def test_insert_all_fields_stored(self, con):
        insert_material(con, _MATERIAL_FULL, verbose=False)
        row = con.execute(
            "SELECT name, description, nuance, t_ref, volumic_mass, rpe "
            "FROM materials WHERE name = 'CuBe'"
        ).fetchone()
        assert row[0] == "CuBe"
        assert row[1] == "Copper-Beryllium alloy"
        assert row[2] == "CuBe2"
        assert row[3] == pytest.approx(293.0)
        assert row[4] == pytest.approx(8250.0)
        assert row[5] == pytest.approx(300.0)

    def test_insert_idempotent_no_error(self, con):
        insert_material(con, _MATERIAL_MINIMAL, verbose=False)
        insert_material(con, _MATERIAL_MINIMAL, verbose=False)
        count = con.execute(
            "SELECT COUNT(*) FROM materials WHERE name = 'Cu'"
        ).fetchone()[0]
        assert count == 1

    def test_insert_none_optional_fields_are_null(self, con):
        insert_material(con, _MATERIAL_MINIMAL, verbose=False)
        row = con.execute(
            "SELECT description, nuance, t_ref FROM materials WHERE name = 'Cu'"
        ).fetchone()
        assert row[0] is None
        assert row[1] is None
        assert row[2] is None


# ---------------------------------------------------------------------------
# Part
# ---------------------------------------------------------------------------


class TestPartCRUD:
    def test_insert_creates_row(self, con):
        insert_part(con, _PART_HELIX, verbose=False)
        row = con.execute(
            "SELECT name, type, status FROM parts WHERE name = 'H1'"
        ).fetchone()
        assert row == ("H1", "helix", "in_use")

    def test_insert_idempotent(self, con):
        insert_part(con, _PART_HELIX, verbose=False)
        insert_part(con, _PART_HELIX, verbose=False)
        count = con.execute(
            "SELECT COUNT(*) FROM parts WHERE name = 'H1'"
        ).fetchone()[0]
        assert count == 1

    def test_insert_with_material_name_fk(self, con):
        insert_material(con, _MATERIAL_MINIMAL, verbose=False)
        part = {"name": "H2", "type": "helix", "status": "in_use", "material_name": "Cu"}
        insert_part(con, part, verbose=False)
        row = con.execute(
            "SELECT material_name FROM parts WHERE name = 'H2'"
        ).fetchone()
        assert row[0] == "Cu"

    def test_insert_with_nested_material_dict(self, con):
        insert_material(con, _MATERIAL_MINIMAL, verbose=False)
        part = {
            "name": "H3",
            "type": "helix",
            "status": "in_use",
            "material": {"name": "Cu"},
        }
        insert_part(con, part, verbose=False)
        row = con.execute(
            "SELECT material_name FROM parts WHERE name = 'H3'"
        ).fetchone()
        assert row[0] == "Cu"

    def test_insert_without_material_stores_null(self, con):
        insert_part(con, _PART_HELIX, verbose=False)
        row = con.execute(
            "SELECT material_name FROM parts WHERE name = 'H1'"
        ).fetchone()
        assert row[0] is None


# ---------------------------------------------------------------------------
# Magnet
# ---------------------------------------------------------------------------


class TestInferMagnetType:
    def test_helix_only_is_insert(self):
        parts = [{"type": "helix"}, {"type": "helix"}]
        assert infer_magnet_type(parts) == "insert"

    def test_bitter_only_is_bitters(self):
        parts = [{"type": "bitter"}, {"type": "bitter"}]
        assert infer_magnet_type(parts) == "bitters"

    def test_mixed_is_hybrid(self):
        parts = [{"type": "helix"}, {"type": "bitter"}]
        assert infer_magnet_type(parts) == "hybrid"

    def test_unknown_type_is_unknown(self):
        parts = [{"type": "support"}]
        assert infer_magnet_type(parts) == "unknown"

    def test_empty_is_unknown(self):
        assert infer_magnet_type([]) == "unknown"


class TestMagnetCRUD:
    def test_insert_creates_row(self, con):
        insert_magnet(con, _MAGNET_INSERT, "insert", verbose=False)
        row = con.execute(
            "SELECT name, type, status FROM magnets WHERE name = 'MAG_INSERT'"
        ).fetchone()
        assert row == ("MAG_INSERT", "insert", "in_study")

    def test_insert_idempotent(self, con):
        insert_magnet(con, _MAGNET_INSERT, "insert", verbose=False)
        insert_magnet(con, _MAGNET_INSERT, "insert", verbose=False)
        count = con.execute(
            "SELECT COUNT(*) FROM magnets WHERE name = 'MAG_INSERT'"
        ).fetchone()[0]
        assert count == 1

    def test_insert_magnet_parts_links(self, con):
        insert_part(con, _PART_HELIX, verbose=False)
        insert_part(con, _PART_BITTER, verbose=False)
        insert_magnet(con, _MAGNET_INSERT, "hybrid", verbose=False)
        insert_magnet_parts(
            con,
            "MAG_INSERT",
            [_PART_HELIX, _PART_BITTER],
            verbose=False,
        )
        count = con.execute(
            "SELECT COUNT(*) FROM magnet_parts WHERE magnet_name = 'MAG_INSERT'"
        ).fetchone()[0]
        assert count == 2

    def test_insert_magnet_parts_assigns_rank(self, con):
        insert_part(con, _PART_HELIX, verbose=False)
        insert_part(con, _PART_BITTER, verbose=False)
        insert_magnet(con, _MAGNET_INSERT, "hybrid", verbose=False)
        insert_magnet_parts(
            con,
            "MAG_INSERT",
            [_PART_HELIX, _PART_BITTER],
            verbose=False,
        )
        rows = con.execute(
            "SELECT part_name, rank FROM magnet_parts "
            "WHERE magnet_name = 'MAG_INSERT' ORDER BY rank"
        ).fetchall()
        assert rows[0] == ("H1", 0)
        assert rows[1] == ("B1", 1)

    def test_insert_magnet_parts_assigns_coil_index(self, con):
        insert_part(con, _PART_HELIX, verbose=False)
        insert_part(con, _PART_BITTER, verbose=False)
        insert_part(con, _PART_SUPPORT, verbose=False)
        insert_magnet(con, _MAGNET_INSERT, "hybrid", verbose=False)
        insert_magnet_parts(
            con,
            "MAG_INSERT",
            [_PART_SUPPORT, _PART_HELIX, _PART_BITTER],
            verbose=False,
        )
        rows = con.execute(
            "SELECT part_name, coil_index FROM magnet_parts "
            "WHERE magnet_name = 'MAG_INSERT' ORDER BY rank"
        ).fetchall()
        assert rows[0] == ("Support1", None)
        assert rows[1] == ("H1", 1)
        assert rows[2] == ("B1", 2)

    def test_insert_magnet_parts_idempotent(self, con):
        insert_part(con, _PART_HELIX, verbose=False)
        insert_magnet(con, _MAGNET_INSERT, "insert", verbose=False)
        insert_magnet_parts(con, "MAG_INSERT", [_PART_HELIX], verbose=False)
        insert_magnet_parts(con, "MAG_INSERT", [_PART_HELIX], verbose=False)
        count = con.execute(
            "SELECT COUNT(*) FROM magnet_parts WHERE magnet_name = 'MAG_INSERT'"
        ).fetchone()[0]
        assert count == 1

    def test_insert_magnet_part_row(self, con):
        insert_part(con, _PART_HELIX, verbose=False)
        insert_magnet(con, _MAGNET_INSERT, "insert", verbose=False)
        insert_magnet_part_row(con, "MAG_INSERT", "H1", rank=0, coil_index=1)
        row = con.execute(
            "SELECT coil_index FROM magnet_parts "
            "WHERE magnet_name = 'MAG_INSERT' AND part_name = 'H1'"
        ).fetchone()
        assert row[0] == 1

    def test_insert_magnet_part_row_idempotent(self, con):
        insert_part(con, _PART_HELIX, verbose=False)
        insert_magnet(con, _MAGNET_INSERT, "insert", verbose=False)
        insert_magnet_part_row(con, "MAG_INSERT", "H1", rank=0, coil_index=1)
        insert_magnet_part_row(con, "MAG_INSERT", "H1", rank=0, coil_index=1)
        count = con.execute(
            "SELECT COUNT(*) FROM magnet_parts "
            "WHERE magnet_name = 'MAG_INSERT' AND part_name = 'H1'"
        ).fetchone()[0]
        assert count == 1

    def test_delete_magnet_removes_row_and_parts(self, con):
        insert_part(con, _PART_HELIX, verbose=False)
        insert_magnet(con, _MAGNET_INSERT, "insert", verbose=False)
        insert_magnet_parts(con, "MAG_INSERT", [_PART_HELIX], verbose=False)
        delete_magnet(con, "MAG_INSERT")
        assert not exists(con, "magnets", "MAG_INSERT")
        count = con.execute(
            "SELECT COUNT(*) FROM magnet_parts WHERE magnet_name = 'MAG_INSERT'"
        ).fetchone()[0]
        assert count == 0


# ---------------------------------------------------------------------------
# Site
# ---------------------------------------------------------------------------


class TestSiteCRUD:
    def test_insert_creates_row(self, con_with_housing):
        insert_site(
            con_with_housing,
            {"name": "LNCMI-M9", "housing": "M9"},
            verbose=False,
            create_housing=False,
        )
        assert exists(con_with_housing, "sites", "LNCMI-M9")

    def test_insert_stores_housing_fk(self, con_with_housing):
        insert_site(
            con_with_housing,
            {"name": "LNCMI-M9", "housing": "M9"},
            verbose=False,
            create_housing=False,
        )
        row = con_with_housing.execute(
            "SELECT housing FROM sites WHERE name = 'LNCMI-M9'"
        ).fetchone()
        assert row[0] == "M9"

    def test_insert_idempotent(self, con_with_housing):
        insert_site(
            con_with_housing,
            {"name": "LNCMI-M9", "housing": "M9"},
            verbose=False,
            create_housing=False,
        )
        insert_site(
            con_with_housing,
            {"name": "LNCMI-M9", "housing": "M9"},
            verbose=False,
            create_housing=False,
        )
        count = con_with_housing.execute(
            "SELECT COUNT(*) FROM sites WHERE name = 'LNCMI-M9'"
        ).fetchone()[0]
        assert count == 1

    def test_insert_without_housing_ok(self, con):
        insert_site(con, {"name": "LNCMI-NOHOUSING"}, verbose=False)
        assert exists(con, "sites", "LNCMI-NOHOUSING")

    def test_insert_missing_housing_raises_when_no_create(self, con):
        with pytest.raises(ValueError, match="Housing config"):
            insert_site(
                con,
                {"name": "LNCMI-M9", "housing": "M9"},
                verbose=False,
                create_housing=False,
            )

    def test_insert_auto_creates_housing_config(self, con):
        pytest.importorskip("python_magnetrun")
        insert_site(
            con,
            {"name": "LNCMI-M9", "housing": "M9"},
            verbose=False,
            create_housing=True,
        )
        assert exists(con, "sites", "LNCMI-M9")
        assert exists(con, "housing_config", "M9")

    def test_insert_auto_create_is_idempotent(self, con):
        pytest.importorskip("python_magnetrun")
        insert_site(
            con,
            {"name": "LNCMI-M9", "housing": "M9"},
            verbose=False,
            create_housing=True,
        )
        insert_site(
            con,
            {"name": "LNCMI-M9", "housing": "M9"},
            verbose=False,
            create_housing=True,
        )
        count = con.execute(
            "SELECT COUNT(*) FROM housing_config WHERE name = 'M9'"
        ).fetchone()[0]
        assert count == 1

    def test_insert_default_status(self, con):
        insert_site(con, {"name": "LNCMI-S"}, verbose=False)
        row = con.execute(
            "SELECT status FROM sites WHERE name = 'LNCMI-S'"
        ).fetchone()
        assert row[0] == "in_study"

    def test_delete_site_removes_row_and_dependents(self, con_with_site):
        insert_magnet(con_with_site, _MAGNET_INSERT, "insert", verbose=False)
        insert_site_magnets(
            con_with_site, "LNCMI-M9", ["MAG_INSERT"], verbose=False
        )
        insert_experiments(
            con_with_site,
            "LNCMI-M9",
            [{"file": "run001"}],
            verbose=False,
        )
        delete_site(con_with_site, "LNCMI-M9")
        assert not exists(con_with_site, "sites", "LNCMI-M9")
        count_mag = con_with_site.execute(
            "SELECT COUNT(*) FROM site_magnets WHERE site_name = 'LNCMI-M9'"
        ).fetchone()[0]
        assert count_mag == 0
        count_exp = con_with_site.execute(
            "SELECT COUNT(*) FROM experiments WHERE site_name = 'LNCMI-M9'"
        ).fetchone()[0]
        assert count_exp == 0


class TestSiteMagnetsCRUD:
    def test_insert_links_magnet_to_site(self, con_with_site):
        insert_magnet(con_with_site, _MAGNET_INSERT, "insert", verbose=False)
        insert_site_magnets(
            con_with_site, "LNCMI-M9", ["MAG_INSERT"], verbose=False
        )
        row = con_with_site.execute(
            "SELECT site_name, magnet_name FROM site_magnets "
            "WHERE site_name = 'LNCMI-M9' AND magnet_name = 'MAG_INSERT'"
        ).fetchone()
        assert row is not None

    def test_insert_idempotent(self, con_with_site):
        insert_magnet(con_with_site, _MAGNET_INSERT, "insert", verbose=False)
        insert_site_magnets(
            con_with_site, "LNCMI-M9", ["MAG_INSERT"], verbose=False
        )
        insert_site_magnets(
            con_with_site, "LNCMI-M9", ["MAG_INSERT"], verbose=False
        )
        count = con_with_site.execute(
            "SELECT COUNT(*) FROM site_magnets "
            "WHERE site_name = 'LNCMI-M9' AND magnet_name = 'MAG_INSERT'"
        ).fetchone()[0]
        assert count == 1

    def test_insert_with_offsets(self, con_with_site):
        insert_magnet(con_with_site, _MAGNET_INSERT, "insert", verbose=False)
        entry = {
            "name": "MAG_INSERT",
            "z_offset": 1.5,
            "r_offset": 0.5,
            "parallax": 0.1,
        }
        insert_site_magnets(con_with_site, "LNCMI-M9", [entry], verbose=False)
        row = con_with_site.execute(
            "SELECT z_offset, r_offset, parallax FROM site_magnets "
            "WHERE site_name = 'LNCMI-M9' AND magnet_name = 'MAG_INSERT'"
        ).fetchone()
        assert row[0] == pytest.approx(1.5)
        assert row[1] == pytest.approx(0.5)
        assert row[2] == pytest.approx(0.1)


class TestExperimentsCRUD:
    def test_insert_creates_rows(self, con_with_site):
        records = [{"file": "run001.tdms"}, {"file": "run002.tdms"}]
        insert_experiments(con_with_site, "LNCMI-M9", records, verbose=False)
        count = con_with_site.execute(
            "SELECT COUNT(*) FROM experiments WHERE site_name = 'LNCMI-M9'"
        ).fetchone()[0]
        assert count == 2

    def test_insert_idempotent(self, con_with_site):
        records = [{"file": "run001.tdms"}]
        insert_experiments(con_with_site, "LNCMI-M9", records, verbose=False)
        insert_experiments(con_with_site, "LNCMI-M9", records, verbose=False)
        count = con_with_site.execute(
            "SELECT COUNT(*) FROM experiments WHERE site_name = 'LNCMI-M9'"
        ).fetchone()[0]
        assert count == 1

    def test_insert_stores_file_name(self, con_with_site):
        insert_experiments(
            con_with_site, "LNCMI-M9", [{"file": "run001.tdms"}], verbose=False
        )
        row = con_with_site.execute(
            "SELECT file, status FROM experiments WHERE site_name = 'LNCMI-M9'"
        ).fetchone()
        assert row[0] == "run001.tdms"
        assert row[1] == "pending"


# ---------------------------------------------------------------------------
# Overview record
# ---------------------------------------------------------------------------


def _overview_exists(con, filename: str) -> bool:
    """overview_records uses 'filename' as PK, not 'name', so exists() cannot be used."""
    return (
        con.execute(
            "SELECT 1 FROM overview_records WHERE filename = ?", [filename]
        ).fetchone()
        is not None
    )


def _make_record(filename: str = "run001", housing: str = "M9") -> _FakeOverviewRecord:
    return _FakeOverviewRecord(
        filename=filename,
        housing=housing,
        mode="pupitre",
        t0=datetime(2024, 11, 6, 9, 15, 0),
        duration=3600.0,
        teb=0.05,
        BP=14.0,
        sources=_FakeFileSet(
            overview=["run001_overview.tdms"],
            archive=["run001_archive.tdms"],
        ),
        signatures={"key": "val"},
        sync_info={"offset": 0.0},
        flow_params={"Q": 100.0},
        metrics={"corr": 0.99},
        debitbrut={"raw": 99.0},
    )


class TestInsertOverviewRecord:
    def test_insert_creates_row(self, con_with_site):
        rec = _make_record()
        insert_overview_record(con_with_site, rec, site_name="LNCMI-M9", verbose=False)
        row = con_with_site.execute(
            "SELECT filename, housing, site_name FROM overview_records WHERE filename = 'run001'"
        ).fetchone()
        assert row == ("run001", "M9", "LNCMI-M9")

    def test_insert_stores_numeric_fields(self, con_with_site):
        rec = _make_record()
        insert_overview_record(con_with_site, rec, site_name="LNCMI-M9", verbose=False)
        row = con_with_site.execute(
            "SELECT duration, teb, bp FROM overview_records WHERE filename = 'run001'"
        ).fetchone()
        assert row[0] == pytest.approx(3600.0)
        assert row[1] == pytest.approx(0.05)
        assert row[2] == pytest.approx(14.0)

    def test_insert_stores_json_fields(self, con_with_site):
        rec = _make_record()
        insert_overview_record(con_with_site, rec, site_name="LNCMI-M9", verbose=False)
        row = con_with_site.execute(
            "SELECT signatures, metrics FROM overview_records WHERE filename = 'run001'"
        ).fetchone()
        assert json.loads(row[0]) == {"key": "val"}
        assert json.loads(row[1]) == {"corr": 0.99}

    def test_insert_stores_source_lists(self, con_with_site):
        rec = _make_record()
        insert_overview_record(con_with_site, rec, site_name="LNCMI-M9", verbose=False)
        row = con_with_site.execute(
            "SELECT sources_overview, sources_archive "
            "FROM overview_records WHERE filename = 'run001'"
        ).fetchone()
        assert list(row[0]) == ["run001_overview.tdms"]
        assert list(row[1]) == ["run001_archive.tdms"]

    def test_insert_idempotent(self, con_with_site):
        rec = _make_record()
        insert_overview_record(con_with_site, rec, site_name="LNCMI-M9", verbose=False)
        insert_overview_record(con_with_site, rec, site_name="LNCMI-M9", verbose=False)
        count = con_with_site.execute(
            "SELECT COUNT(*) FROM overview_records WHERE filename = 'run001'"
        ).fetchone()[0]
        assert count == 1

    def test_insert_without_site_name(self, con):
        rec = _make_record()
        insert_overview_record(con, rec, site_name=None, verbose=False)
        row = con.execute(
            "SELECT filename, site_name FROM overview_records WHERE filename = 'run001'"
        ).fetchone()
        assert row[0] == "run001"
        assert row[1] is None

    def test_insert_empty_sources(self, con):
        rec = _make_record()
        rec.sources = None
        insert_overview_record(con, rec, site_name=None, verbose=False)
        row = con.execute(
            "SELECT sources_overview FROM overview_records WHERE filename = 'run001'"
        ).fetchone()
        assert list(row[0]) == []


class TestUpsertOverviewRecord:
    def test_upsert_inserts_new_row(self, con_with_site):
        rec = _make_record()
        upsert_overview_record(con_with_site, rec, site_name="LNCMI-M9", verbose=False)
        assert _overview_exists(con_with_site, "run001")

    def test_upsert_replaces_existing_row(self, con_with_site):
        rec = _make_record()
        insert_overview_record(con_with_site, rec, site_name="LNCMI-M9", verbose=False)
        rec2 = _make_record()
        rec2.duration = 7200.0
        upsert_overview_record(con_with_site, rec2, site_name="LNCMI-M9", verbose=False)
        row = con_with_site.execute(
            "SELECT duration FROM overview_records WHERE filename = 'run001'"
        ).fetchone()
        assert row[0] == pytest.approx(7200.0)

    def test_upsert_preserves_one_row(self, con_with_site):
        rec = _make_record()
        insert_overview_record(con_with_site, rec, site_name="LNCMI-M9", verbose=False)
        upsert_overview_record(con_with_site, rec, site_name="LNCMI-M9", verbose=False)
        count = con_with_site.execute(
            "SELECT COUNT(*) FROM overview_records WHERE filename = 'run001'"
        ).fetchone()[0]
        assert count == 1


class TestAttachSiteToOverviewRecord:
    def test_attach_sets_site_name_and_housing(self, con_with_site):
        rec = _make_record()
        insert_overview_record(con_with_site, rec, site_name=None, verbose=False)
        attach_site_to_overview_record(
            con_with_site, "run001", "LNCMI-M9", verbose=False
        )
        row = con_with_site.execute(
            "SELECT site_name, housing FROM overview_records WHERE filename = 'run001'"
        ).fetchone()
        assert row[0] == "LNCMI-M9"
        assert row[1] == "M9"

    def test_attach_missing_overview_raises(self, con_with_site):
        with pytest.raises(ValueError, match="No overview_record"):
            attach_site_to_overview_record(
                con_with_site, "nonexistent", "LNCMI-M9", verbose=False
            )

    def test_attach_missing_site_raises(self, con_with_site):
        rec = _make_record()
        insert_overview_record(con_with_site, rec, site_name=None, verbose=False)
        with pytest.raises(ValueError, match="No site"):
            attach_site_to_overview_record(
                con_with_site, "run001", "NONEXISTENT-SITE", verbose=False
            )


# ---------------------------------------------------------------------------
# insert_housing_config_from_magnetrun
# ---------------------------------------------------------------------------


class TestInsertHousingConfigFromMagnetrun:
    def test_inserts_known_housing(self, con):
        pytest.importorskip("python_magnetrun")
        insert_housing_config_from_magnetrun(con, "M9", verbose=False)
        assert exists(con, "housing_config", "M9")

    def test_idempotent(self, con):
        pytest.importorskip("python_magnetrun")
        insert_housing_config_from_magnetrun(con, "M9", verbose=False)
        insert_housing_config_from_magnetrun(con, "M9", verbose=False)
        count = con.execute(
            "SELECT COUNT(*) FROM housing_config WHERE name = 'M9'"
        ).fetchone()[0]
        assert count == 1

    @pytest.mark.parametrize("housing", ["M8", "M9", "M10"])
    def test_coil_assignment_correct(self, con, housing):
        pytest.importorskip("python_magnetrun")
        insert_housing_config_from_magnetrun(con, housing, verbose=False)
        row = con.execute(
            "SELECT coil_assignment FROM housing_config WHERE name = ?",
            [housing],
        ).fetchone()
        ca = dict(row[0])
        assert set(ca) == {"Insert", "Bitter"}
        assert set(ca.values()) == {"GR1", "GR2"}
        expected_insert_gr = "GR1" if housing == "M9" else "GR2"
        assert ca["Insert"] == expected_insert_gr

    def test_unknown_housing_raises(self, con):
        pytest.importorskip("python_magnetrun")
        with pytest.raises(ValueError):
            insert_housing_config_from_magnetrun(con, "M999", verbose=False)
