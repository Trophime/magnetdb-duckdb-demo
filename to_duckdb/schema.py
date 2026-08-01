"""
schema.py
=========
Canonical DuckDB schema for the student magnetdb.
Import ``SCHEMA_SQL`` or call ``ensure_schema(con)`` from any module that
needs to create or migrate the database.
"""

from enums import PartType

COIL_TYPES: frozenset[str] = frozenset(
    {PartType.HELIX.value, PartType.BITTER.value, PartType.SUPRA.value}
)

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

-- Housing configuration must be created before sites so the FK reference below resolves.
CREATE TABLE IF NOT EXISTS housing_config (
    name            VARCHAR PRIMARY KEY,
    coil_assignment MAP(VARCHAR, VARCHAR),
    formats         VARCHAR[],
    extra_config    JSON
);

CREATE TABLE IF NOT EXISTS sites (
    name               VARCHAR PRIMARY KEY,
    description        VARCHAR,
    status             VARCHAR,
    housing            VARCHAR REFERENCES housing_config(name),
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

CREATE SEQUENCE IF NOT EXISTS operationaldata_id_seq START 1;

CREATE TABLE IF NOT EXISTS operationaldata (
    id          INTEGER PRIMARY KEY DEFAULT nextval('operationaldata_id_seq'),
    name        VARCHAR,
    description VARCHAR,
    file        VARCHAR UNIQUE,
    site_name   VARCHAR REFERENCES sites(name),
    type        VARCHAR DEFAULT 'Archive',
    status      VARCHAR DEFAULT 'pending'
);

-- idempotent migration for databases that predate the type column
ALTER TABLE operationaldata ADD COLUMN IF NOT EXISTS type VARCHAR DEFAULT 'Archive';
-- idempotent migration: ensure id has the sequence default (fixes DBs created before the DEFAULT was added)
ALTER TABLE operationaldata ALTER COLUMN id SET DEFAULT nextval('operationaldata_id_seq');

-- One row per processed overview file (OverviewRecord, data attribute excluded).
-- sources_* columns hold the file-path lists from FileSet.
-- signatures / sync_info / flow_params / metrics / debitbrut are stored as JSON.
CREATE TABLE IF NOT EXISTS overview_records (
    filename                  VARCHAR PRIMARY KEY,
    site_name                 VARCHAR REFERENCES sites(name),
    housing                   VARCHAR,
    mode                      VARCHAR,
    t0                        TIMESTAMP,
    duration                  DOUBLE    DEFAULT 0.0,
    teb                       DOUBLE    DEFAULT 0.0,
    bp                        DOUBLE    DEFAULT 0.0,
    sources_overview          VARCHAR[],
    sources_archive           VARCHAR[],
    sources_pupitre           VARCHAR[],
    sources_default           VARCHAR[],
    sources_trigger           VARCHAR[],
    sources_spike             VARCHAR[],
    sources_hybrid_kHz        VARCHAR[],
    sources_hybrid_rms        VARCHAR[],
    sources_hybrid_trigger    VARCHAR[],
    sources_hybrid_vprocess   VARCHAR[],
    sources_pigbrother_runlog VARCHAR[],
    sources_pupitre_runlog    VARCHAR[],
    signatures                JSON      DEFAULT '{}',
    sync_info                 JSON      DEFAULT '{}',
    flow_params               JSON      DEFAULT '{}',
    metrics                   JSON      DEFAULT '{}',
    debitbrut                 JSON      DEFAULT '{}'
);

-- idempotent migration for databases that predate site_name
ALTER TABLE overview_records ADD COLUMN IF NOT EXISTS site_name VARCHAR;

-- ── Operational statistics tables ────────────────────────────────────────────

-- Tracks which operationaldata files have been processed (idempotency guard).
CREATE TABLE IF NOT EXISTS op_stats_processed (
    operationaldata_id  INTEGER PRIMARY KEY REFERENCES operationaldata(id),
    processed_at        TIMESTAMP DEFAULT now(),
    n_rows              INTEGER,
    dt_median           DOUBLE,
    bin_config          JSON
);

-- Per-run scalar quantities (not binned).
-- Intended use cases:
--   'energy_j'            = sum(Ptot * dt)                  electricity billing
--   'heat_extracted_j'    = sum((tsb-teb) * Q_m3s * rho_cp * dt)  fatal heat
--   'duration_s'          = sum(dt)                          total run length
--   'duration_field_on_s' = sum(dt) where Field > threshold  magnet-on time
CREATE TABLE IF NOT EXISTS op_run_scalars (
    operationaldata_id  INTEGER  REFERENCES operationaldata(id),
    channel             VARCHAR  NOT NULL,
    value               DOUBLE   NOT NULL,
    PRIMARY KEY (operationaldata_id, channel)
);

-- Site-level field-bin distributions.
-- One row per (file, field bin, channel).
-- Channels: 'Pmagnet', 'Ptot', 'tsb', 'teb', 'debitbrut', ...
-- Derived at query time:
--   operating time (h)   = SUM(sum_dt) / 3600
--   time-weighted mean   = SUM(sum_x_dt) / SUM(sum_dt)
--   time-weighted stddev = sqrt(SUM(sum_x2_dt)/SUM(sum_dt) - mean^2)
--   peak value           = MAX(max_x)
CREATE TABLE IF NOT EXISTS op_site_bin_stats (
    operationaldata_id  INTEGER  REFERENCES operationaldata(id),
    field_bin_low       DOUBLE   NOT NULL,
    field_bin_high      DOUBLE   NOT NULL,
    channel             VARCHAR  NOT NULL,
    n_samples           BIGINT   NOT NULL,
    sum_dt              DOUBLE   NOT NULL,
    sum_x_dt            DOUBLE,
    sum_x2_dt           DOUBLE,
    min_x               DOUBLE,
    max_x               DOUBLE,
    PRIMARY KEY (operationaldata_id, field_bin_low, channel)
);

-- Per-part field-bin distributions.
-- One row per (file, part, field bin, channel).
-- Channels: 'Icoil', 'Ucoil', 'hoop_stress_proxy' (= I^2, proportional to sigma_theta)
-- Only rows where |Icoil| > current_threshold are included.
CREATE TABLE IF NOT EXISTS op_part_bin_stats (
    operationaldata_id  INTEGER  REFERENCES operationaldata(id),
    part_name           VARCHAR  REFERENCES parts(name),
    field_bin_low       DOUBLE   NOT NULL,
    field_bin_high      DOUBLE   NOT NULL,
    channel             VARCHAR  NOT NULL,
    n_samples           BIGINT   NOT NULL,
    sum_dt              DOUBLE   NOT NULL,
    sum_x_dt            DOUBLE,
    sum_x2_dt           DOUBLE,
    min_x               DOUBLE,
    max_x               DOUBLE,
    PRIMARY KEY (operationaldata_id, part_name, field_bin_low, channel)
);

-- ── Experiment statistics tables ─────────────────────────────────────────────

-- Tracks which experiment files have been processed (idempotency guard).
CREATE TABLE IF NOT EXISTS exp_stats_processed (
    experiment_id   INTEGER PRIMARY KEY REFERENCES experiments(id),
    processed_at    TIMESTAMP DEFAULT now(),
    n_rows          INTEGER,
    dt_median       DOUBLE,
    bin_config      JSON
);

-- Per-run scalar quantities for experiments (not binned).
-- Same intended channels as op_run_scalars:
--   'energy_j', 'heat_extracted_j', 'duration_s', 'duration_field_on_s'
CREATE TABLE IF NOT EXISTS exp_run_scalars (
    experiment_id   INTEGER  REFERENCES experiments(id),
    channel         VARCHAR  NOT NULL,
    value           DOUBLE   NOT NULL,
    PRIMARY KEY (experiment_id, channel)
);

-- Site-level field-bin distributions for experiments.
-- One row per (experiment, field bin, channel).
-- Derived at query time:
--   operating time (h)   = SUM(sum_dt) / 3600
--   time-weighted mean   = SUM(sum_x_dt) / SUM(sum_dt)
--   time-weighted stddev = sqrt(SUM(sum_x2_dt)/SUM(sum_dt) - mean^2)
--   peak value           = MAX(max_x)
CREATE TABLE IF NOT EXISTS exp_site_bin_stats (
    experiment_id   INTEGER  REFERENCES experiments(id),
    field_bin_low   DOUBLE   NOT NULL,
    field_bin_high  DOUBLE   NOT NULL,
    channel         VARCHAR  NOT NULL,
    n_samples       BIGINT   NOT NULL,
    sum_dt          DOUBLE   NOT NULL,
    sum_x_dt        DOUBLE,
    sum_x2_dt       DOUBLE,
    min_x           DOUBLE,
    max_x           DOUBLE,
    PRIMARY KEY (experiment_id, field_bin_low, channel)
);

-- Per-part field-bin distributions for experiments.
-- One row per (experiment, part, field bin, channel).
-- Channels: 'Icoil', 'Ucoil', 'hoop_stress_proxy' (= I^2, proportional to sigma_theta)
-- Only rows where |Icoil| > current_threshold are included.
CREATE TABLE IF NOT EXISTS exp_part_bin_stats (
    experiment_id   INTEGER  REFERENCES experiments(id),
    part_name       VARCHAR  REFERENCES parts(name),
    field_bin_low   DOUBLE   NOT NULL,
    field_bin_high  DOUBLE   NOT NULL,
    channel         VARCHAR  NOT NULL,
    n_samples       BIGINT   NOT NULL,
    sum_dt          DOUBLE   NOT NULL,
    sum_x_dt        DOUBLE,
    sum_x2_dt       DOUBLE,
    min_x           DOUBLE,
    max_x           DOUBLE,
    PRIMARY KEY (experiment_id, part_name, field_bin_low, channel)
);

-- ── Hoop-stress statistics tables ────────────────────────────────────────────

-- Idempotency guard: one row per (experiment, bin_config) pair.
-- bin_config is the canonical edges string, e.g. "0.0,100.0,200.0,300.0,400.0,500.0,600.0".
-- Using a composite PK allows re-running with different bin configs without data loss.
-- parquet_path stores the path to the Parquet file with the full time series.
CREATE TABLE IF NOT EXISTS hoop_stress_processed (
    experiment_id   INTEGER  REFERENCES experiments(id),
    bin_config      VARCHAR  NOT NULL,
    processed_at    TIMESTAMP DEFAULT now(),
    magnet_type     VARCHAR  NOT NULL,
    parquet_path    VARCHAR,
    PRIMARY KEY (experiment_id, bin_config)
);

-- Per-part stress-bin distributions.
-- One row per (experiment, part_name, stress_bin_low).
-- Derived at query time:
--   operating time (h)    = SUM(sum_dt) / 3600
--   time-weighted mean    = SUM(sum_x_dt) / SUM(sum_dt)
--   time-weighted stddev  = sqrt(SUM(sum_x2_dt)/SUM(sum_dt) - mean^2)
--   peak stress           = MAX(max_x)
CREATE TABLE IF NOT EXISTS hoop_stress_bin_stats (
    experiment_id   INTEGER  REFERENCES experiments(id),
    part_name       VARCHAR  REFERENCES parts(name),
    stress_bin_low  DOUBLE   NOT NULL,
    stress_bin_high DOUBLE   NOT NULL,
    n_samples       BIGINT   NOT NULL,
    sum_dt          DOUBLE   NOT NULL,
    sum_x_dt        DOUBLE,
    sum_x2_dt       DOUBLE,
    min_x           DOUBLE,
    max_x           DOUBLE,
    PRIMARY KEY (experiment_id, part_name, stress_bin_low)
);

-- Per-part rainflow fatigue cycle counts.
-- n_cycles: total number of counted half-cycles (rainflow)
-- sum_range3: sum of (delta_sigma^3) — S-N fatigue proxy (Miner's rule with m=3)
CREATE TABLE IF NOT EXISTS hoop_stress_fatigue (
    experiment_id   INTEGER  REFERENCES experiments(id),
    part_name       VARCHAR  REFERENCES parts(name),
    n_cycles        DOUBLE   NOT NULL,
    sum_range3      DOUBLE   NOT NULL,
    PRIMARY KEY (experiment_id, part_name)
);

-- ── Users ─────────────────────────────────────────────────────────────────

-- One row per EXPERIENCES_LOG session: a distinct UserCode (= proposal Acronym,
-- fuzzy-matched) crossed with each base magnet (e.g. "M9i"/"M9e" -> "M9") and each
-- (HStart, HStop) session on it. research_area / type / call_number / access_mode
-- come from the matched proposals CSV row (Type, e.g. "EMFL"/"Supra"/"Instrumentation")
-- and are duplicated across an acronym's rows.
-- hstop is NULL where EXPERIENCES_LOG left it blank (session not closed).
-- experiments_ids holds experiments.id values whose file-embedded timestamp falls
-- within [hstart, hstop] on this row's housing; NULL until populated (see
-- demos/users_table_demo.py) and left NULL for rows with no hstop.
-- No primary key: EXPERIENCES_LOG itself contains exact-duplicate session rows.
-- country is not populated yet.
CREATE TABLE IF NOT EXISTS users (
    acronym         VARCHAR,
    research_area   VARCHAR,
    type            VARCHAR,
    country         VARCHAR,
    call_number     VARCHAR,
    access_mode     VARCHAR,
    housing         VARCHAR,
    hstart          TIMESTAMP,
    hstop           TIMESTAMP,
    experiments_ids INTEGER[]
);
"""


def ensure_schema(con) -> None:
    """Create all tables and apply idempotent migrations on *con*."""
    # users.hstart changed from TIMESTAMP[] (one row per acronym+housing) to a
    # scalar TIMESTAMP (one row per session), and the primary key was dropped;
    # DuckDB can't ALTER COLUMN across incompatible types or drop a primary
    # key, and the table is fully rebuilt by its populating script, so drop
    # and let CREATE TABLE recreate it.
    hstart_type = con.execute(
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_name = 'users' AND column_name = 'hstart'"
    ).fetchone()
    if hstart_type is not None and hstart_type[0] != "TIMESTAMP":
        con.execute("DROP TABLE users")
    con.execute(SCHEMA_SQL)
    # idempotent migration: experiment_ids was renamed to experiments_ids
    has_old_name = con.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = 'users' AND column_name = 'experiment_ids'"
    ).fetchone()
    if has_old_name is not None:
        con.execute("ALTER TABLE users RENAME COLUMN experiment_ids TO experiments_ids")
    # idempotent migration for databases that predate experiments_ids
    con.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS experiments_ids INTEGER[]")
    # idempotent migration for databases that predate the type column
    con.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS type VARCHAR")
