# Student Note — Interactive Assembly Browser with Marimo

> `select_assembly.py` is a [Marimo](https://marimo.io) reactive notebook that lets you
> browse any assembly stored in the student DuckDB without writing SQL.
> Every widget is live-reactive: changing the DB path or the assembly dropdown
> immediately re-runs all downstream cells.

---

## Requirements

`marimo` must be installed in the virtualenv alongside `duckdb` and `pandas`:

```bash
cd to_duckdb/
source venv/bin/activate
pip install marimo          # if not already present
pip install duckdb pandas   # already in requirements.txt
```

---

## Running the notebook

### Read-only presentation mode

Launches the app in a browser tab; no code is visible to the student.

```bash
cd to_duckdb/
source venv/bin/activate
marimo run select_assembly.py
```

### Edit / development mode

Shows the source cells alongside the output; useful for extending the notebook.

```bash
marimo edit select_assembly.py
```

By default Marimo opens `http://localhost:2718` (or the next free port).

---

## What each section shows

| Section | Contents |
|---------|----------|
| **Database** | Text field — enter the path to any `.duckdb` file; defaults to `magnetdb.duckdb` next to the notebook |
| **Assembly selection** | Dropdown — lists every assembly found in `assemblies`; pick one to load its data |
| **Summary card** | Housing, status, commissioning / decommissioning dates, counts of magnets and experiments |
| **Magnets** | One row per magnet in `assembly_magnets`: type, status, axial/radial offsets, commissioning window |
| **Parts hierarchy** | Full join `assembly_magnets → magnets → magnet_parts → parts → materials`: coil index, part type, nuance, rpe (MPa) |
| **Experiments** | All rows from `experiments` for the selected assembly (filename, status); info callout if none are registered |

---

## Changing the database file

The text field at the top accepts any absolute or relative path.
If the file cannot be opened (wrong path, locked by another process, missing tables),
a red error callout is shown and the rest of the notebook is stopped cleanly.

Common paths used in this project:

| File | Contents |
|------|----------|
| `magnetdb.duckdb` | Full teacher database (may be locked if the CLI is running) |
| `student_magnetdb-2604.duckdb` | Student snapshot distributed with the 2026-04 data package |
| `student.duckdb` | Any database you created with `magnetdb.py db create` |

---

## Extending the notebook

Open the notebook in edit mode (`marimo edit select_assembly.py`) and add new cells
after the last one.  Each cell is a plain Python function; any variable it returns
becomes available to later cells.

### Example — plot experiment count per year

```python
@app.cell
def _(con, selected, pd, mo):
    import matplotlib.pyplot as plt

    df = con.execute("""
        SELECT
            YEAR(CAST(REGEXP_EXTRACT(file, r'(\d{4})', 1) AS DATE)) AS year,
            COUNT(*) AS n
        FROM experiments
        WHERE assembly_name = ?
        GROUP BY 1 ORDER BY 1
    """, [selected]).df()

    fig, ax = plt.subplots()
    ax.bar(df["year"].astype(str), df["n"])
    ax.set_xlabel("Year")
    ax.set_ylabel("Experiments")
    ax.set_title(f"Experiments per year — {selected}")
    return mo.as_html(fig)
```

### Example — show the coil-to-channel mapping

```python
@app.cell
def _(con, selected, mo):
    df = con.execute("""
        SELECT 'Icoil' || mp.coil_index AS channel,
               p.name AS part, p.type,
               mat.nuance,
               ROUND(mat.rpe / 1e6, 1) AS rpe_MPa
        FROM assembly_magnets sm
        JOIN magnets m       ON m.name         = sm.magnet_name
        JOIN magnet_parts mp ON mp.magnet_name = m.name
        JOIN parts p         ON p.name         = mp.part_name
        LEFT JOIN materials mat ON mat.name    = p.material_name
        WHERE sm.assembly_name = ?
          AND mp.coil_index IS NOT NULL
        ORDER BY mp.coil_index
    """, [selected]).df()
    return mo.vstack([mo.md("### Coil → channel mapping"), mo.ui.table(df, selection=None)])
```

---

## Relationship to other student scripts

| Script | When to use |
|--------|-------------|
| `select_assembly.py` | Interactive exploration — browse structure, no coding required |
| `tutorials/queries.py` | Static script — copy cells into Jupyter, adapt for analysis |
| `tutorials/statheures_demo.py` | Field-time histogram — loads TSV files, no interactive UI |
| `tutorials/query_cumstats.py` | Query pre-computed `op_*` statistics — requires `compute_op_stats.py` to have run first |
