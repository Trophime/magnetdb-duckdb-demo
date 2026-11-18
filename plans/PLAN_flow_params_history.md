# Water flow parameters: reference, checks per experiment, history

**Status (2026-11-18): 📝 drafted, awaiting approval; phase 0 items 1-2 done**
(python_magnetcooling `9254d59` on `msite_to_assembly`, pinned here in
`acdff56`). Each phase below is approved separately. Supersedes the "Flow parameters" section of
[PLAN_digital_twin_schema.md](PLAN_digital_twin_schema.md) (L3) and the
reference lookup of [PLAN_waterflow_dashboard.md](PLAN_waterflow_dashboard.md)
(`get_flow_params_for_assembly` on `overview_records.flow_params`).

## Goal

For each magnet of an assembly, keep a reference set of water flow
parameters (from the commissioning experiments), check every experiment
(pupitre file) against it, refit when the check fails and the data allows it,
and keep the history of parameters and check results, so that a change of the
cooling-system settings or a degradation of the magnet hydraulics shows up as
a dated step.

## Context and findings

The parameters (`*-flow_params.json`, read by
`python_magnetcooling.waterflow_factory.from_flow_params`) describe the
coolant flow of one magnet, which the control system drives from the magnet
current:

```
Vp(I) = Vpmax (min(I, Imax)/Imax)^2 + Vp0          pump speed [rpm]
F     = F0 + Fmax Vp/(Vpmax + Vp0)                 flow [l/s]
HP    = Pmin + Pmax (Vp/(Vpmax + Vp0))^2           inlet pressure [bar]
BP                                                 back pressure [bar], constant
```

The data is only in the pupitre files (`Rpm*`, `Flow*`, `HP*`, `BP`;
housing configs name them `reference_gr<n>_rpm|flow|pin`, e.g. `RpmH`,
`FlowH`, `HPH`). `overview_records.flow_params` is empty in all 1952 records.

Study on assembly `M9_A230801_00` (insert `M23072801`, `M9Bitters_18MW`;
201 pupitre files, 337 shots; magnet-scipy `prompts/flow_params_check.md`
and its `examples/fit_M23072801_flow_params.py`):

1. **Two kinds of parameters.**
   - *Pump law* (`Vp0`, `Vpmax`, `Imax`): a set point of the control system,
     exact to 0.25-0.30 rpm RMS (R^2 = 1.00000) on both magnets: insert
     Imax = 27 066 A, Vp0 = 999.5, Vpmax = 1800.5 rpm; Bitters
     Imax = 26 916 A, Vp0 = 999.5, Vpmax = 1780.8 rpm. It changes only
     when the control system is reconfigured: 2023-09-06 (Bitters full
     speed at ~22.1 kA, same hydraulics).
   - *Hydraulics* (`F0`, `Fmax`, `Pmin`, `Pmax`, `BP`): the magnet and its
     circuit. Insert: flow 3-5 l/s lower at the same pump speed from
     2024-07-15 on than up to 2024-05-10 (HP 0.3-0.9 bar lower); Bitters:
     no step (per-run flow bias within ±0.8 l/s, 2023-09 to 2024-08).
     2024-04-08 (Bitters alone): ~30 l/s less flow at the same pump speed,
     a different hydraulic configuration.
   - In the model, `Fmax` is scaled by the pump law (`Vpmax + Vp0`): a
     change of the pump law changes `Fmax` with unchanged hydraulics. The
     hydraulics are therefore checked and fitted **against the measured
     pump speed**, and the history uses law-independent indicators.
2. **The operating mode (ECO / NORMAL) does not matter.** ECO, two-supply
   NORMAL and single-supply shots follow the same pump law and hydraulics,
   except on the dated configurations above. The mode is not a key.
3. **Overview records are the wrong granularity.** `M9_Overview_231004-1023`
   spans several pupitre files; its `mode` (NORMAL, from the whole file) is
   wrong for the 12:12 pupitre window (ECO). Runs without an overview record
   (240717) would be missed. One experiment = one pupitre file is the unit
   of data and of checks. All 282 experiments of the assembly join 1:1 to an
   `operationaldata` row of type `Pupitre` (on the bare file name), which
   carries `t_start` / `t_end`.
4. **Data-quality cases seen**: pupitre current frozen after a trip
   (2023-09-19, 15 594 A while the hydraulics move); `Rpm2` reading 200 rpm
   (2023-10-25); duplicate pupitre timestamps.
5. **`python_magnetcooling` cannot be used unattended yet** (phase 0). The
   fitting bugs are fixed (items 1-2, 2026-11-18); the free-Imax pump law,
   the fits against the measured rpm and the check module are still to do
   (items 3-4).
6. **Hand-filled flow params files with Vp0/Vpmax swapped** (found
   2026-11-18): `M9_M19061901`, `M10_M19020601_M19020601` and
   `M9Bitters-flow_params.json` (copies in `apps/notebooks`, python_magnetapi,
   hifimagnet-projects) have Vp0 = rise, Vpmax = idle speed, and the
   template defaults elsewhere (F0 = 0, Fmax = 61.72, Pmin = 4, Pmax = 22, no
   Pout): never fitted. The fitted `M10_M19020601_M10Bitters` has
   Pout = 2923.35, not a pressure. None of these may seed a reference.

## Design

### Tables

Units: params keep today's JSON with explicit units (rpm, l/s, bar, A),
consumed as is by `WaterFlow` (answers open question #14 of
PLAN_digital_twin_schema.md for these tables; check metrics in the same
units, column names say so).

```sql
-- Versioned parameter sets, one part of one magnet each.
CREATE SEQUENCE IF NOT EXISTS flow_params_id_seq START 1;
CREATE TABLE IF NOT EXISTS flow_params (
    id              INTEGER PRIMARY KEY DEFAULT nextval('flow_params_id_seq'),
    assembly_name   VARCHAR NOT NULL,
    magnet_name     VARCHAR NOT NULL,
    housing_version VARCHAR REFERENCES housing_config_versions(name),
    circuit         VARCHAR NOT NULL,      -- 'GR1' | 'GR2'
    part            VARCHAR NOT NULL,      -- 'pump_law' | 'hydraulics'
    params          JSON    NOT NULL,      -- {"Vp0": {"value":..,"unit":"rpm"}, ...}
    source          VARCHAR NOT NULL,      -- commissioning | refit | file | manual
    status          VARCHAR NOT NULL,      -- reference | active | candidate | rejected | superseded
    valid_from      TIMESTAMP NOT NULL,    -- t_start of the first source experiment
    superseded_by   INTEGER,
    method          VARCHAR,               -- e.g. 'clamped_ls/imax_breakpoint'
    software        JSON,                  -- package versions / commit
    quality         JSON,                  -- n, |I| range, rpm range, R^2, RMS, run-bootstrap SE
    thresholds      JSON,                  -- check thresholds derived at fit time
    created_at      TIMESTAMP DEFAULT now(),
    notes           VARCHAR,
    FOREIGN KEY (assembly_name, magnet_name) REFERENCES assembly_magnets (assembly_name, magnet_name)
);

CREATE TABLE IF NOT EXISTS flow_params_sources (
    flow_params_id  INTEGER REFERENCES flow_params(id),
    experiment_id   INTEGER REFERENCES experiments(id),
    n_samples       INTEGER,
    i_min           DOUBLE,                -- [A]
    i_max           DOUBLE,                -- [A]
    PRIMARY KEY (flow_params_id, experiment_id)
);

-- One row per experiment x magnet: the history.
CREATE TABLE IF NOT EXISTS flow_params_checks (
    experiment_id      INTEGER REFERENCES experiments(id),
    magnet_name        VARCHAR,
    circuit            VARCHAR,
    pump_law_id        INTEGER REFERENCES flow_params(id),
    hydraulics_id      INTEGER REFERENCES flow_params(id),
    n_samples          INTEGER,            -- usable samples, |I| > threshold
    n_shots            INTEGER,
    i_max              DOUBLE,             -- [A]
    rpm_bias           DOUBLE,             -- model - measured [rpm]
    rpm_rms            DOUBLE,
    flow_bias          DOUBLE,             -- at the measured pump speed [l/s]
    flow_rms           DOUBLE,
    hp_bias            DOUBLE,             -- at the measured pump speed [bar]
    hp_rms             DOUBLE,
    bp_mean            DOUBLE,             -- [bar]
    k_hydraulic        DOUBLE,             -- (HP - BP) / Q^2 [bar s^2 / l^2]
    flow_at_ref_rpm    DOUBLE,             -- [l/s], at a fixed pump speed per circuit
    verdict            VARCHAR,            -- ok | pump_law_changed | hydraulics_drift
                                           -- | bad_data | not_enough_range | no_reference
    refit_id           INTEGER REFERENCES flow_params(id),
    checked_at         TIMESTAMP DEFAULT now(),
    details            JSON,               -- excluded samples by reason, per-shot summary
    PRIMARY KEY (experiment_id, magnet_name)
);
```

Verdicts other than `ok` also become `record_tags` rows
(`record_table = 'experiments'`), tags `flow:pump_law_changed`,
`flow:hydraulics_drift`, `flow:bad_data`, so the dashboard shows them with
the other file checks. Experiment time: `operationaldata.t_start/t_end`
joined on the file name (no new column on `experiments`).

### Check and refit rules

Per experiment and magnet (circuit channels from the housing config of the
experiment's housing version):

1. **Usable samples**: |I| above a threshold (300 A), outside rests;
   excluded and counted by reason: frozen current (I constant while
   rpm/flow/HP vary), implausible rpm (below the pump law's Vp0 - margin,
   e.g. the 200 rpm readings), duplicate timestamps.
2. **Pump-law check**: measured rpm vs the active pump law; normal scatter
   < 0.5 rpm, threshold 5 rpm (2023-09-06: 245 rpm) -> `pump_law_changed`.
3. **Hydraulics check** at the measured pump speed: flow and HP bias;
   thresholds from the reference's per-experiment scatter (e.g. 3 x the
   spread of the source experiments' biases, floors ~1 l/s and ~0.3 bar);
   M9 values: 2 l/s, 0.5 bar -> `hydraulics_drift`.
4. **Refit only if identifiable**: pump law needs samples above Imax
   (detected breakpoint) and below Imax/2; hydraulics need a pump-speed
   span (e.g. > 50 % of `Vpmax`). Otherwise the verdict stays and
   `refit_id` is NULL (`not_enough_range` when nothing can be checked).
5. A refit is stored as `candidate`; `flow-params promote` makes it
   `active` (manual review), or automatically after N consecutive
   experiments pass against it (N configurable, off by default).
6. Every check is stored, pass or fail: `k_hydraulic` and
   `flow_at_ref_rpm` per experiment are the degradation history, independent
   of the pump law.

### Lookup

`get_flow_params(assembly, magnet, at=None, part=None)` -> active set valid
at `at` (latest `valid_from <= at`), `reference` if none;
`export_flow_params_json(assembly, magnet, at, path)` writes today's
`*-flow_params.json` (both parts merged) for magnet-scipy and `WaterFlow`.

## Files affected

| Path | Phase | Action |
|---|---|---|
| `python_magnetcooling/python_magnetcooling/fitting.py` | 0 | edit (items 1-2 done; 3 to do) |
| `python_magnetcooling/python_magnetcooling/flow_check.py` | 0 | create |
| `python_magnetcooling/tests/test_fitting.py` | 0 | edit (items 1-2 done: saturation tests) |
| `python_magnetcooling/tests/test_flow_check.py` | 0 | create |
| `to_duckdb/schema.py` | 1 | edit (3 tables) |
| `to_duckdb/flow_params.py` | 1-4 | create (extraction, store, lookup, check, refit) |
| `to_duckdb/magnetdb.py` | 2-4 | edit (`flow-params` command group) |
| `to_duckdb/tests/test_flow_params_db.py` | 1-4 | create |
| `apps/dashboards/magnetdb/src/magnetdb_analysis.py` | 5 | edit (lookup + history query) |
| `plans/PLAN_waterflow_dashboard.md` | 5 | edit (lookup from `flow_params`, history plot) |
| `plans/PLAN_digital_twin_schema.md` | 1 | edit (Flow parameters section -> this plan) |
| `ROADMAP.md` | 1 | edit (row for this plan) |

## Approach

### Phase 0 — python_magnetcooling (submodule)

Write the tests first, on synthetic data that saturates at Imax, in time
order, with samples above Imax.

1. Fix `fit_pump_speed_piecewise`: `vpmax = Vp(Imax) - vp0` (today the speed
   at Imax), evaluated with `predict`, not the extracted equations (wrong
   here: `vpmax` = -9.7e7 rpm); the 1-vs-2-segment test must not assume
   data sorted by current (`current[-1]`).
   -> verify: synthetic Vp0 = 1000, rise 1800, Imax = 27 000 A, shuffled:
   vpmax within 1 rpm of 1800, Imax within 50 A.
2. Clamp at Imax everywhere the pump speed is rebuilt:
   `fit_pump_speed_simple`, `fit_flow_rate`, `fit_pressure` and the plot
   helpers, as `PumpSpeedFit.pump_speed` and `WaterFlow` do.
   -> verify: on synthetic data with 12 % of samples above Imax, F0/Fmax/
   Pmin/Pmax recovered within 1 %; on the M9 insert, ECO two-supply samples
   of all 201 pupitre files with Imax = 27 066 A: F0 = 0.62,
   Fmax = 135.6 l/s, Pmin = 3.78, Pmax = 18.92 bar.

   **Done 2026-11-18 (items 1-2)**, python_magnetcooling `9254d59`
   (branch `fix/fitting-clamp`, merged into `msite_to_assembly`):
   - shared clamped model `_pump_speed_model`, used by the three fits and
     the two plot helpers;
   - piecewise: sorted by current; segment check with `predict`; Vpmax/Vp0
     from the clamped least-squares fit at the detected Imax, so `vpmax` is
     the rise and `fit_result` is set; segment equations rebuilt from
     `predict`;
   - also fixed: the `'N/A':.4f` crash in `fit_hydraulic_system` (piecewise)
     and `back_pressure.mean` in `plot_flow_pressure_fit`.

   Verified on synthetic data with a plateau to 1.2 Imax:
   - noiseless: exact;
   - 0.2 % noise, shuffled: piecewise within 2 %.

   On the magnet-scipy campaign (20 pupitre files, 257k ECO samples,
   Imax = 27 066 A), the insert fit is F0 = 0.80, Fmax = 133.9 l/s,
   Pmin = 3.68, Pmax = 19.23 bar. That is a smaller sample than the 201 files
   above, hence the small differences.

   The same Vpmax and sort fixes went into python_magnetrun
   `flow_params.compute` (`d882a6d`) and python_magnetcooling's
   `examples/flow_params_magnetrun.py` (`be99b1f`).
3. Add `fit_pump_law(current, rpm, imax=None)`: clamped least squares with
   Imax free (or fixed); and `fit_hydraulics(rpm, flow, hp, bp, pump_law)`:
   flow and HP against the **measured** pump speed.
   -> verify: on the M9 data, pump laws as in Findings 1 (to 2 A and 0.5 rpm).
4. Add `flow_check.py`: `check_flow_params(samples, pump_law, hydraulics)
   -> metrics` (bias/RMS of rpm, flow, HP; `k_hydraulic`;
   `flow_at_ref_rpm`), `identifiable(samples, pump_law)` (range rules),
   `to_flow_params(...)` (JSON writer, `BP`/`Pout` normalised), and
   run-bootstrap uncertainties (1 Hz samples are correlated: curve_fit
   standard errors are not usable).
   -> verify: unit tests; the magnet-scipy campaign results reproduced.

### Phase 1 — schema

5. Add the three tables and the tags to `schema.py` (idempotent
   `CREATE ... IF NOT EXISTS`).
   -> verify: `test_schema.py` passes; a new test creates/drops; existing
   DB opens unchanged.

### Phase 2 — extraction

6. `flow_params.load_hydraulics(experiment_id)`: read the pupitre file
   (path from `operationaldata.file`), pick the channels of each magnet from
   the housing config of the experiment's housing version, return samples
   with shot index, per-shot mode (informative only) and exclusion reason.
   -> verify: on `2023.09.19 - 19:08:11` the frozen-current samples are
   excluded; on the 2023-10-25 files the 200 rpm samples are excluded.

### Phase 3 — reference

7. `magnetdb flow-params fit --assembly A --experiments <ids|date range>
   --as reference|candidate` and `flow-params import --file X.json`
   (source = file).
   -> verify: M9_A230801_00 pump laws as in Findings 1; `flow_params_sources`
   lists the experiments used.

### Phase 4 — checks and refits

8. `magnetdb flow-params check [--assembly A] [--since DATE]` fills
   `flow_params_checks` and `record_tags`; `flow-params refit` /
   `promote`.
   -> verify on M9_A230801_00: 2023-09-06 Bitters-alone experiments ->
   `pump_law_changed`; 2024-04-08 -> `hydraulics_drift`; 2023-10-25 ->
   `bad_data`; insert `flow_at_ref_rpm` steps down between 2024-05-10 and
   2024-07-15, Bitters does not; re-running is idempotent.

### Phase 5 — consumers

9. Lookup + JSON export; dashboard: waterflow page reads `flow_params`,
   adds the `k_hydraulic` / `flow_at_ref_rpm` history plot; magnet-scipy
   uses the exported JSON (config key `flow_params`) or the lookup.
   `overview_records.flow_params`: dropped, or kept as a cache (decision).
   -> verify: export of the M9 sets reproduces magnet-scipy's
   `examples/M9_M23072801/*-flow_params.json` within fit tolerance.

## Assumptions and open questions

1. **Which experiments are "commissioning"?** For M9_A230801_00 the first
   day (2023-09-06) has the special Bitters pump law: a reference fitted on
   it would be wrong for every later run. Proposed: a date range given per
   assembly, the reference fitted on the experiments of that range that
   pass a self-consistency check; to confirm with the operators.
2. **Where does the pump law belong?** It is a control-system set point
   (L1 `cooling_circuits` in PLAN_digital_twin_schema.md, versioned per
   housing circuit), and Imax may follow the assembly. If the CIRRUS XML or
   the MAGFILE hold it, ingest it there and use the fit only as a check;
   until then `flow_params(part='pump_law')`.
3. **Back pressure**: measured BP rises with flow (3.5 -> 4.6 bar on M9);
   the constant model cannot follow. The loop is pressurised by a nitrogen
   vessel (user, 2026-11-17); SUPERVISION `bdd` has `azote1`, `azote2`
   [bar] and `niv1` [%] (group `Loop_Pressurisation`, formerly `Nitrogen_Level`), but the local export
   (`Data/bdd.csv`) covers 2026-06-18 -> 2026-11-06 only (nitrogen channels
   non-zero from 2026-07; `azote*` up to ~217 bar, i.e. supply-side, not loop
   pressure), so it does not overlap the M9_A230801_00 study.
   **Tested 2026-11-17** on the 296 pupitre files of that window (M5, M8,
   M9, M10; 2.3M samples, SUPERVISION joined as-of, median gap 0-1 s), with
   Q = Flow1 + Flow2 (total flow of the housing):
   - `BP = BP0 + kb Q^2` explains BP within a file (median R^2 0.93-0.96,
     RMS 0.04-0.07 bar, BP resolution 0.1 bar); kb = 1.2-1.4e-5
     bar/(l/s)^2 on M8, M9, M10 (+0.8-0.9 bar at 250 l/s); linear in Q fits
     about as well. M5 (Q < 71 l/s) has no flow range.
   - BP0 is nearly constant: M9 3.47 ± 0.05, M10 3.55 ± 0.10, M8
     3.48 ± 0.07 bar between files, while `azote1`/`azote2` span 7-210 bar
     and `niv1` 60-96 %. Correlations BP0 vs nitrogen are weak and change
     sign between housings; within files, adding the nitrogen channels
     changes BP by < 0.03 bar. **The nitrogen channels do not explain BP**:
     consistent with a regulator holding the loop at ~3.5 bar while the
     supply stays above it (never below 7 bar here).
   - Inlet water temperature adds +0.03 (M9) to +0.09 (M10) bar/degC within
     files (thermal expansion against the gas cushion?), but -0.04 on M8:
     unconfirmed, <= 0.15 bar.
   Consequences: BP depends on the **total flow of the housing** (both
   magnets), so it is a housing quantity (L1 `cooling_circuits`: `bp0`,
   `kb`), not a per-magnet constant; the per-magnet `BP` of the JSON stays
   for `WaterFlow` compatibility only; hydraulic indicators use measured
   `HP - BP`; BP stays out of the degradation verdicts.
   **Operators (2026-11-17):** `azote1`/`azote2` are the pressures [bar] of
   two 200 bar nitrogen bottles that pressurise the low-pressure side (BP)
   through reservoir R1; a pressure reducer brings them down to ~4 bar
   (adjustable) and switches automatically to the second bottle. So BP0 is
   the reducer set point (~3.5 bar measured in 2026: setting, or sensor
   position relative to R1), a configuration value that can change when the
   reducer is adjusted; the bottle pressures only matter when the active
   bottle falls towards the set point (never below 7 bar in 2026).
   Use: a BP0 step between experiments = set-point change (record it,
   housing level); a `flow:low_nitrogen` check when both bottles approach
   the set point. `niv1` is the level [%] of reservoir R1 (operators,
   2026-11-17), watched as a leak indicator together with the drop of the
   bottle pressures: water lost from the loop lowers R1 and the reducer
   refills the gas cushion from the bottles. The level also follows the
   loop water volume (thermal expansion), so a leak check must compare
   `niv1` at equal inlet temperature, or the level drift together with the
   bottle consumption. R1 is shared by all housings (operators,
   2026-11-17), so the set point, `niv1` and the bottles are **site**
   quantities: a set-point change shows as a simultaneous BP0 step in every
   housing, and the leak check is site-level (SUPERVISION, not pupitre),
   outside `flow_params`; it belongs with the anomaly detection plans. The
   BP0 spread between housings (M8 3.48, M9 3.47, M10 3.55 bar) is then a
   per-housing offset (sensor height or piping between R1 and the sensor;
   0.08 bar ~ 0.8 m of water), not separate settings. Open: whether the BP
   of one housing also depends on the flow of the others (shared return to
   R1); the 2026 test fitted the housing's own flow only. Still to confirm:
   the reducer setting history, where each BP sensor sits relative to R1.
4. **Hydraulics across housings**: `HP - BP` includes the housing pipes, so
   `k_hydraulic` is comparable over time for one magnet in one housing, not
   across housings, unless the housing share is known.
5. **Thresholds**: derived per (assembly, magnet) from the reference
   scatter (stored in `flow_params.thresholds`) vs global
   `check_rules`; proposed: per reference, with global floors.
6. **Shots inside one file with different settings**: not seen on M9
   (changes are per day). A shot-level table only if it happens.
7. **Automatic promotion** (step 5 of the rules): off by default.
8. python_magnetcooling changes (phase 0) are made in the submodule and
   proposed upstream (MagnetDB/python_magnetcooling); ROADMAP E3 lists its
   cooling TODOs.
