# Plan — Phase 2: rename hoop-stress Parquet columns to part names

Status: pending approval, not started. Part of the
[hoop-stress history initiative](PLAN_hoop_stress_history.md) — see that
file for the overall status and links to the other phases. Depends on
nothing outstanding (Phase 1 is done); Phase 3
([PLAN_hoop_stress_part_history.md](PLAN_hoop_stress_part_history.md))
depends on this one landing first.

## Goal

`hoop-stress compute` writes per-experiment Parquet files with columns
named after the DB part they represent (e.g. `H12082401`), instead of the
slot names (`H1_fast`, `B2_fast`, …) used internally for computation.

## Files affected

- `to_duckdb/compute_hoop_stats.py` — edit

## Approach

1. In `compute_hoop_stress_history`, build a renamed copy of `df` (via
   `part_map`) right before `save_hoop_parquet`; leave the original `df`
   untouched for bin-stats/fatigue computation, which still relies on
   `H*_fast`/`B*_fast`/`Supra*_fast` naming.
2. Fix `_column_meta` to key off the *original* slot name (via `part_map`)
   instead of parsing the (now renamed) column name directly.

## Verification

1. Run `MPLBACKEND=Agg pytest to_duckdb/tests -k hoop` — confirm no
   regressions in bin-stats/fatigue values after the column rename (only
   names change, not numbers).
2. Run `hoop-stress compute <one site> --reprocess --db <scratch db>` →
   verify the Parquet schema has part-name columns with correct
   `unit`/`symbol` metadata (via `pyarrow.parquet.read_schema`).

## Assumptions & open questions

- Part names (e.g. `H24110501`) are safe to use as Parquet column names —
  no collision risk since `parts.name` is a primary key.
