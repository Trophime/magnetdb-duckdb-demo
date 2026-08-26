# Tutorials

Standalone scripts and notes for exploring the student MagnetDB DuckDB
without the full MagnetDB / Django infrastructure.

All scripts can be run from the `to_duckdb/` directory and default to
`magnetdb.duckdb` in that directory.

---

## Scripts

| File | Description |
|------|-------------|
| `queries.py` | Ready-to-run DuckDB query examples — copy cells into a Jupyter notebook as a starting point |
| `statheures_demo.py` | Field-time histogram demo: bin counts, annual comparisons, no `python_magnetrun` required |
| `stress_map.py` | Backward-compatibility shim — delegates to `magnetdb.py hoop-stress` |

---

## Hoop-stress analysis

The hoop-stress commands are now integrated into the main CLI.
Run them from `to_duckdb/`:

```bash
python magnetdb.py hoop-stress barchart <site> [--i-h A] [--i-b A] [--i-s A]
python magnetdb.py hoop-stress history  <site> [--pupitre FILE ...] [--use-mrun]
python magnetdb.py hoop-stress stats    <site> [--pupitre FILE ...] [--output CSV]
python magnetdb.py hoop-stress fatigue  <site> [--pupitre FILE ...] [--bins N]
```

`stress_map.py` in this directory accepts the same arguments for
backward compatibility. For a step-by-step explanation of how the analysis
chain works, see:

- [README_student_stress_map.md](README_student_stress_map.md)
- [student_statheures_note.md](student_statheures_note.md)

---

## Query examples

`queries.py` covers:

- Full site → magnet → part → material hierarchy
- Coil map for a specific magnet
- Experiment records for a site
- Helix material lookup
- Per-magnet channel list
- Shared-part detection
- Site history for a part

```bash
python tutorials/queries.py
```

---

## Field-time statistics demo

`statheures_demo.py` demonstrates the `statheures` workflow:

```bash
python tutorials/statheures_demo.py
python tutorials/statheures_demo.py --site M10_M19071101_13 --step 1.0
python tutorials/statheures_demo.py --site M10_M19071101_13 --year 2025
python tutorials/statheures_demo.py --site M10_M19071101_13 --compare 2025 2026
```
