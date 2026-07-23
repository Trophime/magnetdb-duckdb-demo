# Migrations

One-off scripts to migrate an existing `magnetdb.duckdb` file to a newer data
convention. Run from `to_duckdb/` with the project venv active:

```bash
cd to_duckdb
source venv-systempackages/bin/activate
python3 migrations/<script>.py --db magnetdb.duckdb [--dry-run]
```

Every script here is safe to run multiple times (idempotent) and supports
`--dry-run` to preview changes without writing anything.

| Script | Table | What it does |
|---|---|---|
| `migrate_experiments_file_relpath.py` | `experiments.file` | absolute path → bare filename |
| `migrate_operationaldata_file_relpath.py` | `operationaldata.file` | absolute path → path relative to `--records-base` |

---

## Migration 1 — `experiments.file` relative path

### Context

`experiments.file` previously stored the **absolute path** to the pupitre TXT
file (e.g. `/mnt/LNCMIG-Data/records/srv-data-install/M10/2025.04.30 - 13:06:03.txt`).

This makes the database non-portable: if the mount point changes, every path in
the table breaks.

The new convention stores **only the filename**
(e.g. `2025.04.30 - 13:06:03.txt`).  The full path is reconstructed at
runtime as:

```
records_base / srv_subdir / housing / filename
```

where `housing` is read from `sites.housing` for the experiment's site, and
`records_base` / `srv_subdir` default to the constants in `populate.py`
(`/mnt/LNCMIG-Data/records` and `srv-data-install`).

### What changed in the code

| File | Change |
|------|--------|
| `magnetdb.py` | `populate experiments` now stores `fpath.name` instead of `str(fpath)` |
| `compute_exp_stats.py` | Joins `sites` to get `housing`; reconstructs full path from `records_base / srv_subdir / housing / filename`; added `--records-base` / `--srv-subdir` CLI flags |
| `compute_hoop_stats.py` | Reconstructs `exp_file` from `pupitre_datadir / housing / filename` when the stored value is not absolute |
| `stress_map.py` | No change needed — `_expand_pupitre_pattern` already handles relative filenames |

Both `compute_exp_stats.py` and `compute_hoop_stats.py` accept absolute paths
unchanged (backward compatibility during and after migration).

### Run it

Run **once** against any database that was populated before this change.
The UPDATE is idempotent: rows that already contain only a filename (no `/`)
are not touched by the `WHERE` clause.

```bash
python3 migrations/migrate_experiments_file_relpath.py --db magnetdb.duckdb
```

### Verification

```sql
-- All values should now be bare filenames (no leading slash)
SELECT COUNT(*) AS still_absolute
FROM experiments
WHERE file LIKE '/%';
-- Expected: 0

-- Spot-check a few rows
SELECT id, site_name, file
FROM experiments
ORDER BY id
LIMIT 5;
```

---

## Migration 2 — `operationaldata.file` relative path

### Context

`operationaldata.file` previously stored the **absolute path** to the TDMS or
pupitre record file (e.g.
`/mnt/LNCMIG-Data/records/pbsurv/M10/Overview/250101-0000.tdms`), same
portability problem as Migration 1.

Unlike `experiments.file`, `operationaldata.file` has a `UNIQUE` constraint,
and TDMS filenames are timestamp-based per housing — two different housings
can plausibly produce an identical basename at an identical timestamp. So the
new convention stores the path **relative to `records_base`**, not a bare
filename:

```
pbsurv/M10/Overview/250101-0000.tdms
```

which keeps the value globally unique (housing + type-subdir are still part
of the string) while still dropping the machine-specific mount point. The
full path is reconstructed at runtime as `records_base / relpath` (see
`populate.resolve_operationaldata_path`).

### What changed in the code

| File | Change |
|------|--------|
| `populate.py` | `_insert_operationaldata` now stores the path relative to `records_base` instead of `str(fpath)`; added `resolve_operationaldata_path()` |
| `magnetdb.py` | `populate overview-records` resolves `operationaldata.file` through `resolve_operationaldata_path()` before opening the file; added `--records-base` |
| `compute_op_stats.py` | `ingest_site()` resolves `operationaldata.file` through `resolve_operationaldata_path()` instead of a naive `records_path / filename` join |

`resolve_operationaldata_path()` passes an already-absolute value through
unchanged, so both scripts also work against a database that hasn't been
migrated yet.

### Run it

Run **once** against any database that was populated before this change.
The UPDATE is idempotent: rows that already contain a relative path (no
leading `/`) are not touched by the `WHERE` clause. Rows whose absolute path
does not fall under `--records-base` are reported and left unchanged rather
than guessed at — resolve those manually.

```bash
python3 migrations/migrate_operationaldata_file_relpath.py --db magnetdb.duckdb \
    --records-base /mnt/LNCMIG-Data/records
```

### Verification

```sql
-- All values should now be relative paths (no leading slash)
SELECT COUNT(*) AS still_absolute
FROM operationaldata
WHERE file LIKE '/%';
-- Expected: 0

-- Spot-check a few rows
SELECT id, site_name, type, file
FROM operationaldata
ORDER BY id
LIMIT 5;
```
