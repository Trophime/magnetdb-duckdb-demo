# Plan: spec-driven ETL for Pupitre files

**Status (2026-11-05): steps 1–8 implemented 2026-11-03 with D1 = b
(parts A and B, branch `housing-config-versions`); the D1 revision of
2026-11-05 below is documented, its code change still to do.** Step 1 of the
cross-plan order in
[PLAN_digital_twin_schema.md](PLAN_digital_twin_schema.md#cross-plan-order-blockers-and-approvals).
**Revised 2026-10-30:** spec per assembly split into a housing part and
per-magnet parts, DuckDB as master with a JSON export for standalone
python_magnetrun, `IH`/`IB` from Idcct only with a per-magnet `Icoil` check;
per-channel companion fields, electrical fields of a missing magnet type
dropped (hydraulics kept), empty-channel check.
**Revised 2026-11-03:** one spec per **(assembly, housing version)**, built
on step H of the digital twin plan (time-versioned housing config): the
housing part comes from the housing-config version in force at the file
start, magnet parts are keyed to a housing version, and `prepare_pupitre`
checks that the spec's version matches the file.
**Revised 2026-11-05 (D1: b → a):** magnet parts get their own
`valid_from` / `valid_to`. The headers of `M9_A250401_00` show that the taps
of one magnet can change inside an assembly while the housing's GR channels
do not (`M25032101`, 2025-05-09: H1–H4 read together on `Ucoil2`), which a
key on the housing version cannot express. A spec now covers one **period**
in which the housing version and every magnet part are constant; it records
the period and is looked up by it. Housing versions stay for changes of the
housing's GR wiring (`M8-260305`). **Not yet implemented:** the code still
keys magnet parts by housing version.

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
add, companions, plus current and channel checks). The spec is defined per
assembly and housing-config version: a housing part (the wiring in force
at the file start) plus one part per magnet, since sensors are attached to
magnets. DuckDB is
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
the run (`load_mrun` on the three files above).

**The wiring changes over time, even inside one assembly** (step H of the
digital twin plan, done 2026-11-03). python_magnetrun `HousingConfig` holds
`versions` (bundled JSON, mirrored in DuckDB `housing_config_versions`);
`HousingConfig.at(t0)` gives the wiring in force at `t0`. Every housing has
a dated base version from its first commissioned assembly (`M5-140101`,
`M7-140101`, `M8-211225`, `M9-181109`, `M10-180220`); M8 then has
`M8-260305` (from 2026-03-05 17:21:09+01:00, inside `M8_A230919_00`):
M8Bitters read on a single tap `Ucoil14`, `Ucoil15–16` exactly 0, so
`UB = Ucoil14` and `UH = Ucoil1–13`. `prepareData` already resolves the
version at the data start, and `cleanupData` no longer drops a
`keys_to_add` column as a duplicate (`UB = Ucoil14` would otherwise
vanish); its all-zero and other duplicate drops are unchanged, hence the
`drop_redundant_columns` keyword below. Some assemblies lack a magnet
type: no insert in 10 M10 assemblies, `M5_A140101_00` and `M8_A211225_00`; no
Bitters in `M7_A140101_00` and `M8_A211225_00` (`Hybrid` only).

## Decisions

| Topic | Decision |
|---|---|
| Scope | Pupitre files only; TDMS and Hybrid keep using `prepareData` |
| Content-based checks (all-zero, duplicate columns, Icoil guessing) | Dropped from the new path; the explicit remove list replaces them. The current check below only warns, it never drops or picks a column |
| Remove list | Full-match regex patterns; plain names work as-is (e.g. `Icoil\d+`, `Ucoil1[5-6]`) |
| Spec granularity | One spec per **(assembly, period)** = housing part + one part per magnet of the assembly. A period is bounded by the assembly lifetime, the housing versions and the start / end of every magnet part: inside it nothing changes. An assembly spanning a wiring change (`M8_A230919_00`: `M8-211225`, `M8-260305`) or a magnet tap change (`M9_A250401_00`, 2025-05-09) has one spec per period. (2026-11-03: one spec per housing version) |
| Housing part | `remove`, `rename`, `add` (`IH`/`IB`), `defaults` (voltage sums used when no magnet part adds them), `companions`; built by `from_housing(cfg.at(t0))` and recorded with its version name (`housing.version`) |
| Magnet parts and wiring changes (D1, revised 2026-11-05: option a) | Each magnet part has its own validity window: `(assembly, magnet, valid_from)` + `valid_to` (`NULL` = open), windows of one magnet never overlap and lie inside the assembly lifetime. A time with no part for a magnet falls back to the housing `defaults` (e.g. `UB = Ucoil14` under `M8-260305`). Two time axes: **housing versions** for the housing's GR wiring, **part windows** for one magnet's taps. (2026-11-03, option b, implemented: keyed by housing version, which cannot express a tap change of one magnet) |
| Version and period checks | `prepare_pupitre` compares the spec's `housing.version` with the version in force at the data start (first `Date`/`Time`, Europe/Paris), and checks that the data start lies in the spec's period (`valid_from` ≤ start < `valid_to`). A mismatch (e.g. an old spec file on a 2026 M8 file) is logged and returned as a `{"kind": "housing_version", …}` or `{"kind": "spec_period", …}` result with `"ok": False` in `etl_checks`; nothing is kept or dropped because of it |
| Companions | `"companions": {"Ucoil": ["Icoil", "DRcoil", "Tcal"]}`: after `remove`, for every *n* whose `Ucoil n` is gone, its companions are removed too. Based on which columns exist, not on their values |
| Missing magnet type | No `insert` in the assembly: the builder emits no `IH` add, no `UH` default, no H current check, and removes `IH`, `UH`, the H group's `Ucoil n` (companions follow) and its Idcct sources (from the H formula). Hydraulics `FlowH`, `TinH`, `RpmH`, `HPH` are kept. Same for B with no `bitters`; both groups for a supras-only assembly. Role names are listed explicitly, never matched with `.*H$` |
| Empty-channel check | Before `remove`, every channel whose `Ucoil n` is about to be removed must have `Ucoil n`, `Icoil n`, `DRcoil n`, `Tcal n` exactly 0 |
| Magnet parts | `channels`, `remove`, `add`, `current` only; never `rename` |
| Merge | Flattened into one remove/rename/add list; an `add` key or a channel claimed twice (two magnet parts, or a magnet part and the housing `add`) raises an error. A magnet `add` key replaces the same key in housing `defaults` |
| Master | DuckDB: magnet parts in `pupitre_etl_magnet`, housing part from `housing_config` + `housing_config_versions`. JSON is an export |
| Builder location | `PupitreEtlSpec.from_housing(cfg)` in python_magnetrun (housing part only, `cfg` already resolved with `.at(t0)`); to_duckdb adds the magnet parts of that version from DuckDB. python_magnetdb (postgres) gets its own later |
| Fallback | A magnet with no row for the version: housing `defaults` apply. No JSON file standalone: `from_housing(get_housing_config(housing, at=t0))` |
| Standalone | Explicit `--etl-spec FILE`, or `--etl-dir DIR` + assembly name → the file `DIR/<assembly>.*.pupitre-etl.json` whose period contains the file start (error if none or several); opt-in, `prepareData` stays the default. (2026-11-03: `DIR/<assembly>.<version>.pupitre-etl.json` by housing version) |
| Currents | `IH`/`IB` = Idcct sums (housing `add`), unchanged for the code reading them (`thermal_pipeline`, `processing/stats.py`, `txt2csv`, `waterflow_pipeline`, `analysis/config.py`, Hybrid comparison). Each magnet part names one `Icoil` to compare with; it is removed afterwards with all other `Icoil` columns |
| M5 | `IB1` in one Bitter's magnet part, `IB2` in the other's |
| Tolerance | Fixed: `ICOIL_CHECK_ATOL = 5.0  # [A]` in `runetl.py` |
| Failed check (current or channel) | `logger.warning`, result returned by `prepare_pupitre` and stored on the experiment (`experiments.etl_checks`); nothing is kept or dropped because of it |
| Migration | New path alongside `prepareData`; callers are switched in a later step |

## Files affected

| File | Action |
|---|---|
| `python_magnetrun/python_magnetrun/runetl.py` | edit: add `PupitreEtlSpec`, `ICOIL_CHECK_ATOL`, `prepare_pupitre()` (with the housing-version check, reusing `_data_start`), `load_pupitre_etl_spec()`, `save_pupitre_etl_spec()` |
| `python_magnetrun/python_magnetrun/magnetdata_pandas.py` | edit: `cleanupData` gets `drop_redundant_columns: bool = True` |
| `python_magnetrun/python_magnetrun/magnetdata_polars.py` | edit: same keyword |
| `python_magnetrun/python_magnetrun/etl_cli.py` | create: `etl show FILE`, `etl create FILE --from-housing M9 [--assembly NAME]` (same pattern as `housing_config.register`) |
| `python_magnetrun/python_magnetrun/config_cli.py` | edit: register the `etl` domain |
| `python_magnetrun/python_magnetrun/utils/txt2csv.py` | edit: opt-in `--etl-spec FILE` / `--etl-dir DIR --assembly NAME` (file picked by the housing version at the file start) |
| `python_magnetrun/python_magnetrun/MagnetRun.py` | edit: `fromtxt(..., etl_spec: PupitreEtlSpec \| None = None)`; `None` keeps `prepareData` |
| `python_magnetrun/tests/test_runetl.py` | edit: tests for the spec, its JSON file and `prepare_pupitre` |
| `python_magnetrun/README.md` | edit: the ETL section documents a `prepare_pupitre` that doesn't exist; replace it with the real usage, including standalone |
| `to_duckdb/schema.py` | edit: `pupitre_etl_magnet` table (keyed by housing version); `experiments.etl_checks`, `experiments.etl_checked_at` |
| `to_duckdb/crud.py` | edit: factor the housing-config dict with its `versions` out of `export_housing_config_json` (`_housing_config_dict(con, name)`), shared with the spec builder |
| `to_duckdb/file_context.py` | create: `FileContext` dataclass and `resolve_file_context(con, path)` (file → experiment → assembly → housing → housing version at the file start), shared with the digital twin's header readers |
| `to_duckdb/tests/test_file_context.py` | create |
| `to_duckdb/etl_spec.py` | create: `build_pupitre_etl_spec(con, assembly_name, at) -> dict`, `set_magnet_part(...)`, `export_pupitre_etl_spec(...)` (one file per version overlapping the assembly) |
| `to_duckdb/magnetdb.py` | edit: `etl set-magnet \| show \| export` commands, with `--version V` / `--at TIME` |
| `to_duckdb/check_experiment_files.py` | edit: `--etl` fills `etl_checks` / `etl_checked_at` |
| `to_duckdb/tests/test_etl_spec.py` | create |
| `to_duckdb/tests/test_check_experiment_files.py` | edit: `--etl` case |

**D1 revision (2026-11-05), still to implement:**

| File | Change |
|---|---|
| `to_duckdb/schema.py` | `pupitre_etl_magnet`: `valid_from` / `valid_to` instead of `housing_version` |
| `to_duckdb/etl_spec.py` | `set_magnet_part(con, assembly, magnet, part, valid_from, valid_to=None)` (no overlap, inside the assembly lifetime); `build_pupitre_etl_spec` uses the parts valid at `at` and records the period; `export_pupitre_etl_spec` writes one file per period |
| `to_duckdb/magnetdb.py` | `etl set-magnet ASSEMBLY MAGNET PART.json --from TIME [--to TIME]` |
| `python_magnetrun/python_magnetrun/runetl.py` | `PupitreEtlSpec.valid_from` / `valid_to` (optional); `from_housing` records the housing version's window; `spec_period` check; `find_pupitre_etl_spec(etl_dir, assembly, at)` picks the file by period |
| `python_magnetrun/python_magnetrun/MagnetRun.py`, `utils/txt2csv.py` | follow the new `find_pupitre_etl_spec` signature |
| `python_magnetrun/README.md` | file naming, `--from` / `--to` |
| tests | `test_etl_spec.py`, `test_check_experiment_files.py`, `test_runetl.py`, `test_magnetrun.py`, `test_txt2csv.py` |

## Design

### JSON format

One file per assembly and period,
`<assembly>.<housing version>.<yymmdd-HHMM of the period start>.pupitre-etl.json`
(e.g. `M9_A260602_00.M9-181109.260602-0800.pupitre-etl.json`). The name is
for reading only: files are looked up by the period they record.
(2026-11-03, implemented: `<assembly>.<housing version>.pupitre-etl.json`.)

```json
{
  "kind": "pupitre-etl-spec",
  "version": 1,
  "assembly": "M9_A260602_00",
  "valid_from": "2026-06-02T08:00:00+02:00",
  "valid_to": "2026-07-07T07:00:00+02:00",
  "housing": {
    "name": "M9",
    "version": "M9-181109",
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
  The top-level `version` is the spec format; `housing.version` is the
  housing-config version the housing part was built from (`""` for data
  older than the housing's first version, standalone only).
- `valid_from` / `valid_to` (ISO 8601 with a UTC offset; `valid_to` `null`
  = open) bound the period in which the spec applies; optional, so the
  format version stays 1. `from_housing` records the window of its housing
  version; specs exported from DuckDB record the period.
- M8 example: the `M8-260305` spec of `M8_A230919_00` has no M8Bitters
  part, so the housing default `UB = Ucoil14` applies; the `M8-211225` one
  gives `UB = Ucoil15 + Ucoil16`.
- Tap-change example: `M9_A250401_00` has two periods inside `M9-181109`,
  split on 2025-05-09 14:31, where the insert part changes (slots 1–7, then
  H1–H4 on `Ucoil2` and `Ucoil1` removed).
- `channels` documents which pupitre channels carry the magnet's taps in this
  assembly; it is used for the "channel claimed twice" check.
- `assembly` and `magnets` may be empty (`from_housing` output).

### API (python_magnetrun)

```python
ICOIL_CHECK_ATOL = 5.0  # [A]

@dataclass(frozen=True)
class PupitreEtlSpec:
    assembly: str | None
    housing: dict              # name, version, remove, rename, add, defaults, companions
    magnets: dict[str, dict]   # magnet name -> channels, remove, add, current
    valid_from: str | None = None   # period of the spec, ISO 8601 with offset (2026-11-05)
    valid_to: str | None = None     # None = open

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
        # cfg is already resolved: get_housing_config(housing, at=t0); housing.version = cfg.version;
        # valid_from / valid_to = the window of that housing version (2026-11-05)

def load_pupitre_etl_spec(path: str | Path) -> PupitreEtlSpec: ...
def save_pupitre_etl_spec(path: str | Path, spec: PupitreEtlSpec) -> None: ...
def pupitre_file_start(path: str | Path) -> datetime: ...   # first Date/Time row, Europe/Paris
def find_pupitre_etl_spec(etl_dir, assembly, at) -> Path: ...
    # 2026-11-05: the <assembly>.*.pupitre-etl.json whose period contains `at`
    # (error if none or several); implemented 2026-11-03 as
    # find_pupitre_etl_spec(etl_dir, assembly, housing, at) -> <assembly>.<version>.pupitre-etl.json

def prepare_pupitre(data: PandasMagnetData | PolarsMagnetData, spec: PupitreEtlSpec) -> list[dict]:
    # version and period checks → addTime → rename → add → checks (current, channel)
    # → remove (patterns matched on current keys) → companions → dedupe t
```

The structure is kept (not flattened) so `to_dict` round-trips; the
flattened lists are computed properties.

- **Rename before add**, so formulas can use renamed names. Today's formulas
  only use `Idcct*` and `Ucoil*`, which are never renamed, so nothing changes
  for them.
- **Version check first:** the housing version in force at the data start
  (`HousingConfig.at`, first `Date`/`Time` read as Europe/Paris time) is
  compared with `housing.version`. Result
  `{"kind": "housing_version", "spec": "M8-211225", "data": "M8-260305", "ok"}`.
  The spec is still applied; the result only flags it.
- **Period check** (2026-11-05), when the spec records a period: the data
  start must lie in `[valid_from, valid_to)`. Result
  `{"kind": "spec_period", "valid_from", "valid_to", "data_start", "ok"}`.
  It catches a spec of the right housing version but the wrong magnet-part
  period (e.g. `M9_A250401_00` before / after 2025-05-09).
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
- **`from_housing(cfg)`** emits the housing part only, from a config
  already resolved at the file start (`cfg.at(t0)`):
  - `version`: `cfg.version`;
  - `valid_from` / `valid_to`: the window of that housing version (from
    `cfg.versions`), 2026-11-05;
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
-- D1 = a (2026-11-05); implemented 2026-11-03 with housing_version instead
-- of valid_from / valid_to
CREATE TABLE IF NOT EXISTS pupitre_etl_magnet (
    assembly_name   VARCHAR,
    magnet_name     VARCHAR,
    valid_from      TIMESTAMPTZ NOT NULL,
    valid_to        TIMESTAMPTZ,  -- NULL = open
    spec            JSON,         -- {"channels": [...], "remove": [...], "add": {...}, "current": {...}}
    updated_at      TIMESTAMP DEFAULT now(),
    PRIMARY KEY (assembly_name, magnet_name, valid_from),
    FOREIGN KEY (assembly_name, magnet_name) REFERENCES assembly_magnets (assembly_name, magnet_name)
);

ALTER TABLE experiments ADD COLUMN IF NOT EXISTS etl_checks     JSON DEFAULT '[]';
ALTER TABLE experiments ADD COLUMN IF NOT EXISTS etl_checked_at TIMESTAMP;
```

- The composite foreign key makes a magnet part for a magnet outside the
  assembly impossible: no drift check against the assembly is needed.
- **Validity windows** (decision D1 = a, 2026-11-05): a magnet part applies
  in `[valid_from, valid_to)`. `set_magnet_part` refuses a window that
  overlaps another window of the same (assembly, magnet) — the same
  `valid_from` replaces the part — or that does not lie inside the
  assembly's `[commissioned_at, decommissioned_at)`. A tap change of one
  magnet is a new part from the date of the first file with the new taps;
  a change of the housing's GR wiring is still a housing version. (2026-11-03,
  implemented: one part per housing version.)
- The housing part is not stored again: `build_pupitre_etl_spec(con,
  assembly, at)` reads the assembly's housing config with its versions
  (`_housing_config_dict`, shared with `export_housing_config_json`) →
  `HousingConfig.from_dict(...).at(at)` → `PupitreEtlSpec.from_housing`,
  then applies the missing-type rule, then adds the `pupitre_etl_magnet`
  rows valid at `at`.
- **Period of a spec:** the largest interval around `at` in which nothing
  changes: start = the latest of the assembly start, the housing version
  start and every part boundary (`valid_from`, `valid_to`) ≤ `at`; end =
  the earliest of those > `at` (or the assembly end; open if none).
  `export_pupitre_etl_spec` writes one file per period of the assembly.
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
  - `etl set-magnet ASSEMBLY MAGNET PART.json --from TIME [--to TIME]`
    validates through `from_dict` and writes the part for that window
    (2026-11-03, implemented: `etl set-magnet ASSEMBLY MAGNET VERSION PART.json`);
  - `etl show ASSEMBLY [--version V | --at TIME]` prints the assembled spec
    (default: the one in force now, or at the assembly's end);
  - `etl export ASSEMBLY [--version V | --at TIME] [-o DIR]` writes the spec
    file(s); without an option, one file per period of the assembly
    (`--version V`: the periods inside that housing version).
- `check_experiment_files.py --etl` builds, for each experiment, the spec
  of its assembly at the file start, runs `prepare_pupitre` on the file and
  stores the results in `etl_checks` / `etl_checked_at`. `--recheck` and `--assembly` work as
  today; after editing a magnet part, run
  `--etl --recheck --assembly <name>`.

## Assembly resolution (added 2026-10-07)

Reading a raw pupitre file (`load_magnetdata`) does not need the assembly;
**applying the spec does**, since the spec is per assembly (magnet parts,
`IS` in step 1b, M5's `IB1`/`IB2`). The assembly is resolved from the
database before the file is opened. Implemented once, in
`to_duckdb/file_context.py`:
`resolve_file_context(con, path) -> FileContext(experiment_id, assembly,
housing, housing_version, t0)` (steps 1–3 below, then the housing
version), and reused by the digital twin's header readers (phase 2, same
resolution order, see its L2 "Pupitre header reader"):

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

Then the **housing version**: the file start (first `Date`/`Time`,
Europe/Paris; the filename timestamp before the file is read) →
`HousingConfig.at(t0)`. Every housing has a dated base version from its
first commissioned assembly, so every file linked to an assembly gets a
named version; files older than that (e.g. M8 2011–2021, M10 2011–2018)
get the base wiring with version `""`, and only through case 3.

Standalone python_magnetrun resolves only the housing version (from the
file start and its bundled configs): the caller gives the spec file, or the
directory and the assembly name (the file is then picked by the period it
records, 2026-11-05).

The pupitre header (line 1, `MagnetCode`) is only a cross-check, never used
to resolve the assembly (`MagnetCode` is unreliable as a key). During the
commissioning of a new magnet it may even be the previous assembly's
(`M9_A250121_00`: `M09052601` in its first 2 files), see the digital twin
plan, L2 "Header versions, commissioning and stale headers".

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
     `Flow1→FlowB`) and no magnet parts; `housing.version` is the resolved
     version (`M9-181109`); M8 resolved on 2026-03-06 gives the default
     `UB = Ucoil14` and a `UH` without `Ucoil14`, M8 on 2025-11-05 gives
     `UB = Ucoil15 + Ucoil16`;
   - version check: an `M8-211225` spec on a synthetic M8 file dated
     2026-03-06 returns `{"kind": "housing_version", "ok": False}` (warning
     logged) and the data is still processed; a matching spec returns
     `ok: True`;
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
   `etl create /tmp/x.json --from-housing M9 [--at TIME]` then `etl show`
   prints it with its `housing.version`; `txt2csv --etl-spec` runs on a
   synthetic file and `--etl-dir` picks `<assembly>.<version>` from the file
   start; existing `txt2csv` and `MagnetRun` tests still pass.
5. Write `to_duckdb/tests/test_file_context.py` and
   `to_duckdb/tests/test_etl_spec.py` (in-memory DB loaded with the
   bundled M8/M9/M10 configs and their versions, as in
   `test_housing_config_db.py`), then `file_context.py`, the `schema.py`
   changes, the shared `_housing_config_dict` in `crud.py` (the existing
   export tests still pass), `etl_spec.py` and the `etl` CLI → verify: the
   tests pass, and
   - `resolve_file_context`: a registered file gives its experiment and
     assembly; a file not in `experiments` resolves by the assembly time
     window; an M8 file starting 2026-03-06 gives `M8-260305` and one
     starting 2025-11-05 gives `M8-211225`; a file covered by no assembly
     gives `assembly = None` (open question #28);
   - the M9 spec without magnet rows contains `IH`, `IB`, `Flow1→FlowH`,
     `Icoil\d+`, the default `UH`/`UB` and `housing.version = "M9-181109"`;
   - with a `M25032101` row for `M9-181109`, `UH` sums `Ucoil2–7` only and
     the `Icoil2` check is present;
   - `M8_A230919_00`: the specs at 2026-03-05 15:56 and 17:22 are
     `M8-211225` (`UB = Ucoil15 + Ucoil16`) and `M8-260305` (`UB = Ucoil14`);
     an M8Bitters part written for `M8-211225` is absent from the
     `M8-260305` spec; `etl export` without an option writes both files;
   - inserting a part for a magnet not in the assembly is refused by the
     foreign key; a part for an unknown version is refused by the foreign
     key, one for another housing's version or a version not overlapping the
     assembly by `set_magnet_part`;
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
   Git LFS pointers): M9 2026-05-15 and 2023-02-08, an M10 file with
   current, and M8 `2026.10.30 - 09:10:03` and `2025.11.05 - 14:42:13`
   (both sides of `M8-260305`), old `prepareData` versus the new spec path
   → verify: identical values on shared columns (M8 2026: `UB` ≈ 357 V =
   `Ucoil14` on both paths); the current checks pass (≈1.2 A and 1.6 A on
   the M9 files), so do the channel checks for the removed channels and the
   housing-version checks.
   Expected differences, to be listed for review: all-zero and duplicate
   columns now kept, companions now removed with their `Ucoil`, and the
   electrical fields of a missing magnet type.
8. Update the README ETL section → verify: its examples run.
9. **D1 revision (2026-11-05, to implement; files in "D1 revision" under
   Files affected).** Tests first → verify: they fail, then pass, and both
   full suites pass:
   - a part change inside an assembly (`M9_B`-like test assembly) gives two
     periods, two specs and two exported files;
   - an overlapping window and a window outside the assembly are refused;
     the same `valid_from` replaces the part;
   - `find_pupitre_etl_spec` picks the file by period, and fails when none
     or several match;
   - `spec_period`: a spec of another period is flagged, the data still
     processed; `from_housing` records the housing version's window;
   - the step 7 comparison gives the same results with parts given windows.

## Assumptions and open questions

- **v1 magnet parts are written by hand** (`etl set-magnet`), with explicit
  channel names and a validity window (2026-11-05; one per housing version
  as implemented on 2026-11-03). No row is seeded for existing assemblies;
  without rows the spec is the housing-only content of the version.
- **Two time axes for the wiring** (D1 = a, 2026-11-05): housing versions for
  the housing's GR channels, part windows for one magnet's taps. The
  2026-11-03 assumption that a magnet's tap change is rare and can be
  declared as a housing version is withdrawn: `M25032101` changed taps
  inside `M9_A250401_00` on 2025-05-09 (H1–H4 on `Ucoil2`). The dates of
  such changes can be read from the pupitre headers (a new header version,
  see the digital twin plan). Generating magnet parts needs a rule for
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
- **No migration of `pupitre_etl_magnet` for the D1 revision:** no real
  database has the table yet (they predate step H) and the clean rebuild
  creates the new shape; only scratch databases built since part B have the
  old one (drop the empty table, `ensure_schema` recreates it).
- **DuckDB foreign keys don't cascade.** Removing an assembly–magnet link
  (e.g. [PLAN_part_delete.md](to_duckdb/PLAN_part_delete.md)) must delete its
  `pupitre_etl_magnet` rows first.
- **No caller is switched yet** (`load_mrun`, the dashboards,
  `stress_map.py`): the new path is opt-in. Making it the default is a later
  step, after reviewing the step 7 comparison.

## Follow-ups (not in this plan; each needs its own plan and approval)

- **Raw pupitre view in `file_viewer`:** a "Processed / Raw" switch (pupitre
  files only, Processed by default). Raw = `load_magnetdata` + `addTime()` +
  `Units()`, no `prepareData`, cached apart from `load_mrun_object`; the
  existing group menus work since `pupitre-defs.json` defines the raw names.
  In Raw mode, fields dropped by processing are marked in the sensor menus.
  Independent of this plan; useful to review its step 7 comparison and,
  later, failed `etl_checks`.
- **Switch Pupitre callers to the spec path** (step 2a of the cross-plan
  order): the spec path becomes the default.
- **Current check tolerance during transients** (found 2026-11-03, step 7):
  on M9 `2026.05.15 - 13:05:36` (`M9_A260505_00`), `IH − Icoil2` reaches
  13.2 A on 2 of 2844 rows, inside an 852 A/s current drop, while the
  steady-state gap is ≤ 0.14 A. The rule "max over all rows ≤
  `ICOIL_CHECK_ATOL` (5 A)" therefore flags fast transients. Options: ignore
  rows with a high |dI/dt|, or use a high percentile instead of the maximum.
- **Re-export the specs when a housing version is added** (e.g. M8 going
  back to `Ucoil15/16`): `etl export ASSEMBLY` for the affected assemblies,
  then `check_experiment_files.py --etl --recheck --assembly <name>`.
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
  `Ucoil8–14`, null channels (unplugged or absent) left out. The channels
  of each group come from the **housing-config version in force at the file
  start** (python_magnetrun `HousingConfig.at(t0)`, DuckDB
  `housing_config_versions`, done 2026-11-03), not from a fixed rule: the
  wiring can change inside one assembly (M8 Bitters on `Ucoil14` from
  2026-03-05 17:21:09, version `M8-260305`; base wiring `Ucoil15–16`).
  The magnet parts follow the digital twin's L2 header version valid at the
  file start (2026-11-05): each `valid` header version gives the parts'
  windows, so a magnet tap change (`M25032101`, 2025-05-09) is picked up
  from the headers; `stale` and `commissioning` header versions are not
  used to generate parts.
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
