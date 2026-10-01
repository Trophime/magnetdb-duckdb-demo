# Assembly-commissioning measurements + numerical-companion tables

**Status:** Design plan — not yet approved for implementation.

## Context

When an assembly is commissioned, two kinds of measurements are taken per
magnet in the assembly:

- **Field factor** — ratio of measured magnetic field at (0,0) to magnet
  current, at several PID-stabilized current setpoints.
- **Resistance** — measured across a range of currents.

Current is controlled by a PID, and cooling flow rate is itself a function
of current (see `flow_params` on `overview_records` / Postgres
`Magnet.flow_params`). The goal is twofold:

1. Keep track of all commissioning measurement data (not just derived
   summaries).
2. Build a "numerical companion" — the calibration data needed to replay an
   assembly with **magnet-scipy** (`RLCircuitPID` / `CoupledRLCircuitsPID`):
   R(I,T), self-inductance, mutual inductance between magnets in the
   assembly, and PID gains. Field factor, resistance, and inductance may
   each come from a measurement, an analytical fit, or an FEM pipeline
   (`python_magnetapi`/`python_magnetworkflows`, e.g. `inductances.py`), so
   the schema must let multiple sources coexist per quantity for
   comparison.

Grounding for this design:
- [to_duckdb/schema.py](to_duckdb/schema.py) / [to_duckdb/docs/schema.md](to_duckdb/docs/schema.md) — existing table conventions (natural-name PKs, JSON payload columns, per-table sequences, `experiments`/`operationaldata` file-tracking pattern, `op_part_bin_stats`/`hoop_stress_bin_stats` as precedent for per-part derived-quantity tables).
- [PLAN_duckdb_postgres_merge.md](PLAN_duckdb_postgres_merge.md) — DuckDB vs. Postgres split; confirms `flow_params` already exists (Postgres `Magnet.flow_params`, DuckDB `overview_records.flow_params`) and that Postgres already has a heavier `simulations`/`simulation_currents` FEM-job model, which this is deliberately lighter-weight than.
- `magnet-scipy` (`~/github/magnet-scipy`) — `RLCircuitPID` takes `R` (constant or `resistance_csv` giving R(I,T)), `L` (scalar), PID gains (`Kp/Ki/Kd_low/high` + thresholds); `CoupledRLCircuitsPID` takes an NxN `mutual_inductances` matrix. No direct `field_factor` parameter in magnet-scipy itself — it's used downstream to convert simulated current into a comparable field trace for validation against measured field.
- `python_magnetapi/inductances.py` — existing FEM-based inductance computation pipeline (site/magnet), confirming inductance has an "FEM source" in addition to measurement/analytical.

## Files affected

- `to_duckdb/schema.py` — edit: add 5 `CREATE TABLE IF NOT EXISTS` blocks + 2 sequences.
- `to_duckdb/enums.py` — edit: add `ParameterSource` enum (`measured`/`analytical`/`fem`), mirroring `AssemblyStatus`/`LifecycleStatus`.
- `to_duckdb/docs/schema.md` — edit: document the new tables in the table overview + a short new section.
- `to_duckdb/tests/test_schema.py` — edit: add the 5 new names to `EXPECTED_TABLES`.

No CLI/`crud.py` insert commands in this pass — scoped to schema only. Populating these tables (CLI commands, and any ETL from the FEM/analytical pipeline) is a follow-up.

## Approach

### 1. Raw commissioning measurements (per PID-stabilized setpoint, always `source = measured`)

```sql
CREATE SEQUENCE IF NOT EXISTS commissioning_field_factor_id_seq START 1;
CREATE TABLE IF NOT EXISTS commissioning_field_factor (
    id                   INTEGER PRIMARY KEY DEFAULT nextval('commissioning_field_factor_id_seq'),
    assembly_name        VARCHAR REFERENCES assemblies(name),
    magnet_name          VARCHAR REFERENCES magnets(name),
    current_a            DOUBLE NOT NULL,
    field_t              DOUBLE NOT NULL,
    field_factor_t_per_a DOUBLE,              -- field_t / current_a
    flow_rate_m3s        DOUBLE,
    temp_in_degc         DOUBLE,
    measured_at          TIMESTAMP,
    experiment_id        INTEGER REFERENCES experiments(id),  -- optional link to backing raw file
    notes                VARCHAR
);

CREATE SEQUENCE IF NOT EXISTS commissioning_resistance_id_seq START 1;
CREATE TABLE IF NOT EXISTS commissioning_resistance (
    id                INTEGER PRIMARY KEY DEFAULT nextval('commissioning_resistance_id_seq'),
    assembly_name     VARCHAR REFERENCES assemblies(name),
    magnet_name       VARCHAR REFERENCES magnets(name),
    current_a         DOUBLE NOT NULL,
    voltage_v         DOUBLE NOT NULL,
    resistance_ohm    DOUBLE,                 -- voltage_v / current_a
    flow_rate_m3s     DOUBLE,
    temp_in_degc      DOUBLE,
    measured_at       TIMESTAMP,
    experiment_id     INTEGER REFERENCES experiments(id),
    notes             VARCHAR
);
```

Keyed to `assembly_name` (not just magnet) since field factor/resistance depend on the other magnets sharing the bore. Surrogate id (not a natural PK) because a setpoint can be repeated across a campaign.

### 2. Numerical-companion calibration parameters

```sql
CREATE TABLE IF NOT EXISTS assembly_magnet_parameters (
    assembly_name  VARCHAR REFERENCES assemblies(name),
    magnet_name    VARCHAR REFERENCES magnets(name),
    quantity       VARCHAR NOT NULL,   -- 'field_factor' | 'resistance' | 'self_inductance'
    source         VARCHAR NOT NULL,   -- ParameterSource
    unit           VARCHAR,
    data           JSON NOT NULL,      -- [{current_a, temperature_degc, value}, ...]; single-point list for a scalar (e.g. L)
    source_ref     VARCHAR,            -- commissioning table id range, or FEM/workflow run ref, or Postgres simulations.id
    computed_at    TIMESTAMP,
    metadata       JSON DEFAULT '{}',
    PRIMARY KEY (assembly_name, magnet_name, quantity, source)
);
```

One generic table (quantity + source discriminator, JSON tabulated payload) covers field_factor/resistance/self_inductance, rather than three separate typed tables — matches magnet-scipy's own tabulated-CSV shape and the schema's existing JSON-payload precedent (`flow_params`, `geometry_data`). Lets measured/analytical/FEM values coexist per (assembly, magnet, quantity) for comparison.

### 3. Mutual inductance (assembly-level, pairwise)

```sql
CREATE TABLE IF NOT EXISTS assembly_mutual_inductance (
    assembly_name  VARCHAR REFERENCES assemblies(name),
    magnet_name_a  VARCHAR REFERENCES magnets(name),
    magnet_name_b  VARCHAR REFERENCES magnets(name),
    value_h        DOUBLE NOT NULL,
    source         VARCHAR NOT NULL,   -- ParameterSource
    source_ref     VARCHAR,
    computed_at    TIMESTAMP,
    PRIMARY KEY (assembly_name, magnet_name_a, magnet_name_b, source)
);
```

`magnet_name_a < magnet_name_b` by convention (app-layer), not a DB-enforced `CHECK` — matches the rest of `schema.py`, which validates in the app layer rather than via SQL constraints.

### 4. PID controller gains

```sql
CREATE TABLE IF NOT EXISTS assembly_magnet_pid_params (
    assembly_name    VARCHAR REFERENCES assemblies(name),
    magnet_name      VARCHAR REFERENCES magnets(name),
    kp_low DOUBLE, ki_low DOUBLE, kd_low DOUBLE,
    kp_high DOUBLE, ki_high DOUBLE, kd_high DOUBLE,
    low_threshold_a  DOUBLE,
    high_threshold_a DOUBLE,
    source           VARCHAR DEFAULT 'measured',
    tuned_at         TIMESTAMP,
    PRIMARY KEY (assembly_name, magnet_name)
);
```

Single "current" row per (assembly, magnet) — no retuning history in this pass; extend later if PID gains get iterated during commissioning and that history needs tracking.

### 5. Enum, docs, tests

- `enums.py`: add `ParameterSource(str, enum.Enum)` with `MEASURED = "measured"`, `ANALYTICAL = "analytical"`, `FEM = "fem"`, and a `.choices()` classmethod.
- `docs/schema.md`: add the 5 tables to the table overview list, plus a short "Commissioning & numerical replay" section describing the shape (similar to the existing `site_magnets columns` / `coil_index` sections).
- `tests/test_schema.py`: add `commissioning_field_factor`, `commissioning_resistance`, `assembly_magnet_parameters`, `assembly_mutual_inductance`, `assembly_magnet_pid_params` to `EXPECTED_TABLES`.

## Verification

1. Schema builds → `python -c "import duckdb,schema; con=duckdb.connect(':memory:'); schema.ensure_schema(con); schema.ensure_schema(con)"` runs twice without error (idempotency, matches existing convention).
2. `pytest to_duckdb/tests/test_schema.py -q` passes with updated `EXPECTED_TABLES`.
3. `python -c "from enums import ParameterSource; print(ParameterSource.choices())"` prints the 3 values.
4. `pytest to_duckdb/tests -q` — full suite, no regressions.

## Assumptions & open questions

- Biggest judgment call: one generic `assembly_magnet_parameters` table (quantity+source discriminator, JSON tabulated payload) instead of three separate typed tables for field_factor/resistance/self_inductance.
- `assembly_magnet_pid_params` keeps only the current tuning (no retuning history) — extend later if needed.
- `experiment_id` on the two commissioning tables is optional — assumes not every setpoint necessarily has a backing raw TDMS/TSV file.
- Populating these tables (CLI commands, and any ETL from the python_magnetapi/python_magnetworkflows FEM pipeline) is out of scope here — a follow-up once the shape is approved.
