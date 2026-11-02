# Plan: spec-driven ETL for Pupitre files

**Status (2026-10-07): awaiting approval.** Step 1 of the cross-plan order
in [PLAN_digital_twin_schema.md](PLAN_digital_twin_schema.md#cross-plan-order-blockers-and-approvals);
no blocker.
**Revised 2026-10-30:** spec per assembly split into a housing part and
per-magnet parts, DuckDB as master with a JSON export for standalone
python_magnetrun, `IH`/`IB` from Idcct only with a per-magnet `Icoil` check;
per-channel companion fields, electrical fields of a missing magnet type
dropped (hydraulics kept), empty-channel check.

Related:
- [NOTES_M5_bitters_wiring.md](NOTES_M5_bitters_wiring.md): M5 is the first
  case that needs assembly-driven ETL (§3.2 describes its spec entries).
- [PLAN_digital_twin_schema.md](PLAN_digital_twin_schema.md): its L2 section
  mapping (`v_config_sections`, phase 2) gives the assembly → `Ucoil` rule
  used by v2 of the builder; its L3 binding and commissioning readings rely
  on the channel names this ETL produces; its supra current `IS` (M8) is
  added by this ETL in step 1b (see Follow-ups); its step E file quality
  columns on `experiments` are extended here with `etl_checks`.
- [PLAN_duckdb_master_control_plane.md](PLAN_duckdb_master_control_plane.md):
  DuckDB is the master for magnet data, hence for the magnet parts of the
  spec.

## Goal

Add a second Pupitre ETL path that applies an explicit spec (remove / rename /
add, companions, plus current and channel checks). The spec is defined per assembly: a housing part
plus one part per magnet, since sensors are attached to magnets. DuckDB is
the master; the spec is exported to JSON so python_magnetrun can run it
standalone, with a fallback built from the housing config alone.
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
M9, M10) defines `IH`/`IB` as Idcct sums. Raw pupitre files contain no
`IH`/`IB`/`UH`/`UB`: they are always created by the ETL.

`Icoil<n>` is the pupitre's own reading of the current in channel *n*: the
current of the group the channel is wired to, exactly 0 when unplugged
(measured 2026-10-30, samples with current):

| File | Plugged channels | max \|Icoil − Idcct sum\| | Unplugged |
|---|---|---|---|
| M9 2026-05-15 (`M25032101`) | `Icoil2–7` ≈ Idcct1+Idcct2 (2.4 kA); `Icoil15–16` ≈ Idcct3+Idcct4 (1.06 kA) | 1.20 A; 1.07 A | `Icoil1`, `Icoil8–14` |
| M9 2023-02-08 | `Icoil1–7` ≈ Idcct1+Idcct2 (10 kA) | 1.60 A | `Icoil8–16` (Bitters off) |

So one `Icoil` per magnet is an independent reading of the Idcct sum. Picking
it blindly is fragile (`Icoil1` gives `IH` = 0 on the 2026 file); the current
code only gets it right because its all-zero drop removes `Icoil1` first.

The raw files have exactly four fields per channel, 16 of each: `Icoil n`,
`Ucoil n`, `DRcoil n`, `Tcal n` (16 × 4 + 24 others = 88 columns). On
unplugged channels all four are exactly 0; on plugged ones `Tcal` is non-zero
even without current (measured 2026-10-30):

| File (assembly) | Channels | `Ucoil` / `Icoil` / `DRcoil` / `Tcal` |
|---|---|---|
| M9 2026-05-15 (`M9_A260602_00`) | 1, 8–14 | all exactly 0 |
| M9 2023-02-08 | 8–14 | all exactly 0 |
| M10 2022-04-13 (`M10_A220223_00`, no current) | 1–4, 8–14 | all exactly 0 |
| | 5–7 | `Tcal` = 9.3, `Ucoil` ≈ 0.03 V, `Icoil` = `DRcoil` = 0 |

Today `prepareData` keeps or drops these fields by content (all-zero and
duplicate checks), so the same housing gives 35 to 52 columns depending on
the run (`load_mrun` on the three files above). Some assemblies lack a magnet
type: no insert in 10 M10 assemblies, `M5_A140101_00` and `M8_A211225_00`; no
Bitters in `M7_A140101_00` and `M8_A211225_00` (`Hybrid` only).

## Decisions

| Topic | Decision |
|---|---|
| Scope | Pupitre files only; TDMS and Hybrid keep using `prepareData` |
| Content-based checks (all-zero, duplicate columns, Icoil guessing) | Dropped from the new path; the explicit remove list replaces them. The current check below only warns, it never drops or picks a column |
| Remove list | Full-match regex patterns; plain names work as-is (e.g. `Icoil\d+`, `Ucoil1[5-6]`) |
| Spec granularity | One spec per assembly = housing part + one part per magnet of the assembly |
| Housing part | `remove`, `rename`, `add` (`IH`/`IB`), `defaults` (voltage sums used when no magnet part adds them), `companions` |
| Companions | `"companions": {"Ucoil": ["Icoil", "DRcoil", "Tcal"]}`: after `remove`, for every *n* whose `Ucoil n` is gone, its companions are removed too. Based on which columns exist, not on their values |
| Missing magnet type | No `insert` in the assembly: the builder emits no `IH` add, no `UH` default, no H current check, and removes `IH`, `UH`, the H group's `Ucoil n` (companions follow) and its Idcct sources (from the H formula). Hydraulics `FlowH`, `TinH`, `RpmH`, `HPH` are kept. Same for B with no `bitters`; both groups for a supras-only assembly. Role names are listed explicitly, never matched with `.*H$` |
| Empty-channel check | Before `remove`, every channel whose `Ucoil n` is about to be removed must have `Ucoil n`, `Icoil n`, `DRcoil n`, `Tcal n` exactly 0 |
| Magnet parts | `channels`, `remove`, `add`, `current` only; never `rename` |
| Merge | Flattened into one remove/rename/add list; an `add` key or a channel claimed twice (two magnet parts, or a magnet part and the housing `add`) raises an error. A magnet `add` key replaces the same key in housing `defaults` |
| Master | DuckDB: magnet parts in `pupitre_etl_magnet`, housing part from `housing_config`. JSON is an export |
| Builder location | `PupitreEtlSpec.from_housing(cfg)` in python_magnetrun (housing part only); to_duckdb adds the magnet parts from DuckDB. python_magnetdb (postgres) gets its own later |
| Fallback | A magnet with no row: housing `defaults` apply. No JSON file standalone: `from_housing` |
| Standalone | Explicit `--etl-spec FILE`, or `--etl-dir DIR` + assembly name → `DIR/<assembly>.pupitre-etl.json`; opt-in, `prepareData` stays the default |
| Currents | `IH`/`IB` = Idcct sums (housing `add`), unchanged for the code reading them (`thermal_pipeline`, `processing/stats.py`, `txt2csv`, `waterflow_pipeline`, `analysis/config.py`, Hybrid comparison). Each magnet part names one `Icoil` to compare with; it is removed afterwards with all other `Icoil` columns |
| M5 | `IB1` in one Bitter's magnet part, `IB2` in the other's |
| Tolerance | Fixed: `ICOIL_CHECK_ATOL = 5.0  # [A]` in `runetl.py` |
| Failed check (current or channel) | `logger.warning`, result returned by `prepare_pupitre` and stored on the experiment (`experiments.etl_checks`); nothing is kept or dropped because of it |
| Migration | New path alongside `prepareData`; callers are switched in a later step |

## Files affected

| File | Action |
|---|---|
| `python_magnetrun/python_magnetrun/runetl.py` | edit: add `PupitreEtlSpec`, `ICOIL_CHECK_ATOL`, `prepare_pupitre()`, `load_pupitre_etl_spec()`, `save_pupitre_etl_spec()` |
| `python_magnetrun/python_magnetrun/magnetdata_pandas.py` | edit: `cleanupData` gets `drop_redundant_columns: bool = True` |
| `python_magnetrun/python_magnetrun/magnetdata_polars.py` | edit: same keyword |
| `python_magnetrun/python_magnetrun/etl_cli.py` | create: `etl show FILE`, `etl create FILE --from-housing M9 [--assembly NAME]` (same pattern as `housing_config.register`) |
| `python_magnetrun/python_magnetrun/config_cli.py` | edit: register the `etl` domain |
| `python_magnetrun/python_magnetrun/utils/txt2csv.py` | edit: opt-in `--etl-spec FILE` / `--etl-dir DIR --assembly NAME` |
| `python_magnetrun/python_magnetrun/MagnetRun.py` | edit: `fromtxt(..., etl_spec: PupitreEtlSpec \| None = None)`; `None` keeps `prepareData` |
| `python_magnetrun/tests/test_runetl.py` | edit: tests for the spec, its JSON file and `prepare_pupitre` |
| `python_magnetrun/README.md` | edit: the ETL section documents a `prepare_pupitre` that doesn't exist; replace it with the real usage, including standalone |
| `to_duckdb/schema.py` | edit: `pupitre_etl_magnet` table; `experiments.etl_checks`, `experiments.etl_checked_at` |
| `to_duckdb/etl_spec.py` | create: `build_pupitre_etl_spec(con, assembly_name) -> dict`, `set_magnet_part(...)`, `export_pupitre_etl_spec(...)` |
| `to_duckdb/magnetdb.py` | edit: `etl set-magnet \| show \| export` commands |
| `to_duckdb/check_experiment_files.py` | edit: `--etl` fills `etl_checks` / `etl_checked_at` |
| `to_duckdb/tests/test_etl_spec.py` | create |
| `to_duckdb/tests/test_check_experiment_files.py` | edit: `--etl` case |

## Design

### JSON format

One file per assembly, `<assembly>.pupitre-etl.json`:

```json
{
  "kind": "pupitre-etl-spec",
  "version": 1,
  "assembly": "M9_A260602_00",
  "housing": {
    "name": "M9",
    "remove": ["Icoil\\d+"],
    "rename": {"Flow1": "FlowH", "Flow2": "FlowB", "...": "..."},
    "add": {
      "IH": {"formula": "IH = Idcct1 + Idcct2", "symbol": "I_H", "unit": "ampere", "label": "...", "description": "..."},
      "IB": {"formula": "IB = Idcct3 + Idcct4", "...": "..."}
    },
    "defaults": {
      "UH": {"formula": "UH = Ucoil1 + ... + Ucoil14", "...": "..."},
      "UB": {"formula": "UB = Ucoil15 + Ucoil16", "...": "..."}
    },
    "companions": {"Ucoil": ["Icoil", "DRcoil", "Tcal"]}
  },
  "magnets": {
    "M25032101": {
      "channels": ["Ucoil2", "Ucoil3", "Ucoil4", "Ucoil5", "Ucoil6", "Ucoil7"],
      "remove": ["Ucoil1", "Ucoil(8|9|1[0-4])"],
      "add": {"UH": {"formula": "UH = Ucoil2 + Ucoil3 + Ucoil4 + Ucoil5 + Ucoil6 + Ucoil7", "...": "..."}},
      "current": {"source": "Icoil2", "check": "IH"}
    },
    "M9Bitters-newBi08": {
      "channels": ["Ucoil15", "Ucoil16"],
      "add": {"UB": {"formula": "UB = Ucoil15 + Ucoil16", "...": "..."}},
      "current": {"source": "Icoil15", "check": "IB"}
    }
  }
}
```

- `kind` and `version` are checked by `from_dict`; anything else is refused.
- `channels` documents which pupitre channels carry the magnet's taps in this
  assembly; it is used for the "channel claimed twice" check.
- `assembly` and `magnets` may be empty (`from_housing` output).

### API (python_magnetrun)

```python
ICOIL_CHECK_ATOL = 5.0  # [A]

@dataclass(frozen=True)
class PupitreEtlSpec:
    assembly: str | None
    housing: dict              # name, remove, rename, add, defaults, companions
    magnets: dict[str, dict]   # magnet name -> channels, remove, add, current

    @property
    def remove(self) -> list[str]: ...        # housing + magnet parts
    @property
    def rename(self) -> dict[str, str]: ...   # housing only
    @property
    def add(self) -> dict[str, dict]: ...     # housing add + magnet add + unreplaced defaults
    @property
    def checks(self) -> list[dict]: ...       # one per magnet part with a `current`

    @classmethod
    def from_dict(cls, d: dict) -> "PupitreEtlSpec": ...   # validates kind, version, field_def keys, merge conflicts
    def to_dict(self) -> dict: ...
    @classmethod
    def from_housing(cls, cfg: HousingConfig, assembly: str | None = None) -> "PupitreEtlSpec": ...

def load_pupitre_etl_spec(path: str | Path) -> PupitreEtlSpec: ...
def save_pupitre_etl_spec(path: str | Path, spec: PupitreEtlSpec) -> None: ...

def prepare_pupitre(data: PandasMagnetData | PolarsMagnetData, spec: PupitreEtlSpec) -> list[dict]:
    # addTime → rename → add → checks (current, channel) → remove (patterns matched
    # on current keys) → companions → dedupe t
```

The structure is kept (not flattened) so `to_dict` round-trips; the
flattened lists are computed properties.

- **Rename before add**, so formulas can use renamed names. Today's formulas
  only use `Idcct*` and `Ucoil*`, which are never renamed, so nothing changes
  for them.
- **Checks before remove**, so the checked columns still exist. Every
  result has a `kind` and an `ok`; every result that is not `ok` is logged
  as a warning. `prepare_pupitre` returns the list.
  - **Current check** (one per magnet part with a `current`):
    `max |check − source|` over all rows (NaN ignored). Result
    `{"kind": "current", "magnet", "target", "source", "max_abs_diff", "ok"}`;
    `ok` is `False` above `ICOIL_CHECK_ATOL` and `None` when the source or
    target column is missing.
  - **Channel check** (one per channel whose `Ucoil n` the `remove` patterns
    are about to match): `Ucoil n` and its companions must be exactly 0
    (NaN ignored). Result
    `{"kind": "channel", "channel": n, "fields": {"Tcal5": 9.3, ...}, "ok"}`,
    `fields` listing the non-zero ones with their max |value|. No tolerance:
    unplugged channels are exactly 0 (see Context), and `Tcal` catches a
    plugged channel even in a run without current, where the current check
    cannot.
- **Remove, then companions:** `Icoil\d+` removes all `Icoil` columns (only
  `IH`/`IB` remain); then for every *n* whose `Ucoil n` is gone, `DRcoil n`
  and `Tcal n` are removed.
- **Missing columns:**
  - a missing rename source is warned about and skipped;
  - an add whose key already exists is warned about and skipped;
  - a remove pattern that matches nothing is only logged at debug level,
    because older files have fewer columns.
- **No content checks:** no all-zero or duplicate-column dropping, and no
  Icoil guessing. The `t` dedupe still runs, via
  `cleanupData(drop_redundant_columns=False)`. The default `True` keeps
  `prepareData` behaving exactly as now.
- **`from_housing(cfg)`** emits the housing part only:
  - `add`: `pupitre_formula_map`;
  - `defaults`: `get_pupitre_voltage_formulas()` over all
    `voltage_channels_gr1`/`gr2` (not filtered by file content);
  - `rename`: `get_pupitre_rename_map()`;
  - `remove`: `["Icoil\d+"]`;
  - `companions`: `{"Ucoil": ["Icoil", "DRcoil", "Tcal"]}`.

  With no magnet parts there is no current check, and no `Ucoil` is
  removed so no channel check runs: both groups are kept. `from_housing`
  does not know the assembly, so it never applies the missing-type rule;
  an exported JSON carries it.

### Storage (DuckDB)

```sql
CREATE TABLE IF NOT EXISTS pupitre_etl_magnet (
    assembly_name VARCHAR,
    magnet_name   VARCHAR,
    spec          JSON,          -- {"channels": [...], "remove": [...], "add": {...}, "current": {...}}
    updated_at    TIMESTAMP DEFAULT now(),
    PRIMARY KEY (assembly_name, magnet_name),
    FOREIGN KEY (assembly_name, magnet_name) REFERENCES assembly_magnets (assembly_name, magnet_name)
);

ALTER TABLE experiments ADD COLUMN IF NOT EXISTS etl_checks     JSON DEFAULT '[]';
ALTER TABLE experiments ADD COLUMN IF NOT EXISTS etl_checked_at TIMESTAMP;
```

- The composite foreign key makes a magnet part for a magnet outside the
  assembly impossible: no drift check against the assembly is needed.
- The housing part is not stored again: `build_pupitre_etl_spec` reads the
  assembly's `housing_config` row → `_derive_housing_config_dict` →
  `HousingConfig.from_dict` → `PupitreEtlSpec.from_housing`, then applies
  the missing-type rule, then adds the `pupitre_etl_magnet` rows.
- **Missing-type rule:** the assembly's magnet types come from
  `magnets.type` (`insert` / `bitters` / `supras`). The H group is the one
  whose `reference_grX_current` is `IH` (GR1 in M7/M9, GR2 in M8/M10), the
  B group the one with `IB`. With no `insert`, the builder drops from the
  housing part the `IH` add and the `UH` default, and appends to `remove`:
  `IH`, `UH`, the group's `voltage_channels_grX`, and the `Idcct` names
  read from the `IH` formula. `FlowH`, `TinH`, `RpmH`, `HPH` stay. Same for
  B with no `bitters`. The removed channels get the channel check and their
  companions are removed. Example, M10 Bitters-only: removes `IH`, `UH`,
  `Ucoil1–14`, `Idcct3`, `Idcct4` (+ `DRcoil`/`Tcal` 1–14).
- `build_pupitre_etl_spec` returns a plain dict, ready for JSON; it
  goes through `PupitreEtlSpec.from_dict`, so merge conflicts are caught
  when building. to_duckdb already imports python_magnetrun; the reverse
  import never happens.
- `etl_checks` holds the list returned by `prepare_pupitre` (current and
  channel results). It is kept apart from step E's `file_checks`: editing a
  magnet part must trigger a recheck, not of file integrity.
- CLI (`magnetdb.py`):
  - `etl set-magnet ASSEMBLY MAGNET PART.json` validates through
    `from_dict` and upserts the row;
  - `etl show ASSEMBLY` prints the assembled spec;
  - `etl export ASSEMBLY [-o FILE]` writes `<assembly>.pupitre-etl.json`.
- `check_experiment_files.py --etl` builds the spec of each experiment's
  assembly, runs `prepare_pupitre` on the file and stores the results in
  `etl_checks` / `etl_checked_at`. `--recheck` and `--assembly` work as
  today; after editing a magnet part, run
  `--etl --recheck --assembly <name>`.

## Assembly resolution (added 2026-10-07)

Reading a raw pupitre file (`load_magnetdata`) does not need the assembly;
**applying the spec does**, since the spec is per assembly (magnet parts,
`IS` in step 1b, M5's `IB1`/`IB2`). The assembly is resolved from the
database before the file is opened:

1. **Registered file:** file → `experiments.file` → `assembly_name`
   (experiments are created per assembly from the assembly JSON's records,
   `crud.insert_experiments`).
2. **File not in `experiments`** (new file, overview-linked file): housing
   and start time from the filename (`parse_filename_timestamp`) → the
   assembly whose `[commissioned_at, decommissioned_at)` window covers it
   (the assembly overlap guard ensures at most one).
3. **No assembly covers it** (e.g. data issue #9 in the digital twin plan):
   open question #28 there — housing-only spec (`from_housing`, no
   magnet parts) with a warning (recommended), or refuse the ETL.

Standalone python_magnetrun does not resolve anything: the caller gives the
spec file, or the directory and the assembly name.

The pupitre header (line 1, `MagnetCode`) is only a cross-check, never used
to resolve the assembly (`MagnetCode` is unreliable as a key).

Once step E of the cross-plan order exists, the ETL can also read
`experiments.file_integrity` (`ok` / `truncated` / `unreadable`) to skip or
flag broken files.

## Steps

1. Write the python_magnetrun tests first → verify: they fail.
   - spec: `to_dict`/`from_dict` round-trip, wrong `kind` refused, merge
     conflict (two magnet parts adding `UH`) raises, a magnet `add` replaces
     the housing default;
   - JSON file: `save` then `load` gives the same spec;
   - `from_housing`: M9 and M10 give different renames (`Flow1→FlowH` vs
     `Flow1→FlowB`) and no magnet parts;
   - `prepare_pupitre`: rename→add order, pattern removal, zero columns
     kept, `t` present, no `Icoil` left;
   - current check: synthetic file with `Icoil1` = 0 and `Icoil2` = `IH`
     passes (`ok: True`), a 7 A offset fails (`ok: False`, warning logged),
     a missing source gives `ok: None`;
   - companions: removing `Ucoil1` drops `DRcoil1`/`Tcal1`; `DRcoil2`/`Tcal2`
     stay with `Ucoil2`;
   - channel check: a removed channel with all four fields at 0 passes; one
     with `Tcal5` = 9.3 and no current fails (`kind: "channel"`, `fields`
     lists `Tcal5`);
   - one polars case.
2. Add the `drop_redundant_columns` keyword in pandas and polars → verify: the
   existing `test_runetl.py`, `test_magnetdata.py` and
   `test_magnetdata_polars.py` still pass.
3. Implement `PupitreEtlSpec`, `from_housing`, `load`/`save` and
   `prepare_pupitre` with NumPy docstrings → verify: the step 1 tests pass.
4. Add `etl_cli.py`, register it, and the opt-in `--etl-spec` / `--etl-dir`
   in `txt2csv` and `etl_spec=` in `MagnetRun.fromtxt` → verify:
   `etl create /tmp/x.json --from-housing M9` then `etl show` prints it;
   `txt2csv --etl-spec` runs on a synthetic file; existing `txt2csv` and
   `MagnetRun` tests still pass.
5. Write `to_duckdb/tests/test_etl_spec.py` (in-memory DB loaded with the
   bundled M8/M9/M10 configs, as in `test_housing_config_db.py`), then the
   `schema.py` changes, `etl_spec.py` and the `etl` CLI → verify: the tests
   pass, and
   - the M9 spec without magnet rows contains `IH`, `IB`, `Flow1→FlowH`,
     `Icoil\d+` and the default `UH`/`UB`;
   - with a `M25032101` row, `UH` sums `Ucoil2–7` only and the `Icoil2`
     check is present;
   - inserting a part for a magnet not in the assembly is refused by the
     foreign key;
   - an M10 Bitters-only assembly: no `IH` add, `remove` holds `IH`, `UH`,
     `Ucoil1–14`, `Idcct3`, `Idcct4`; `FlowH`, `TinH`, `RpmH`, `HPH` are
     not removed;
   - a supras-only assembly (`M8_A211225_00`-like): both groups' electrical
     fields removed, all hydraulics kept;
   - the same magnet in an M9 and an M10 assembly: different renames, same
     magnet part;
   - `etl export` then `load_pupitre_etl_spec` gives the same spec.
6. Add `--etl` to `check_experiment_files.py` → verify: on an in-memory DB
   with a synthetic file, `etl_checks` holds one result per magnet part and
   `etl_checked_at` is set; without `--recheck` a second run skips it.
7. Run a comparison script (in the scratchpad, not committed) on real files
   from the records mount (the bundled `python_magnetrun/data` samples are
   Git LFS pointers): M9 2026-05-15 and 2023-02-08 and an M10 file with
   current, old `prepareData` versus the new spec path → verify: identical
   values on shared columns; the current checks pass (≈1.2 A and 1.6 A on
   the M9 files) and so do the channel checks for the removed channels.
   Expected differences, to be listed for review: all-zero and duplicate
   columns now kept, companions now removed with their `Ucoil`, and the
   electrical fields of a missing magnet type.
8. Update the README ETL section → verify: its examples run.

## Assumptions and open questions

- **v1 magnet parts are written by hand** (`etl set-magnet`), with explicit
  channel names. No row is seeded for existing assemblies; without rows the
  spec is the housing-only content. Generating magnet parts needs a rule for
  mapping assembly magnets and parts to `Ucoil`/`Icoil` channels: the L2
  section mapping of [PLAN_digital_twin_schema.md](PLAN_digital_twin_schema.md)
  (`v_config_sections`, its phase 2), used by v2 of the builder. M5 also
  stays on hold, per its notes.
- **Voltage sums are no longer filtered by file content.** If a `Ucoil` in the
  formula is missing from a file, `UH` is skipped with a warning instead of
  being a partial sum. This is arguably more correct, but it is a behaviour
  change; the fix is a magnet part with the right channels.
- **The current check covers all rows**, zero-current ones included (both
  sides are ≈ 0 there). The 5 A tolerance comes from the 1.07–1.6 A gaps
  measured above.
- **The channel check uses exact 0**, from three files (Context). If an
  unplugged channel turns out to carry small noise on other files, a
  tolerance is added then.
- **Missing magnet type keeps the hydraulics** (`Flow`, `Tin`, `Rpm`, `HP`
  of the missing group): the water circuit may still run.
- **DuckDB foreign keys don't cascade.** Removing an assembly–magnet link
  (e.g. [PLAN_part_delete.md](to_duckdb/PLAN_part_delete.md)) must delete its
  `pupitre_etl_magnet` rows first.
- **No caller is switched yet** (`load_mrun`, the dashboards,
  `stress_map.py`): the new path is opt-in. Making it the default is a later
  step, after reviewing the step 7 comparison.

## Follow-ups (not in this plan; each needs its own plan and approval)

- **Bug: `MagnetRun.fromtxt` ignores its ETL arguments** (found 2026-10-30).
  It accepts `keys_to_remove` / `keys_to_rename` / `keys_to_add` but calls
  `prepareData(data, housing)` without them
  ([MagnetRun.py:254](python_magnetrun/python_magnetrun/MagnetRun.py#L254)),
  so callers passing them silently get the default housing ETL. Fix: write a
  test first (a `keys_to_add` entry must appear in the result), then forward
  the three arguments. Independent of this plan; can be fixed before it.
- **Raw pupitre view in `file_viewer`:** a "Processed / Raw" switch (pupitre
  files only, Processed by default). Raw = `load_magnetdata` + `addTime()` +
  `Units()`, no `prepareData`, cached apart from `load_mrun_object`; the
  existing group menus work since `pupitre-defs.json` defines the raw names.
  In Raw mode, fields dropped by processing are marked in the sensor menus.
  Independent of this plan; useful to review its step 7 comparison and,
  later, failed `etl_checks`.
- **Switch Pupitre callers to the spec path** (step 2a of the cross-plan
  order): the spec path becomes the default.
- **Show `etl_checks` in the dashboards** (current and channel checks): an
  "ETL check" column (`⚠ IH Δ 7.3 A`, `⚠ ch5 Tcal5 9.3`) and an amber row
  (`#fff3cd`) in the assembly_stats
  Experiments table, a warning line in the `file_viewer` banner, failing
  pupitre sources marked in the overview-records banner. Reads from DuckDB
  only.
- **v2 builder driven by the assembly** through `v_config_sections` (step 3;
  needs digital twin phase 2): generates the magnet parts. Voltage sums use
  only the slots present under the digital twin's L2 section mapping rules
  (2026-10-08): pair layout with `Ucoil7` = outermost pair (e.g. `Ucoil2–7`
  for a 12-helix insert), per-helix layout detected from probes or non-null
  `Ucoil8–14`, Bitters on `Ucoil15–16`, null channels (unplugged or absent)
  left out.
- **M5 entries** (step 4; blocked on the formal wiring confirmation):
  `IB1`/`IB2` in the two Bitters' magnet parts.
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
