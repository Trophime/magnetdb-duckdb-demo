# Migration — `experiments.file` relative path

## Context

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

---

## What changed in the code

| File | Change |
|------|--------|
| `magnetdb.py` | `populate experiments` now stores `fpath.name` instead of `str(fpath)` |
| `compute_exp_stats.py` | Joins `sites` to get `housing`; reconstructs full path from `records_base / srv_subdir / housing / filename`; added `--records-base` / `--srv-subdir` CLI flags |
| `compute_hoop_stats.py` | Reconstructs `exp_file` from `pupitre_datadir / housing / filename` when the stored value is not absolute |
| `stress_map.py` | No change needed — `_expand_pupitre_pattern` already handles relative filenames |

Both `compute_exp_stats.py` and `compute_hoop_stats.py` accept absolute paths
unchanged (backward compatibility during and after migration).

---

## Migration script

Run **once** against any database that was populated before this change.
The UPDATE is idempotent: rows that already contain only a filename (no `/`)
are not touched by the `WHERE` clause.

```bash
cd to_duckdb
source venv-systempackages/bin/activate
python3 migrate_experiments_file_relpath.py --db magnetdb.duckdb
```

Or as a one-liner:

```bash
python3 - <<'EOF'
import duckdb, sys
db = sys.argv[1] if len(sys.argv) > 1 else "magnetdb.duckdb"
con = duckdb.connect(db)
n = con.execute(
    "UPDATE experiments "
    "SET file = regexp_extract(file, '[^/]+$', 0) "
    "WHERE file LIKE '/%'"
).rowcount
print(f"Migrated {n} row(s).")
con.close()
EOF
```

---

## Verification

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
