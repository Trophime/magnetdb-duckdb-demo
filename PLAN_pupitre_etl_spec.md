# Plan: spec-driven ETL for Pupitre files

**Status (2026-10-07): awaiting approval.** Step 1 of the cross-plan order
in [PLAN_digital_twin_schema.md](PLAN_digital_twin_schema.md#cross-plan-order-blockers-and-approvals);
no blocker.

Related:
- [NOTES_M5_bitters_wiring.md](NOTES_M5_bitters_wiring.md): M5 is the first
  case that needs assembly-driven ETL (§3.2 describes its spec entries).
- [PLAN_digital_twin_schema.md](PLAN_digital_twin_schema.md): its L2 section
  mapping (`v_config_sections`, phase 2) gives the assembly → `Ucoil` rule
  used by v2 of the builder; its L3 binding and commissioning readings rely
  on the channel names this ETL produces; its supra current `IS` (M8) is
  added by this ETL in step 1b (see Follow-ups).

## Goal

Add a second Pupitre ETL path that applies an explicit spec (remove / rename /
add). to_duckdb builds the spec from the assembly and its housing.
`prepareData` and all its callers stay unchanged, and python_magnetrun never
reads the database.

## Context

Today `runetl.prepareData` derives its formula and rename lists from the
bundled `*-housing-config.json` files. It then runs content-based checks
twice, with different lists of protected columns:

- `cleanupData` drops all-zero and duplicate columns;
- `_cleanup_pupitre_icoil` repeats the all-zero drop, removes near-duplicate
  Icoil columns, renames Icoil to IH/IB and drops the rest.

The Icoil rename only runs as a fallback, because every housing (M5, M7, M8,
M9, M10) defines `IH`/`IB` as Idcct sums.

## Decisions

| Topic | Decision |
|---|---|
| Scope | Pupitre files only; TDMS and Hybrid keep using `prepareData` |
| Content-based checks (all-zero, duplicate columns, Icoil guessing) | Dropped from the new path; the explicit remove list replaces them |
| Remove list | Full-match regex patterns; plain names work as-is (e.g. `Icoil\d+`, `Ucoil1[5-6]`) |
| Builder location | to_duckdb, emitting plain JSON-ready dicts; python_magnetdb (postgres) gets its own later |
| Migration | New path alongside `prepareData`; callers are switched in a later step |

## Files affected

| File | Action |
|---|---|
| `python_magnetrun/python_magnetrun/runetl.py` | edit: add `PupitreEtlSpec` and `prepare_pupitre()` |
| `python_magnetrun/python_magnetrun/magnetdata_pandas.py` | edit: `cleanupData` gets `drop_redundant_columns: bool = True` |
| `python_magnetrun/python_magnetrun/magnetdata_polars.py` | edit: same keyword |
| `python_magnetrun/tests/test_runetl.py` | edit: tests for the spec and `prepare_pupitre` |
| `python_magnetrun/README.md` | edit: the ETL section documents a `prepare_pupitre` that doesn't exist; replace it with the real usage |
| `to_duckdb/etl_spec.py` | create: `build_pupitre_etl_spec(con, assembly_name) -> dict` |
| `to_duckdb/tests/test_etl_spec.py` | create |

## Design

```python
@dataclass(frozen=True)
class PupitreEtlSpec:
    remove: list[str]          # full-match regex; plain names work as-is
    rename: dict[str, str]
    add: dict[str, dict]       # field_def: formula, symbol, unit, label, description

    @classmethod
    def from_dict(cls, d: dict) -> "PupitreEtlSpec": ...   # validates field_def keys
    def to_dict(self) -> dict: ...

def prepare_pupitre(data: PandasMagnetData | PolarsMagnetData, spec: PupitreEtlSpec) -> None:
    # addTime → rename → add → remove (patterns matched on current keys) → dedupe t
```

- **Rename before add**, so formulas can use renamed names. Today's formulas
  only use `Idcct*` and `Ucoil*`, which are never renamed, so nothing changes
  for them.
- **Missing columns:**
  - a missing rename source is warned about and skipped;
  - an add whose key already exists is warned about and skipped;
  - a remove pattern that matches nothing is only logged at debug level,
    because older files have fewer columns.
- **No content checks:** no all-zero or duplicate-column dropping, and no
  Icoil guessing. The `t` dedupe still runs, via
  `cleanupData(drop_redundant_columns=False)`. The default `True` keeps
  `prepareData` behaving exactly as now.
- **v1 builder** (to_duckdb): assembly → its housing row →
  `_derive_housing_config_dict` → `HousingConfig.from_dict`. From that it
  emits:
  - `add`: `pupitre_formula_map` plus the voltage sums;
  - `rename`: `get_pupitre_rename_map()`;
  - `remove`: `["Icoil\d+"]`.

  It returns a plain dict, ready for JSON. to_duckdb already imports
  python_magnetrun; the reverse import never happens.

## Assembly resolution (added 2026-10-07)

Reading a raw pupitre file (`load_magnetdata`) does not need the assembly;
**applying the spec does**, since the builder produces one spec per assembly
(voltage sums in v2, `IS` in step 1b, M5's `IB1`/`IB2`). The assembly is
resolved from the database before the file is opened:

1. **Registered file:** file → `experiments.file` → `assembly_name`
   (experiments are created per assembly from the assembly JSON's records,
   `crud.insert_experiments`).
2. **File not in `experiments`** (new file, overview-linked file): housing
   and start time from the filename (`parse_filename_timestamp`) → the
   assembly whose `[commissioned_at, decommissioned_at)` window covers it
   (the assembly overlap guard ensures at most one).
3. **No assembly covers it** (e.g. data issue #9 in the digital twin plan):
   open question #28 there — housing-only spec (v1 content, no
   assembly-specific entries) with a warning (recommended), or refuse the
   ETL.

The pupitre header (line 1, `MagnetCode`) is only a cross-check, never used
to resolve the assembly (`MagnetCode` is unreliable as a key).

Once step E of the cross-plan order exists, the ETL can also read
`experiments.file_integrity` (`ok` / `truncated` / `unreadable`) to skip or
flag broken files.

## Steps

1. Write the python_magnetrun tests first: spec round-trip and validation,
   rename→add order, pattern removal, zero columns kept, `t` present, one
   polars case → verify: they fail.
2. Add the `drop_redundant_columns` keyword in pandas and polars → verify: the
   existing `test_runetl.py`, `test_magnetdata.py` and
   `test_magnetdata_polars.py` still pass.
3. Implement `PupitreEtlSpec` and `prepare_pupitre` with NumPy docstrings →
   verify: the step 1 tests pass.
4. Write `to_duckdb/tests/test_etl_spec.py` (in-memory DB loaded with the
   bundled M8/M9/M10 configs, as in `test_housing_config_db.py`), then
   `etl_spec.py` → verify: the tests pass, and the spec for M9 contains `IH`,
   `IB`, `UH`, `UB`, `Flow1→FlowH` and `Icoil\d+`.
5. Run a comparison script (in the scratchpad, not committed) on the sample
   M9 and M10 files: old `prepareData` versus the new spec path → verify:
   identical values on shared columns. The only expected difference is the
   extra all-zero and duplicate columns now kept, to be listed for review.
6. Update the README ETL section → verify: its example runs.

## Assumptions and open questions

- **v1 is housing-driven only.** The assembly is used just to find its
  housing. Real assembly-driven content (number of `Ucoil` channels per
  insert, M5's two Bitters) needs a rule for mapping assembly magnets and
  parts to `Ucoil`/`Icoil`/`Flow` channels. That rule is the L2 section
  mapping of [PLAN_digital_twin_schema.md](PLAN_digital_twin_schema.md)
  (`v_config_sections`, its phase 2): v2 of the builder uses it. M5 also
  stays on hold, per its notes.
- **Voltage sums are no longer filtered by file content.** If a `Ucoil` in the
  formula is missing from a file, `UH` is skipped with a warning instead of
  being a partial sum. This is arguably more correct, but it is a behaviour
  change.
- **No caller is switched yet** (`load_mrun`, the dashboards,
  `stress_map.py`). That's a later step, after reviewing the step 5
  comparison.

## Follow-ups (not in this plan; each needs its own plan and approval)

- **Switch Pupitre callers to the spec path** (step 2a of the cross-plan
  order).
- **v2 builder driven by the assembly** through `v_config_sections` (step 3;
  needs digital twin phase 2). Voltage sums use only the slots present under
  the digital twin's L2 section mapping rules (2026-10-08): pair layout with
  `Ucoil7` = outermost pair (e.g. `Ucoil2–7` for a 12-helix insert),
  per-helix layout detected from probes or non-null `Ucoil8–14`, Bitters on
  `Ucoil15–16`, null channels (unplugged or absent) left out.
- **M5 entries** (step 4; blocked on the formal wiring confirmation).
- **Supra current `IS` for M8** (step 1b, after v1; outline agreed
  2026-10-07, resolves digital twin open question #15). `IS` becomes a
  column of the Pupitre data after the ETL:
  - **new `external` entry type** in `PupitreEtlSpec`: reader, date, FEPC
    system, channel, resampling, alignment, field definition, e.g.

    ```json
    "external": {
      "IS": {
        "reader": "hybrid", "date": "2024-03-15", "fepc_system": "FEPC-LNCMI",
        "channel": "kHz/FEPC-LNCMI/I_BOB",
        "resample": "1s", "align": {"method": "nearest", "tolerance_s": 0.5},
        "symbol": "I_S", "unit": "ampere", "label": "Supra current",
        "description": "Derived from Hybrid I_BOB during ETL"
      }
    }
    ```
  - **builder (to_duckdb):** emits the `IS` entry only when the housing is
    M8, the assembly has a `supra` part, and `overview_records` links a
    hybrid source; the date comes from `sources_hybrid_kHz`;
  - **`prepare_pupitre` (python_magnetrun):** loads the channel with
    `HybridRun.fromdir` (base directory: python_magnetrun's
    `HYBRID_DATA_DIR` by default, optional override argument), downsamples
    with `resample("1s").mean()`, aligns with `merge_asof` (`nearest`,
    0.5 s) onto the Pupitre `timestamp` column, adds `IS` [A]; `NaN`
    outside the tolerance, no column when there is no entry;
  - **code moved** from the dashboard (`load_hybrid_supra_current`) to
    python_magnetrun, fixing its hours range, which is empty for a run that
    crosses midnight (`range(start.hour, end.hour + 1)`);
  - removing the dashboard's own `hybrid:I_BOB` path is a later step;
  - **check first** (digital twin open question #27): whether the Hybrid and
    pupitre clocks need a lag correction before the 0.5 s `merge_asof`
    alignment — pupitre vs pigbrother clocks do differ
    ([PLAN_signature_regime_robustness.md](apps/dashboards/magnetdb/PLAN_signature_regime_robustness.md)).
