"""
schema.py
=========
Canonical DuckDB schema for the student magnetdb.
Import ``SCHEMA_SQL`` or call ``ensure_schema(con)`` from any module that
needs to create or migrate the database.
"""

COIL_TYPES: frozenset[str] = frozenset({"helix", "bitter"})

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS materials (
    name                    VARCHAR PRIMARY KEY,
    description             VARCHAR,
    nuance                  VARCHAR,
    t_ref                   DOUBLE,
    volumic_mass            DOUBLE,
    specific_heat           DOUBLE,
    alpha                   DOUBLE,
    electrical_conductivity DOUBLE,
    thermal_conductivity    DOUBLE,
    magnet_permeability     DOUBLE,
    young                   DOUBLE,
    poisson                 DOUBLE,
    expansion_coefficient   DOUBLE,
    rpe                     DOUBLE
);

CREATE TABLE IF NOT EXISTS parts (
    name                    VARCHAR PRIMARY KEY,
    type                    VARCHAR,
    status                  VARCHAR,
    material_name           VARCHAR REFERENCES materials(name),
    geometry                VARCHAR,
    geometry_data           JSON,
    cad                     VARCHAR,
    design_office_reference VARCHAR
);

CREATE TABLE IF NOT EXISTS magnets (
    name                    VARCHAR PRIMARY KEY,
    type                    VARCHAR,
    status                  VARCHAR,
    geometry                VARCHAR,
    geometry_data           JSON,
    design_office_reference VARCHAR
);

-- idempotent migrations for databases that predate geometry_data columns
ALTER TABLE parts   ADD COLUMN IF NOT EXISTS geometry_data JSON;
ALTER TABLE magnets ADD COLUMN IF NOT EXISTS geometry_data JSON;

CREATE TABLE IF NOT EXISTS magnet_parts (
    magnet_name VARCHAR REFERENCES magnets(name),
    part_name   VARCHAR REFERENCES parts(name),
    rank        INTEGER,
    coil_index  INTEGER,
    PRIMARY KEY (magnet_name, part_name)
);

CREATE TABLE IF NOT EXISTS sites (
    name               VARCHAR PRIMARY KEY,
    description        VARCHAR,
    status             VARCHAR,
    housing            VARCHAR,
    commissioned_at    TIMESTAMP,
    decommissioned_at  TIMESTAMP
);

CREATE TABLE IF NOT EXISTS site_magnets (
    site_name          VARCHAR REFERENCES sites(name),
    magnet_name        VARCHAR REFERENCES magnets(name),
    z_offset           DOUBLE    DEFAULT 0.0,
    r_offset           DOUBLE    DEFAULT 0.0,
    parallax           DOUBLE    DEFAULT 0.0,
    commissioned_at    TIMESTAMP,
    decommissioned_at  TIMESTAMP,
    metadata           JSON      DEFAULT '{}',
    PRIMARY KEY (site_name, magnet_name)
);

-- idempotent migrations for databases that predate SiteMagnet positional fields
ALTER TABLE site_magnets ADD COLUMN IF NOT EXISTS z_offset          DOUBLE    DEFAULT 0.0;
ALTER TABLE site_magnets ADD COLUMN IF NOT EXISTS r_offset          DOUBLE    DEFAULT 0.0;
ALTER TABLE site_magnets ADD COLUMN IF NOT EXISTS parallax          DOUBLE    DEFAULT 0.0;
ALTER TABLE site_magnets ADD COLUMN IF NOT EXISTS commissioned_at   TIMESTAMP;
ALTER TABLE site_magnets ADD COLUMN IF NOT EXISTS decommissioned_at TIMESTAMP;
ALTER TABLE site_magnets ADD COLUMN IF NOT EXISTS metadata          JSON      DEFAULT '{}';

CREATE TABLE IF NOT EXISTS experiments (
    id          INTEGER PRIMARY KEY,
    name        VARCHAR,
    description VARCHAR,
    file        VARCHAR,
    site_name   VARCHAR REFERENCES sites(name),
    status      VARCHAR DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS operationaldata (
    id          INTEGER PRIMARY KEY,
    name        VARCHAR,
    description VARCHAR,
    file        VARCHAR UNIQUE,
    site_name   VARCHAR REFERENCES sites(name),
    type        VARCHAR DEFAULT 'Archive',
    status      VARCHAR DEFAULT 'pending'
);

-- idempotent migration for databases that predate the type column
ALTER TABLE operationaldata ADD COLUMN IF NOT EXISTS type VARCHAR DEFAULT 'Archive';
"""


def ensure_schema(con) -> None:
    """Create all tables and apply idempotent migrations on *con*."""
    con.execute(SCHEMA_SQL)
