# Plan: M19 joint operation (M9 + M10 Bitters on the four supplies)

**Status (2026-11-12): drafted, not approved.** Answers ROADMAP G8 /
`to_duckdb/TODOs.md` "How to handle special experiments" for M19. Needs the
answers to the [open questions](#open-questions) (the data volume is not
mounted yet) and `approve` before any step. Written from the magnet-scipy
side: the motivating use is replaying M19 and identifying R/L with magnet-scipy
(`magnet-scipy/prompts/ode_config_from_magnetdb.md`,
`magnet-scipy/prompts/parameter_identification.md`).

## Context

M19 was a test run for the new 30 MW installation (2024-02-08): the M9 and M10
housings were operated **at the same time**, each assembly holding only its
Bitters magnet. pigbrother names these files with the `M19_` prefix
(`M19_Overview_240208-0941.tdms`, `M19_Archive_240208-0941.tdms`).

Wiring, read from `M19_Overview_240208-0941.tdms` (magnet-scipy
`examples/M19/`, checked 2026-11-09):

| Supply group | Magnet | Taps | Circuit voltage | Peak |
|---|---|---|---|---|
| GR2 (`A3 + A4`) | M9 Bitters | `M9Externe1/2` | `ALL externes` | 553 V × 32.4 kA ≈ 17.9 MW |
| GR1 (`A1 + A2`) | M10 Bitters | `M10Externe1/2` | `ALL externes 2` | 411 V × 31.7 kA ≈ 13.1 MW |

- `Externe1 + Externe2 = ALL externes` to 6e-5 V, for both magnets.
- `ALL internes` and `ALL internes 2` are identically 0 (no inserts).
- `Infos/Pmax` = 31.5 MW.
- `TODOs.md` says "M9 with 18 MW and M10 with 10 MW". That matches the
  M9/M10 labels of the data.

## State of the DB (`magnetdb-2026-11-05.duckdb`, read-only check 2026-11-09)

- **No `M19_*` file** in `operationaldata`. The ingest only knows the
  housing prefixes M5–M10. No `overview_records` row on 2024-02-08.
- **Pupitre files exist** for that day, attached to the regular assemblies,
  which include the inserts:
  - M9: `2024.02.08 - 09:07:52.txt` and `2024.02.08 - 12:54:21.txt` →
    `M9_A230801_00` (`M23072801` + `M9Bitters-newBi08`);
  - M10: `2024.02.08 - 09:07:57.txt` → `M10_A230509_00`
    (`M19071101` + `M10Bitters`).
- `housing_config.coil_assignment`: M9 `{Insert: GR1, Bitter: GR2}`,
  M10 `{Bitter: GR1, Insert: GR2}`. One version per housing
  (`M9-181109`, `M10-180220`).

## Principle

M19 is **neither a housing nor an assembly**. It is a temporary routing of
the four supplies to two housings at once.

- A housing is a physical place. M9 and M10 stay the housings.
- A magnet is in one assembly at a time. An `M19` assembly holding
  `M9Bitters-newBi08` and `M10Bitters` would overlap their M9 and M10
  assemblies.
- `coil_assignment` (role → GR) can't hold two Bitters magnets (open
  question #26 of [PLAN_digital_twin_schema.md](PLAN_digital_twin_schema.md)).

In the target L1 design, the routing is just two `power_circuits` rows valid
for the test window: `(M10, GR1, [A1, A2])` and `(M9, GR2, [A3, A4])`. M19
needs no special case there. The steps below get the same result with
today's tables.

## Steps

### 1. Assemblies: what was physically in the housings

Depends on open question 1.

- **Inserts physically removed:** close `M9_A230801_00` and
  `M10_A230509_00` at removal. Add Bitters-only assemblies for the test
  window (`M9_A2402xx_00` = `M9Bitters-newBi08`, `M10_A2402xx_00` =
  `M10Bitters`). Then add new assemblies, with the same magnets as before
  and new dated names, from the date the inserts went back. No schema
  change.
- **Inserts left in place but not powered:** assemblies unchanged. Steps 2–4
  carry all of the M19 information.

→ verify: if the inserts were removed, the 3 pupitre files of 2024-02-08
resolve to the Bitters-only assemblies. The lifecycle checks report no
assembly overlap.

### 2. Supply routing: housing-config versions for the window

Add dated versions in `housing_config_versions`. Write them back to
python_magnetrun's `M9-housing-config.json` and `M10-housing-config.json`
with `export_housing_config_json`.

- `M9-240208`: Bitters on GR2 only (no GR1 circuit). pigbrother channels
  `M9Externe1/2`, `ALL externes`.
- `M10-240208`: Bitters on GR1 only (no GR2 circuit). pigbrother channels
  `M10Externe1/2`, `ALL externes 2`.
- Versions only have a `valid_from`, so the window also needs closing
  versions (`M9-2402yy`, `M10-2402yy`) that restore the base overrides.

→ verify: `HousingConfig.at(t0)` returns the M19 wiring inside the window
and the base wiring before and after it.

### 3. Records: one M19 file → one record per housing

- **python_magnetrun:** a new `M19-housing-config.json` that describes the
  split. For each member housing it gives the GR, the supplies, the current
  channel (`Courant GR1` / `Courant GR2`), and the voltage and tap channels.
  It also gives the channel-name normalisation (in the M9 half,
  `M9Externe1` → `Externe1`). It has no role-based `coil_assignment`.
- **Ingest (`populate`):** recognise the `M19` prefix and the `pbsurv/M19`
  directory in `operationaldata`.
- **Overview-record builder:** emit **two records per M19 file**, e.g.
  `M19_Overview_240208-0941@M9` and `…@M10`. Each record has its own
  housing, its assembly at t0 and its own pupitre source. Both have the
  same pigbrother sources.
- **Why split:** it keeps the invariant "one record = one assembly", which
  the op/exp stats, hoop stress and the dashboards rely on. The alternative
  is a link table `overview_record_assemblies`. It is more general, but
  every per-assembly query would have to change, so it is not proposed.

→ verify: on the 2024-02-08 files, 2 records are created. The stats of each
half see one Bitters magnet, with the current and voltage of its own GR. The
powers of the two halves add up to `Puissance Alims` (31.5 MW peak).

### 4. Tags

Add `record_tags` on both halves:
`{"campaign": "M19", "note": "30 MW test, M9 + M10 Bitters simultaneously",
"sibling": "<other half>"}`. Statistics can then include or exclude special
experiments. The same mechanism covers the negative IH/IB experiments (G8),
without a special schema.

→ verify: a query that excludes `campaign` tags drops exactly the M19
records.

### 5. Consumers

- **magnet-scipy builder** (`ode_config_from_magnetdb.md`): take the two
  sibling records (same source file) and build one case with 2 circuits and
  `M = 0`, since the housings are separate. `examples/M19/M19.json` does
  this by hand today.
- **Identification:** the coupling between the two housings is zero, so the
  estimated cross-coupling must come out zero. That is a built-in check of
  the inductance estimate.

## Open questions

1. Were the inserts **physically removed** for the test? If so, what are the
   removal and reinstallation dates for M9 and M10?
2. Which `M19_*` files exist in `pbsurv/M19` besides 2024-02-08 (other test
   days; Default, Trigger or SignalStats files)?
3. What is the exact window of the M19 wiring (first and last M19 file, or
   the supply switch times)? It sets the housing-config versions.
4. Were the M9 and M10 cooling loops independent during the test (separate
   Tin/Flow per pupitre file), or shared?
5. Once the data is mounted, check the M9/M10 labels against the power
   split (M9 ≈ 18 MW, M10 ≈ 13 MW in the Overview file).

## Out of scope

- The L1 `power_circuits` tables themselves (phase 1 of
  PLAN_digital_twin_schema).
- Generalising to multi-assembly records.
- Mateo's negative-current experiments, beyond the shared tag mechanism.
