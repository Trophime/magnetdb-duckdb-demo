# Cumulative statistics

The cumulative statistics are calculated by the notebook `import_housing_summary.ipynb`.
It imports the housing summary files into `magnetdb.duckdb` and 
computes additional quantities used by the statistics pipeline.

## Requirements

- An up-to-date `magnetdb.duckdb` database.
- Housing summary JSON files (`M9_summary-*.json`, `M10_summary-*.json`).
- Pupitre data corresponding to the imported experiments.

## Usage

- Copy the housing summary JSON into `Data for Stage/`.
- Open `import_housing_summary.ipynb`.
- Update the paths at the beginning of the notebook if necessary: `DATA_DIR`, `PUPITRE_ROOT`, `DB`.
- Open the notebook and run all cells.

## Output

The notebook:
- imports the housing summary files into `housing_summary` table
- links the imported records with the `experiments` table
- computes the following statistics:
    - `field_max`
    - `field_mean`
    - `field_time_on`
    - `field_signature`
    These values are then available for the cumulative statistics.
- imports `proposals.csv` into the `proposals` table
- links proposals to the `experiments` table


## Verification

To verify that the notebook completed successfully, execute:

```sql
SELECT COUNT(*) FROM housing_summary;
```

or, for more detailed inspection, view a few rows:
```sql
SELECT * FROM housing_summary LIMIT 10;
```


# Dashboard

A first dashboard prototype is available in  `dash_site_stats.py`.

Current functionality:
- loads experiment information directly from `magnetdb.duckdb`
- displays the energy consumed by each experiment
- displays the total energy per site
- provides a sortable table containing
    - experiment identifier
    - experiment date
    - site
    - energy
    - extracted heat
    - experiment duration
    - field-on duration
    - processing status 

The dashboard is currently read-only and intended as an initial visualisation of the statistics stored in the database.
