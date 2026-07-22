# Interactive Dashboard User Guide (LNCMI Magnets)

This guide explains how to launch and use the M1 CSMI interactive dashboard to explore resistive magnet data (Pupitre and PigBrother) stored in DuckDB.

---

## 1. Prerequisites & Launch

**Setup:** 
Ensure the required database (`magnetdb.duckdb`) is located in the `to_duckdb/` root directory.

**Startup:**
1. Open a terminal and navigate to the dashboard folder:
   ```bash
   cd stage/dashboard/src

```

2. Run the Dash server:
```bash
python magnetdb_app.py

```


3. Open your web browser at: **localhost**

---

## 2. Application Architecture

The dashboard features two main pages (accessible via the navigation menu):

* **Home (Single-file Analysis):** Deep and fluid exploration of a single data file.
* **Multi-file Comparison:** Overlay and compare physical behaviors (e.g., current, temperature) across multiple files.

---

## 3. Workflow

### A. "Home" Page

Select options in the control panel from top to bottom:

1. **Site:** Select the experimental site (e.g., *M9*, *M10*).
2. **Table:** Choose the database table (e.g., *operationaldata*).
3. **File:** Select the specific data file to explore.
4. **X-Axis:** Define the abscissa (usually `t` or `timestamp`).
5. **Sensors (Y-Axis):** Expand categories and check the desired sensors.
6. **Downsampling:** Choose the reduction algorithm (e.g., *LTTB*, *Decimation*, *Mean*).

> *Note: Downsampling is mandatory to maintain a fluid display and prevent browser crashes with large datasets.*

### B. "Multi-file Comparison" Page

Align curves from different files, regardless of their architecture.

1. **Site:** Select the relevant site.
2. **File Selection:** Choose multiple files from the dropdown menu.
3. **X-Axis:** Set the reference abscissa.
4. **Sensors:** Check the specific physical quantities to overlay.

---

## 4. Troubleshooting

* **Large TDMS Files:** Initial loading takes time. The object is then cached in RAM, making subsequent clicks instant.
* **Empty Graph:** If the graph disappears suddenly, verify that at least one sensor is checked and the X-Axis is properly defined.

