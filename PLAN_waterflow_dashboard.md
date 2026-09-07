# Plan: Waterflow comparison dashboard

**Goal.** Add a new Dash page where a user picks Housing/Year/Status filters
then an assembly, picks one or more pupitre experiments for it, and sees
Flow(I), Pressure(I), Rpm(I) plots comparing each experiment's raw hydraulic
data against a reference `WaterFlow` curve — read from
`overview_records.flow_params` when the DB has one, otherwise fitted
on-the-fly via `python_magnetrun.waterflow_pipeline` / `python_magnetcooling`.
Along the way, fix the cwd-dependent `importlib.resources` bug in both
`housing_config.py` and `field_defs.py` at its root, rather than working
around it.

**Files affected**
- Edit `python_magnetrun/python_magnetrun/housing_config.py` — fix the
  packaging bug.
- Edit `python_magnetrun/python_magnetrun/field_defs.py` — fix the same bug
  in `_bundled_defs_path()`.
- Create `apps/dashboards/magnetdb/src/pages/waterflow_stats.py` — the new
  page (layout + callbacks).
- Edit `apps/dashboards/magnetdb/src/magnetdb_analysis.py` — add one
  read-only DB helper.
- Edit `apps/dashboards/magnetdb/src/magnetdb_plot.py` — add one
  figure-builder helper.
- No edits to `magnetdb_app.py` (pages under `src/pages/` self-register via
  `dash.register_page`).

**Approach**

1. **Fix `python_magnetrun/python_magnetrun/housing_config.py`**:
   - `get_bundled_housing_config_path()`: replace
     `importlib.resources.files("python_magnetrun") / filename` with
     `Path(__file__).parent / filename`.
   - `_load_bundled_configs()`: replace
     `pkg = importlib.resources.files("python_magnetrun")` with
     `pkg = Path(__file__).parent`. `pkg.iterdir()` / `entry.name` /
     `entry.open(...)` need no further change.
   - Remove the now-unused `import importlib.resources`.
   → verify: with cwd = repo root,
     `from python_magnetrun.housing_config import HOUSING_CONFIGS; print(HOUSING_CONFIGS.keys())`
     → `['M8','M10','M9','M7','M5']` (previously `[]`);
     `get_housing_config('M9')` → `IH FlowH RpmH HPH`;
     `get_housing_config('M10')` → `IB FlowB RpmB HPB`.

2. **Fix `python_magnetrun/python_magnetrun/field_defs.py`**:
   - `_bundled_defs_path()`: replace
     `ref = importlib.resources.files("python_magnetrun") / filename; return Path(str(ref))`
     with `return Path(__file__).parent / filename`.
   - Remove the now-unused `import importlib.resources` (confirmed this is
     its only use in the file).
   → verify: with cwd = repo root,
     `_bundled_defs_path('pupitre-defs.json').exists()` → `True` (previously
     `False`); `resolve_defs_file('pupitre-defs.json')` resolves without
     raising; and — as a regression check — re-run the earlier
     `db.load_mrun_object('2018.02.21 - 10:18:54.txt', 'M10')` probe with
     cwd = repo root this time (it already worked from
     `apps/dashboards/magnetdb/src`; after the fix it must also work from
     repo root) and confirm `Groups` still builds identically
     (`Hydraulics`, `Pressures_Hydraulics`, `Courants_Alimentations`, etc.).

3. `magnetdb_analysis.py` — add
   `get_flow_params_for_assembly(assembly_name, before=None, db_path=None)`.
   Queries `overview_records` for rows with `assembly_name = ?`,
   `merged_into IS NULL`, and non-empty `flow_params`, ordered by `t0`. Picks
   the row nearest at-or-before `before` (falls back to most recent overall,
   or earliest if `before` unset), returns `{filename, t0, flow_params}` or
   `None`.
   → verify: returns `None` against `to_duckdb/test-magnetdb.duckdb` (empty
     table today), no error.

4. Housing-config-based channel resolution in the new page, now via
   `get_housing_config(housing)` directly (no workaround needed post-fix).

5. `magnetdb_plot.py` — add
   `create_waterflow_plot(series, quantity_label, y_symbol_unit)`: one
   `go.Figure` per quantity ("Flow [l/s]", "Pressure [bar]", "Rpm [rpm]").
   `series` is a list of
   `{label, color, x_raw, y_raw, x_fit, y_fit, dash}` — raw points as
   markers, fit as a line, color = experiment, dash style = circuit
   (solid="H", dash="B"). Matches `create_plot`/`create_comparison_plot`
   styling (plotly_white template).
   → verify: call with 2-3 synthetic series, confirm it renders.

6. `pages/waterflow_stats.py` (`path="/waterflow"`, `name="Waterflow"`,
   `order=8`):
   - **Layout**, in order: Housing filter → Year filter → Status filter →
     Assembly filter (options narrowed by the three, same "All" +
     filtered-list pattern as `assembly_stats.py`) → Experiments
     multi-select (scoped to assembly, `.txt`/pupitre only) → Circuit
     checklist (`H`, `B`, default both) → three `dcc.Graph`s (Flow(I),
     Pressure(I), Rpm(I)) → params/source details table.
   - **Callback A — filter cascade** (cheap, metadata-only):
     `Input(dd-database, wf-housing-filter, wf-year-filter, wf-status-filter)`
     → `Output(wf-assembly-filter.options, wf-housing-filter.options, wf-year-filter.options, wf-status-filter.options)`.
     Logic ported from `assembly_stats.py`'s `update_assembly_stats`
     (lines 736–772): year options via `db.assemblies_year_range`; status
     options via `db.get_distinct_statuses("assemblies", ...)`; assembly
     options = all assemblies filtered by housing prefix ∩ year-active
     (`db.assemblies_active_in_year`) ∩ status (`db.get_names_with_status`).
   - **Callback B — experiments options**:
     `Input(wf-assembly-filter.value, dd-database)` →
     `Output(wf-experiments.options)` via
     `db.get_files_for_assembly(assembly, "experiments", db_path)`, filtered
     to `.txt`.
   - **Callback C — main plot/table callback**: for each selected
     experiment × selected circuit:
     a. `housing = assembly.split("_")[0]`; resolve channel names via
        `get_housing_config(housing)`.
     b. `mrun = db.load_mrun_object(file, housing)`;
        `df = mrun.MagnetData.getData([current_col, rpm_col, flow_col, pin_col, "BP"])`.
     c. `waterflow_pipeline.extract_hydraulic_data(df, current_col, rpm_col, flow_col, pin_col, "BP")`
        → `HydraulicData`.
     d. Reference: try
        `db.get_flow_params_for_assembly(assembly, before=<experiment date>)`
        → `waterflow_factory.from_flow_params(...)`; else
        `waterflow_pipeline.compute_waterflow(data, method="piecewise")`.
        Memoized per `(file, housing, circuit)` via `functools.lru_cache`.
     e. Fit curve over `I ∈ [0, wf.current_max]`: `flow_rate(I)×1000`
        (m³/s→l/s), `pressure(I)` (bar), `pump_speed(I)` (rpm).
     f. `try/except` per experiment/circuit combo (missing columns, <3
        points) — skip with a visible warning rather than crashing the
        callback.
     g. Call `plot.create_waterflow_plot()` three times; populate the
        params table.
   - No changes needed to `dash_selectors.py` or `magnetdb_app.py`.

**Verification**
- Steps 1 & 2's direct import/regression checks (above), run first since
  later steps depend on them.
- `apps/dashboards/magnetdb/tests` suite still passes.
- Any tests under `python_magnetrun/tests/` covering `housing_config.py` /
  `field_defs.py` still pass after the fixes.
- Launch the app (`python magnetdb_app.py` from
  `apps/dashboards/magnetdb/src/`, via the `run` skill) against
  `to_duckdb/test-magnetdb.duckdb`; pick an M9 or M10 assembly via the new
  filters, select 2-3 pupitre experiments, confirm all three plots render
  with raw scatter + fitted line, params table shows "fitted from this
  experiment" for every row (DB table is empty today).
- Confirm the Housing/Year/Status filters narrow the Assembly dropdown
  correctly and never trigger the heavy fitting callback by themselves.
- Manually trigger the missing-columns path and confirm a warning, not a
  crash.

**Assumptions & open questions**
- No automated Dash-callback test added — matches existing page coverage in
  this repo.
- Experiments restricted to pupitre (`.txt`) files.
- Fit method defaults to `"piecewise"`, no manual Imax control in v1.
