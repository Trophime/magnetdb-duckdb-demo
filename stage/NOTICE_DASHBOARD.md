# Interactive Dashboard User Guide (LNCMI Magnets)

This guide explains how to launch and use the M1 CSMI interactive dashboard to explore resistive magnet data (Pupitre and PigBrother) stored in DuckDB.

---

## 1. Prerequisites & Launch

**Setup:**
Ensure the required database (`magnetdb.duckdb`) is located in the `to_duckdb/` root directory. If your database lives elsewhere, set the `MAGNETDB_DB_PATH` environment variable to its path before launching; `MAGNETDB_DB_DIR` controls where the in-app **Database** dropdown looks for other `.duckdb` files to switch between (defaults to the same directory as `MAGNETDB_DB_PATH`).

**Startup:**
1. Open a terminal and navigate to the dashboard folder:
   ```bash
   cd apps/dashboards/magnetdb/src
   ```

2. Run the Dash server:
   ```bash
   python magnetdb_app.py
   ```


3. Open your web browser at: **localhost:8050**

---

## 2. Application Architecture

The dashboard has seven pages, accessible via the top navigation menu:

* **Assembly stats** (`/`) — fleet-wide overview of experiments and energy usage across all sites. Default landing page.
* **Magnet stats** (`/magnet_stats`) — energy and field-on statistics broken down per mounted magnet.
* **Part stats** (`/part_stats`) — operating time and hoop-stress overview per magnet part (helix, bitter, supra).
* **File viewer** (`/home`) — deep, fluid exploration of a single data file.
* **Multi-file comparison** (`/comparison`) — overlay and compare physical behaviors (e.g., current, voltage) across multiple files, with automatic time synchronization.
* **Housing Summary** (`/summary`) — auto-loads every file linked to a chosen Pupitre run for a housing, side by side.
* **Metrics** (`/metrics`) — placeholder page, currently under construction and not yet functional.

A **Database** dropdown at the top of every page lets you switch between DuckDB files discovered in the configured database directory.

---

## 3. Workflow

### A. "Assembly stats" Page (`/`)

1. **Site filter (optional):** Narrow the summary, charts, and table to one site.
2. Review the summary counts (total sites, sites in operation, experiment count, stats computed) and the bar charts (Energy per Experiment, Energy per Site, Magnet Time per Site, Energy/Magnet Time per Housing per Year).
3. Use the sortable table to browse experiments. Click an **Experiment** entry to jump straight into the File viewer for that run, with the "Field" sensor pre-selected.

### B. "Magnet stats" Page (`/magnet_stats`)

Same layout as Assembly stats, pivoted per magnet instead of per site:

1. **Magnet filter (optional).**
2. Review the summary counts and the "Field ON Time per Magnet" chart.
3. Browse the table (adds a **Magnet** column).

> [!Note] Experiment links on this page currently point back to the Assembly stats page (`/`) rather than the File viewer — this is a known issue, not intended behavior. Use the equivalent link on the Assembly stats table to open a specific file.

### C. "Part stats" Page (`/part_stats`)

1. **Part filter (optional).**
2. Review the summary counts and the "Operating Time per Part" chart.
3. Browse the table, which includes a peak hoop-stress proxy and a **Hoop Stress Status** column (Computed / Not computed).

> [!Note] As on the Magnet stats page, Experiment links here point to `/` instead of the File viewer — known issue, not intended behavior.

### D. "File viewer" Page (`/home`)

Select options in the control panel from top to bottom:

1. **Site:** Select the experimental site (e.g., *M9*, *M10*).
2. **Table:** Choose the database table (e.g., *operationaldata*).
3. **File:** Select the specific data file to explore.
4. **X-Axis:** Define the abscissa (usually `t` or `timestamp`).
5. **Sensors (Y-Axis):** Expand categories and check the desired sensors.
6. **Downsampling:** Choose the reduction algorithm (e.g., *LTTB*, *M4*, *minmax*).

> [!Note] Downsampling is mandatory to maintain a fluid display and prevent browser crashes with large datasets.

This page can also be opened directly from an **Experiment** link on the Assembly stats table, which pre-fills the site and file.

### E. "Multi-file Comparison" Page (`/comparison`)

Align curves from different files, regardless of their architecture.

1. **Site:** Select the relevant site.
2. **File Selection:** Choose multiple files to compare (Pupitre and PigBrother files are paired by matching date).
3. **Group:** Choose the sensor group to overlay (*Courants_Alimentations* or *Tensions_Aimant*).
4. **X-Axis:** Set the reference abscissa.
5. **Downsampling:** Choose the reduction algorithm.

The **Time Synchronization** panel automatically detects and displays the time offset between each selected file and a reference file (an Overview/PigBrother file if one is selected, otherwise a Pupitre file), so overlaid curves line up even if the files weren't started at the same instant.

### F. "Housing Summary" Page (`/summary`)

Browse everything recorded for one measurement session at a glance, without hunting for each file separately.

1. **Housing:** Select the housing.
2. **Pupitre File:** Select a Pupitre run (enabled once a housing is chosen).

All files linked to that run (Overview/PigBrother, Archive, Default) load automatically as separate cards, each with its own sensor groups and graphs.

### G. "Metrics" Page (`/metrics`)

Not yet implemented — displays a placeholder message only.

---

## 4. Troubleshooting

* **Large TDMS Files:** Initial loading takes time. The object is then cached in RAM, making subsequent clicks instant.
* **Empty Graph:** If the graph disappears suddenly, verify that at least one sensor is checked and the X-Axis is properly defined.
* **Empty Assembly/Magnet/Part stats page:** If the summary, charts, and table are empty, the required stats table (`exp_run_scalars` or `exp_part_bin_stats`) is likely missing or empty for that database. Populate it by running, for each site:
  ```bash
  to_duckdb/venv-systempackages/bin/python3 to_duckdb/compute_exp_stats.py --db <path> --site <SITE_NAME>
  ```
* **Housing Summary shows a red/orange message:** A red "referenced in database, but physically missing" box means the file is recorded in the database but not found on disk. An orange "Unable to read data" message means the file exists but could not be parsed.
