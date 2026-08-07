# Follow-up prompt — orchestration test for `compute_hoop_stress_history()`

Status: not yet started (deferred as "item 11" from the `compute_hoop_stats.py`
test-coverage plan)

Paste the block below into a fresh session to pick up this work.

---

```
Add an orchestration-level test for compute_hoop_stress_history() in
to_duckdb/compute_hoop_stats.py.

## Context

to_duckdb/tests/test_compute_hoop_stats.py already exists and covers every
pure-logic/DB-helper function in compute_hoop_stats.py (bins_to_key,
_parse_bins, build_part_column_map, _column_meta, save_hoop_parquet,
_bin_series, _rainflow_stats, _compute_dt, _merge_configs, _get_experiments,
_check_processed/_mark_processed, _insert_bin_stats/_insert_fatigue). What's
still missing is a test of compute_hoop_stress_history() itself — the
function that orchestrates the whole `hoop-stress compute` CLI pipeline:
for each experiment at a site, it loads site config, computes hoop stress,
writes bin stats + rainflow fatigue to DuckDB, saves a Parquet file, and
marks the experiment processed (idempotency guard keyed on
(experiment_id, bin_config)).

Reuse the `con` fixture from tests/conftest.py (`:memory:` DuckDB +
ensure_schema) and the `hoop_site` / `hoop_site_with_experiments` fixtures
already defined in test_compute_hoop_stats.py (a site "HOOP_SITE" with
magnets/parts/experiments already wired up) — extend them if needed rather
than duplicating setup.

**Hard constraint: tests must be hermetic.** Never open magnetdb.duckdb or
any student_magnetdb*.duckdb file — in-memory DuckDB only, matching every
other file in tests/. Use pytest's tmp_path for any Parquet output
(parquet_dir argument) — never write into the real to_duckdb/hoop_parquet/
directory.

## What needs mocking

compute_hoop_stress_history() does `from stress_map import
(load_site_config_from_duckdb, load_magnettools,
prepare_geometry_directory, validate_fast_from_pupitre)` as a *local* import
inside the function body (see compute_hoop_stats.py around line 383) — so
monkeypatch these via `monkeypatch.setattr("stress_map.<name>", fake)`,
which the local import will pick up at call time. These four all require
real geometry YAML files / MagnetTools physics objects in production and
must not be exercised for real in a unit test:

- load_site_config_from_duckdb(site_name, db_path, con=...) → return a
  fake (housing_str, [(magnet_name, config_dict, geometry_data), ...])
  matching the shape consumed later by prepare_geometry_directory /
  load_magnettools / _merge_configs.
- prepare_geometry_directory(...) → no-op fake.
- load_magnettools(combined_config, tmpdir_path) → return any sentinel
  object; it's just passed through opaquely to validate_fast_from_pupitre.
- validate_fast_from_pupitre(data, exp_file, housing, magnet_type=...,
  use_mrun=..., site=...) → return a small synthetic pandas DataFrame with
  columns like "t" and "H1_fast" with known values, so the real
  _bin_series/_rainflow_stats logic (NOT mocked — let it run for real) run
  against known input and produce checkable output in
  hoop_stress_bin_stats/hoop_stress_fatigue.

## Behaviors to verify (each currently uncovered)

1. Already-processed experiments (same bin_config) are skipped unless
   reprocess=True — check results["skipped"] and that no duplicate DB rows
   appear.
2. dry_run=True writes nothing to the DB and creates no Parquet file.
3. An experiment previously processed under a *different* bin_config
   prints the "[WARN] ... previously processed with different bin(s)"
   message (assert via capsys) — and per current code
   (compute_hoop_stats.py:456-464), is NOT skipped for the new bin_key: it
   still computes and inserts rows under the new bin_config.
4. A full successful run populates hoop_stress_bin_stats, hoop_stress_fatigue,
   and hoop_stress_processed correctly for every experiment, with values
   matching what _bin_series/_rainflow_stats would produce for the known
   synthetic DataFrame.
5. If validate_fast_from_pupitre raises for one experiment, it's recorded
   in results["errors"] and processing continues to the next experiment
   (compute_hoop_stats.py:474-485) rather than aborting the whole run.
6. If the returned DataFrame has no H*/B*/Supra*_fast columns, the
   experiment is skipped with results["errors"] containing "no hoop
   columns" (compute_hoop_stats.py:488-493).

## Process

Follow this project's plan-first workflow (see CLAUDE.md): investigate
read-only first (re-read compute_hoop_stress_history in full, and check
whether anything has changed in compute_hoop_stats.py or
tests/test_compute_hoop_stats.py since this prompt was written), then
present a plan (Goal / Files affected / Approach / Verification /
Assumptions) and wait for explicit approval (approve/approved/go/
proceed/LGTM) before writing any test code.

Run `MPLBACKEND=Agg venv-systempackages/bin/python3 -m pytest
tests/test_compute_hoop_stats.py tests -k hoop -v` from to_duckdb/ to
verify (test_matplotlib.py hangs — always exclude/skip it).
```
