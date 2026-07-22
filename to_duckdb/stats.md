# Cumulative statistics

This notebook imports the housing summary files into `magnetdb.duckdb` and 
computes additional quantities used by the statistics pipeline.

## Usage

- Update `magnetdb.duckdb`.
- Place the housing summary JSON files in the expected directory.
- Open the notebook and run all cells.

## Output

The notebook updates the `housing_summary` table by computing the following statistics:

- `field_max`
- `field_mean`
- `field_time_on`
- `field_signature`
- `reference_signature`

These values are then available for the cumulative statistics.

## Verification

To verify that the notebook completed successfully, execute:

```sql
SELECT COUNT(*) FROM housing_summary;
```

or, for more detailed inspection, view a few rows:
```sql
SELECT * FROM housing_summary LIMIT 10;
```