# Housing summary

This directory contains the scripts used to import and populate the 
`housing_summary` table in the DuckDB database. The workflow is split into 
several independent scripts so that changes to one step do not require 
rerunning the entire import process.


## Workflow

Run the scripts in the following order (or simply run `main.py`).

### 1. `_housing_summary.py`

Creates the `housing_summary` table from the yearly `*_summary-YYYY.json` 
files. This script:
- loads all housing summary JSON files;
- normalises the records into a single DataFrame;
- adds metadata columns (`housing`, `year`);
- creates the `housing_summary` table in DuckDB;
- performs basic data quality checks.

To run the script from `/workspaces/Stage/stage`:

```bash
python3 _housing_summary.py
```

### 2. `_link_experiments.py`

Links the housing records with the `experiments` table. This script:
- matches Pupitre filenames with experiment filenames;
- fills the `experiment_id` column in `housing_summary`;
- prints validation statistics.

To run the script from `/workspaces/Stage/stage`:

```bash
python3 _link_experiments.py
```

### 3. `_field_statistics.py`

Loads each Pupitre file and computes the following magnetic field statistics:
- maximum magnetic field;
- mean magnetic field;
- time above the field threshold;
- field signature.

These results are stored in `housing_summary`. Only records without an 
existing field signature are processed.

To run the script from `/workspaces/Stage/stage`:

```bash
python3 _field_statistics.py
```

### 4. `_proposals.py`

Imports proposal metadata and links proposals with housing records. This 
script:
- imports `proposals.csv`;
- creates the `proposals` table;
- links proposals to the `housing_summary` table using magnet site and 
  experiment timestamp extracted from the Pupitre filename.
- validates the linkage.

To run the script from `/workspaces/Stage/stage`:

```bash
python3 _proposals.py
```

### 5. `_mode_inferring.py`

Infers the operating mode (`NORMAL` or `ECO`) from the relation between the 
Helices current (`IH`) and the Bitter current (`IB`) in PigBrother overview 
files. The implementation follows the criterion provided:
- compute the slope of the `IH(IB)` relation near `IB = 0`;
- if the slope is between `0.66` and `1.5`, the mode is classified as `NORMAL`;
- if `IH = 0` or `IB = 0` -> `NORMAL`;
- if data is missing of insufficient -> `UNKNOWN`;
- otherwise -> `ECO`.

The script saves the scatter plot of `IH` versus `IB`, together with the 
fitted straight line used for mode inference, as `IH_vs_IB.png`.
The script also outputs:
- fitted current interval;
- fitted slope;
- shift;
- inferred operating mode;
- fitted equation.

To run the script from `/workspaces/Stage/stage`:

```bash
python3 _mode_inferring.py
```