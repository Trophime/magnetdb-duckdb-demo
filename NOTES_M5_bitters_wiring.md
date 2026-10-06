# Notes: M5 Bitters wiring — proposed changes

**Status (2026-10-06): ON HOLD.** Nothing below is to be applied until a
**formal confirmation** that the M5 Bitters are powered in parallel, i.e.
each Bitter on its own power supply (Bitter 1 on A1, Bitter 2 on A2). These
notes collect the evidence, the defects found, and the agreed changes so they
can be turned into a plan once the confirmation arrives.

Related: [PLAN_digital_twin_schema.md](PLAN_digital_twin_schema.md) (section
mapping, variable binding, data issue #8).

---

## 1. Evidence

- **MAGFILE field notes** (`magfile.txt`, `Type`): "Seul M5 nécessite encore
  ce type pour dire que la bitter 1 est sur A1 et la bitter 2 est sur A2 à
  15kA chacune." `Couplage`: supplies paralleled "tous les aimants sauf M5".
- **Pupitre data** — each supply feeds one coil:

  | File | Idcct1 (A1) | Idcct2 (A2) | Icoil1 | Icoil2 | Field |
  |---|---|---|---|---|---|
  | `M5/2026.07.27 - 16:48:43.txt` | 5999.9 A | 6002.7 A | 5999.9 A | 6002.8 A | 6.9 T |
  | `M5/2026.09.08 - 14:13:56.txt` | 8742.1 A | 8743.5 A | 8742.1 A | 8743.5 A | 10.0 T |

- **Field check** with the MAGFILE field factors (G/A, one per circuit):
  6.899 × 8742.1 + 4.539 × 8743.5 = 99,998 G = **10.0 T** (measured 10.0 T).
- **Pigbrother** (`pbsurv/M5/Overview/M5_Overview_260908-1413.tdms`,
  group `Courants_Alimentations`): `Courant_A1` = 8731.9 A,
  `Courant_A2` = 8745.3 A, native **`Courant_GR1` = 17,477.2 A = A1 + A2**;
  no `Courant_GR2`. `Champ_magn` = 10,130.6 G.
- **Pupitre header** (line 1, `M5/2026.09.08 - 14:27:54.txt`):
  `NbCoil = 2`, empty `MagnetCode`, `Imax1 = Imax2 = 9550`, two coils with
  distinct R(I) (r0 = 23.79 and 18.87 mΩ).

## 2. Current state and defects

| Where | Today | Defect |
|---|---|---|
| `python_magnetrun/.../M5-housing-config.json` | single group GR1 (A1 + A2); `IB = Idcct1 + Idcct2`; `UB = Ucoil1 + Ucoil2`; `voltage_channels_gr1 = [Ucoil1, Ucoil2]`; `reference_gr1_flow = "FlowB"` | `IB` ≈ 17.5 kA = **2× each Bitter's current** |
| same, `pigbrother_formula_map` | `Référence_GR1 = Référence_A1 + Référence_A2` | doubled reference |
| `housing_config.get_pupitre_rename_map` | H/B-suffix logic: `Flow1 → FlowB`, **`Flow2 → FlowH`** (also `Rpm`, `Tin`, `HP`) | Bitter 2's loop labelled as the helix insert, which M5 does not have |
| `runetl._cleanup_pupitre_icoil` | `IB` already exists → no rename → all `Icoil*` dropped | per-Bitter currents lost (only `Idcct1/2` remain) |
| Pigbrother TDMS (native) | `Courant_GR1 = A1 + A2` | meaningless for M5 (no paralleled group) |
| `magnetdb.duckdb` | one assembly `M5_A140101_00` with **one** magnet `M5Bitters` (parts `M5Bi`, `M5Be`); `housing_config` M5 = `{'Bitter': 'GR1'}` (set 2026-10-05, data issue #8) | to revisit with two Bitters magnets |
| `to_duckdb/stress_map.py` | one `IB` column per Bitters magnet | M5 hoop stress would use 2× the current (≈ 4× the stress). **0 M5 hoop-stress rows today.** |
| Overview records | none for M5 in `magnetdb.duckdb` / `test-magnetdb.duckdb` | if populated today: signatures/plateaux at 2× scale |

## 3. Proposed changes

### 3.1 Assemblies

M5 assemblies contain **two Bitters magnets** (one per supply) instead of one
`M5Bitters` magnet with two parts. Source JSON in
`~/github/hifimagnet-projects/magnetdb.json` (`M5_A140101_00.json`,
`M5Bitters.json`, `M5_Bi.json`, `M5_Be.json`) to be corrected by the user.

### 3.2 Housing config (`M5-housing-config.json`)

| Item | GR1 = A1 → Bitter 1 | GR2 = A2 → Bitter 2 |
|---|---|---|
| current | `IB1` (from `Icoil1` = `Idcct1`) | `IB2` (from `Icoil2` = `Idcct2`) |
| voltage | `UB1 = Ucoil1` | `UB2 = Ucoil2` |
| voltage channels | `voltage_channels_gr1 = [Ucoil1]` | `voltage_channels_gr2 = [Ucoil2]` |
| hydraulics | `FlowB1`, `RpmB1`, `TinB1`, `HPB1` (from `Flow1`, `Rpm1`, `Tin1`, `HP1`) | `FlowB2`, `RpmB2`, `TinB2`, `HPB2` (from `…2`) |

- **`IB` and `UB` are discarded** for M5 (no summed formula).
- `UB1`/`UB2` come for free from `HousingConfig.get_pupitre_voltage_formulas`
  once `reference_gr<n>_voltage` and `voltage_channels_gr<n>` are set — no
  code change.
- `IB1`/`IB2` come from the existing `Icoil → role` rename in
  `_cleanup_pupitre_icoil` once the summed `IB` formula is removed.

### 3.3 Pigbrother

- **`Courant_GR1` rewritten from `Courant_A1`, `Courant_GR2` from
  `Courant_A2` — in the ETL only; raw TDMS files are never modified.**
  Implemented as `pigbrother_formula_map` entries
  (`Courants_Alimentations/Courant_GR1 = Courant_A1`,
  `Courants_Alimentations/Courant_GR2 = Courant_A2`), the first flagged
  `"replace": true` because the native channel exists.
- `Référence_GR1` / `Référence_GR2` as one-term aliases of `Référence_A1` /
  `Référence_A2` (neither exists natively).
- Effect: all code keyed on `Courant_GR1`/`Courant_GR2` (overview analysis
  thresholds and processing, `HousingConfig.get_pupitre_current_channel`,
  dashboard overlay) works unchanged with per-Bitter meaning.

## 4. Labels

**Problem:** labels are global per format (`pupitre-defs.json`,
`pigbrother-defs.json`); a user override replaces the whole file; the
dashboard reads the global pupitre defs directly. `Ucoil1` is "Voltage tap on
H1 or H1/H2" everywhere — wrong for M5.

**Design:** a `field_overrides` section in the housing config, keyed by
format, with **partial entries merged per key** over the global defs.
Resolution: global defs → housing `field_overrides`. A user
`~/.config/magnetrun/M5-housing-config.json` keeps overriding the bundled one.
M8/M9/M10 need no overrides.

**M5 labels** ("Bitter 1/2" until inner/outer is confirmed, then e.g.
"Inner Bitter (A1)"):

| Format | Channel | label | description | pairing |
|---|---|---|---|---|
| pupitre | `IB1` / `IB2` | `I_B1` / `I_B2` | Bitter 1/2 current (supply A1/A2) | pigbrother `Courants_Alimentations/Courant_GR1` / `Courant_GR2` |
| pupitre | `UB1` / `UB2` | `U_B1` / `U_B2` | Bitter 1/2 voltage (`Ucoil1`/`Ucoil2`) | pigbrother `Tensions_Aimant/Interne1` / `Interne2` |
| pupitre | `FlowB1` / `FlowB2` | `Q_B1` / `Q_B2` | Bitter 1/2 cooling loop flow | |
| pupitre | `RpmB1` / `RpmB2` | `Rpm_B1` / `Rpm_B2` | Bitter 1/2 pump speed | |
| pupitre | `TinB1` / `TinB2` | `Tin_B1` / `Tin_B2` | Bitter 1/2 inlet temperature | |
| pupitre | `HPB1` / `HPB2` | `HP_B1` / `HP_B2` | Bitter 1/2 high pressure | |
| pupitre | `DRcoil1` / `DRcoil2` | `dR_B1` / `dR_B2` | Bitter 1/2 resistance deviation | |
| pupitre | `Tcal1` / `Tcal2` | `T_cal_B1` / `T_cal_B2` | Bitter 1/2 estimated mean temperature | |
| pigbrother | `Courants_Alimentations/Courant_GR1` | `I_B1` | Bitter 1 current — rewritten from `Courant_A1` (native A1+A2 sum discarded) | |
| pigbrother | `Courants_Alimentations/Courant_GR2` | `I_B2` | Bitter 2 current — from `Courant_A2` | |
| pigbrother | `Courants_Alimentations/Référence_GR1` / `GR2` | `I_ref_B1` / `I_ref_B2` | Bitter 1/2 reference current (`Référence_A1`/`A2`) | |
| pigbrother | `Tensions_Aimant/Interne1` / `Interne2` | `U_B1` / `U_B2` | Bitter 1/2 voltage | |

- **`Ucoil1` / `Ucoil2` are hidden in M5 menus** (they duplicate `UB1` /
  `UB2`), via a per-housing channel exclusion list (today
  `_GROUP_CHANNEL_EXCLUSIONS` in `magnetdb_analysis.py` is global).
- Code touchpoints:
  - python_magnetrun: a helper, e.g. `get_field_defs(fmt, housing)`, used
    where `load_units_from_json` sets labels/units for a run (the
    `fromtxt` / `fromtdms` paths, where the housing is known);
  - renamed channels (`Flow1 → FlowB1`) take their label from the override
    after the rename;
  - dashboard: pupitre ↔ pigbrother pairing and `plot.group_display_unit`
    read the merged view instead of the global `_PUPITRE_DEFS`.

## 5. Code changes

| Component | Change |
|---|---|
| `to_duckdb/crud.py` `_housing_config_data_from_magnetrun` | derivation that understands `IB1`/`IB2` and two Bitters magnets (today the suffix `1` raises `ValueError`, which would break M5 housing auto-creation and `assembly add` for M5) |
| `python_magnetrun/housing_config.py` `get_pupitre_rename_map` | use per-GR flow names as given (`FlowB1`/`FlowB2`) instead of the H/B-suffix logic |
| `python_magnetrun/magnetdata_tdms.py` `TdmsMagnetData.cleanupData` | support `"replace": true` on a formula entry (overwrite an existing channel) — default behaviour unchanged |
| `python_magnetrun` housing config / defs | `field_overrides` support + `get_field_defs(fmt, housing)`; per-housing channel exclusions |
| `apps/dashboards/magnetdb/src/magnetdb_analysis.py` | pairing via the merged defs (M5: `IB1` ↔ `Courant_GR1`, `UB1` ↔ `Interne1`, …); per-housing exclusions |
| `to_duckdb/stress_map.py` | per-magnet current columns (two Bitters magnets on `IB1` / `IB2`); today a missing `IB` silently gives 0 A |
| `to_duckdb/crud.py` `infer_overview_record_fields` | run mode inference **after the ETL rewrite**: load the overview through `load_mrun(path, housing=…)` or call `prepareData(mdata, housing)` instead of the raw `load_magnetdata(path)` used today. M5 then gets `Courant_GR1` = A1, `Courant_GR2` = A2 → slope ≈ 1 → NORMAL (acceptable: no insert, no eco mode). `infer_operating_mode` itself needs no change. Check on M9/M10: re-infer a sample and compare with the stored `mode` (their native `Courant_GR1/GR2` are unchanged by the ETL) |
| `python_magnetrun/pupitre-defs.json` | entries for `IB1`, `IB2`, `UB1`, `UB2`, `FlowB1/2`, `RpmB1/2`, `TinB1/2`, `HPB1/2` (unit, group) so they appear in menus |

## 6. DB changes (`magnetdb.duckdb`)

- `housing_config` M5 row: new `coil_assignment` for two Bitters magnets.
  DuckDB cannot `UPDATE` this `MAP` column while assemblies reference the row
  → same export / patch / import procedure as data issue #8 (backup,
  rehearsal, table-by-table comparison).
- M5 assembly: two Bitters magnets once the source JSON is corrected — via a
  backed-up repair (as for the M9 assemblies), since `assembly add` now
  refuses a re-add whose magnet list differs.

## 7. Dashboard impact

| Area | Today | After the changes |
|---|---|---|
| Pupitre current | `IB` ≈ 17.5 kA (2×) | `IB1`, `IB2` ≈ 8.7 kA each |
| Pupitre voltage | `UB = Ucoil1 + Ucoil2` | `UB1`, `UB2`; `Ucoil1/2` hidden |
| Hydraulics | `Flow1 → FlowB`, `Flow2 → FlowH` (wrong) | `FlowB1`, `FlowB2` (and `Rpm`, `Tin`, `HP`) |
| Pigbrother current | native `Courant_GR1` = sum | `Courant_GR1` = A1, `Courant_GR2` = A2 (ETL) |
| Pupitre ↔ pigbrother overlay | `IB` ↔ `Courant_GR1` (both sums) | `IB1` ↔ `Courant_GR1`, `IB2` ↔ `Courant_GR2` |
| Labels | generic helix labels on `Ucoil1/2` | M5 labels from `field_overrides` |
| Overview records | none for M5 | per-Bitter scale; mode NORMAL (inferred after the ETL rewrite) |
| Hoop stress | would use 2× current | per-Bitter currents |

## 8. Side findings (not M5-specific)

- `to_duckdb/crud.py` `infer_operating_mode` names `Courant_GR1` "IH" and
  `Courant_GR2` "IB" — true for M9 (insert on GR1), misleading for M8/M10
  (GR1 = Bitters). **Classification is unaffected:** the NORMAL band
  0.66 ≤ slope ≤ 1.5 is symmetric under swapping the two currents
  (1/1.5 = 0.667, 1/0.66 = 1.515), so ECO (slope ≈ 2.6 for M9, ≈ 0.38 for
  M10) is detected either way; stored modes agree (ECO ≈ 73 % for M9,
  ≈ 72 % for M10). It already returns NORMAL when one current is absent or
  stays below 50 A. Remaining: cosmetic renaming (`I_gr1` / `I_gr2`).
  The 37 M10 records with a NULL mode are not a classification problem —
  see data issue #9 in `PLAN_digital_twin_schema.md` (missing M10 assembly).
- The pigbrother acquisition for M5 computes `Courant_GR1 = A1 + A2`:
  arithmetically "the GR1 current", but no conductor carries it on M5. Worth
  reporting upstream to whoever maintains the pigbrother configuration — the
  same contact could give the pending formal confirmation of the M5 wiring.
  Low priority: the ETL rewrite fixes it in our tools.

## 9. Open details

- Which Bitter is inner and which is outer (on A1 / A2)?
- Does M5 have one cooling loop per Bitter (`Flow1`/`Flow2` both active)?
  The renaming above assumes yes.
- ~~"ETL only" scope~~ — answered: the rewrite lives in python_magnetrun's
  `prepareData` (`runetl.py`), which the dashboards and (after the change in
  §5) overview mode inference go through; raw TDMS files are never modified.
- `Imax<n>` semantics (per supply?) — see the MAGFILE defs work.
