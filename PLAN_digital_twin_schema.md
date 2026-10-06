# Plan: Real/digital magnets, installations and run configurations in DuckDB

**Status (2026-10-05).** Design document, written on approval of the design
discussion; revised the same day: L1 (PID semantics from
`configAlims/README.md`), L2 (pupitre header reader, `ct` cross-check), L3
(characteristics, units, variable binding, default selection), open
questions reviewed. **No implementation phase is approved yet** — each phase below
gets its own short plan + approval before any code or schema change.
Items marked **[unconfirmed]** are assumptions awaiting an answer (see
[Open questions](#open-questions)).

---

## Goal

Let students (internships, M1/M2 projects) set up and run simulations and
workflow pipelines **in a realistic context** — real assemblies, real
operating conditions, real installation settings — from the standalone
DuckDB database, without going through `python_magnetdb` and its SSO.

Before any simulation runner, the DuckDB schema must hold:

1. the **power and cooling installations** (slow-changing, versioned);
2. the **run configuration** of an assembly (what MAGFILE describes today),
   in a source-independent form;
3. **magnet characteristics** with provenance (R(I,Tin), L, M, field factor,
   flow law);
4. **digital variants** of magnets (geometry/characteristics used by models);
5. **simulations/workflows**, whose CAD/mesh inputs and results live in S3
   (MinIO today → rustfs).

**Acceptance target for the whole design:** for a selected run,
`build_ode_config(<experiment or overview record>)` rebuilds a
magnet-scipy configuration equivalent to
`~/github/magnet_scipy/examples/M9_M23072801/circuits-pid-temp.json`
(R(I,Tin) table, L, mutual M, 3-threshold PID, reference current from the
pigbrother `Signature`, Tin series) entirely from the database.

### Non-goals (for this plan)

- Porting `python_magnetdb`'s FastAPI routes, auth, or Celery worker.
- Fitting/inferring missing history from experiment data (reserved as a
  `source` value only, see L2).
- Writing to any external database.
- Housing M1 (records exist under `srv-data-install/M1`): out of scope for
  now.

---

## Sources inventory

| Source | Content | Current location | Feeds |
|---|---|---|---|
| CIRRUS XML per power supply (`A1_version_config_24.xml`, …) | `version_config`, `date`; regulators by controller type (`numero`: 1 current, 2 voltage, 3–6 Pont1–4), 20 parameter sets (`numero_jeu`, 17–20 = M7–M10), 3 current ranges (`numero_seuil`: 0–60, 60–1000, >1000 A): `Kp`, `Ki`, `Kd` (−1 = 0), `rapport_entre_boucle` (GR1 A1–A2, GR2 A3–A4 coupling), `commande_max/min`, `source_mesure`, `frequence_regulation`; ramps not parsed | history: `https://srv-data-install.lncmi.cnrs.fr/cirrus/<supply>/xml/` or `/srv-data/cirrus/<supply>/xml/` (**not mirrored locally**); 4 samples in `magnet_scipy/examples/M9_M23072801/`; parser + semantics: `python_magnetrun/configAlims/convertxml.py`, `README.md` | L1 |
| Housing configs (`M5`–`M10-housing-config.json`) | GR1/GR2 reference channels, voltage channels `Ucoil1–14` (GR1) / `Ucoil15–16` (GR2), pupitre/pigbrother formula maps (`Référence_GR1 = A1 + A2`, …) | `python_magnetrun/python_magnetrun/`; `housing_config` table | L1, section mapping |
| `WaterFlow` / hysteresis / `HeatExchangerConfig` | pump curve params, primary-loop hysteresis thresholds/values, plate HX geometry + correlation | `python_magnetcooling` | L1, L3 |
| `*-flow_params.json` | `Vp0, Vpmax, F0, Fmax, Pmax, Pmin, Imax` per (assembly, magnet) | `apps/notebooks/`; `overview_records.flow_params` | L3 |
| MAGFILE (`MAGFILEM<n>.conf`) | run configuration: header, per-circuit limits, supply loads, field factors, per-coil R(I) + protection | 14 samples in `~/Downloads/MAGFILE*.conf` (2011–2026); **future: external MySQL**; field notes (French, with units) in `magfile.txt` (repo root) → `python_magnetrun/python_magnetrun/magfile-defs.json` | L2, L3 |
| magnettools / `python_magnetworkflows` CSV | R(I,Tin) per section and total, L, M | e.g. `R_14Helices.csv`, `Rtot_M9Bitters_18MW.csv` | L3 |
| Pupitre file **line 1** (skipped today by python_magnetrun, `skiprows=1`) | embedded MAGFILE core fields: `NbCoil MagnetCode Imax1 Imax2 [r0 a0 b0 ct] × NbCoil` — matches the conf files exactly (checked on M8 `M23012001`, M9 `M25032101`); era-dependent, see L2 "Pupitre header reader" | `~/LNCMIG-Data/records/srv-data-install/<housing>/*.txt` | L2 (per experiment) |
| Channel defs (`pupitre-defs.json`, `hybrid-defs.json`, `pigbrother-defs.json`) | channel units; `IH`/`IB`, `TinH`/`TinB` (older/M8 `Tin1`/`Tin2`), hybrid `I_BOB` (supra current); pupitre `IS` = supra current derived from `I_BOB` during ETL (to add) | `python_magnetrun/python_magnetrun/` | L3 variable binding (`I`, `Tin`) |
| pigbrother `Signature` | reference currents per circuit | `overview_records.signatures` | L5 inputs |
| `overview_records.plateaux` | plateau metadata | `overview_records` | run search only (view), not an entity |
| `python_magnetdb` `Probe` / `python_magnetgeo` `Probe` | name, type (`voltage_taps`/`temperature`/`magnetic_field`), labels, points | held by `Insert`/`Bitters`/`Supras` in magnetgeo | `probes` table |

---

## Design principles

1. **Sources are adapters, the schema is the model.** MAGFILE (conf file
   today, MySQL tomorrow) is parsed into a typed in-memory object, then a
   single writer stores it. Changing source never changes the schema.
2. **Every derived value carries provenance:** `source`
   (`magfile_conf` | `mysql` | `pupitre_header` | `xml` | `json` |
   `magnettools` | `workflow` | `fem` | `measurement` | `fit` | `inferred` |
   `manual`) and `source_ref` (sha256 / row id / path).
3. **Time validity everywhere** (`valid_from` / `valid_to`), resolved
   "active at experiment t0" — same pattern as `assembly_magnets`.
4. **Keep the existing conventions:** name-keyed resources
   (`magnets.name`, `assemblies.name`, …), `CREATE … IF NOT EXISTS` +
   idempotent `ALTER … ADD COLUMN IF NOT EXISTS` in `to_duckdb/schema.py`;
   integer ids from sequences for new versioned/config tables (as
   `operationaldata_id_seq`).
5. **Values stored in SI**, units in column comments and docstrings
   (`[A]`, `[V]`, `[Ohm]`, `[H]`, `[K]`, `[m]`, …). Source units are declared
   in `*-defs.json` files (e.g. `magfile-defs.json`) and converted with pint
   at ingest — see L3 "Units and defs files".
6. **Fields with unconfirmed semantics stay in JSON** until confirmed, then
   are promoted to typed columns by an idempotent migration.
7. **Installation (PID) and run configuration (MAGFILE) are distinct
   layers** (L1 vs L2) — PID changes with the power installation, MAGFILE
   with the run/assembly.

---

## L1 — Installation (versioned, independent of magnets)

```sql
-- Power supplies (A1..A4, hybrid supplies...)
CREATE TABLE IF NOT EXISTS power_supplies (
    name        VARCHAR PRIMARY KEY,     -- 'A1'
    type        VARCHAR,                 -- e.g. thyristor rectifier
    i_max       DOUBLE,                  -- [A]
    u_max       DOUBLE,                  -- [V]
    p_max       DOUBLE,                  -- [W]
    status      VARCHAR,
    metadata    JSON DEFAULT '{}'
);

-- Circuits per housing: GR1 = A1 + A2, GR2 = A3 + A4 (from housing configs)
CREATE SEQUENCE IF NOT EXISTS power_circuits_id_seq START 1;
CREATE TABLE IF NOT EXISTS power_circuits (
    id                  INTEGER PRIMARY KEY DEFAULT nextval('power_circuits_id_seq'),
    housing             VARCHAR REFERENCES housing_config(name),
    circuit             VARCHAR,         -- 'GR1' | 'GR2'
    supplies            VARCHAR[],       -- ['A1','A2']
    reference_current   VARCHAR,         -- channel name, e.g. 'IH'
    reference_voltage   VARCHAR,
    valid_from          TIMESTAMP,
    valid_to            TIMESTAMP
);
-- The M8 hybrid supra supply is not a GR1/GR2 circuit; whether it becomes a
-- power_circuits row (e.g. circuit 'SUPRA') is open question #21. Today the
-- supra current is bound through reference_supra_current (L3).

-- One row per CIRRUS XML file (per supply, per version)
CREATE SEQUENCE IF NOT EXISTS pid_configs_id_seq START 1;
CREATE TABLE IF NOT EXISTS pid_configs (
    id              INTEGER PRIMARY KEY DEFAULT nextval('pid_configs_id_seq'),
    supply          VARCHAR REFERENCES power_supplies(name),
    version_config  INTEGER,
    config_date     TIMESTAMP,           -- XML @date
    sha256          VARCHAR UNIQUE,
    storage_object  INTEGER,             -- raw XML in S3 (L5 storage_objects)
    valid_from      TIMESTAMP,
    valid_to        TIMESTAMP
);

-- Regulator parameters: (config, controller, jeu, seuil)
-- Semantics from python_magnetrun/configAlims/README.md
CREATE TABLE IF NOT EXISTS pid_params (
    pid_config_id         INTEGER REFERENCES pid_configs(id),
    controller            VARCHAR,       -- XML numero: 1 current | 2 voltage | 3..6 pont1..pont4
    jeu                   INTEGER,       -- numero_jeu (parameter set, see pid_param_sets)
    seuil                 INTEGER,       -- numero_seuil 1..3 (current range, see pid_thresholds)
    kp                    DOUBLE,        -- XML -1 stored as 0 (README convention); raw in extra
    ki                    DOUBLE,        -- idem
    kd                    DOUBLE,        -- idem
    rapport_entre_boucle  DOUBLE,        -- loop coupling ratio between the group's two supplies
    commande_min          DOUBLE,
    commande_max          DOUBLE,
    frequence_regulation  DOUBLE,        -- [Hz]
    source_mesure         VARCHAR,
    extra                 JSON DEFAULT '{}',
    PRIMARY KEY (pid_config_id, controller, jeu, seuil)
);
-- All controllers are stored; the ODE builder uses controller = 'current'.

-- Which parameter set a housing uses
CREATE TABLE IF NOT EXISTS pid_param_sets (
    jeu         INTEGER PRIMARY KEY,
    housing     VARCHAR,                 -- jeu = numero_jeu, the id of a parameter set in the XML;
                                         -- 17..20 -> M7..M10; 1..16 have no housing (NULL)
    description VARCHAR
);

-- Current ranges of the PID thresholds (README, ref. "R14L09 p13")
CREATE TABLE IF NOT EXISTS pid_thresholds (
    seuil       INTEGER,
    i_min       DOUBLE,                  -- [A]
    i_max       DOUBLE,                  -- [A], NULL = no upper bound
    source_ref  VARCHAR,                 -- 'R14L09 p13'
    valid_from  TIMESTAMP,
    valid_to    TIMESTAMP,
    PRIMARY KEY (seuil, valid_from)
);
-- Seed: (1, 0, 60), (2, 60, 1000), (3, 1000, NULL).
-- magnet-scipy defaults to high_threshold = 800 A (rlcircuitpid.py) — conflicts
-- with 1000 A here [unconfirmed, open question #18]; build_ode_config passes the
-- DB thresholds explicitly instead of relying on magnet-scipy defaults.
-- Ramps (analogique.rampes.rampe) are not ingested yet (open question #19).

-- Cooling: secondary circuit per housing circuit (pump limits = WaterFlow fields)
CREATE SEQUENCE IF NOT EXISTS cooling_circuits_id_seq START 1;
CREATE TABLE IF NOT EXISTS cooling_circuits (
    id              INTEGER PRIMARY KEY DEFAULT nextval('cooling_circuits_id_seq'),
    housing         VARCHAR REFERENCES housing_config(name),
    circuit         VARCHAR,             -- 'GR1' | 'GR2'
    pump_speed_min  DOUBLE,              -- [rpm]
    pump_speed_max  DOUBLE,              -- [rpm]
    flow_min        DOUBLE,              -- [l/s]
    flow_max        DOUBLE,              -- [l/s]
    pressure_min    DOUBLE,              -- [bar]
    pressure_max    DOUBLE,              -- [bar]
    pressure_back   DOUBLE,              -- [bar]
    heat_exchanger  VARCHAR,             -- FK heat_exchangers(name)
    valid_from      TIMESTAMP,
    valid_to        TIMESTAMP
);

CREATE TABLE IF NOT EXISTS heat_exchangers (
    name                VARCHAR PRIMARY KEY,
    area                DOUBLE,          -- [m^2]
    num_plates          INTEGER,
    plate_spacing       DOUBLE,          -- [m]
    plate_width         DOUBLE,          -- [m]
    correlation_params  DOUBLE[],        -- Nu = a Re^b Pr^c
    metadata            JSON DEFAULT '{}'
);

-- Primary open loop: flow controlled by dissipated power with hysteresis
CREATE SEQUENCE IF NOT EXISTS primary_loop_id_seq START 1;
CREATE TABLE IF NOT EXISTS primary_loop (
    id                  INTEGER PRIMARY KEY DEFAULT nextval('primary_loop_id_seq'),
    scope               VARCHAR,         -- 'installation' or housing name [unconfirmed]
    thresholds          JSON,            -- [[asc, desc], ...] [MW]
    low_values          DOUBLE[],        -- [m^3/h]
    high_values         DOUBLE[],        -- [m^3/h]
    valid_from          TIMESTAMP,
    valid_to            TIMESTAMP
);
```

---

## L2 — Run configuration (source-independent; MAGFILE is one source)

### MAGFILE facts (confirmed in discussion)

- `NMagnet` = **housing** (`NMagnet="9"` → `M9`).
- `MagnetCode` = the **insert** magnet only; the Bitters are implicit.
- `Date`/`Heure` are the **calibration / generation time of the file**
  (`magfile.txt`), related to an **experiment record**; the assembly is
  retrieved from `experiments.assembly_name` — not by "assembly active in
  housing at t0". Since the time is the file's generation time, not an
  experiment start, the conf → experiment link is open question #2.
- A coil slot with `r0 = a0 = b0 = 0` means **that coil does not exist** in
  the assembly.
- Key set varies by era (64 → 208 keys; `Seuil`, `Ratio`, `Ivar2` added
  later; 2- and 3-coil files for M5 and a 2021 `NMagnet=3` file).
- `MagnetCode` can be empty or a non-M code (`HL23`); file names are
  unreliable (named by magnet, date, or with `(2022)`/`b` suffixes).
- MAGFILE history is **incomplete** and will be retrieved from an
  **external MySQL database** in the future.

### Field decomposition

Authoritative per-key definitions (meaning, unit, status, target):
**`python_magnetrun/python_magnetrun/magfile-defs.json`** (created
2026-10-06 from the annotated field notes in `magfile.txt`; 45 entries,
indexed families as `match` regex entries; covers all 2610 key occurrences of
the 14 sample files). Summary:

| MAGFILE fields | Meaning (unit) | Status | Target |
|---|---|---|---|
| `Imax<n>`, `Seuil` | max current of circuit n — per supply in paralleled housings? **[unconfirmed]** (A); eco-mode threshold (A) | active | `config_circuits` |
| `dIdtmax` | theoretical max ramp (A/s); superseded by dB/dt ≈ 50 A/s × FF in eco mode | obsolete | `config_circuits` |
| `Ratio` | eco mode: I_helix = I_bitter × Ratio below `Seuil` (dimensionless) | active | `config_circuits` |
| `Ivar`/`Ivar2`, `Nmaxaimant<n>` | pump law v = 1000 + 2000 (I/Ivar)² [rpm] capped at `Nmaxaimant` (A, rpm) | active | `config_circuits` |
| `Qnom<n>`, `PBnom<n>` | nominal flow (l/s) and pressure (bar) for surveillance | active | `config_circuits` |
| `FF<n>` | field factor (G/A), one per circuit: B = FF1·I₁ + FF2·I₂ — checked on M5 (10.0 T) and M9 (34.986 T); FF3/FF4 duplicate FF1/FF2 in M9 | active | `config_supply_loads.field_factor` + L3 in-situ FF rows |
| `AR<n>`, `AL<n>` | load resistance / inductance (unit unknown) | unused | `config_supply_loads` |
| `r0/a0/b0_coil<i>` | R(I) = r0 + a0·I + b0·I² per section (mΩ, mΩ/A, mΩ/A² — **inferred from data**) | active | `config_sections` + L3 R rows (`polynomial`, section level) |
| `ar/dr_coil<i>` | alarm / fault threshold on resistance deviation (%) — pupitre `DRcoil<i>` | active | `config_sections.protection` |
| `at/dt_coil<i>` | alarm / fault threshold on coil temperature (°C) — pupitre `Tcal<i>` | active | `config_sections.protection` |
| `ct<i>` | temperature coefficient (1/K), often wrong; checked vs `materials.alpha` | active | `config_sections.protection` |
| `G<i>` | gain of the 0/10 V conditioning drawer (dimensionless) | active | `config_sections.protection` |
| `H<i>` | rough inductance from trial and error (mH — **inferred**) | active | `config_sections.protection` |
| `DeltaIA/IU/IS` | supply current surveillance: alarm (A), fault (A), activation flag | active | `operating_configurations.protection` |
| `CableStop` | water-cooled cable surveillance activation | active | `operating_configurations.protection` |
| `DeltaQA/QU/QS` | flow surveillance bands (l/s), activation flag — `DeltaQS = 0`: disabled, flowmeters unreliable | active / disabled | `operating_configurations.protection` |
| `DeltaPBA/PBU/PBS` | pressure surveillance bands (bar), activation flag | active | `operating_configurations.protection` |
| `DeltaPFA/PFU/PFS` | filter ΔP surveillance (mbar? — inferred) | unused | `operating_configurations.protection` |
| `DeltaT0` | not documented | unknown | `operating_configurations.protection` |
| `Center position` | magnetic centre of the helices, from Kévin's field map (mm) | active | `operating_configurations.center_position` |
| `PSused` | supplies ON/OFF bitmask (4 bits, 0..15), for failure cases | active | header column |
| `Couplage` | supplies paralleled (all housings except M5); unused since Basis | obsolete | header column |
| `Type` | supply → coil coupling; obsolete by convention (helices 1–14, Bitters 15–16) except M5 | obsolete | header column |
| `NbCoil` | number of coil slots; obsolete by the same convention | obsolete | header column |

The `****` banner block at the top of old files (e.g. `MAGFILEM5.conf`:
`MAGNET PARAMETERS FILE M5 // D300 : Qnom="63" // Qnom="97"`) is a comment,
not a key: the reader skips it (keeps it in `extra.banner`).

### DDL draft

```sql
CREATE SEQUENCE IF NOT EXISTS operating_configurations_id_seq START 1;
CREATE TABLE IF NOT EXISTS operating_configurations (
    id                INTEGER PRIMARY KEY DEFAULT nextval('operating_configurations_id_seq'),
    assembly_name     VARCHAR REFERENCES assemblies(name),
    experiment_id     INTEGER REFERENCES experiments(id),   -- when the source links one
    valid_from        TIMESTAMP,
    valid_to          TIMESTAMP,
    source            VARCHAR,          -- magfile_conf | mysql | pupitre_header | inferred | manual
    source_ref        VARCHAR,          -- sha256 (content minus Date/Heure) | MySQL row id
    source_timestamp  TIMESTAMP,        -- MAGFILE Date/Heure
    housing           VARCHAR,          -- from NMagnet, cross-check vs assembly
    insert_code       VARCHAR,          -- MagnetCode, cross-check vs assembly insert
    resolution_status VARCHAR,          -- ok | insert_mismatch | no_experiment | section_mismatch
                                        -- | source_mismatch | ct_mismatch (several → JSON list)
    nb_coil           INTEGER,
    ps_used           INTEGER,
    couplage          INTEGER,
    type_code         INTEGER,
    center_position   DOUBLE,           -- [m] (source: mm, magfile-defs.json)
    protection        JSON DEFAULT '{}',-- Delta*, CableStop, DeltaT0
    extra             JSON DEFAULT '{}',-- any key not mapped above (era-dependent keys)
    storage_object    INTEGER           -- raw source file in S3, when file-based
);

CREATE TABLE IF NOT EXISTS config_circuits (
    config_id     INTEGER REFERENCES operating_configurations(id),
    circuit       INTEGER,              -- 1 | 2 (GR1 | GR2)
    i_max         DOUBLE,               -- [A]
    i_var         DOUBLE,               -- [A]
    n_max_pump    DOUBLE,               -- Nmaxaimant [rad/s] (source rpm)
    q_nom         DOUBLE,               -- Qnom [m^3/s] (source: l/s)
    pb_nom        DOUBLE,               -- PBnom [Pa] (source bar)
    didt_max      DOUBLE,               -- [A/s] (header-level, repeated per circuit)
    seuil         DOUBLE,
    ratio         DOUBLE,
    PRIMARY KEY (config_id, circuit)
);

CREATE TABLE IF NOT EXISTS config_supply_loads (
    config_id     INTEGER REFERENCES operating_configurations(id),
    slot          INTEGER,              -- 1..4 (key index; FF1/FF2 = circuits 1/2, FF3/FF4 duplicates in M9)
    load_r        DOUBLE,               -- AR — unused, source unit unknown
    load_l        DOUBLE,               -- AL — unused, source unit unknown
    field_factor  DOUBLE,               -- FF [T/A] (source: G/A)
    PRIMARY KEY (config_id, slot)
);

CREATE TABLE IF NOT EXISTS config_sections (
    config_id     INTEGER REFERENCES operating_configurations(id),
    slot          INTEGER,              -- MAGFILE coil index (1..NbCoil)
    r0            DOUBLE,
    a0            DOUBLE,
    b0            DOUBLE,
    protection    JSON DEFAULT '{}',    -- ar, dr, at, dt, ct, G, H; ct_check result
    PRIMARY KEY (config_id, slot)
);
-- Slots with r0 = a0 = b0 = 0 are NOT stored (section absent).
```

### Resolution rules

- **Experiment → assembly:** `experiments.assembly_name` (already stored).
- **Experiment → configuration:** the `operating_configurations` row for that
  assembly with `valid_from <= t0 < valid_to` (t0 parsed from
  `experiments.name` = `"YYYY.MM.DD - HH:MM:SS"`; optionally materialise as a
  new `experiments.t0 TIMESTAMP` column).
- **MAGFILE conf → experiment (reader detail):** candidates filtered by
  housing `M{NMagnet}`; matching rule **[unconfirmed, open question #2]**.
  `Date`/`Heure` is the file's generation time, which favours a validity
  window (the conf applies to the housing's experiments from that time until
  the next conf) over the earlier proposal "nearest *preceding* experiment on
  the same day" (gap in `extra.match_delta_s`). Example: `MAGFILEM9.conf`
  2026-07-07 13:28:52 vs M9 experiment `2026.07.07 - 13:02:15` (id 6248).
- **Configuration validity:** `valid_from` = source timestamp; `valid_to` =
  next configuration of the same assembly (or assembly decommissioning).
- **Cross-checks (logged, never rejected):** housing vs assembly housing;
  `insert_code` vs the assembly's insert magnet; number of stored sections vs
  sections expected from the mapping below.

### Section (MAGFILE "coil") mapping — confirmed rules

A MAGFILE coil is a **section**, a different unit from `magnet_parts.coil_index`
(which maps one part to one `Icoil_N` column, see `to_duckdb/docs/schema.md`).
To avoid the name clash, the schema calls it a *section*.

1. **Slot of each magnet role — derived, no extra key:** slot *s* is the
   `Ucoil<s>` / `Icoil<s>` channel. A role's sections start at the first
   `Ucoil` index of the GR assigned to it (`housing_config.coil_assignment`
   + `voltage_channels_gr<n>` of the housing config):

   | Housing | Wiring | Slots |
   |---|---|---|
   | M8, M10 | Insert GR2 (`Ucoil1–14`), Bitters GR1 (`Ucoil15–16`) | insert 1–14, Bitters 15–16 |
   | M9 | Insert GR1 (`Ucoil1–14`), Bitters GR2 (`Ucoil15–16`) | insert 1–14, Bitters 15–16 |
   | M7 | Insert only, GR1 (`Ucoil1–7`) | insert 1–7 |
   | M5 | Bitters only, GR1 (`Ucoil1–2`) | Bitters 1–2 |
   | M3 | needs a new `M3-housing-config.json` (3 coils) | open question #20 |

   M5 and M7 are single-group housings (confirmed); their `magnetdb.duckdb`
   rows were corrected on 2026-10-05 (data issue #8).
2. **Probes defined:** local section *i* = the *i*-th probe of
   `type = 'voltage_taps'` of that magnet (ordered by `probes.rank`).
   Temperature and magnetic-field probes never count.
3. **No probes — insert:** disjoint helix pairs, as in magnet-scipy
   `R_14Helices.csv`: section *k* = helix parts with `coil_index` ∈
   {2k−1, 2k} (H1H2, H3H4, …).
4. **No probes — Bitters:** one voltage tap per Bitter part: section *j* =
   Bitter part with `coil_index` = j.
5. **Ordering** is inner → outer. `magnet_parts.coil_index` follows the magnet
   definition order, so this assumes magnet JSON lists parts inner → outer;
   verified at ingest (inner radius increasing with `coil_index`, from
   `geometry_data`).

Exposed as a view, so adding probes later automatically overrides the
default:

```sql
-- v_config_sections: (config_id, slot, magnet_name, section_index, part_names[] | probe_name)
```

### Probes

```sql
CREATE TABLE IF NOT EXISTS probes (
    name          VARCHAR PRIMARY KEY,
    magnet_name   VARCHAR REFERENCES magnets(name),
    part_name     VARCHAR REFERENCES parts(name),
    type          VARCHAR,              -- voltage_taps | temperature | magnetic_field
    rank          INTEGER,              -- order within (magnet, type), inner -> outer
    labels        VARCHAR[],
    points        JSON,                 -- [[x, y, z], ...] [m]
    metadata      JSON DEFAULT '{}'
);
```

Built to round-trip with `python_magnetgeo.Probe` (`name`, `type`,
`labels`, `points`) so FEM setups can write probe YAML.

### Reader architecture

```
MagfileConfReader   (now)       ┐
MagfileMySQLReader  (future)    ├─> OperatingConfig (dataclass) ─> write_operating_config(con, cfg)
PupitreHeaderReader (now)       ┤
InferredConfigBuilder (reserved)┘
```

- New modules (snake_case), e.g. `to_duckdb/operating_config.py`
  (dataclass + writer + resolution helpers) and
  `to_duckdb/readers/magfile_conf.py`.
- `MagfileConfReader`: tolerant `key="value"` parser; ignores `#` lines;
  key → column mapping and source units come from `magfile-defs.json`
  (values converted to SI); keys without a defs entry go to `extra`
  (flagged); content hash excludes
  `Date`/`Heure` (an unchanged MAGFILE re-saved per session is not a new
  version); raw file uploaded to S3 once L5 storage exists.
- Coverage view `v_experiments_without_config`: experiments with no
  configuration version, per assembly — gaps stay visible, never silently
  filled.

### Pupitre header reader (embedded MAGFILE parameters)

Line 1 of recent pupitre files carries the MAGFILE core fields **for that
exact experiment**:

```
NbCoil  MagnetCode  Imax1  Imax2  [r0  a0  b0  ct] × NbCoil
16      M23012001   14490  13990  0.526603 2.86009e-06 6.34217e-11 0.0038 …
```

(4 + 4 × NbCoil values; identical to `MAGFILEM8.conf` / `MAGFILEM9.conf`.)
It largely closes the MAGFILE history gap for recent runs: no time matching
is needed for these fields. The conf file / MySQL stays the source for the
other fields (`Ivar`, `FF`, `Qnom`, `AR/AL`, surveillance, protection).

- `PupitreHeaderReader` feeds the same `OperatingConfig` → writer, with
  `source = 'pupitre_header'` and `experiment_id` set directly. Units from
  `magfile-defs.json` (same keys).
- **Line-1 classification** (era-dependent, observed in
  `~/LNCMIG-Data/records/srv-data-install`):

  | Class | Recognised by | Stored |
  |---|---|---|
  | full | first token integer `NbCoil`, field count = 4 + 4 × NbCoil (split on **tab**, keeping empty fields: M3 has an empty `MagnetCode`) | everything |
  | short | `NbCoil` only (2011–2012); `NbCoil MagnetCode` (M10 2018); `NbCoil <label>` (M8 2016 `HL-28_1_BI04_1_BE02_1_13/05/2014`) | what is present; label in `extra` |
  | data | first token parses as a date (M10 2011/2013 files) | nothing — no parameter line; file flagged |
  | empty / unreadable | empty line, null bytes | nothing; file flagged |

- **Observed coverage** (files with more than 4 values on line 1, first
  occurrence): M9 1816 / 6413 from 2021-09-03; M7 11 / 322 from
  2021-12-09; M8 162 / 960 from 2022-11-24; M10 1498 / 5287 — **start not
  established** (inflated by "data" lines; first `MagnetCode` line
  2018-01-20). To be measured with the reader's own classification in
  phase 2.
- **Reconciliation and precedence:** when a conf/MySQL configuration and a
  pupitre header both exist for a run, overlapping fields are compared. For
  its own experiment the **pupitre header wins** (written with the run); the
  conf value is kept in `extra` and `resolution_status` gets
  `source_mismatch`.
- **Versioning:** a new configuration version is created only when the
  header content changes within the same assembly; repeated identical
  headers (e.g. ~1800 M9 files) point to the existing version, whose
  `experiment_id` is the first occurrence.
- Files of class *data* or *empty* get a file-level flag
  (`no_parameter_line`) in the coverage view, never a configuration row.
- Section absence still requires `r0 = a0 = b0 = 0`: M8 Bitters coils 15/16
  have `r0 = 0` with non-zero `a0`/`b0`. Slot 1 of M9 `M25032101` is
  `0 0 0` in both `MAGFILEM9.conf` and the 2026-10-02 pupitre header (see
  open question #3).

### Temperature coefficient cross-check (`ct` vs `materials.alpha`)

`ct<i>` is the temperature coefficient [1/K] of section *i* (confirmed).
**`materials.alpha` is the reference**; `ct` is checked against it, never
used to compute R(T).

- Parts of the section come from the section mapping above (insert section
  *k* → its helix pair; Bitters section *j* → that Bitter part; probes when
  defined).
- **Insert:** `ct` is one global alpha for the material of the 2 consecutive
  helices. Expected value = resistance-weighted mean of the two helices in
  series:
  α_eff = (R₁,ref·α₁ + R₂,ref·α₂) / (R₁,ref + R₂,ref).
  Same alpha for both helices → compare directly; different alphas with
  part-level reference R known (L3 part rows, or geometry + conductivity) →
  compare with α_eff; otherwise plain mean, check marked `approximate`.
- **Bitters:** one Bitter part per section → compare directly.
- Tolerance: float precision (≈1e-6) — both given to 2–4 significant digits.
- Result per section in `config_sections.protection.ct_check`
  (`{"alpha": …, "ct": …, "delta": …, "method": "direct|weighted|approximate"}`);
  mismatches add `ct_mismatch` to `resolution_status` and are listed by
  `magnetdb.py check`. Never rejected.
- Done at ingest by both readers (conf files and pupitre headers carry `ct`).
- Until `materials.alpha` is corrected (data issue #7), almost every section
  will report a mismatch.

---

## L3 — Magnet characteristics (with provenance)

### Requirements (confirmed 2026-10-05)

- **Quantities:** resistance R, self-inductance L and field factor FF **per
  magnet**; mutual inductance M **per assembly**.
- **Granularity:** a value may be given for the whole magnet, for each part
  (`helix` | `bitter` | `supra`), or for each voltage-tap section (MAGFILE
  `r0/a0/b0` are per section).
- **Representations:** constant, polynomial fit, sympy expression, CSV table.
- **Several models** may coexist (MAGFILE, magnettools, FEM/workflow,
  measurement fit, manual), each with its own provenance.
- **Values change over time** (ageing, reconfiguration) → validity windows.
- **Units:** everything stored in **SI** (Ω, H, T/A, A, K). Source units are
  declared explicitly in defs files (see [Units](#units-and-defs-files)).

### Table

```sql
CREATE SEQUENCE IF NOT EXISTS electrical_characteristics_id_seq START 1;
CREATE TABLE IF NOT EXISTS electrical_characteristics (
    id                    INTEGER PRIMARY KEY DEFAULT nextval('electrical_characteristics_id_seq'),
    quantity              VARCHAR NOT NULL,  -- resistance | self_inductance | field_factor | mutual_inductance
    -- target: the level of detail is set by which columns are filled
    magnet_name           VARCHAR REFERENCES magnets(name),
    part_name             VARCHAR REFERENCES parts(name),        -- per-part value
    section_index         INTEGER,                               -- per voltage-tap section
    assembly_name         VARCHAR REFERENCES assemblies(name),   -- mutual (required) / in-situ FF (optional)
    digital_magnet_name   VARCHAR,          -- L4 option B: FK digital_magnets(name)
    digital_assembly_name VARCHAR,          -- L4 option B: FK digital_assemblies(name)
    -- value
    representation        VARCHAR NOT NULL,  -- constant | polynomial | expression | table | vector
    variables             VARCHAR[],         -- independent variables: subset of ['I', 'Tin']
    unit                  VARCHAR,           -- SI unit of the quantity: 'ohm' | 'H' | 'T/A'
    value                 DOUBLE,            -- representation = constant
    params                JSON,              -- polynomial / expression / table mapping / vector
    storage_object        INTEGER,           -- CSV table in S3 (L5 storage_objects)
    -- provenance
    source                VARCHAR,           -- magfile_conf | mysql | magnettools | workflow | fem | measurement | fit | manual
    model                 VARCHAR,           -- model / method / version
    source_ref            VARCHAR,           -- config id, file sha256, ...
    simulation_id         INTEGER,           -- when computed by an L5 simulation
    conditions            JSON DEFAULT '{}', -- reference Tin, flow, cooling, FF reference point {"r":0,"z":..} [m]
    -- time and default
    valid_from            TIMESTAMP,
    valid_to              TIMESTAMP,
    preferred             BOOLEAN DEFAULT FALSE,
    created_at            TIMESTAMP DEFAULT current_timestamp,
    comment               VARCHAR,
    -- mutual inductance lives at assembly level only
    CHECK (quantity <> 'mutual_inductance'
           OR ((assembly_name IS NOT NULL OR digital_assembly_name IS NOT NULL)
               AND magnet_name IS NULL AND digital_magnet_name IS NULL)),
    -- a magnet-level quantity targets exactly one real or digital magnet
    CHECK (quantity = 'mutual_inductance'
           OR ((magnet_name IS NULL) <> (digital_magnet_name IS NULL)))
);
```

**Target levels** (which columns are filled):

| Level | Columns |
|---|---|
| magnet | `magnet_name` (or `digital_magnet_name`) |
| part | + `part_name` — the writer checks the part belongs to the magnet |
| section | + `section_index` (see the L2 section mapping) |
| in-situ FF | `magnet_name` + `assembly_name` |
| mutual | `assembly_name` (or `digital_assembly_name`) only |

### Representations (`params`, validated by Python dataclasses at write time)

| Representation | Example |
|---|---|
| `constant` | `value = 0.0133`, `unit = 'ohm'` |
| `polynomial` | `{"variable": "I", "coefficients": [r0, a0, b0]}` (power basis, SI); multivariate: `{"terms": [{"coef": c, "powers": {"I": 2, "Tin": 0}}]}` |
| `expression` | `{"expr": "R0*(1 + alpha*(Tin - T0)) + k*I**2", "parameters": {"R0": …, "alpha": …, "T0": 293.15}}` — sympy, **never `eval()`** |
| `table` | CSV in S3 + column mapping: `{"x": ["I[A]"], "y": "R_H1H2[ohm]", "fixed": {"Tinit[C]": 4}}` |
| `vector` | mutual inductances only, see below |

One CSV may feed several rows: `R_14Helices.csv` gives 7 section rows
(`R_H1H2` … `R_H13H14`) and 1 magnet row (`R[ohm]`), all pointing to the
same `storage_object` with different `y` columns.

### Expression variables and their binding

Expressions, polynomials and tables use **generic variables**, bound to
measured channels when evaluated:

- `I` [A] — the current of the circuit feeding the magnet (all sections of a
  magnet are in series, so they share it); for **supra** parts, the supra's
  own current.
- `Tin` [K] — the inlet temperature of that circuit.

Binding helper, e.g.
`bind_variables(con, assembly, magnet, source_format) -> {"I": "IH", "Tin": "TinH"}`:

1. magnet role → circuit via `housing_config.coil_assignment`
   (e.g. M10 `{'Insert': 'GR2', 'Bitter': 'GR1'}`; the insert is on GR1 in
   M9 but GR2 in M8/M10);
2. circuit → current channel via `reference_gr<n>_current` (exists today);
3. circuit → inlet temperature via **new** `reference_gr<n>_tin` keys
   (e.g. M9: `TinH` / `TinB`) — explicit, not derived from the `H`/`B`
   suffix, because older data and M8 files use `Tin1`/`Tin2` (also
   `Flow1/2`, `HP1/2`, `Rpm1/2`);
4. supra → **new** `reference_supra_current` = pupitre **`IS`** when present,
   otherwise hybrid `I_BOB` extracted on the fly (same procedure as below).
   Pupitre files have no native supra current; `IS` is a **derived channel
   added during ETL** (see [Supra current](#supra-current-is-derived-during-etl));
5. pigbrother names resolved through the formula maps already in the
   housing configs;
6. each bound channel converted with pint from its defs unit to SI before
   evaluation (e.g. `TinH` is `degC` in `pupitre-defs.json`; `Tin` is in K).

Limit: a quantity depends on its own circuit's current only. A dependence on
two circuits at once would need named variables (`I_GR1`, `I_GR2`, …) —
future extension, not designed now.

### Supra current: `IS` derived during ETL

Procedure, as implemented (uncommitted) for M8 in
`apps/dashboards/magnetdb/src/magnetdb_analysis.py`:

1. condition: housing M8 (today the only one), the experiment's assembly
   contains a `supra` part (`assembly_has_supra`), and a hybrid kHz source is
   linked through `overview_records.sources_hybrid_kHz`
   (`get_hybrid_khz_source`);
2. load `kHz/FEPC-LNCMI/I_BOB` with `HybridRun.fromdir(…, fepc_system="FEPC-LNCMI")`
   for the UTC hours the pupitre file spans, resample to 1 Hz
   (`load_hybrid_supra_current`);
3. align onto the pupitre timestamps with `merge_asof(direction="nearest",
   tolerance=0.5 s)`; store as column **`IS`** [A].

- Provenance: column marked as derived (hybrid `I_BOB`, hybrid source path)
  — fits python_magnetrun Stream 4.7 (`properties`, `FieldMeta.category`).
- `pupitre-defs.json` gains an `IS` entry ("Supra current, derived from
  Hybrid I_BOB during ETL", unit `ampere`, group `Courants_Alimentations`).
- No linked hybrid source → no `IS` column (never zero-filled).
- `get_hybrid_khz_source` / `load_hybrid_supra_current` move from the
  dashboard to a shared module (python_magnetrun or `to_duckdb`) so ETL,
  dashboard and binding share one implementation.
- Where the ETL step lives (python_magnetrun Stream 4.7 parquet save, or
  `to_duckdb` populate) — open question #15; decided in its phase plan.

### Mutual inductance (confirmed rules)

- **Only coupling terms between different magnets** are stored — no self
  terms, no part-to-part mutuals within one magnet. Building the full matrix
  and grouping parts into sections is done in magnet-scipy.
- **Magnet level — `vector`:** upper triangle in `np.triu_indices(n, k=1)`
  order (the magnet-scipy layout, n(n−1)/2 values), with an **explicit
  order**:
  `{"order": ["M25032101", "M9Bitters-newBi10"], "layout": "triu", "values": [0.001965]}`.
  The writer checks `order` = the assembly's magnets and
  `len(values) == n(n−1)/2`.
- **Part level — `table`** (CSV in S3), **one block per part**: for each
  part of magnet *i*, its coupling with every part of magnets *j > i* in
  `order` (each pair stored once). Columns
  `magnet_i, part_i, magnet_j, part_j, M[H]`. The writer checks block
  completeness.
- **Current dependence — supra only:** L and M of supra parts may depend on
  `I` (the supra current, see binding); they then use `table` or
  `expression` with `variables = ['I']`. Everything else is constant.

### Field factor

- **Intrinsic** rows (`magnet_name` only): factor at the magnet's own centre.
- **In-situ** rows (`magnet_name` + `assembly_name`): contribution at the
  assembly field centre, which depends on the magnet's position
  (`assembly_magnets.z_offset`, MAGFILE `Center position`).
- `get_field_factor(..., assembly=X)` returns the in-situ row when one
  exists, else the intrinsic one. The reference point is stored in
  `conditions`.
- MAGFILE `FF<n>` are in-situ values in G/A, **one per circuit**:
  B = FF1·I₁ + FF2·I₂, checked against measured field on M5
  (6.899 × 8742.1 + 4.539 × 8743.5 → 10.0 T) and M9
  (8.943 × 29515 + 3.634 × 23640 → 34.986 T, measured 34.986 T). `FF3`/`FF4`
  duplicate `FF1`/`FF2` in `MAGFILEM9.conf`.

### Default and source selection

- **`preferred` flag = the default.** At most one preferred row per target,
  quantity and overlapping validity period (enforced by the writer and
  `set_preferred`).
- The writer marks the **first** row of a target/quantity/period as
  preferred automatically; later rows stay non-preferred until
  `set_preferred` is called — adding a new model never changes the default
  silently.
- **Lookup with an explicit `source`** (optionally `model`): choose among that
  source's rows (preferred first, then latest `valid_from`); **none → error**,
  never a silent fallback to another source.
- **Lookup without `source`:** the preferred row. **No preferred row and
  several candidates → raise an error** listing the candidates and telling
  the user to set a preferred one, e.g.:
  > Several resistance models are valid for M25032101 at 2026-07-07 13:02:15
  > and none is marked as preferred: [12 magfile_conf polynomial, 31
  > magnettools table, 44 fem …]. Pass `source=…`, or set a default with
  > `set_preferred(con, <id>)` (CLI: `magnetdb.py characteristic set-preferred <id>`).

### Lookup API

New module, e.g. `to_duckdb/characteristics.py`:

| Function | Returns |
|---|---|
| `get_resistance(con, magnet, *, at, part=None, section=None, source=None, model=None)` | `Characteristic`: callable `f(I=…, Tin=…)` in SI + `id`, `source`, `model`, `representation`, `unit`, `valid_from/to` |
| `get_self_inductance(con, magnet, *, at, part=None, source=None, model=None)` | `Characteristic` (current-dependent for supra only) |
| `get_field_factor(con, magnet, *, at, assembly=None, part=None, source=None, model=None)` | `Characteristic` (in-situ first when `assembly` given) |
| `get_mutual_inductances(con, assembly, *, at, level="magnet", source=None, model=None)` | magnet level: `order` + upper-triangle `values`; part level: the coupling table |
| `list_characteristics(con, quantity, *, magnet=None, assembly=None, at=None)` | DataFrame of all candidates (source, model, validity, preferred) |
| `get_characteristic_by_id(con, id)` | the exact row — reproducing a past run |
| `set_preferred(con, id)` | marks the row as default, clears overlapping preferred rows |

Real and digital targets go through the same functions (a `digital=True`
argument, or accepting either kind of name).

Aggregation fallback: with no magnet-level row, R and FF may be summed over
parts or sections (series connection, superposition at the field centre).
L is never aggregated (part-to-part mutuals within a magnet are not stored).

Temperature dependence: R(T) models use **`materials.alpha`** (per part, or
the resistance-weighted α_eff per section, see L2 cross-check). MAGFILE `ct`
is kept with the configuration as provenance only.

### What existing sources produce

| Source | Rows |
|---|---|
| MAGFILE `r0/a0/b0_coil<i>` | R, `polynomial`, section level, `source = magfile_conf`, valid from the configuration's `valid_from` |
| MAGFILE `FF1–4` | FF, `constant`, in-situ |
| magnet-scipy `inductance` | self L, `constant`, magnet level |
| magnet-scipy `mutual_inductances` | M, `vector`, assembly level |
| `R_14Helices.csv` | R, `table`, 7 section rows + 1 magnet row |
| `Rtot_M9Bitters_18MW.csv` | R, `table`, magnet level |

### Units and defs files

- Storage is **SI only**.
- Units of data read from MAGFILE (conf file or the future MySQL database)
  are declared in **`magfile-defs.json`, bundled in
  `python_magnetrun/python_magnetrun/`** next to the other `*-defs.json`
  files and resolved through `python_magnetrun.field_defs.resolve_defs_file`
  (user override first, then bundled) — same format as
  `supervision-bdd-defs.json`: `{description, symbol, unit (pint string or
  null), group}`, plus a `target` field naming the schema column the key
  feeds (e.g. `config_sections.r0`), so the reader is driven by the defs file.
  **Created 2026-10-06** (not yet committed in the submodule). Extra keys per
  entry: `description_fr` (verbatim note from `magfile.txt`), `unit_status`
  (`confirmed` | `inferred` | `unknown` | `n/a`), `status` (`active` |
  `obsolete` | `unused` | `disabled` | `unknown`), `related`, `index`.
- Indexed key families (`r0_coil<i>`, `FF<i>`, `AR<i>`, `Imax<i>`, …) use
  one pattern entry per family with a `"match"` regex, aligned with
  python_magnetrun Stream 3.7 ("pattern defs", not implemented in
  `load_units_from_json` yet — the MAGFILE reader applies the regexes itself).
- **[FIXED 2026-10-06]** Bundled-resource lookup from the repo root. Python
  started there imported the submodule directory `python_magnetrun/` (no
  `__init__.py`) as a namespace package, so
  `importlib.resources.files("python_magnetrun")` pointed to the outer
  directory: code still imported, but no bundled JSON was found
  (`HOUSING_CONFIGS` empty, `resolve_defs_file` failing). `housing_config.py`
  and `field_defs.py` now resolve bundled files from `Path(__file__)` (as
  `plotting/style.py` already did); regression test
  `python_magnetrun/tests/test_bundled_resources.py`. This is the fix
  proposed in `PLAN_waterflow_dashboard.md` (its steps 1–2). Not committed
  (submodule branch `spike/tdms-polars-benchmark`).
- Conversion at ingest: value [defs unit] → pint → SI. A key without a defs
  entry is kept raw in `extra` and flagged, never converted.
- MySQL: shared `magfile-defs.json` or a separate defs file — decided once
  the MySQL schema is known.

### Flow parameters

```sql
CREATE SEQUENCE IF NOT EXISTS flow_params_id_seq START 1;
CREATE TABLE IF NOT EXISTS flow_params (
    id             INTEGER PRIMARY KEY DEFAULT nextval('flow_params_id_seq'),
    assembly_name  VARCHAR REFERENCES assemblies(name),
    magnet_name    VARCHAR,             -- or circuit
    circuit        VARCHAR,
    fitted_at      TIMESTAMP,
    source         VARCHAR,             -- fit | file | magfile_conf | manual
    source_ref     VARCHAR,
    params         JSON                 -- {"Vp0": {"value":..,"unit":"rpm"}, ...} as today
);
```

`flow_params` also provides the missing
`get_flow_params_for_assembly(assembly, before=date)` assumed by
`PLAN_waterflow_dashboard.md`.

---

## L4 — Digital variants

**Option B (recommended) [unconfirmed]:** separate tables, existing real
tables and lifecycle rules untouched.

```sql
CREATE TABLE IF NOT EXISTS digital_magnets (
    name             VARCHAR PRIMARY KEY,
    real_name        VARCHAR,           -- NULL for pure design studies
    variant          VARCHAR,           -- as_designed | as_built | study
    geometry_data    JSON,
    owner            VARCHAR,
    created_at       TIMESTAMP DEFAULT current_timestamp,
    metadata         JSON DEFAULT '{}'
);
-- digital_parts / digital_magnet_parts / digital_assemblies follow the same pattern,
-- with material overrides; CAD/mesh referenced via storage_objects.
```

Option A (a `kind` column on `parts`/`magnets`/`assemblies`) was rejected
as the default because every lifecycle/overlap/stats query in `crud.py`
would need a `kind = 'real'` filter.

The geometry builders in `to_duckdb/stress_map.py`
(`magnet_geometry_config_to_yaml`, `geometry_config_to_yaml`,
`prepare_geometry_directory`) are refactored to accept either a real or a
digital source.

---

## L5 — Storage objects and simulations

```sql
CREATE SEQUENCE IF NOT EXISTS storage_objects_id_seq START 1;
CREATE TABLE IF NOT EXISTS storage_objects (
    id            INTEGER PRIMARY KEY DEFAULT nextval('storage_objects_id_seq'),
    bucket        VARCHAR,
    key           VARCHAR,
    size          BIGINT,
    sha256        VARCHAR,
    content_type  VARCHAR,
    created_at    TIMESTAMP DEFAULT current_timestamp
);

CREATE SEQUENCE IF NOT EXISTS simulations_id_seq START 1;
CREATE TABLE IF NOT EXISTS simulations (
    id                 INTEGER PRIMARY KEY DEFAULT nextval('simulations_id_seq'),
    kind               VARCHAR,         -- fem (python_magnetsetup) | ode (magnet-scipy) | workflow
    target_type        VARCHAR,         -- magnet | assembly | digital_magnet | digital_assembly
    target_name        VARCHAR,
    experiment_id      INTEGER,         -- realistic context: the run being replayed
    overview_filename  VARCHAR,         -- signatures / reference currents
    config_id          INTEGER,         -- L2 operating configuration used
    method             VARCHAR,         -- fem: cfpdes, ...
    model              VARCHAR,
    geometry           VARCHAR,         -- Axi | 3D
    cooling            VARCHAR,
    static             BOOLEAN,
    non_linear         BOOLEAN,
    status             VARCHAR DEFAULT 'pending',
    setup_status       VARCHAR DEFAULT 'pending',
    setup_state        JSON DEFAULT '{}',
    setup_object       INTEGER,         -- storage_objects
    output_object      INTEGER,
    log_object         INTEGER,
    owner              VARCHAR,
    inputs             JSON DEFAULT '{}',  -- ids of every L3 characteristic, L1/L2 row used
    metadata           JSON DEFAULT '{}',
    created_at         TIMESTAMP DEFAULT current_timestamp,
    updated_at         TIMESTAMP
);

CREATE TABLE IF NOT EXISTS simulation_currents (
    simulation_id  INTEGER REFERENCES simulations(id),
    magnet_name    VARCHAR,
    value          DOUBLE,              -- [A]
    PRIMARY KEY (simulation_id, magnet_name)
);
```

- `inputs` records the exact characteristic / configuration ids a run used
  (`get_characteristic_by_id`), so it can be reproduced even after the
  `preferred` default changes.
- S3 key convention and client: reuse `rustfs/magnetfs` and the convention
  being defined by `python_magnetrun` Stream 4.7 (D7), not a second one.
- **DuckDB single-writer constraint:** a runner must not hold a write
  connection while a job runs (it would lock out dashboards). Open → update
  status → close; results are written in one short transaction at the end.
- `simulation_measures` (optional, later): load `*.measures/values.csv`
  into a table so simulated and measured values can be compared in SQL.
- Plateaux: `v_run_plateaux` view flattening `overview_records.plateaux`
  for run search; no entity.

---

## Phasing

Each phase gets its own plan file + approval; tests are written first,
following the existing `to_duckdb/tests/test_*_db.py` pattern.

1. **L1 installation** — `power_supplies`, `power_circuits`, `pid_configs`,
   `pid_params`, `pid_param_sets`, `pid_thresholds`, `cooling_circuits`,
   `heat_exchangers`, `primary_loop`; ingest from CIRRUS XML + housing
   configs. **Prerequisite:** access to the CIRRUS XML history on srv-data
   (mirror locally or read in place); the 4 magnet-scipy samples suffice for
   tests, not for history.
   → verify: ingesting `magnet_scipy/examples/M9_M23072801/A*_version_config_*.xml`
   gives, for A1 / controller `current` / jeu 19, Kp = 4/4/6 and Ki = 2
   (= magnet-scipy `M9Bitters` `pid_params`); `Kd = -1` stored as 0 with the
   raw value in `extra`; all controllers (current, voltage, pont1–4)
   ingested; re-ingest is idempotent (sha256).
2. **Probes + L2 run configuration** — `probes`, `operating_configurations`
   and children, `MagfileConfReader`, `PupitreHeaderReader`,
   `v_config_sections`, `v_experiments_without_config`;
   **python_magnetrun:** `magfile-defs.json` (created 2026-10-06, to commit)
   and `M3-housing-config.json` (bundled in `python_magnetrun/python_magnetrun/`).
   (M5/M7 `housing_config` rows: fixed, data issue #8.)
   → verify: all 14 sample MAGFILEs parse (64–208 keys) with keys lacking a
   defs entry in `extra`; values stored in SI per the defs units;
   `MAGFILEM9.conf` → housing M9, 6 stored insert sections (slots 2–7) +
   Bitters slots 15–16, slot 1 absent; re-saved identical file → no new
   version; pupitre headers of M8/M9/M10 2026 files give the same
   `r0/a0/b0/ct`/`Imax` as the matching conf files; one sample per line-1
   class (full / short / data / empty) classified correctly, including the
   M3 header with an empty `MagnetCode`; slots map to roles per the derived
   rule for M5 (Bitters 1–2), M7 (insert 1–7), M8/M9/M10; coverage per
   housing reported from the reader's own classification.
3. **L3 characteristics** — `electrical_characteristics` +
   `to_duckdb/characteristics.py` (lookup API, `set_preferred`, binding),
   `flow_params`; projection of MAGFILE R(I)/FF; import of magnettools CSV,
   magnet-scipy L / M and `*-flow_params.json`; CLI
   `characteristic list | set-preferred`. **python_magnetrun:**
   `reference_gr<n>_tin` and `reference_supra_current` in the housing
   configs, `IS` entry (derived channel) in `pupitre-defs.json`.
   **Before phase 4:** `IS` ETL step (location per open question #15) +
   move of `get_hybrid_khz_source` / `load_hybrid_supra_current` to a
   shared module — needed for M8 supra runs.
   → verify: `R_14Helices.csv`/`Rtot_M9Bitters_18MW.csv` round-trip;
   `get_resistance(M25032101, at=…)` evaluated with `I=IH`, `Tin=TinH`
   (bound + converted to K) matches the CSV; no preferred + 2 candidates →
   error naming both; explicit `source` never falls back; M `vector` length
   checked against n(n−1)/2; waterflow dashboard lookup returns DB params
   when present.
4. **ODE config builder** — `build_ode_config(...)`.
   **Prerequisites:** reference currents come from
   `overview_records.signatures` — `magnetdb.duckdb` has **0** overview
   records, `test-magnetdb.duckdb` has 1915 (both have magnet `M23072801`,
   assembly `M9_A230801_00`, and 3 M9 experiments on 2023-09-16), so the
   acceptance test runs against `test-magnetdb.duckdb` or a fixture
   extracted from it until `magnetdb.duckdb` has overview records; R(T)
   depends on corrected `materials.alpha` (data issue #7).
   → verify: acceptance target above for M9_M23072801.
5. **Storage objects + rustfs** — `storage_objects`, upload/download helpers.
   → verify: against a test rustfs instance (or a local S3-compatible
   fixture in tests).
6. **L4 digital variants** — after the A/B decision.
7. **L5 simulations** — FEM (magnetsetup, Axi first) and ODE runners,
   CLI subcommands in `to_duckdb/magnetdb.py`.

Files expected per phase (to be confirmed in each phase plan): edit
`to_duckdb/schema.py`, `to_duckdb/docs/schema.md`; create new snake_case
modules under `to_duckdb/` (e.g. `operating_config.py`, `installation.py`,
`readers/`); create tests under `to_duckdb/tests/`; edit
`to_duckdb/magnetdb.py` for CLI subcommands; edit `to_duckdb/stress_map.py`
in phase 6.

---

## Data issues found during design (separate follow-ups, not part of this plan)

1. **[FIXED 2026-10-05] `M9_A260602_00` held 3 magnets in `magnetdb.duckdb`**
   (`M25032101`, `M9Bitters-newBi10`, `M9Bitters-newBi08`) instead of 2.
   *Cause:* in `~/github/hifimagnet-projects/magnetdb.json` the contents of
   `M9_A260602_00.json` and `M9_A260707_00.json` were swapped and **both
   declared `"name": "M9_A260602_00"`** (commit `527392d9`). Loaded in
   file-name order, the first created the assembly (newBi10, from 07-07);
   the second was skipped as "already exists" by `insert_assembly` while
   `insert_assembly_magnets` still appended `M9Bitters-newBi08` — so the DB
   held the union, with an M9 gap 2026-06-02 → 2026-07-07 and no
   `M9_A260707_00`.
   *Fix:* JSON contents swapped back (not committed in hifimagnet-projects);
   `magnetdb.duckdb` repaired by a one-off SQL transaction (backup
   `to_duckdb/magnetdb.duckdb.bak-20261005T120155`):
   `M9_A260602_00` = `M25032101` + `M9Bitters-newBi08`,
   2026-06-02 08:00 → 2026-07-07 07:00, `disassembled`;
   `M9_A260707_00` = `M25032101` + `M9Bitters-newBi10`, from 2026-07-07
   08:00, `in_operation`; the 84 experiments (ids 6247–6330) moved to
   `M9_A260707_00`. `test-magnetdb.duckdb` not touched (picks up the
   corrected JSON on its next rebuild).
2. **`M9Bitters-newBi08` vs `M9Bitters-newBi08_01`** — two records that
   look like the same physical Bitters; to confirm. Broader Bitters lineage:
   `newBi08` / `newBi08_01` / `newBi09` / `newBi10` all share part `M9Be`,
   and their "Superseded by …" statuses need checking.
3. **[FIXED 2026-10-05] Code guard in `assembly add`** (`to_duckdb/magnetdb.py`):
   refuses a file whose name differs from its `"name"` field, and refuses
   re-adding an existing assembly whose JSON differs from the DB (magnet
   set, housing, and commissioning dates when the JSON gives them); the
   differences are listed, also with `--dry-run`. Tests in
   `to_duckdb/tests/test_add_assembly.py`; documented in
   `to_duckdb/docs/loading.md`.
   *Follow-up:* `assembly update --sync <json>` — show the
   `_assembly_conflicts` differences, then on confirmation add/close magnet
   links and update assembly dates through `crud` (status cascades,
   `status_history`, operation log), without touching experiments. Revisits
   the "partial refresh by design" choice of `update_assembly_from_json`;
   needs its own plan.
4. **Stale naming in `to_duckdb/docs/loading.md`:** examples still use the
   old `<Housing>_<Magnet>_<N>.json` naming (`M10_M19071101_13.json`); no
   such file exists any more in hifimagnet-projects.
5. **python_magnetrun pupitre reader drops a data row** in files without a
   parameter line: `skiprows=1` assumes line 1 is the parameter line, but
   some files (e.g. M10 2011/2013) start directly with data; some files also
   contain null bytes. Separate follow-up in python_magnetrun.
6. **`python_magnetdb` (separate repo):** `Probe.geometry_config_to_yaml`
   uses a non-existent `self.geometry_config` and an unimported `copy` —
   any magnet with probes would fail `run_setup`. Not to be ported as is.
7. **Bad `materials.alpha` data:** every material checked (helices of
   `M25032101`, `M23012001`; `CuAg01` of the M9 Bitters) has
   `alpha = 0.0036`, while MAGFILE `ct` is 0.0035–0.004 per section. Known
   bad data, to be corrected by the user later. Until then the `ct`
   cross-check flags almost every section and R(T) models inherit the wrong
   alpha. Does not block phases 1–3; the phase 4 acceptance test depends on
   it.
8. **[FIXED 2026-10-05] Stale M5/M7 `housing_config` rows in `magnetdb.duckdb`:** stored as
   `{'Insert': 'GR1', 'Bitter': 'GR2'}` for both, with no `extra_config`.
   Correct (user-confirmed, and what the current — uncommitted —
   `_housing_config_data_from_magnetrun` single-group branch produces):
   M5 = `{'Bitter': 'GR1'}` (no insert), M7 = `{'Insert': 'GR1'}` (no
   Bitters), each with `voltage_channels_gr1` in `extra_config`. The rows
   came from pre-fix code; `insert_housing_config_from_magnetrun` skips
   existing rows, so they were never corrected.
   *Fix:* DuckDB 1.5.5 cannot `UPDATE` a `MAP` column of a row referenced by a
   foreign key (nor repoint `assemblies.housing`), so the database was
   rebuilt with `EXPORT DATABASE` → patch the two rows in the exported
   parquet → `IMPORT DATABASE` (backup
   `to_duckdb/magnetdb.duckdb.bak-20261005T162208`). Verified against the
   backup: all 23 tables identical except the M5/M7 `housing_config` rows,
   same columns/constraints, sequences unchanged; `pytest` 467 passed.
   *Caveat:* the correct values come from the uncommitted single-group change
   in `crud.py`; a rebuild with the old code would bring the wrong rows back.
   *Possible follow-up:* `insert_housing_config_from_magnetrun` silently skips
   existing rows — it could report differences, like the `assembly add` guard.
9. **Missing M10 assembly, 2024-12-09 → 2025-03-11 (confirmed by the user,
   2026-10-06).** No M10 assembly exists between `M10_A230509_00` (ends
   2024-12-09 07:00) and `M10_A250311_00` (starts 2025-03-11 08:00) in either
   `magnetdb.duckdb` or `test-magnetdb.duckdb`, although M10 ran (overview
   files exist, e.g. `M10_Overview_241211-1139.tdms`). Consequence in
   `test-magnetdb.duckdb`: **36 overview records** (2024-12-10 → 2025-03-10)
   have `assembly_name`, `t0` and `mode` NULL — mode inference is skipped
   (`skipped_no_assembly`) before any current is read.
   *Fix:* the user defines the missing assembly (or assemblies) in
   `~/github/hifimagnet-projects/magnetdb.json` (name, insert + Bitters,
   dates within the gap); `assembly add` inserts it (new name, so the guard
   does not object); then the overview records are re-resolved and their mode
   inferred. Own plan, once the JSON exists.
   *Related:* (a) one more M10 record, `M10_Overview_220422-0930`, has NULL
   `t0` although `M10_A220422_00` covers it (from 2022-04-22 08:00) — cause
   not investigated; (b) optional code change: mode depends only on the
   currents, so `infer_overview_record_fields` could infer it even when
   `assembly_name` is NULL.

---

## Open questions

| # | Question | Blocks |
|---|---|---|
| 1 | MAGFILE semantics/units — **mostly resolved** in `magfile-defs.json` (from `magfile.txt`; FF in G/A per circuit and r0 scale checked against data). Remaining: units of `r0/a0/b0` (mΩ, mΩ/A, mΩ/A² inferred from data) and `H<i>` (mH inferred); meaning and unit of `DeltaT0`; unit of `DeltaPFA/PFU` (mbar?, unused); whether `Imax<n>` is per supply (M9 IH reached 29.5 kA with `Imax1` = 14.8 kA) | phase 2 typed columns |
| 2 | MAGFILE conf → experiment link — only for **conf-only fields** (`Ivar`, `FF`, `Qnom`, surveillance), since the pupitre header links its fields to the experiment directly. `Date`/`Heure` is the file's **generation time**, not an experiment start, which favours a **validity window** (a conf applies from its generation time until the next one for that housing/assembly) over "nearest preceding experiment" | phase 2 reader |
| 3 | Insert slot 1 is `0 0 0` for `M25032101` in both `MAGFILEM9.conf` and the 2026-10-02 pupitre header (so absent in live data too), while the magnet has 14 helices (7 pairs): **which** helix pair has no section — real voltage-tap probes not yet in DuckDB, pairing starting at slot 2, or H1H2 not instrumented? | phase 2 section-count check |
| 4 | ~~PID `jeu` 1–16~~ — resolved: `jeu` is just the parameter-set id (`numero_jeu`); 17–20 = M7–M10, 1–16 stored with no housing; threshold ranges from `configAlims/README.md` | — |
| 5 | Primary-loop hysteresis: installation-wide or per housing | phase 1 |
| 6 | ~~R/L ageing~~ — resolved: values change over time, `valid_from/valid_to` used in L3 | — |
| 7 | Digital variants: option A or B (B recommended; L3 already carries option B's `digital_*` columns); may a digital magnet exist without a real counterpart (assumed yes) | phase 6 |
| 8 | External MySQL for MAGFILE: same database as M1-note items 29/50? schema or sample dump available? read-only access assumed; shared `magfile-defs.json` or a separate defs file (former #13) | MySQL reader |
| 9 | ~~Inference of missing history~~ — decided: reserved (listed in Non-goals; `inferred` kept as a `source` value) | — |
| 10 | rustfs test instance available for students; reuse `rustfs/magnetfs` key convention (assumed yes) | phase 5 |
| 11 | Installation tables LNCMI-specific (M5–M10, GR1/GR2) or generic | phase 1 |
| 12 | ~~Pupitre `IS`~~ — resolved: no native supra current in pupitre; `IS` derived from hybrid `I_BOB` during ETL (M8, supra in assembly, hybrid source linked), on-the-fly `I_BOB` as fallback | — |
| 13 | ~~MySQL defs file~~ — merged into #8 | — |
| 14 | L1 cooling/flow tables (`cooling_circuits`, `primary_loop`, `flow_params`) are drafted in python_magnetcooling's working units (rpm, l/s, bar, MW, m³/h): convert to SI like L2/L3, or keep those units for direct use by `WaterFlow`? | phase 1 / 3 |
| 15 | Where does the `IS` ETL step live: python_magnetrun Stream 4.7 (parquet save) or `to_duckdb` populate? | before phase 4 |
| 16 | ~~Meaning of `ct`~~ — resolved: temperature coefficient [1/K]; cross-checked against `materials.alpha` (reference), resistance-weighted per helix pair for inserts (L2) | — |
| 17 | Exact start of full pupitre parameter lines in M10 (shell scan inconclusive) | phase 2 coverage |
| 18 | PID third-range threshold: 1000 A (CIRRUS README, R14L09 p13) vs 800 A (magnet-scipy `high_threshold` default) — which is right? If 1000 A, magnet-scipy's default needs a separate fix | phase 1 seed / phase 4 |
| 19 | CIRRUS ramps (`analogique.rampes.rampe`): needed (e.g. ramp rates vs MAGFILE `dIdtmax`), or out of scope? | low priority |
| 20 | Section slots outside M8/M9/M10 — **resolved for M5/M7** by the derived rule (first `Ucoil` of the role's GR; M5 Bitters GR1, M7 insert GR1). **M3** still open: a new `M3-housing-config.json` is needed — which magnet(s) (3 coils, `Imax1 = Imax2 = 13010`), on which circuit(s), and the channel mapping (`Idcct1–4`, `Tin1/2`, `Flow1/2`, `HP1/2`, `Rpm1/2`) | phase 2 (M3) |
| 21 | Should the M8 hybrid supra supply be an L1 `power_circuits` row (e.g. circuit `SUPRA`), or stay only as `reference_supra_current` binding? | phase 1 / 3 |
