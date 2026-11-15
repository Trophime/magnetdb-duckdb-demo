# Migration plan — `housing_config` foreign key in `sites`

## Context

`housing` in every Python script and JSON file is the **name of a
`housing_config` row** (e.g. `"M8"`, `"M9"`, `"M10"`).  It is **not** a
free-form label.  The goal is to enforce this at the database level by making
`sites.housing` a proper foreign key into `housing_config.name`.

Because the database is a demonstrator that can be rebuilt from scratch, we
can rewrite the schema instead of writing an ALTER TABLE migration.

---

## Step 1 — Reorder tables in `schema.py`

`housing_config` must be declared **before** `sites` so DuckDB can resolve the
foreign key at CREATE TABLE time.

Move the `housing_config` block from the end of `SCHEMA_SQL` to just before
the `sites` table.  Then add `REFERENCES housing_config(name)` to the
`housing` column of `sites`:

```sql
-- housing_config (new position, before sites)
CREATE TABLE IF NOT EXISTS housing_config (
    name            VARCHAR PRIMARY KEY,
    coil_assignment MAP(VARCHAR, VARCHAR),
    formats         VARCHAR[],
    extra_config    JSON
);

CREATE TABLE IF NOT EXISTS sites (
    name               VARCHAR PRIMARY KEY,
    description        VARCHAR,
    status             VARCHAR,
    housing            VARCHAR REFERENCES housing_config(name),  -- FK added
    commissioned_at    TIMESTAMP,
    decommissioned_at  TIMESTAMP
);
```

Remove the old `housing_config` block that was appended at the end of
`SCHEMA_SQL`.

---

## Step 2 — Seed `housing_config` before `sites`

Any code path that calls `ensure_schema` and then inserts sites must
populate `housing_config` first.

### 2a — `seeds_to_duckdb.py` (`_write_to_duckdb`)

Add a call to `insert_housing_config` for each known housing **before**
`insert_site` is called:

```python
from crud import insert_housing_config          # add to existing imports
from housing_defaults import HOUSING_SEED_DATA  # see Step 3

def _write_to_duckdb(output_path):
    con = duckdb.connect(str(output_path))
    ensure_schema(con)

    # ① housing configs — must come before sites (FK constraint)
    for row in HOUSING_SEED_DATA:
        insert_housing_config(con, row, verbose=False)

    for m in _materials.values(): ...           # unchanged
    for s in _sites.values():
        insert_site(con, s, verbose=False)      # FK now enforced
    ...
```

### 2b — `add_site.py` / `magnetdb.py site add`

Before inserting a site, check that its `housing` value exists in
`housing_config`.  If it does not, abort with a clear message:

```
Error: housing 'M10' not found in housing_config.
Load it first with:  python magnetdb.py housing add M10
```

---

## Step 3 — `housing_defaults.py` (new file)

Create a small helper module that holds the seed data for all known housings
so it can be imported by both `seeds_to_duckdb.py` and the new CLI command.

```python
# housing_defaults.py
from pathlib import Path
import json

_MAGNETRUN_PKG = Path(__file__).parent.parent / "python_magnetrun" / "python_magnetrun"

def _load(name):
    ref = json.loads((_MAGNETRUN_PKG / f"{name}-housing-config.json").read_text())
    suffix_to_coil = {"H": "Insert", "B": "Bitter"}
    s1 = ref["reference_gr1_current"][-1]
    s2 = ref["reference_gr2_current"][-1]
    ca = {suffix_to_coil[s1]: "GR1", suffix_to_coil[s2]: "GR2"}
    extra_keys = [
        "reference_gr1_hybrid", "reference_gr2_hybrid",
        "hybrid_formula_map", "hybrid_voltage_mask_map",
    ]
    extra = {k: ref[k] for k in extra_keys if k in ref and ref[k]} or None
    return {"name": name, "coil_assignment": ca, "formats": ref["formats"], "extra_config": extra}

HOUSING_SEED_DATA = [_load(n) for n in ("M8", "M9", "M10")]
```

---

## Step 4 — `crud.py` — guard in `insert_site`

Add a FK pre-check to give a clear error rather than a raw DuckDB constraint
violation:

```python
def insert_site(con, data: dict, verbose: bool = True) -> None:
    housing = data.get("housing")
    if housing:
        row = con.execute(
            "SELECT 1 FROM housing_config WHERE name = ?", [housing]
        ).fetchone()
        if row is None:
            raise ValueError(
                f"insert_site: housing '{housing}' not found in housing_config. "
                f"Insert it first with insert_housing_config()."
            )
    # ... rest of existing insert unchanged
```

---

## Step 5 — `magnetdb.py` — add `housing` subcommand

Extend the unified CLI with a new `housing` entity so students can manage
housing configs without touching Python:

```
python magnetdb.py housing list
python magnetdb.py housing add M9
python magnetdb.py housing view M9
python magnetdb.py housing export M9 [--output-dir .]
```

`housing add <name>` loads the row from `HOUSING_SEED_DATA` (Step 3).
`housing export <name>` calls `export_housing_config_json` (already in
`crud.py`).

---

## Step 6 — `crud.py` — `view_housing_configs` helper

Add a simple display helper consistent with `view_sites` / `view_magnets`:

```python
def view_housing_configs(con) -> None:
    rows = con.execute(
        "SELECT name, coil_assignment FROM housing_config ORDER BY name"
    ).fetchall()
    for name, ca in rows:
        print(f"  {name:<6}  {dict(ca)}")
```

---

## Step 7 — Update tests

Update `test_housing_config_db.py`:

- Verify the FK is enforced: inserting a site with an unknown housing must
  raise an error.
- Verify the happy path: after inserting a housing config, inserting a site
  with that housing succeeds.

```python
def test_fk_enforced_on_site_insert(con):
    with pytest.raises(Exception):   # duckdb ConstraintException or ValueError
        insert_site(con, {"name": "S1", "housing": "UNKNOWN"}, verbose=False)

def test_site_insert_after_housing(con):
    insert_housing_config(con, {"name": "M9", "coil_assignment": {"Insert": "GR1", "Bitter": "GR2"},
                                 "formats": ["pupitre"], "extra_config": None}, verbose=False)
    insert_site(con, {"name": "S1", "housing": "M9"}, verbose=False)
    row = con.execute("SELECT housing FROM sites WHERE name = 'S1'").fetchone()
    assert row[0] == "M9"
```

---

## Execution order

| # | File | Change |
|---|------|--------|
| 1 | `schema.py` | Move `housing_config` before `sites`; add `REFERENCES housing_config(name)` |
| 2 | `housing_defaults.py` | Create new file with `HOUSING_SEED_DATA` |
| 3 | `crud.py` | Guard in `insert_site`; add `view_housing_configs` |
| 4 | `seeds_to_duckdb.py` | Seed `housing_config` rows before sites |
| 5 | `magnetdb.py` | Add `housing` subcommand (`list`, `add`, `view`, `export`) |
| 6 | `test_housing_config_db.py` | Add FK and happy-path tests |

Steps 1–4 are required for correctness.  Steps 5–6 improve usability and
coverage.
