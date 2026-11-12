# Plan: Real/digital magnets, installations and run configurations in DuckDB

**Status (2026-10-05).** Design document, written on approval of the design
discussion; revised the same day: L1 (PID semantics from
`configAlims/README.md`), L2 (pupitre header reader, `ct` cross-check), L3
(characteristics, units, variable binding, default selection), open
questions reviewed. Revised 2026-10-07: §1 of
[PLAN_commissioning_numerical_companion.md](PLAN_commissioning_numerical_companion.md)
(raw commissioning measurements) merged into L3, the rest of that plan
superseded; cross-references to
[PLAN_pupitre_etl_spec.md](PLAN_pupitre_etl_spec.md) and
[NOTES_M5_bitters_wiring.md](NOTES_M5_bitters_wiring.md); order, blockers and
approvals across these plans in
[Cross-plan order, blockers and approvals](#cross-plan-order-blockers-and-approvals).
Revised 2026-11-03: pupitre header = monitoring model (R00/Adv/Bdv/CT,
checked on real files), slot → magnet through the **housing-config version
in force at t0** (step H, done), CT reference temperature, `Tout` binding;
data issues #10–#11.
Revised 2026-11-05: header versions with explicit validity and a status
(`stale` | `commissioning` | `valid`), from the line-1 headers of the
commissioning assemblies `M9_A250121_00` / `M9_A250401_00`; tap change of
`M25032101` inside `M9_A250401_00` (data issue #12); ETL magnet wirings get
their own validity windows (ETL plan D1 = a).
**No implementation phase is approved yet** — each phase below
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
| Commissioning measurements | field and voltage per magnet at PID-stabilized current setpoints, with flow and Tin, taken when an assembly is commissioned | extracted from experiments' pupitre files with a proper header (`header_class = 'full'`, #29) at load time; candidate commissioning experiments identified by a `Field` signature still to be defined — **[unconfirmed, open question #24]** | L3 (raw tables, then fits) |
| pigbrother `Signature` | reference currents per circuit | `overview_records.signatures` — **empty today** (0 / 1915 records in `test-magnetdb.duckdb`; the python_magnetrun extraction stores placeholder min/max/mean only), filled by step S2 | L5 inputs |
| `overview_records.plateaux` | plateau metadata | `overview_records` — **empty today** (0 / 1915), filled by step S2 | run search only (view), not an entity |
| `python_magnetdb` `Probe` / `python_magnetgeo` `Probe` | name, type (`voltage_taps`/`temperature`/`magnetic_field`), labels, points | held by `Insert`/`Bitters`/`Supras` in magnetgeo | `probes` table (FEM inputs; checked for coherence, not used to build the section mapping) |

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
| `Imax<n>`, `Seuil` | max current (A) of circuit n ("Imax tr<n>" in the pupitre writer, "tr" = GR): M8/M9/M10 `Imax1` = GR1, `Imax2` = GR2; M5 `Imax1` = supply A1, `Imax2` = supply A2; M7 `Imax1` = GR1 only (user, 2026-10-08); eco-mode threshold (A) | active | `config_circuits` |
| `dIdtmax` | theoretical max ramp (A/s); superseded by dB/dt ≈ 50 A/s × FF in eco mode | obsolete | `config_circuits` |
| `Ratio` | eco mode: I_helix = I_bitter × Ratio below `Seuil` (dimensionless) | active | `config_circuits` |
| `Ivar`/`Ivar2`, `Nmaxaimant<n>` | pump law v = 1000 + 2000 (I/Ivar)² [rpm] capped at `Nmaxaimant` (A, rpm) | active | `config_circuits` |
| `Qnom<n>`, `PBnom<n>` | nominal flow (l/s) and pressure (bar) for surveillance | active | `config_circuits` |
| `FF<n>` | field factor (G/A), one per circuit: B = FF1·I₁ + FF2·I₂ — consistent with the pupitre's computed `Field` on M5 (10.0 T) and M9 (34.986 T), a check of the factors in use, not a measurement (see L3 "Field factor"); FF3/FF4 duplicate FF1/FF2 in M9 | active | `config_supply_loads.field_factor` + L3 in-situ FF rows |
| `AR<n>`, `AL<n>` | load resistance / inductance (unit unknown) | unused | `config_supply_loads` |
| `r0/a0/b0_coil<i>` | R at 0 °C vs current, R0c = r0 + a0·I + b0·I² per section (mΩ, mΩ/A, mΩ/A² — **confirmed** 2026-11-03: the pupitre computes 1000·U/I [mΩ], see [Monitoring model](#pupitre-monitoring-model)) | active | `config_sections` + L3 R rows (`expression`, section level) |
| `ar/dr_coil<i>` | alarm / fault threshold on resistance deviation (%) — pupitre `DRcoil<i>` | active | `config_sections.protection` |
| `at/dt_coil<i>` | alarm / fault threshold on coil temperature (°C) — pupitre `Tcal<i>` | active | `config_sections.protection` |
| `ct<i>` | temperature coefficient (1/K) at 0 °C, part of the monitoring model with r0/a0/b0; often wrong; checked vs `materials.alpha` | active | `config_sections.ct` (typed: semantics confirmed) |
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
    valid_from        TIMESTAMP,        -- pupitre header: start of the first file of this version
    valid_to          TIMESTAMP,        -- start of the next version, or the assembly end
    status            VARCHAR,          -- stale | commissioning | valid (pupitre header, 2026-11-05):
                                        -- only `valid` versions give L3 monitoring rows
    source            VARCHAR,          -- magfile_conf | mysql | pupitre_header | inferred | manual
    source_ref        VARCHAR,          -- sha256 (content minus Date/Heure) | MySQL row id
    source_timestamp  TIMESTAMP,        -- MAGFILE Date/Heure
    housing           VARCHAR,          -- from NMagnet, cross-check vs assembly
    housing_version   VARCHAR REFERENCES housing_config_versions(name),
                                        -- wiring in force at the source time (file start);
                                        -- slots are resolved against it
    insert_code       VARCHAR,          -- MagnetCode, cross-check vs assembly insert
    resolution_status VARCHAR,          -- ok | insert_mismatch | no_experiment | section_mismatch
                                        -- | source_mismatch | ct_mismatch | layout_mismatch
                                        -- (several → JSON list)
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
    circuit       INTEGER,              -- 1 | 2: GR1 | GR2 (M7: GR1 only); M5: supply A1 | A2
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
    slot          INTEGER,              -- MAGFILE coil index (1..NbCoil) = Ucoil<slot>
    r0            DOUBLE,               -- [Ohm] at 0 °C (source mOhm)
    a0            DOUBLE,               -- [Ohm/A] (source mOhm/A)
    b0            DOUBLE,               -- [Ohm/A^2] (source mOhm/A^2)
    ct            DOUBLE,               -- [1/K] at 0 °C
    protection    JSON DEFAULT '{}',    -- ar, dr, at, dt, G, H; ct_check result
    PRIMARY KEY (config_id, slot)
);
-- Stored by slot, as written: which magnet a slot belongs to is resolved at
-- read time (section mapping below), never at write time. Slots with
-- r0 = a0 = b0 = 0 are not stored; a stored slot is not proof that the
-- channel is plugged (M8 slots 15-16 since 2026-03-05: r0 = 0, a0/b0 != 0).
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

Rules confirmed by the user on 2026-10-08 (they replace the earlier
"sections start at the first `Ucoil` of the GR" rule). Slot *s* is the
`Ucoil<s>` / `Icoil<s>` channel; the pupitre header coefficients
(`R00/Adv/Bdv/CT` of channel *s*) and the MAGFILE `r0/a0/b0_coil<s>` follow
the same numbering.

1. **Channels per role** come from the **housing-config version in force at
   t0** (2026-11-03, step H): magnet role → GR (`coil_assignment`) → that GR's
   `voltage_channels_grX`, the wiring of python_magnetrun `HousingConfig.at(t0)`
   (DuckDB: `housing_config` + `housing_config_versions`). The wiring can
   change inside one assembly, so it is never a fixed rule per housing or
   per assembly. Base wiring:

   | Housing | Wiring | Insert channels | Bitters channels |
   |---|---|---|---|
   | M8, M10 | Insert GR2, Bitters GR1 | `Ucoil1–14` | `Ucoil15–16`, one per Bitter |
   | M9 | Insert GR1, Bitters GR2 | `Ucoil1–14` | `Ucoil15–16`, one per Bitter |
   | M7 | Insert only, GR1 | `Ucoil1–7` (same insert rules) | — |
   | M5 | Bitters only, GR1 | — | `Ucoil1–2` |
   | M3 | needs a new `M3-housing-config.json` (3 coils) | open question #20 | |

   Versions: each housing starts with a **dated base version** (empty
   overrides) from its first commissioned assembly — `M5-140101`,
   `M7-140101`, `M8-211225`, `M9-181109`, `M10-180220`; earlier data gets
   the base wiring with no version name. Then **`M8-260305`** (from
   2026-03-05 17:21:09+01:00, in
   `M8_A230919_00`): M8Bitters read on a **single tap `Ucoil14`**, insert on
   `Ucoil1–13`, `Ucoil15–16` exactly 0 in all 71 files checked up to
   2026-11-03 (data issue #11). The expected wiring stays `Ucoil15/16`
   (user); going back to it is a new version.

   M5 and M7 are single-group housings (confirmed); their `magnetdb.duckdb`
   rows were corrected on 2026-10-05 (data issue #8).
2. **Insert layout — pair (standard today):** voltage taps on the
   **HP-side rings joining consecutive pairs** (H2H3, H4H5, …, H12H13, ring
   `bpside = false`) plus the **two current leads**. Each `Ucoil` is the
   difference between two consecutive taps; the **reference tap** (start of
   the first section) is the inner current lead. Taps run
   inner → outer and **`Ucoil7` is always the outermost pair (largest
   diameter)**: for an insert of N helices, pair *k* (helices 2k−1, 2k,
   counted from the inside) is on **`Ucoil(7 − N/2 + k)`** — 14 helices →
   `Ucoil1–7`, 12 → `Ucoil2–7`, 10 → `Ucoil3–7`. Section *k* = helix parts
   with `coil_index` ∈ {2k−1, 2k} (as in magnet-scipy `R_14Helices.csv`).

   ```
   lead_in ─H1─H2─ [H2H3] ─H3─H4─ [H4H5] … [H12H13] ─H13─H14─ lead_out
      │  Ucoil1   │    Ucoil2     │   …    │     Ucoil7     │
   ```

   Ring sides (2026-11-05): H1H2, H3H4, …, H13H14 are BP-side
   (`bpside = true`), H2H3, …, H12H13 HP-side, in the `Ring-*.yaml` files of
   HL-27/29/31/34; all 54 ring parts in DuckDB carry `bpside` in
   `geometry_data`. Both leads are then on the HP side (inferred, open
   question #31).
3. **Insert layout — one tap per helix (older):** taps on every ring plus
   the two current leads (reference = inner lead).
   `Ucoil14` = outermost helix (confirmed 2026-10-08); helix *j* of an N-helix
   insert is on **`Ucoil(14 − N + j)`**. Section *j* = the helix part with
   `coil_index` = j.
4. **Which insert layout:**
   1. assume the **pair layout**;
   2. data check: any non-null `Ucoil8`–`Ucoil14` (or non-zero header
      coefficients in slots 8–14) contradicts the pair assumption → treat as
      the per-helix layout and flag it (`layout_mismatch` in
      `resolution_status`).

   Probes never define the layout or the sections: they are FEM inputs,
   checked against this mapping (see [Probes](#probes)).
5. **Null channel** (`Ucoil_n` null, coefficients all 0) means either the
   channel is **unplugged**, or that pair / helix **does not exist** in this
   insert. Told apart from the insert's `geometry_data` (helix count,
   rings). E.g. M9 `M25032101` (14 helices): `Ucoil1` null
   → unplugged. **A third case (2026-11-05):** the pair's taps are read
   together with the next pair on one channel — `M25032101` since
   2025-05-09: H1–H4 on `Ucoil2`, `Ucoil1` empty (data issue #12). The pair
   rule of rule 2 then does not hold for that magnet; the layout of each
   header version (L2 "Header versions, …") says which slots carry which
   sections.
6. **Bitters:** one voltage tap per Bitter part: section *j* = Bitter part
   with `coil_index` = j — or, when the GR has a single channel
   (`M8-260305`), one section for the whole Bitters magnet.
7. **Ordering** is inner → outer. `magnet_parts.coil_index` follows the magnet
   definition order, so this assumes magnet JSON lists parts inner → outer;
   verified at ingest (inner radius increasing with `coil_index`, from
   `geometry_data`).

Exposed as a view:

```sql
-- v_config_sections: (config_id, slot, magnet_name, section_index, part_names[], probe_label)
-- slots resolved against operating_configurations.housing_version (its GR
-- channels) and the assembly's magnets; t0 is never recomputed here.
-- probe_label: label section_index of the magnet's voltage_taps probe, or
-- null; links FEM results on probes to the measured Ucoil<slot>.
```

- **Used by the Pupitre ETL:** this slot mapping is the assembly → `Ucoil`
  channel rule that [PLAN_pupitre_etl_spec.md](PLAN_pupitre_etl_spec.md)
  lacks in its v1. ETL spec v2 builds the voltage sums from
  `v_config_sections`, summing only the slots present under the rules
  above (e.g. `Ucoil2–7` for a 12-helix insert; `Ucoil1` empty on M9
  `M25032101` since 2025-05-09). The ETL magnet wirings get the validity
  window of the `valid` header version they come from (ETL plan D1 = a,
  2026-11-05).
- **M5 row** of the slot table above (Bitters 1–2 on GR1) changes if the M5
  rewiring in [NOTES_M5_bitters_wiring.md](NOTES_M5_bitters_wiring.md) is
  confirmed (Bitter 1 on GR1, Bitter 2 on GR2) — see open question #26.

### Probes

```sql
CREATE TABLE IF NOT EXISTS probes (
    name          VARCHAR PRIMARY KEY,
    magnet_name   VARCHAR REFERENCES magnets(name),
    type          VARCHAR,              -- voltage_taps | temperature | magnetic_field
    labels        VARCHAR[],            -- in order, inner -> outer
    points        JSON,                 -- [[x, y, z], ...] [m], one per label
    metadata      JSON DEFAULT '{}'
);
```

Built to round-trip with `python_magnetgeo.Probe` (`name`, `type`,
`labels`, `points`) so FEM setups can write probe YAML. One row is one probe
collection, attached to a **magnet** (never to a part); python_magnetdb's
`Probe.part` is not carried over (data issue 6).

**Role (2026-11-05):** probes are **FEM inputs**. They do not feed the
section mapping; they are checked for coherence with it, so FEM results on
probes can later be compared with measured `Ucoil` data (via
`v_config_sections.probe_label`).

**`voltage_taps` collection:** one label = one section, inner → outer;
point *i* = the outer end tap of section *i*; the start of section 1 is
the reference tap (inner current lead), implicit, not stored.

**Coherence check** (view `v_probe_coherence`, flags only, never rejects),
per magnet × housing-config version in which the magnet ran (the wiring
changes, the probes stay on the magnet):

- at most one `voltage_taps` collection per magnet;
- label count = expected sections: N/2 (pair layout), N (per-helix
  layout), number of Bitter parts (Bitters), or 1 when the GR has a single
  channel (`M8-260305`);
- points ordered by increasing radius;
- point *i* within the radial range of the expected HP-side ring (rule 2 /
  rule 3); last point at the outer current lead.

Temperature and magnetic-field probes are not checked: no housing channel
is tied to them.

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
- **File context, shared with the Pupitre ETL** (2026-11-03): readers get
  the experiment, assembly and housing version of a file from
  `to_duckdb/file_context.py`,
  `resolve_file_context(con, path) -> FileContext(experiment_id, assembly,
  housing, housing_version, t0)`, created in step 5 of
  [PLAN_pupitre_etl_spec.md](PLAN_pupitre_etl_spec.md) and reused here, so
  that resolution is written once.
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

**Writer (pupitre acquisition C++ code, received from the user 2026-10-08):**
line 1 is written as `nbcoils \t mag_code \t imax1 \t imax2` then, for each
of the `nbcoils` measurement channels, `\t R00 \t Adv \t Bdv \t CT`; no
trailing tab. Designer's notes in that code:

- `mag_code` may be null or empty → an empty field between two tabs.
- `R00`, `Adv`, `Bdv` are the coefficients **in use at that instant**:
  R(I) = R00 + Adv·I + Bdv·I²; `CT` is the temperature coefficient.
- The loop covers the measurement channels (16 on M8/M9/M10); **all four
  values at 0 = channel not used**. Not true in practice (2026-11-03): `CT`
  is non-zero on unused slots (M9 slot 1 and slots 8–14 are
  `0 0 0 0.0038`), and M8 slots 15–16 keep `a0`/`b0` ≠ 0 with `r0 = 0`
  while the channels read exactly 0.
- `imax1` / `imax2` are annotated "Imax tr1" / "Imax tr2"; "tr" = GR
  (user, 2026-10-08): GR1 / GR2 on M8/M9/M10, supplies A1 / A2 on M5,
  GR1 only on M7 (see the MAGFILE field table).
- A comment in that code about M9 (4 helices on one channel) is
  misleading and is ignored (user, 2026-10-08); channel numbering follows
  the section mapping rules above.

It largely closes the MAGFILE history gap for recent runs: no time matching
is needed for these fields. The conf file / MySQL stays the source for the
other fields (`Ivar`, `FF`, `Qnom`, `AR/AL`, surveillance, protection).

**Resolution order** (2026-11-03): the context of a file is resolved
**before** its header is interpreted, with `resolve_file_context` (see
reader architecture):

1. file → experiment (`experiments.file`), or the time window for a file
   not in `experiments` (same rules as the Pupitre ETL "Assembly
   resolution");
2. → assembly (`experiments.assembly_name`) → housing (`assemblies.housing`);
3. → housing version in force at the file start (`HousingConfig.at(t0)`,
   first `Date`/`Time` in Europe/Paris time);
4. → read line 1 and interpret it against that context.

| Step on line 1 | Needs assembly / housing version |
|---|---|
| Parse and classify (`header_class`, step E) | No — format only |
| Store the coefficients by slot (`config_sections`) | No — raw by slot |
| Link to the experiment; `MagnetCode` vs the assembly's insert | Assembly |
| Slot → magnet section, CT check, L3 rows | Assembly and housing version |
| Header check (`layout_mismatch`) | Housing version |

**The header checks, it never decides.** Neither the coefficients nor
`MagnetCode` ever choose the assembly or the housing version. A non-empty
slot outside the version's channels, or a mapped channel whose slot is
empty, sets `layout_mismatch`: the sign that a new housing version is
needed (as for M8 on 2026-03-05, see data issue #11).

- `PupitreHeaderReader` feeds the same `OperatingConfig` → writer, with
  `source = 'pupitre_header'` and `experiment_id` set directly. Units from
  `magfile-defs.json` (same keys).
- **Line-1 classification** (era-dependent, observed in
  `~/LNCMIG-Data/records/srv-data-install`):

  | Class | Recognised by | Stored |
  |---|---|---|
  | full = **proper header** (#29) | first token integer `NbCoil` ≥ 1, field count = 4 + 4 × NbCoil (split on **tab**, keeping empty fields: M3 and M5 have an empty `MagnetCode`), `Imax1`, `Imax2` and the 4 × NbCoil coefficients numeric | everything |
  | short | `NbCoil` only (2011–2012); `NbCoil MagnetCode` (M10 2018); `NbCoil <label>` (M8 2016 `HL-28_1_BI04_1_BE02_1_13/05/2014`) | what is present; label in `extra` |
  | data | first token parses as a date (M10 2011/2013 files) | nothing — no parameter line; file flagged |
  | empty / unreadable | empty line, null bytes | nothing; file flagged |

- **Observed coverage** (files with more than 4 values on line 1, first
  occurrence): M9 1816 / 6413 from 2021-09-03; M7 11 / 322 from
  2021-12-09; M8 162 / 960 from 2022-11-24; M10 1498 / 5287 — **start not
  established** (inflated by "data" lines; first `MagnetCode` line
  2018-01-20). To be measured with the reader's own classification in
  phase 2.
  **Measured by step E** (2026-10-22, `magnetdb-2026-10-08.duckdb`, 6483
  experiments, i.e. files linked to an assembly): `full` M9 1815, M10 1490,
  M8 162, M5 68, M7 11; `short` 2927; `empty` 7; `data` 0 (the M10
  2011/2013 data-line files are not in `experiments`). `file_integrity`:
  12 `truncated` (11 corrupt tails, 1 incomplete last line), 10
  `unreadable` (header-only). M10 `2020.10.13 - 11:38:15.txt`, first
  `unreadable` (binary tail, invalid UTF-8), is `truncated` since
  [PLAN_pupitre_binary_tail.md](PLAN_pupitre_binary_tail.md).
- **Reconciliation and precedence:** when a conf/MySQL configuration and a
  pupitre header both exist for a run, overlapping fields are compared. For
  its own experiment the **pupitre header wins** (written with the run); the
  conf value is kept in `extra` and `resolution_status` gets
  `source_mismatch`.
- **Versioning:** a new configuration version is created when the
  assembly, the **housing version** or the header content changes;
  repeated identical headers (e.g. ~1800 M9 files) point to the existing
  version, whose `experiment_id` is the first occurrence. Each
  configuration therefore maps to exactly one housing version
  (`operating_configurations.housing_version`), even when the coefficients
  stay the same across a wiring change. **Validity** (2026-11-05):
  `valid_from` = start of the first file of the version, `valid_to` = start
  of the next version of the assembly (or the assembly end). A header change
  is a new version, never an error: coefficients refitted, a magnet's taps
  moved (data issue #12) or the housing wiring changed are all "normal"
  changes. Each version gets a `status`, see "Header versions,
  commissioning and stale headers" below.
- Files of class *data* or *empty* get a file-level flag
  (`no_parameter_line`) in the coverage view, never a configuration row.
- **File quality on `experiments`** (step E of the cross-plan order, before
  phase 2, which reuses its classification):

  ```sql
  ALTER TABLE experiments ADD COLUMN IF NOT EXISTS header_class    VARCHAR;  -- full | short | data | empty (line-1 classes above)
  ALTER TABLE experiments ADD COLUMN IF NOT EXISTS file_integrity  VARCHAR;  -- ok | truncated | unreadable
  ALTER TABLE experiments ADD COLUMN IF NOT EXISTS file_checks     JSON DEFAULT '{}';  -- reason, rows read, lines dropped, …
  ALTER TABLE experiments ADD COLUMN IF NOT EXISTS file_checked_at TIMESTAMP;
  ```

  - `file_integrity` (user, 2026-10-07): `ok` = read completely;
    `truncated` = broken but recovered by python_magnetrun reading up to the
    point of failure, data partial; `unreadable` = cannot be read
    (`FileFormatError`: header only, missing `Date`/`Time`, …), no data.
  - **Recovery up to the point of failure** (2026-10-22): `on_bad_lines="warn"`
    alone does not do it. A crash leaves the end of the file as NUL padding
    followed by rows from an older run still on the disk, and those lines
    usually have an acceptable field count. Example: M10
    `2024.12.05 - 11:16:02.txt` ends with rows of
    `2014.07.27 - 19:17:04.txt`, giving `field_max` = 182.4 T. python_magnetrun
    now drops every row from the first one whose `Date`/`Time` does not parse
    or is more than 1 h earlier than the row before
    (`count_valid_pupitre_rows`). The 1 h tolerance keeps the end of summer
    time (M9 `2018.10.27 - 18:12:19.txt` steps back 3599 s).
  - python_magnetrun **reports** it: `truncated` (file does not end cleanly,
    see `check_pupitre_truncation`, or rows dropped) and `rows_dropped` on
    the loaded data object, pandas and polars.
  - Filled by `to_duckdb/check_experiment_files.py`; `compute_exp_stats.py`
    leaves out `unreadable` files.
  - A crash tail of binary data (invalid UTF-8) is cut before parsing —
    see [PLAN_pupitre_binary_tail.md](PLAN_pupitre_binary_tail.md) (done
    2026-10-22).
  - Kept separate from `experiments.status`, which holds processing tokens
    (`STATS DONE`, `HOOP STRESS DONE`).
  - **"Proper" header (open question #29, resolved 2026-10-08):** defined
    by line 1 only, as the writer produces it — i.e. **proper header ⇔
    `header_class = 'full'`**. Checked on the latest file of M3, M5, M7,
    M8, M9, M10 (all full); the 2019 M9 / 2020 M10 sample files in
    python_magnetrun are *short*.
- **Which slots are sections** comes from the housing-config version at t0
  and the assembly (section mapping), not from the coefficients: M8 slots
  15–16 have `r0 = 0` with non-zero `a0`/`b0` but are unplugged since
  2026-03-05 (`M8-260305`). Slot 1 of M9 `M25032101` is `0 0 0` in both
  `MAGFILEM9.conf` and the 2026-10-02 pupitre header: not simply unplugged
  — since 2025-05-09 its taps are read together with slot 2's on `Ucoil2`
  (H1–H4, data issue #12; open question #3 revised).
- **Header check** (logged, never rejected; information on the version, not
  a request for a new housing version): a slot with non-zero `r0/a0/b0`
  that is not among the channels of the housing-config version at t0, or a
  mapped channel whose slot is all zero, adds `layout_mismatch` to
  `resolution_status`. This is what reveals a wiring change: the M8 header
  moved the Bitters to slot 14 on 2026-03-05 17:21:09, the first file with
  the new wiring. Not raised on `stale` / `commissioning` versions, whose
  slots may reflect the previous assembly.

#### Header versions, commissioning and stale headers (2026-11-05)

When a **brand-new magnet** is used for the first time in an assembly, the
first experiments are its **commissioning** (user, 2026-11-05): resistances
are measured to set the reference resistances later used to monitor the
magnet, and a run estimates its field factor (field at the centre / current).
During these experiments the header still holds, at least at first, the
**previous assembly's settings**. Line 1 of every experiment file of the two
latest commissioning assemblies shows three phases:

| Assembly (new insert) | Phase | Files | Header |
|---|---|---|---|
| `M9_A250121_00` (`M25012001`, from 2025-01-21) | stale | 2025.01.23 16:56 → 01.24 10:30 (2) | MagnetCode `M09052601` (previous insert), previous coefficients, no slot 1 |
| | stale | 01.24 10:37 (1) | MagnetCode `M25012001`, previous coefficients |
| | commissioning | 01.24 11:41 → 01.27 13:25 (35 files, 5 header versions) | slot 1 added (R00 0.6 → 0.540 → 0.530 → 0.525 → 0.521 mΩ), other slots refitted each time |
| | valid | 01.27 14:06 → 03.21 (87) | stable reference |
| `M9_A250401_00` (`M25032101`, from 2025-04-01) | stale | 04.01 16:29 → 04.03 13:18 (7) | MagnetCode `M25032101`, coefficients identical to the last header of `M9_A250121_00` |
| | valid | 04.03 15:09 → 05.09 11:45 (25) | references of `M25032101` |
| | valid | 05.09 14:31 → 07.14 (98) | taps changed: slot 1 empty, slot 2 R00 = 1.28641 mΩ = 0.518954 + 0.767459 (old slots 1 + 2, data issue #12) |

- **`stale`** (detectable from the data): the version's coefficients are
  identical to those of the last header of the housing's previous
  assembly, or its MagnetCode is not the assembly's insert.
- **`commissioning`:** a version inside the commissioning period of a
  brand-new magnet. Its coefficients are being refitted; they are kept as
  history, never used as references. **[unconfirmed, open question #32]**
  end of the period: the first header version that then stays stable
  (2025-01-27 14:06 for `M25012001`, 2025-04-03 15:09 for `M25032101`), or
  an operational marker (the field-factor run, a recorded date).
- **`valid`:** every other version. Only `valid` versions give L3 monitoring
  rows (reference R00/Adv/Bdv/CT) and, in ETL v2, magnet parts.
- **Commissioning experiments** (L3 raw tables, open question #24): the
  experiments of the first assembly of a brand-new magnet, from the
  assembly start to the end of commissioning. Whether a magnet moved to a
  new assembly (e.g. `M23012001`, M9 2023-01 then M8 2023-09) also gets a
  commissioning: **[unconfirmed, open question #33]**.

### Pupitre monitoring model

The header coefficients are the reference of the pupitre's live
monitoring (notes `reference-resistance.md` and `resistance-temperature.md`
in `~/github/magnet-scipy`). Per section, at each sample:

| Quantity | Formula | Pupitre channel |
|---|---|---|
| reference R at 0 °C [mΩ] | R0c = R00 + Adv·\|I\| + Bdv·I² | — |
| measured R [mΩ] | Rm = 1000·\|U/I\| | — |
| mean water temperature [°C] | Tmoy = (Tin + Tout)/2 | — |
| measured R at 0 °C [mΩ] | R0 = Rm / (1 + CT·Tmoy) | — |
| deviation [%] | 100·(R0 − R0c)/R0c | `DRcoil<i>` (alarm `ar`, fault `dr`) |
| equivalent coil temperature [°C] | \|Rm/R00 − 1\| / CT | `Tcal<i>` (alarm `at`, fault `dt`) |

- **Checked 2026-11-03** by recomputing `DRcoil`/`Tcal` from line 1 and the
  raw channels (rows above 2000 A): M9 `2026.10.29 - 18:03:45` and M8
  `2026.10.30 - 09:10:03` match to the file's rounding (median gaps 0.025 %
  and 0.03 K) on every active slot. Units mΩ confirmed; `Tcal` uses R00 only;
  `Tout` is the pupitre `Tout` column (one primary-loop channel).
- **Meaning** (`resistance-temperature.md`): the `I` terms are the Taylor
  expansion of the conductor heating above the water,
  R/R00 ≈ 1 + CT·ΔT(I) + CT²·σ²(I) at fixed water temperature, so Adv and
  Bdv scale with CT. `Tcal` is the first-order estimate of the 1/r-weighted
  mean conductor temperature ⟨T⟩_w with T₀ = 0 °C, R₀ = R00; it ignores the
  CT²·σ² term (overestimates for an uneven temperature).
- **R00, Adv, Bdv and CT form one model:** CT cannot be replaced by
  `materials.alpha` without refitting R00/Adv/Bdv.
- **Which `Tin`:** the pupitre uses `Tin2` for insert slots and `Tin1` for
  Bitters slots, on M8 (insert GR2) and on M9 (insert GR1). On M9 `Tin1` is
  the GR1 inlet (user, 2026-11-03; the M9 pumps `Rpm1`/`Flow1`/`HP1` follow
  the GR1 current), so the M9 insert's `DRcoil` uses the Bitters inlet:
  data issue #10.

### Temperature coefficient cross-check (`ct` vs `materials.alpha`)

`ct<i>` is the temperature coefficient [1/K] of section *i* at 0 °C
(confirmed). `ct` is part of the [monitoring model](#pupitre-monitoring-model)
and is used by its L3 rows; **`materials.alpha` is the reference for
physics models** (magnettools, FEM). The check compares the two as a
diagnostic.

- **Reference temperatures differ:** `materials.alpha` is given at
  `materials.t_ref` (293 K for all 115 materials, `alpha = 0.0036`), `ct` at
  0 °C. Convert before comparing: α₀ = α / (1 − α·(t_ref − 273.15 K)) —
  0.0036 → 0.00388, close to the `ct` = 0.0038 of the headers, so data
  issue #7 is partly this reference mismatch.

- Parts of the section come from the section mapping above (insert section
  *k* → its helix pair; Bitters section *j* → that Bitter part).
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
- Until `materials.alpha` is corrected (data issue #7), many sections will
  report a mismatch even after the reference-temperature conversion.

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
    variables             VARCHAR[],         -- independent variables: subset of ['I', 'Tin', 'Tout']
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
- `Tout` [K] — the outlet temperature: the pupitre `Tout` column, one
  channel for the primary loop, shared by all circuits (used by the
  [monitoring model](#pupitre-monitoring-model)).

Binding helper, e.g.
`bind_variables(con, assembly, magnet, source_format) -> {"I": "IH", "Tin": "TinH"}`:

1. magnet role → circuit via `housing_config.coil_assignment`
   (e.g. M10 `{'Insert': 'GR2', 'Bitter': 'GR1'}`; the insert is on GR1 in
   M9 but GR2 in M8/M10), with the channels of the housing-config version
   in force at t0;
2. circuit → current channel via `reference_gr<n>_current` (exists today);
3. circuit → inlet temperature via **new** `reference_gr<n>_tin` keys
   (e.g. M9: `TinH` / `TinB`; M9 `Tin1` = GR1 confirmed 2026-11-03) —
   explicit, not derived from the `H`/`B`
   suffix, because older data and M8 files use `Tin1`/`Tin2` (also
   `Flow1/2`, `HP1/2`, `Rpm1/2`). Once Pupitre files go through the
   spec-driven ETL ([PLAN_pupitre_etl_spec.md](PLAN_pupitre_etl_spec.md)),
   the spec's rename (`Tin1 → TinH`) already holds this mapping on the
   database side; whether the new keys are still needed in python_magnetrun's
   housing JSON is decided in the phase 3 plan;
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

   **Clock lag (#27, measured 2026-11-08):** the Hybrid and pupitre clocks
   differ by minutes (−190 s on `2026.10.30 - 09:10:03`, pupitre time +
   lag = Hybrid time). Without shifting `I_BOB` by the lag first, the
   0.5 s `merge_asof` pairs `IS` with a current about 3 min off; the
   dashboard's `load_hybrid_supra_current` has the same misalignment
   today.

- Provenance: column marked as derived (hybrid `I_BOB`, hybrid source path)
  — fits python_magnetrun Stream 4.7 (`properties`, `FieldMeta.category`).
- `pupitre-defs.json` gains an `IS` entry ("Supra current, derived from
  Hybrid I_BOB during ETL", unit `ampere`, group `Courants_Alimentations`).
- No linked hybrid source → no `IS` column (never zero-filled).
- **Where the ETL step lives — decided 2026-10-07 (open question #15):**
  `IS` is a column of the Pupitre data after the ETL, added through the
  `external` entries of the Pupitre ETL spec
  ([PLAN_pupitre_etl_spec.md](PLAN_pupitre_etl_spec.md), step 1b):
  - the to_duckdb builder emits the `IS` entry when the condition above
    holds; the hybrid date comes from `overview_records.sources_hybrid_kHz`
    (`get_hybrid_khz_source` and `assembly_has_supra` logic moves to the
    builder);
  - python_magnetrun `prepare_pupitre` loads, downsamples and aligns
    `I_BOB` (`load_hybrid_supra_current` logic moves to python_magnetrun,
    shared by ETL, dashboard and binding); the hybrid data directory is
    python_magnetrun's `HYBRID_DATA_DIR`, never stored in the spec or the
    database.

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
- **Alternative shape** (from the commissioning plan): one row per magnet
  pair (`assembly, magnet_a, magnet_b, value`), easier to query in SQL; the
  `vector` above keeps the magnet-scipy layout and an explicit `order`. Open
  question #23.

### Field factor

- **Intrinsic** rows (`magnet_name` only): factor at the magnet's own centre.
- **In-situ** rows (`magnet_name` + `assembly_name`): contribution at the
  assembly field centre, which depends on the magnet's position
  (`assembly_magnets.z_offset`, MAGFILE `Center position`).
- `get_field_factor(..., assembly=X)` returns the in-situ row when one
  exists, else the intrinsic one. The reference point is stored in
  `conditions`.
- MAGFILE `FF<n>` are in-situ values in G/A, **one per circuit**:
  B = FF1·I₁ + FF2·I₂, consistent with the pupitre's `Field` on M5
  (6.899 × 8742.1 + 4.539 × 8743.5 → 10.0 T) and M9
  (8.943 × 29515 + 3.634 × 23640 → 34.986 T, pupitre `Field` 34.986 T).
  This is a consistency check of the factors **in use**, not a comparison
  with a measured field (next item). `FF3`/`FF4` duplicate `FF1`/`FF2` in
  `MAGFILEM9.conf`.
- **Pupitre `Field` and pigbrother `Champ_magn` are computed**, by design:
  both apply the factors in use to the circuit currents (`Champ_magn` [mT]
  = `Field` [T] × 1000; fits exact to 0.05–0.1 mT, e.g. M9 2026-05-08:
  7.329 / 3.766 G/A, M9 2026-10-29: 8.943 / 3.634 G/A). Each system uses
  its own configured factors, which may not be synced between pupitre and
  pigbrother (so the two channels can differ). Neither is a measured field;
  the "Hall probe" / "Axial field" descriptions in the defs JSON are wrong
  (separate python_magnetrun fix). Fitting them recovers the factors in
  use per experiment, see
  [PLAN_header_field_factor_study.md](PLAN_header_field_factor_study.md);
  the measured field comes from the pickup coil (below, open question #34).
- **Configured factors are recoverable per file** by a least-squares fit of
  the recorded field on the circuit currents, unless the two currents are
  proportional (2026-11-10: pupitre M9 2025-01-27 16:22:31 → 8.926 / 3.766
  G/A, residual ≤ 2.3 mT; pigbrother M10 Overview 250127-1605 → 3.402 /
  7.343 G/A). Such rows, if stored, are **configured** values
  (`source_ref` naming the file), never measured ones.
- **The only physical field measurement** is the **pickup-coil** step of the
  commissioning process (user, 2026-11-10); those data are **not available
  yet**. Measured FF rows are blocked until they are (see
  [Commissioning measurements](#commissioning-measurements-raw), open
  questions #24 and #25).
- **M8:** `TotalField = Field + SupraField`, with `SupraField = ffS·IS`
  (supra current from Hybrid `I_BOB`); ffS in use = **11.837 G/A**
  (SupraField / I_BOB on `2026.10.30 - 09:10:03`, after the clock-lag
  correction of #27).

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

Temperature dependence: physics R(T) models use **`materials.alpha`** (per
part, or the resistance-weighted α_eff per section, see L2 cross-check). The
MAGFILE / pupitre-header rows use their own `ct`, which is part of the
[monitoring model](#pupitre-monitoring-model).

### What existing sources produce

| Source | Rows |
|---|---|
| MAGFILE / pupitre header `r0/a0/b0/ct` (slot) | R, `expression` `(r0 + a0*abs(I) + b0*I**2) * (1 + ct*((Tin + Tout)/2 - 273.15))` (SI), `variables = ['I', 'Tin', 'Tout']`, `model = 'pupitre_monitoring'`, section level (slot → magnet section from the housing-config version at t0), `source = magfile_conf` or `pupitre_header`, valid from the configuration's `valid_from` |
| MAGFILE `FF1–4` | FF, `constant`, in-situ |
| magnet-scipy `inductance` | self L, `constant`, magnet level |
| magnet-scipy `mutual_inductances` | M, `vector`, assembly level |
| `R_14Helices.csv` | R, `table`, 7 section rows + 1 magnet row |
| `Rtot_M9Bitters_18MW.csv` | R, `table`, magnet level |
| Commissioning measurements (below) | R and FF fitted from the raw rows, `source = fit`, `source_ref` = the commissioning row ids |

### Commissioning measurements (raw)

Merged from §1 of
[PLAN_commissioning_numerical_companion.md](PLAN_commissioning_numerical_companion.md)
(2026-10-01), adapted to this plan's conventions: values in SI with units in
comments; the derived ratios (`field / current`, `voltage / current`) are not
stored — they are computed by the fit that writes the
`electrical_characteristics` row. The rest of that plan (§2 parameters, §3
mutual inductance, §4 PID gains) is covered by L3 and L1.

```sql
-- One row per PID-stabilized setpoint; a setpoint may be repeated in a campaign
CREATE SEQUENCE IF NOT EXISTS commissioning_field_factor_id_seq START 1;
CREATE TABLE IF NOT EXISTS commissioning_field_factor (
    id             INTEGER PRIMARY KEY DEFAULT nextval('commissioning_field_factor_id_seq'),
    assembly_name  VARCHAR REFERENCES assemblies(name),
    magnet_name    VARCHAR REFERENCES magnets(name),
    current        DOUBLE NOT NULL,     -- [A] [unconfirmed, open question #25]
    field          DOUBLE NOT NULL,     -- [T], at the assembly field centre, pickup coil (not pupitre Field)
    flow_rate      DOUBLE,              -- [m^3/s]
    tin            DOUBLE,              -- [K]
    measured_at    TIMESTAMP,
    experiment_id  INTEGER REFERENCES experiments(id),  -- backing raw file, when any
    source_ref     VARCHAR,             -- pickup-coil file/entry for field; pupitre file + plateau for current (open question #24)
    notes          VARCHAR
);

CREATE SEQUENCE IF NOT EXISTS commissioning_resistance_id_seq START 1;
CREATE TABLE IF NOT EXISTS commissioning_resistance (
    id             INTEGER PRIMARY KEY DEFAULT nextval('commissioning_resistance_id_seq'),
    assembly_name  VARCHAR REFERENCES assemblies(name),
    magnet_name    VARCHAR REFERENCES magnets(name),
    current        DOUBLE NOT NULL,     -- [A]
    voltage        DOUBLE NOT NULL,     -- [V]
    flow_rate      DOUBLE,              -- [m^3/s]
    tin            DOUBLE,              -- [K]
    measured_at    TIMESTAMP,
    experiment_id  INTEGER REFERENCES experiments(id),
    source_ref     VARCHAR,
    notes          VARCHAR
);
```

- Keyed by assembly, not only magnet: field factor and resistance depend on
  the other magnets sharing the bore (commissioning plan rationale).
- PID gains tuned at commissioning end up in the CIRRUS XML of the supplies,
  so they are ingested by L1 (`pid_configs` / `pid_params`), not stored per
  assembly.
- **Origin of the readings (user, 2026-10-07; open question #24):**
  extracted from experiments when loading their pupitre data, only for files
  with a proper header (`header_class = 'full'`, #29 resolved). **[unconfirmed]** Candidate
  commissioning experiments are those whose pupitre `Field` signature
  matches a commissioning pattern **still to be defined**, to be checked
  against real commissioning runs. Computed by a `to_duckdb` step after the
  ETL, since they need the per-magnet channel names produced by the
  spec-driven ETL ([PLAN_pupitre_etl_spec.md](PLAN_pupitre_etl_spec.md)) —
  for M5, `IB1` / `UB1` / `IB2` / `UB2` — and python_magnetrun never writes
  to the database. Plateau detection finds the PID-stabilized setpoints, so
  this depends on step S2.
- **Field source for `commissioning_field_factor` (user, 2026-11-10):** the
  `field` column comes from the **pickup-coil** measurement taken during
  commissioning, not from pupitre `Field` (an FF×I recomputation, see
  [Field factor](#field-factor): fitting it would only return the
  configured factor). Pupitre files give the current and the plateau only.
  The pickup-coil data are **not available yet**, so this table cannot be
  filled with measured values until they are; `commissioning_resistance` is
  not affected.

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
   housing reported from the reader's own classification;
   `v_probe_coherence` on fixtures: a 14-helix pair-layout insert with a
   7-label `voltage_taps` probe is coherent, with 6 labels it is flagged
   (label count); a 2-label Bitters probe on M8 is flagged under
   `M8-260305` (single channel) and coherent under `M8-211225`.
3. **L3 characteristics** — `electrical_characteristics` +
   `to_duckdb/characteristics.py` (lookup API, `set_preferred`, binding),
   `flow_params`, `commissioning_field_factor` / `commissioning_resistance`
   (merged from the commissioning plan); projection of MAGFILE R(I)/FF; import of magnettools CSV,
   magnet-scipy L / M and `*-flow_params.json`; CLI
   `characteristic list | set-preferred`. **python_magnetrun:**
   `reference_gr<n>_tin` and `reference_supra_current` in the housing
   configs, `IS` entry (derived channel) in `pupitre-defs.json`.
   **Before phase 4:** `IS` ETL step — step 1b of the cross-plan order
   (Pupitre ETL spec `external` entries, see "Supra current") — needed for
   M8 supra runs.
   → verify: `R_14Helices.csv`/`Rtot_M9Bitters_18MW.csv` round-trip;
   `get_resistance(M25032101, at=…)` evaluated with `I=IH`, `Tin=TinH`
   (bound + converted to K) matches the CSV; no preferred + 2 candidates →
   error naming both; explicit `source` never falls back; M `vector` length
   checked against n(n−1)/2; waterflow dashboard lookup returns DB params
   when present.
4. **ODE config builder** — `build_ode_config(...)`.
   **Prerequisites:** reference currents come from
   `overview_records.signatures` — `magnetdb.duckdb` has **0** overview
   records, `test-magnetdb.duckdb` has 1915 but **all with empty
   `signatures`, `plateaux` and `sync_info`** (checked 2026-10-07; filling
   them is step S2 of the cross-plan order) (both have magnet `M23072801`,
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

## Cross-plan order, blockers and approvals

As of 2026-10-07. Plans covered: this plan,
[PLAN_pupitre_etl_spec.md](PLAN_pupitre_etl_spec.md),
[NOTES_M5_bitters_wiring.md](NOTES_M5_bitters_wiring.md),
[PLAN_commissioning_numerical_companion.md](PLAN_commissioning_numerical_companion.md)
(superseded; its §1 is merged into L3),
[apps/dashboards/magnetdb/PLAN_signature_regime_robustness.md](apps/dashboards/magnetdb/PLAN_signature_regime_robustness.md)
(methodology approved 2026-08-11, not executed).

**Approved so far:** step 0 only (documentation), plus the signature
robustness *methodology* (S1, 2026-08-11). **Nothing else is approved for
implementation.**

| Step | Work | Depends on | Blockers | Approval |
|---|---|---|---|---|
| 0 | Reconcile the plan documents | — | — | **Done** 2026-10-07 |
| E | File quality on `experiments` (`header_class`, `file_integrity` ok / truncated / unreadable, `file_checks`; python_magnetrun reports truncation) — see L2 "Pupitre header reader" | — | none | **Done** 2026-10-22 (approved 2026-10-22); filled in `magnetdb-2026-10-08.duckdb` |
| H | Time-versioned housing config: python_magnetrun `HousingConfig.versions` / `at(t0)` resolved by every caller (`prepareData`, `HybridRun`, overview processing, analysis CLI, dashboard), `cleanupData` keeps `keys_to_add` columns, DuckDB `housing_config_versions` (exported back by `export_housing_config_json`); dated base version per housing (first commissioned assembly) and `M8-260305` (data issue #11) | — | none | **Done** 2026-11-03 (approved 2026-11-03); versions not yet loaded into `magnetdb.duckdb` |
| R | Header resolution order (assembly → housing version → header; the header checks, never decides), `operating_configurations.housing_version`, shared `resolve_file_context` helper — documents only, see L2 "Pupitre header reader" | H | none | **Done** 2026-11-03 (approved 2026-11-03) |
| S1 | Signature regime robustness study ([PLAN_signature_regime_robustness.md](apps/dashboards/magnetdb/PLAN_signature_regime_robustness.md)), incl. a robust pupitre `Field` signature | — | before running: where the tooling lives; library fixes vs local work-arounds; RDP vs PELT; 3–4 test file pairs to pick. Deferred by that plan (2026-08-11): the "one pupitre file → several pigbrother files" case (no discovery logic in that direction yet) | **Methodology approved** 2026-08-11; execution choices to decide |
| S2 | Fill `overview_records.signatures`, `plateaux`, `sync_info` with real `Signature` output (replacing the placeholder `_extract_signatures` in python_magnetrun `analysis/processing.py`); per-experiment `Field` signature (existing work: `stage/` writes `overview_experiments.field_signature` with a hand-picked `FIELD_THRESHOLD = 0.1`). The clock lags vary from file to file (e.g. pupitre ↔ pigbrother +33 s on M9 2026-05-08, pupitre ↔ Hybrid −190 s on M8 2026-10-30): they are computed per overview record, once `overview_records` has attached the pupitre, pigbrother and Hybrid sources, and stored in `sync_info` (#27) | S1; 2a for channel names — the lag computation (`_compute_lag_correlation`) looks up pupitre current channels by their post-ETL names (`IH`/`IB` via `get_pupitre_current_channel`): use the spec's names, or the raw `Idcct*` columns | none beyond its dependencies | Plan to write, then approval |
| S3 | `teb` as a time series: an ETL step shifting pupitre `teb` by the lag stored in `sync_info` (for magnet cooling modeling; signature plan "Related future work"). **Assumption to flag:** one clock offset per pupitre file, borrowed from the current-channel lag — no pigbrother temperature to verify it against | S2 (lag in `sync_info`), 2a (spec path) | none beyond its dependencies | Plan to write, then approval |
| 1 | Pupitre ETL spec v1 ([PLAN_pupitre_etl_spec.md](PLAN_pupitre_etl_spec.md)); revised 2026-11-03: one spec per (assembly, housing version), magnet parts keyed to a housing version (D1); creates `resolve_file_context`; revised 2026-11-05: magnet parts with their own validity windows (D1 = a) | H, R | none | **Done 2026-11-03** with D1 = b (parts A and B, branch `housing-config-versions`); the D1 = a revision of 2026-11-05 is documented, its code change still to approve |
| 1b | Supra current `IS` for M8: `external` spec entries, hybrid loading moved from the dashboard to python_magnetrun (outline in [PLAN_pupitre_etl_spec.md](PLAN_pupitre_etl_spec.md)) | 1 | #27 measured on one run (−190 s); the lag source (`overview_records.sync_info` from S2, per-file estimate as fallback) is decided in the 1b plan | Outline agreed 2026-10-07; detailed plan to write, then approval |
| 2a | Switch Pupitre callers (`load_mrun`/dashboards, `stress_map.py`) to the spec path | 1 + review of its step 5 comparison | none | Plan to write, then approval |
| 2b | Phase 2: probes + L2 run configuration + `v_config_sections` | R (reuses `resolve_file_context` from step 1 if done first) | #2 (conf → experiment link, conf reader only), #17 (M10 coverage start), #20 (M3 only) | Phase plan to write, then approval |
| 2c | Phase 1: L1 installation | — | **CIRRUS XML history access** (the 4 magnet-scipy samples suffice for tests and the phase 4 acceptance case); #5, #11, #14, #18, #21 | Phase plan to write, then approval |
| 3 | Pupitre ETL spec v2: builder driven by the assembly through `v_config_sections` | 1, 2b | none beyond its dependencies | Plan to write, then approval |
| 4 | M5 rewiring ([NOTES_M5_bitters_wiring.md](NOTES_M5_bitters_wiring.md)) | 2a (Pupitre part), 3 (optional) | **Formal confirmation of the M5 wiring**; corrected M5 source JSON (two Bitters magnets, user); #26 (`coil_assignment` key for two Bitters); M5 notes §9 open details | Notes ON HOLD; plan to write after confirmation, then approval |
| 5 | Phase 3: L3 characteristics, incl. raw commissioning tables | 2a (binding uses names after the ETL), 2b (sections), 1b (`IS` for M8 supra), S2 + E (commissioning readings) | #22 (source vocabulary), #23 (mutual-inductance shape), #24 (commissioning `Field` signature to define and check), #25 (per-magnet field factor) | Phase plan to write, then approval |
| 6 | Phase 4: ODE config builder | 2c, 5, S2 (reference currents from signatures) | data issue #7 (`materials.alpha`); 0 overview records in `magnetdb.duckdb` and empty signatures in `test-magnetdb.duckdb` (until S2) | Phase plan to write, then approval |
| 7 | Phases 5–7: storage, L4 digital variants, L5 simulations | 5, 6 | #10 (rustfs instance); #7 (L4 option A/B) | Phase plans to write, then approval |

Steps 1, E, S1, 2b and 2c can run in parallel.

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
   Also, `Probe.part` should not exist: probes are attached to the magnet
   only (`Probe.magnet`); the DuckDB `probes` table has no part column
   (fix in python_magnetdb, 2026-11-05).
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
10. **M9 insert `DRcoil` computed with the Bitters inlet temperature
    (found 2026-11-03).** The pupitre uses `Tin2` for insert slots and
    `Tin1` for Bitters slots in every housing; on M9 the insert is on GR1,
    whose inlet is `Tin1` (user). On M9 `2026.10.29 - 18:03:45`,
    `Tin2 − Tin1` ≈ 0.6 K under load, so the insert `DRcoil` reads
    ≈ +0.10 % high (max 0.16 %); `Tcal` is not affected (R00 only). M8 is
    consistent (insert on GR2). To report to the pupitre maintainer; see
    open question #30 for the L3 binding.
11. **M8 Bitters on a single tap `Ucoil14` since 2026-03-05 17:21:09
    (found 2026-11-03).** Inside `M8_A230919_00`, the pupitre header moved
    the Bitters from slots 15/16 (R00 6.92 + 3.22 mΩ) to slot 14 (R00
    10.14 mΩ, 10.44 mΩ from 2026-03-06 to 2026-04-14); `Ucoil15–16` are
    exactly 0 and `Ucoil14` carries ≈ 357 V at 29 kA in all 71 files up to
    2026-11-03. The expected wiring is `Ucoil15/16` (user).
    *Fix (step H, done 2026-11-03):* housing-config version `M8-260305`
    (python_magnetrun `HousingConfig.at`, DuckDB
    `housing_config_versions`): `UB = Ucoil14`, `UH = Ucoil1–13`. Before
    it, `UH` included the Bitters voltage (+357 V) and `UB` was all-zero
    and dropped. *Follow-up (own plan):* recompute the stored statistics of
    the 50 M8 experiments since 2026-03-05 in `magnetdb.duckdb`.
12. **Tap change of `M25032101` inside `M9_A250401_00` on 2025-05-09
    (found 2026-11-05 from the line-1 headers).** From
    `2025.05.09 - 14:31` slot 1 is `0 0 0` and slot 2's R00 becomes
    1.28641 mΩ = 0.518954 + 0.767459, the R00 of the old slots 1 and 2:
    H1–H4 are read together on `Ucoil2`, `Ucoil1` no longer carries a
    section; kept in the later assemblies of `M25032101`. This confirms the
    pupitre writer's comment about "4 helices on one channel" on M9, which
    was set aside on 2026-10-08 (open question #3). The housing's GR
    channels do not change (`UH` still sums `Ucoil1–14`), so it is not a
    housing version: in the ETL it is a new magnet part from that date
    (ETL plan D1 = a), in L2 a new header version.
    **[unconfirmed]** that this is the intended wiring (user: such a change
    "could be normal").
    **Update 2026-11-07:** the ETL now derives each insert's taps from its
    helix count (`Ucoil1–7` for 14 helices); the empty `Ucoil1` is kept as
    a tap and adds 0 to `UH`, so the ETL needs no exception
    ([PLAN_pupitre_checks_file.md](PLAN_pupitre_checks_file.md), revision 2).
    Several other 14-helix inserts show empty `Ucoil1` (or `Ucoil1–2`) taps
    (`M09052601`, `M20022001`, `M22011801`, `M12082401`): a section-mapping
    question for L2, not for the ETL.
13. **Insert supplies swapped, found by the check rule `IH - Icoil7`
    (2026-11-07):**
    - **M7, 2014-03-17 → 2014-04-15:** the insert is fed by A1 + A3
      (`Idcct1 + Idcct3` = `Icoil7`, `Idcct2` = `Idcct4` = 0) in every
      powered file, not A1 + A2; three isolated A1 + A3 files follow in
      2016 (`2016.07.27 - 10:17`, `2016.08.03 - 19:38` and `20:18`) among
      A1 + A2 ones. Fixed by the housing versions `M7-140317` (`IH = Idcct1 +
      Idcct3`) and `M7-160726` (base again); the three 2016 files stay
      tagged. With A1 + A3, `IH - Icoil7` still reaches 5.7–7.2 A (p99) at
      ≈ 13.8 kA, a systematic offset (A3 DCCT calibration?) above the 5 A
      tolerance: 16 files tagged, kept on purpose (2026-11-07).
    - **M10, 2021-03-25 → 2021-07-10** (end of `M10_A201214_00`,
      `M10_A210414_00`, `M10_A210519_00`): insert fed by A1 + A2, Bitters by
      A3 + A4, the reverse of the M10 base wiring. Fixed by `M10-210325`
      (`IH = Idcct1 + Idcct2`, `IB = Idcct3 + Idcct4`) and `M10-210929`. In
      half of these files the Bitters ran on A3 alone (`Idcct4` = 0): tagged
      by `A3_vs_A4`, a real imbalance.
    - The stats computed with the old `IH` for these files (`compute_exp_stats`)
      need a recompute after `housing sync` (A22).
14. **[FIXED 2026-11-09] `M8_A211225_00` is supras-only in DuckDB**, yet
    `Idcct1` reaches 6 856 A (a Bitters-group supply) and insert / Bitters
    taps carry signal (`ch1–7`, `11`, `12`, `15`, `16`) in up to all 28
    files: 181 channel-check tags (2026-11-07). Missing magnets in the
    assembly JSON, or that supply and those taps served something else — to
    check.
    Checked on the 28 pupitre files and EXPERIENCES_LOG (2026-11-09):
    - 2022-11-24 → 2023-07-25 (17 files, 12-slot pupitre, stale header
      `HL-28_1_BI04_1_BE02_1_13/05/2014`): only the B supply (Idcct1/2, up
      to IB = 30.5 kA, 9.0 T), Bitters voltage on `Ucoil11`/`Ucoil12`
      (Icoil11/12 = IB), no `Ucoil13–16` columns, one hydraulic circuit;
      Field/IB = 2.94 × 10⁻⁴ T/A in every powered file; M8e (Bitters)
      sessions in the log. So M8Bitters was in the assembly.
    - 2023-09-13 → 2023-09-15 (11 files, 16-slot pupitre, header
      `M23012001`): insert on the H supply (Idcct3/4, up to IH = 12 kA,
      10.7 T) on `Ucoil1–7`, Bitters on `Ucoil15`/`Ucoil16` with the same
      Field/IB ratio; M8i sessions from 2023-09-13 13:45. These are runs of
      `M8_A230919_00`, six days before its recorded commissioning.

    Fix (user decision, option A): `M8_A211225_00` = Hybrid + M8Bitters
    until 2023-09-13 07:00; `M8_A230919_00` commissioned 2023-09-13 08:00
    (name kept; assembly names are not parsed for dates); M8Bitters
    `assembled_at` 2021-12-25 (hifimagnet-projects JSON). Housing versions:
    `M8-211225` now carries the 12-slot wiring (`voltage_channels_gr1` =
    Ucoil11/12, `voltage_channels_gr2` = Ucoil1–10, an exception to the
    empty-base rule) and the new `M8-230913` (2023-09-13T13:48:50+02:00, first
    16-slot file) is back to the base wiring. Renaming `M8_A230919_00` to
    `M8_A230913_00` is planned in
    [PLAN_m8_assembly_rename.md](PLAN_m8_assembly_rename.md) (not approved).
    Takes effect at the next build;
    `assembly update` cannot change assembly dates or magnets. Not handled:
    `Ucoil15`/`16` read ≈ 238 V at < 50 A on `2023.09.13 - 13:48:50` and
    `13:53:31` (left to the check rules).
15. **`M10_A220223_00` (insert `M19071101`, 12 helices) reads taps 5–7
    only from `2022.04.06 - 11:42:33`** (2–7 until `2022.04.02 - 14:22:58`),
    up to ≈ 27 kA, while the DB keeps it until 2022-04-22; nothing changes
    at 2022-04-22 in the pupitre files. Either a 6-helix insert from
    ≈ 2022-04-06 (`M10_A220422_00` → `M10_A220406_00`?) or `M19071101`
    cabled on 5–7 only — to check by the user (2026-11-07). Taps show the
    cabling, not the magnet: the Bitters-only `M10_A241209_00` has taps 2–7
    plugged.
16. **[FIXED 2026-11-08] Hybrid resistive currents zeroed at M8 standby.**
    The Hybrid system records the supply currents (`ALIM1`, `ALIM2`)
    whatever housing they feed, while the M8 voltages are recorded only
    when M8 is fed. `HybridRun.getData` zeroed the currents where the
    companion voltage (`BITTER_V2`, `PH_V14`) was "off" by an Otsu
    threshold, which depends on the hours loaded: the M8 standby steps
    (447 / 411 A at 1.7 / 0.33 V) read 0 A. Fixed in python_magnetrun by
    `LoadOptions.sessions_log`: with the EXPERIENCES_LOG CSV, a current is
    kept only inside a session of the housing on its supply group
    (`hybrid_session_group_map`, padded by 5 min), Otsu remains the
    fallback after the end of the log. Checked on 2026-10-14 (M8 standby
    kept, the M10 session on the same supplies zeroed) and on the lag run
    of #27 (residual 273 / 356 A → 7.5 / 4.8 A). Masked samples are still
    0; switching to NaN is a separate plan. Unclosed log rows can widen the
    windows (study note, open question 4).
17. **[FIXED in code 2026-11-12; stored modes not yet reprocessed]
    `to_duckdb` `infer_operating_mode` assumes `Courant_GR1` = IH and
    `Courant_GR2` = IB**, true on M9 only: on M8 and M10 GR1 feeds the
    Bitters (`reference_gr1_current` = `IB`), so the IH(IB) fit is
    inverted there (M5, M7: one circuit, NORMAL, fine). NORMAL vs ECO still
    comes out right while the slope is near 1 (1/0.97 lies in 0.66–1.5),
    but the slope is the inverse and an ECO run can be misclassified.
    **Fix to plan (separate plan, tests in `to_duckdb/tests/test_crud.py`):**
    resolve the housing version at the overview's start
    (`HousingConfig.at(t0)`) in both callers (`populate._overview_mode`,
    the overview-mode step of `crud.py`), map GR1/GR2 to IH/IB through
    `reference_gr1_current` / `reference_gr2_current`, keep the
    single-circuit case as NORMAL, then check the stored
    `operationaldata.mode` values on M8/M10.
    Fix ([PLAN_overview_mode_gr_mapping.md](PLAN_overview_mode_gr_mapping.md),
    plan B): `crud._overview_current_channels(housing, t0)` reads the
    version in force through python_magnetrun
    `get_pupitre_current_channel` (GR2 is IH when GR1 → `IB` and GR2 → `IH`,
    else GR1); `infer_operating_mode(df, ih=, ib=)`; both callers pass the
    channels. The M10 supply swap is covered by the new
    `pigbrother_current_map` of `M10-210325`
    ([PLAN_pigbrother_pupitre_current_channels.md](PLAN_pigbrother_pupitre_current_channels.md)).
    DBs built before the fix (`magnetdb-2026-11-10.duckdb` included) keep
    the old M8/M10 modes until reprocessed (plan B steps 6–7) or rebuilt.
18. **24 pupitre files stored under two housings** (found 2026-11-10 on
    `magnetdb-2026-11-05`, byte-identical copies checked with `cmp`): each
    file is copied into another housing's folder, so its experiment (and its
    `operationaldata` Pupitre row) is inserted twice, under two assemblies.
    - 5 M10 files, 2019-12-04 → 12-07 (header `M19071101`), copied into
      `M5/`: wrong copies = experiment ids 2938–2942 (`M5_A140101_00`),
      right ones 716–720 (`M10_A190429_00`).
    - 13 M10 Bitters-only files, 2020-02-06 → 03-06 (`Idcct3/4` = 0, stale
      header naming `M19071101`), copied into `M5/`: wrong copies = ids
      2956–2968, right ones 721–733 (`M10_A200122_00`).
    - 6 M9 files, 2025-01-27 15:35:40 → 16:33:39 (header `M25012001`),
      copied into `M10/`: wrong copies = ids 2027–2032 (`M10_A241209_00`),
      right ones 5896–5901 (`M9_A250121_00`). M10 did run that afternoon
      (Overview `Champ_magn` 28.7 T at 16:28 Paris) but has no pupitre file
      of its own.
    - Cross-source comparisons (pupitre vs pigbrother of the same housing)
      can pair two different magnets; check the header magnet against the
      assembly first. Fix (skip rule in the build, stats recompute) not yet
      planned.

---

## Open questions

| # | Question | Blocks |
|---|---|---|
| 1 | MAGFILE semantics/units — **mostly resolved** in `magfile-defs.json` (from `magfile.txt`; FF in G/A per circuit and r0 scale checked against data). ~~units of `r0/a0/b0`~~ — confirmed mΩ, mΩ/A, mΩ/A² (2026-11-03, monitoring model recomputed from real files). Remaining: unit of `H<i>` (mH inferred); meaning and unit of `DeltaT0`; unit of `DeltaPFA/PFU` (mbar?, unused); ~~whether `Imax<n>` is per supply~~ — resolved 2026-10-08 (user): M8/M9/M10 one `Imax` per GR, M5 one per supply (A1, A2), M7 one for GR1. Note to explain in phase 2: M9 IH reached 29.5 kA with `Imax1` = 14.8 kA (limit not a hard cap on the measured current, or `IH = Idcct1 + Idcct2` is not the limited quantity?) | phase 2 typed columns |
| 2 | MAGFILE conf → experiment link — only for **conf-only fields** (`Ivar`, `FF`, `Qnom`, surveillance), since the pupitre header links its fields to the experiment directly. `Date`/`Heure` is the file's **generation time**, not an experiment start, which favours a **validity window** (a conf applies from its generation time until the next one for that housing/assembly) over "nearest preceding experiment" | phase 2 reader |
| 3 | Insert slot 1 is `0 0 0` for `M25032101` in both `MAGFILEM9.conf` and the 2026-10-02 pupitre header (so absent in live data too), while the magnet has 14 helices (7 pairs): **which** helix pair has no section — real voltage-tap probes not yet in DuckDB, pairing starting at slot 2, or H1H2 not instrumented? — **resolved 2026-10-08** (user): insert channel rules in the L2 section mapping (pair layout, `Ucoil7` = outermost pair; a null channel = unplugged or pair absent, told apart via `geometry_data` and probes). For `M25032101` (14 helices) `Ucoil1` is unplugged; the C++ writer comment about 4 helices on one channel is ignored. Per-helix layout: `Ucoil14` = outermost helix (confirmed). **Revised 2026-11-05:** for `M25032101`, `Ucoil1` is empty because H1–H4 are read together on `Ucoil2` since 2025-05-09 (data issue #12), so the writer's comment was right; before that date slot 1 was a normal section | — |
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
| 15 | ~~Where does the `IS` ETL step live~~ — resolved 2026-10-07: `IS` is a column of the Pupitre data after the ETL, through the Pupitre ETL spec's `external` entries (step 1b); hybrid directory from python_magnetrun's `HYBRID_DATA_DIR` | — |
| 16 | ~~Meaning of `ct`~~ — resolved: temperature coefficient [1/K] at 0 °C, part of the pupitre monitoring model with r0/a0/b0 (2026-11-03); cross-checked against `materials.alpha` converted to 0 °C, resistance-weighted per helix pair for inserts (L2) | — |
| 17 | Exact start of full pupitre parameter lines in M10 (shell scan inconclusive) | phase 2 coverage |
| 18 | PID third-range threshold: 1000 A (CIRRUS README, R14L09 p13) vs 800 A (magnet-scipy `high_threshold` default) — which is right? If 1000 A, magnet-scipy's default needs a separate fix | phase 1 seed / phase 4 |
| 19 | CIRRUS ramps (`analogique.rampes.rampe`): needed (e.g. ramp rates vs MAGFILE `dIdtmax`), or out of scope? | low priority |
| 20 | Section slots outside M8/M9/M10 — **resolved for M5/M7** by the derived rule (first `Ucoil` of the role's GR; M5 Bitters GR1, M7 insert GR1). **M3** still open: a new `M3-housing-config.json` is needed — which magnet(s) (3 coils, `Imax1 = Imax2 = 13010`), on which circuit(s), and the channel mapping (`Idcct1–4`, `Tin1/2`, `Flow1/2`, `HP1/2`, `Rpm1/2`) | phase 2 (M3) |
| 21 | Should the M8 hybrid supra supply be an L1 `power_circuits` row (e.g. circuit `SUPRA`), or stay only as `reference_supra_current` binding? | phase 1 / 3 |
| 22 | Source vocabulary: the commissioning plan used `measured` / `analytical` / `fem`; this plan uses `magfile_conf`, …, `measurement`, `fit`, `manual`. Recommended: keep this plan's list, `measured` → `measurement`; add `analytical` only if a model other than magnettools needs it | phase 3 |
| 23 | Mutual-inductance shape: `vector` with explicit `order` (magnet-scipy layout, recommended) or one row per magnet pair (commissioning plan, easier SQL) | phase 3 |
| 24 | Commissioning readings — **partly resolved 2026-10-07:** extracted from experiments when loading their pupitre data, only for files with a proper header (#29), computed after the ETL by `to_duckdb`. **Open [unconfirmed]:** candidate commissioning experiments have a given pupitre `Field` signature, still to be defined and checked against real commissioning runs. **Revised 2026-11-05 (user):** the commissioning experiments are the first experiments of the first assembly of a brand-new magnet (reference resistances, field-factor run), a criterion read from the database; their end and the case of moved magnets are open questions #32 and #33. **Revised 2026-11-10 (user):** the field of the field-factor run is measured with a **pickup coil**, not read from pupitre `Field` (an FF×I recomputation); the pupitre files give the current and plateau only. Pickup-coil data **not available yet**. Study notes (header validity, field factors in use, lags): [PLAN_header_field_factor_study.md](PLAN_header_field_factor_study.md) | phase 3 (commissioning tables) |
| 25 | Per-magnet field factor at commissioning: the measured centre field is the sum of all powered magnets (B = FF1·I₁ + FF2·I₂). Is one magnet powered at a time, or is FF fitted over several (I₁, I₂) setpoints? In the second case a row must store every circuit's current, not one `current`. **Note 2026-11-08 (factors in use):** fitting the computed `Field` on IH / IB recovers the factors in use, separable only where the IH(IB) relation is not a single ratio. M8 NORMAL runs co-ramp IH and IB (slope ≈ 0.97, condition number 800–3700), so one NORMAL file only fixes ffH·0.97 + ffB. As on M9/M10, the operating-mode inference picks the separating runs: the ECO run `2026.10.28 - 09:02:02` and the low-current test `2026.11.03 - 11:17:21` (condition number 13–17) give ffH ≈ 8.926 / ffB ≈ 2.946 G/A, consistent with the pooled fit of 17 files (8.930 / 2.942); see [PLAN_header_field_factor_study.md](PLAN_header_field_factor_study.md) and data issue #17. **Partly answered 2026-11-10 (user):** the centre field is measured with a pickup coil at commissioning (data not available yet); pupitre `Field` / pigbrother `Champ_magn` are FF×I recomputations and only give the **configured** factors (recoverable by a per-file fit), never a measured FF. The setpoint layout question stays open | phase 3 (commissioning tables) |
| 26 | `housing_config.coil_assignment` is `MAP(role → GR)`: it cannot express two Bitters magnets on GR1/GR2 (M5 rewiring). Which key (magnet name, `Bitter1`/`Bitter2`, …)? Also affects the L2 slot rule for M5 and L1 `power_circuits` | M5 (step 4), phase 1 / 2 |
| 27 | Do the Hybrid and pupitre clocks need a lag correction before `IS` is aligned with `merge_asof` (0.5 s)? Pupitre vs pigbrother lag is the subject of the signature robustness plan; Hybrid vs pupitre was never checked. **Partly resolved 2026-11-08: yes.** Measured with python_magnetrun `examples/hybrid_pupitre_lag.py` on M8 `2026.10.30 - 09:10:03.txt` (pupitre time + lag = Hybrid time): −190 s for IB vs `ALIM1` and IH vs `ALIM2`, −191 s for `SupraField` vs `I_BOB`; no drift over the 5 h run (residual 7.5 / 4.8 A with the session-log mask, data issue #16). Clock lags vary from file to file (pupitre ↔ pigbrother as well), so the lag is stored per overview record in `sync_info` (S2), with a per-file estimate as fallback. Open: only one Hybrid run checked | step 1b |
| 28 | Pupitre file with no assembly covering its time (e.g. data issue #9): build a housing-only spec (v1 content, no assembly-specific entries) with a warning (recommended), or refuse the ETL? | step 1 follow-ups / 2a |
| 29 | ~~"Proper" pupitre header~~ — resolved 2026-10-08 from the pupitre writer's C++ code: defined by line 1 only; proper ⇔ `header_class = 'full'` (see L2 "Pupitre header reader") | — |
| 30 | Monitoring-model L3 rows on M9: bind `Tin` to the GR1 inlet (`Tin1`, physically right) or to `Tin2`, which the pupitre used when the coefficients were in use (data issue #10)? | phase 3 |
| 31 | Voltage-tap positions for the probe coherence check: are both current leads on the HP side (inferred from ring `bpside`, L2 section mapping rule 2)? Which z sign / end is HP in the geometry, to tell a tap on an HP-side ring from one on a BP-side ring? | phase 2 (`v_probe_coherence`) |
| 32 | End of commissioning of a brand-new magnet (L2 "Header versions, commissioning and stale headers"): the first header version that then stays stable (2025-01-27 14:06 for `M25012001`, 2025-04-03 15:09 for `M25032101`), or an operational marker (field-factor run, a recorded date)? Material from the study in [PLAN_header_field_factor_study.md](PLAN_header_field_factor_study.md) (header versions, operator-only sessions as a hint) | phase 2 (`status`), phase 3 (commissioning tables) |
| 33 | Does a magnet moved to a new assembly (e.g. `M23012001`: M9 from 2023-01, M8 from 2023-09) also go through a commissioning, or only a brand-new magnet? | phase 2 (`status`), phase 3 |
| 34 | Where does the **measured** centre field of a commissioning come from? Pupitre `Field` and pigbrother `Champ_magn` are both computed from the factors in use (L3 "Field factor"), so neither gives a measured field factor. **Partly resolved 2026-11-10 (user):** from the **pickup-coil** step of the commissioning; those data are **not available yet**. Open: where and in which format the pickup-coil data are kept (once available, they can be compared with the factors in use), or whether measured factors are entered by hand (L3 commissioning tables). See [PLAN_header_field_factor_study.md](PLAN_header_field_factor_study.md) | phase 3 (commissioning tables) |
