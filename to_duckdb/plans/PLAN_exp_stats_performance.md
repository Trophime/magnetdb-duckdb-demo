# Plan — `compute_exp_stats.py` performance

Status: **awaiting approval** — drafted 2026-10-09.

## Goal

Make per-file ingestion in `compute_exp_stats.py` ~3× faster, with the same
rows written to the DB, and make each file's writes atomic (all-or-nothing).

## Profiling results (2026-10-09)

Reprocess of `M10_A190220_00` (30 files, 14 coil parts) on a scratch copy of
`magnetdb-2026-10-08.duckdb`: **27.4 s, ~0.9 s/file** (→ ~1.6 h for all
6 483 experiments).

| Phase | Time | Share |
|---|---|---|
| DuckDB inserts (3 397 single-row `INSERT OR REPLACE`) | 15.5 s | 57 % |
| `load_file` (python_magnetrun read + `to_pandas` + `_compute_dt`) | 6.0 s | 22 % |
| `compute_part_bin_stats` (420 calls) | 4.8 s | 18 % |
| `compute_assembly_bin_stats` + `compute_scalars` | 0.8 s | 3 % |

### Bottleneck 1 — row-at-a-time inserts

Each `con.execute` costs ~4.3 ms (PK + FK checks on `experiments`/`parts`
per statement). Benchmark, 3 000 rows into `exp_part_bin_stats`
(DuckDB 1.5.5):

| Strategy | Time |
|---|---|
| per-row autocommit (current) | 12.9 s |
| per-row in one transaction | 12.8 s |
| `executemany` | 13.1 s |
| one `INSERT OR REPLACE … SELECT * FROM df` | **0.05 s** |

A transaction alone does not help; one statement per table does.

### Bottleneck 2 — redundant bin work per part

`compute_part_bin_stats` re-runs `_assign_bins` for every part (identical
result), and `df[mask]` copies the full frame (100+ pupitre columns) per
bin × part: ~4 500 full-frame copies plus 4 500 masked `Series.__setitem__`
for this assembly.

### Bottleneck 3 — file loading (out of scope, see F2)

## Approach

1. Write tests first: golden-output tests for the current
   `compute_assembly_bin_stats` / `compute_part_bin_stats` on a synthetic
   DataFrame (several bins, an empty bin, inactive coil rows, missing
   `Ucoil`), plus an insert round-trip on in-memory DuckDB.
   → verify: new tests pass on the current code.
2. Rewrite the three `insert_*` functions as one
   `INSERT OR REPLACE INTO … SELECT … FROM df` each. In `ingest_assembly`,
   compute all rows for a file first, then write them + `mark_processed` +
   the status update inside one `BEGIN … COMMIT`, with `ROLLBACK` in the
   existing `except`. Add a test that a file failing mid-way leaves no rows.
   → verify: step 1 tests + new atomicity test pass.
3. Compute the bin index once per file and pass it to
   `compute_part_bin_stats` / `compute_assembly_bin_stats` (optional
   argument); replace `df[mask]` with numpy arrays of the needed columns
   only. Signatures and output unchanged.
   → verify: step 1 tests pass with identical rows.
4. Benchmark: rerun the phase timer on a scratch DB copy.
   → verify: well under 27.4 s (expected ~8–9 s).
5. Equivalence on real data: diff `exp_*` rows for `M10_A190220_00` between
   the scratch DB and the original.
   → verify: no differences (float tolerance).
6. Update this file with the outcome.

## Files affected

- `to_duckdb/tests/test_compute_stats.py` — edit
- `to_duckdb/compute_exp_stats.py` — edit
- `to_duckdb/PLAN_exp_stats_performance.md` — this file

## Assumptions (checked 2026-10-09)

- **No reader depends on insert order.** All readers of `exp_run_scalars`,
  `exp_assembly_bin_stats`, `exp_part_bin_stats` (dashboards
  `assembly_stats`/`part_stats`/`magnet_stats`/`housing_stats`,
  `magnetdb_analysis.py`, `apps/tutorials/query_cumstats.py`, demos,
  `stage/_field_stats.py`, marimo) aggregate or use explicit `ORDER BY`;
  `rowid` is only used on unrelated tables. `compute_exp_stats.py` is the
  sole writer.
- **No reader depends on partial writes.** Today a file failing mid-way
  leaves already-written rows (each statement autocommits) without
  `exp_stats_processed` / `STATS DONE`; readers join `exp_*` directly, so
  dashboards currently show these half-written experiments.
- **Behaviour change:** after step 2, a file failing mid-way writes nothing.

## Follow-ups

- **F1 — `compute_op_stats.py`:** same per-part `_assign_bins` /
  `df[mask]` pattern and per-row inserts (lines 329, 429). Apply the same
  fix once this plan lands.
- **F2 — file loading in python_magnetrun:** each file is opened ~5×
  (validate, 2 header parses, 1-row stub read, full read, truncation
  check); `Units()` re-parses `pupitre-defs.json` with pint per file
  (~60 ms; `load_units_from_json` calls uncached `load_defs` although
  `field_defs._cached_defs` exists); `to_pandas()` converts every column
  although only ~10–40 are used. Needs its own plan in the
  python_magnetrun repo.
- **F3 — stale rows on `--reprocess`:** `INSERT OR REPLACE` never deletes,
  so reprocessing with different `--bins`, or after a channel/part
  disappears, leaves old rows next to the new ones. Fix:
  `DELETE FROM exp_{run_scalars,assembly_bin_stats,part_bin_stats}
  WHERE experiment_id = ?` inside the per-file transaction. Same issue in
  `compute_op_stats.py`.
