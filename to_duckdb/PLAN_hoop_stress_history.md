# Plan — hoop-stress part history, part-name columns, Bitter/Supra fatigue fix

Status: Phase 1 (compute pipeline correctness), Phase 2 (Parquet part-name
columns), and Phase 3 (`part-history` command) implemented, **all
uncommitted**. Phase 4 (per-part stats/history tests) written and passing
in isolation (2026-08-14) — see
[PLAN_hoop_stress_per_part_tests.md](PLAN_hoop_stress_per_part_tests.md) for
what's still blocked pending `magnettools` availability. Phase 5
(fatigue-additivity question) not yet started.

## Phase 1 — done (compute pipeline correctness)

Originally scoped as just the Bitter/Supra regex drop (item 5 below), this
grew substantially during implementation: real-data verification against
`test-magnetdb.duckdb` surfaced a chain of previously-hidden bugs, each only
reachable once the prior one was fixed. `hoop-stress compute` had never
actually succeeded against real data before this pass.

1. **`prepare_geometry_directory()` call fix** (`compute_hoop_stats.py`) — was
   called once per magnet with an invalid `geometry_data` kwarg the function
   doesn't accept, silently swallowed by a bare `except`. Fixed to a single
   per-site call with a `{"name":..., "magnets":[...]}` config dict, matching
   `_load_site()`'s already-working pattern.
2. **Stale docstrings corrected** (`stress_map.py`) — `prepare_geometry_directory`/
   `geometry_config_to_yaml` described a "geometry_data argument" source that
   was never implemented; both now document the real design: geometry is
   always rebuilt on the fly from `parts.geometry_data` (the only geometry
   ever persisted), never from a passed-in argument or `magnets.geometry_data`.
   `magnetdb.py magnet add --geometry`'s help text corrected to match (it
   stores an optional cache, not something the hoop-stress pipeline reads).
3. **`magnets.geometry_data` flagged in `ROADMAP.md`** as a future cleanup
   candidate (vestigial under the on-the-fly design) — not dropped, still has
   real writers (`magnet add --geometry`, `check --fix`).
4. **DuckDB connection-reuse fix** — `compute_hoop_stress_history` held its
   own read-write connection open while `prepare_geometry_directory` tried to
   open a second, read-only connection to the same file (DuckDB disallows
   this). Fixed by threading `con=` reuse through `prepare_geometry_directory`
   → `geometry_config_to_yaml` → `magnet_geometry_config_to_yaml`, the same
   pattern `load_site_config_from_duckdb` already used.
5. **`load_magnettools()` call fix** — was called with a malformed config
   (`_merge_configs()`, now deleted along with its tests) instead of the
   site-shaped `{"name":..., "magnets":[...]}` dict `msite_setup()` actually
   requires (`confdata['magnets']`, unconditionally). Fixed to reuse the same
   `site_config` built for step 1.
6. **Bitter multi-plate crash fix** — a Bitter part can decompose into
   multiple physical plates (`BMagnets`, via `mt.create_Bstack`), but
   `build_part_column_map` assumes one column per DB part, so extra plates
   fell back to using the raw column name as `part_name`, violating the
   `hoop_stress_bin_stats.part_name` foreign key. Fixed by grouping `BMagnets`
   per part via `mt.create_Bstack()` and collapsing to one representative
   value per part in `validate_fast_from_pupitre()` — no schema change,
   `part_name` stays the plain part name (`build_part_column_map` untouched).
7. **Representative-section selection fixed for both Helix and Bitter** — the
   old heuristic (`mid_elem`, an array-index "middle") had a genuine off-by-one
   bug, confirmed against real data (a Bitter part with `turns=[6,158,6]`:
   `mid_elem` picked an end section, not the actual z=0-centered one).
   Replaced with `_section_index_at_z()` (`stress_map.py`), which finds the
   section whose z-extent actually contains an observation point z0 — Bz is
   evaluated at that same point via a reworked `_bz_at(radii, z0s)`. z0 is
   resolved **per magnet** from `site_magnets.z_offset` (new
   `resolve_z0_by_type()` in `compute_hoop_stats.py`, mirroring
   `build_part_column_map`'s traversal), defaulting to `0.0` — matches all
   current real data (0 of 89 `site_magnets` rows have non-zero `z_offset`).
   No CLI flag; fully automatic and DB-driven.
8. **3 `H\d+_fast`-only regexes fixed** (`stress_map.py`: `cmd_fatigue`,
   `plot_stress_history`, `_load_history`'s preview print) → `(H|B|Supra)\d+_fast`,
   matching the pattern `compute_stress_stats` already used correctly.
9. **Tests**: orchestration test added for `compute_hoop_stress_history()`
   (previously completely untested — the deferred `PROMPT_test_hoop_orchestration.md`
   is now obsolete), unit tests for `compute_stress_stats()`,
   `_section_index_at_z()`, `resolve_z0_by_type()`, and regression tests
   locking in the regex fix.

**Verified**: 306/306 tests pass (`MPLBACKEND=Agg pytest tests -k hoop`,
excluding `test_matplotlib.py`); real end-to-end run on site `M9_A241202_00`
against `test-magnetdb.duckdb` — 14 Helix parts + 2 Bitter parts, correct
writes to `hoop_stress_bin_stats`/`hoop_stress_fatigue`/`hoop_stress_processed`,
Parquet output confirmed.

**Not committed.**

## Phase 2+ — status

Split into separate plan files, one per phase, each with its own
Goal/Files/Approach/Verification/Assumptions and explicit dependency on the
previous phase landing:

- **Phase 2** — [PLAN_hoop_stress_parquet_columns.md](PLAN_hoop_stress_parquet_columns.md):
  rename Parquet columns to part names. **Implemented** (commit `c26d74f`),
  uncommitted-on-top-of status still applies per this file's overall header
  (see git log for actual commit state).
- **Phase 3** — [PLAN_hoop_stress_part_history.md](PLAN_hoop_stress_part_history.md):
  going from site to part — `part_history_stats`, `build_part_history_series`,
  new `hoop-stress part-history` CLI command. **Implemented** (commit
  `c975a5d`).
- **Phase 4** — [PLAN_hoop_stress_per_part_tests.md](PLAN_hoop_stress_per_part_tests.md):
  test coverage for Phase 3's aggregation/concatenation functions.
  **Tests written and passing in isolation** (2026-08-14); full-suite
  re-verification and the real-DB cross-check are blocked on `magnettools`
  availability (this machine's venv lacks it) — see that file for details.
- **Phase 5** — [PLAN_hoop_stress_fatigue_additivity.md](PLAN_hoop_stress_fatigue_additivity.md):
  the `TODOs.md` "test if fatigue can be used like a cumulative stats??"
  question. Depends on Phase 3 (satisfied). **Not started.**
