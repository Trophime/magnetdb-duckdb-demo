# Plan: spec-driven ETL for Pupitre files

**Status (2026-10-06): awaiting approval.**

Related: [NOTES_M5_bitters_wiring.md](NOTES_M5_bitters_wiring.md) (M5 is the
first case that needs assembly-driven ETL).

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
  parts to `Ucoil`/`Icoil`/`Flow` channels. Open: is there one? M5 also stays
  on hold, per its notes.
- **Voltage sums are no longer filtered by file content.** If a `Ucoil` in the
  formula is missing from a file, `UH` is skipped with a warning instead of
  being a partial sum. This is arguably more correct, but it is a behaviour
  change.
- **No caller is switched yet** (`load_mrun`, the dashboards,
  `stress_map.py`). That's a later step, after reviewing the step 5
  comparison.
