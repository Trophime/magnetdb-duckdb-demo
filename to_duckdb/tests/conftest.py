"""
Shared fixtures and test-data constants for the to_duckdb test suite.
"""

import pytest
import duckdb

from schema import ensure_schema

# ---------------------------------------------------------------------------
# Minimal, self-consistent test data
# ---------------------------------------------------------------------------

MATERIAL_COPPER = {
    "name": "MAT_COPPER",
    "description": "Copper alloy",
    "nuance": "CuAg2.75",
    "t_ref": 293.0,
    "volumic_mass": 9000.0,
    "specific_heat": 385.0,
    "alpha": 0.0036,
    "electrical_conductivity": 52_900_000.0,
    "thermal_conductivity": 380.0,
    "magnet_permeability": 1.0,
    "young": 117e9,
    "poisson": 0.33,
    "expansion_coefficient": 1.8e-5,
    "rpe": 490e6,
}

MATERIAL_STEEL = {
    **MATERIAL_COPPER,
    "name": "MAT_STEEL",
    "nuance": "SS316L",
    "electrical_conductivity": 1_380_000.0,
    "thermal_conductivity": 13.0,
    "rpe": 200e6,
}

PART_HELIX = {
    "name": "HELIX_01",
    "type": "helix",
    "status": "in_operation",
    "material_name": "MAT_COPPER",
    "geometry": None,
    "cad": None,
    "design_office_reference": "HL-TEST",
}

PART_RING = {
    "name": "RING_01",
    "type": "ring",
    "status": "in_operation",
    "material_name": "MAT_STEEL",
    "geometry": None,
    "cad": None,
    "design_office_reference": "",
}

MAGNET_DATA = {
    "name": "MAG_01",
    "status": "in_operation",
    "design_office_reference": "MAG-TEST-001",
    "geometry": None,
}

SITE_DATA = {
    "name": "SITE_01",
    "description": "Test site",
    "status": "in_operation",
    "housing": "M10",
    "commissioned_at": "2025-01-01 00:00:00",
    "decommissioned_at": None,
}

# Full magnet JSON (as exported from MagnetDB) with two parts: one helix, one ring
MAGNET_JSON = {
    "name": "MAG_JSON",
    "status": "in_operation",
    "design_office_reference": "",
    "parts": [
        {
            "name": "H_JSON_01",
            "type": "helix",
            "status": "in_operation",
            "design_office_reference": "",
            "geometry": None,
            "material": {**MATERIAL_COPPER, "name": "MAT_JSON_CU"},
        },
        {
            "name": "R_JSON_01",
            "type": "ring",
            "status": "in_operation",
            "design_office_reference": "",
            "geometry": None,
            "material": {**MATERIAL_STEEL, "name": "MAT_JSON_SS"},
        },
    ],
}

SITE_JSON = {
    "name": "SITE_JSON_01",
    "description": "",
    "status": "in_operation",
    "housing": "M10",
    "commissioned_at": "2025-01-01 00:00:00",
    "decommissioned_at": "None",
    "magnets": ["MAG_JSON"],
    "records": [
        {
            "name": "M10_2025.01.01---00:00:00.txt",
            "description": "",
            "file": "M10_2025.01.01---00:00:00.txt",
        }
    ],
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def con():
    """Fresh in-memory DuckDB connection with the canonical schema applied."""
    c = duckdb.connect(":memory:")
    ensure_schema(c)
    yield c
    c.close()


@pytest.fixture
def con_populated(con):
    """Connection with two materials, two parts, one magnet, and one site pre-loaded."""
    from crud import (
        insert_magnet,
        insert_magnet_part_row,
        insert_material,
        insert_part,
        insert_site,
    )
    insert_material(con, MATERIAL_COPPER, verbose=False)
    insert_material(con, MATERIAL_STEEL, verbose=False)
    insert_part(con, PART_HELIX, verbose=False)
    insert_part(con, PART_RING, verbose=False)
    insert_magnet(con, MAGNET_DATA, "insert", verbose=False)
    insert_magnet_part_row(con, "MAG_01", "HELIX_01", 0, 1)
    insert_magnet_part_row(con, "MAG_01", "RING_01", 1, None)
    insert_site(con, SITE_DATA, verbose=False)
    return con
