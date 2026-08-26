# Profiling the dashboard and notebooks

Tool basics (what each tool measures, install extras) are covered in
[`python_magnetrun/docs/profiling.md`](../../../python_magnetrun/docs/profiling.md) — that
doc targets the `python_magnetrun` CLI entry points. This doc covers the same tools applied
to two different shapes of program: the live Dash server (`magnetdb_app.py`) and Jupyter
notebooks, where "run the CLI under a profiler" doesn't apply directly.

All commands below use the project virtualenv: `to_duckdb/venv/bin/python`,
`to_duckdb/venv/bin/pip`, etc. It already has `psutil`, `memory_profiler`, `snakeviz`,
`line_profiler` and `pyinstrument` installed.

---

## Profiling the dashboard

The dashboard is a long-running Flask/Dash server, not a one-shot script — profiling means
capturing what happens during specific HTTP requests (page loads, and every callback fires
as a `POST /_dash-update-component`), not the process lifetime as a whole.

### 1. cProfile — per-request, zero code changes

`magnetdb_app.py` already wires a `ProfilerMiddleware` toggle, gated by an env var so it's
opt-in with zero overhead when off:

```bash
cd apps/dashboards/magnetdb/src
export MAGNETDB_DB_PATH=... MAGNETDB_DB_DIR=...   # or `source ../.envrc`
MAGNETDB_PROFILE=1 ../../../to_duckdb/venv/bin/python magnetdb_app.py
```

Click through the app as usual (e.g. the comparison page). Every request drops a `.prof`
file into `profiles/`, named `<time>-<method>-<path>-<elapsed_ms>ms.prof`. Callback
invocations all share the path `_dash-update-component`, so filter and sort by elapsed time
to find the slow ones:

```bash
ls profiles/ | grep update-component | sort -t- -k4 -rn | head
snakeviz profiles/<file>.prof
```

Set `PROFILE_DIR=other/path` to change the dump location. `profiles/`, `*.prof` etc. are
gitignored — nothing to clean up manually.

### 2. line_profiler — a specific callback or function

Best once cProfile/snakeviz has pointed at a specific function, e.g.
`update_single_pair_graph` in [`comparison.py`](../src/pages/comparison.py) or `load_data` /
`load_mrun_object` in `magnetdb_analysis.py`.

Decorate temporarily:

```python
@profile
def update_single_pair_graph(...):
    ...
```

Run the server under `kernprof` instead of `python`:

```bash
cd apps/dashboards/magnetdb/src
../../../to_duckdb/venv/bin/kernprof -l magnetdb_app.py
# exercise the slow page in the browser, then Ctrl+C
../../../to_duckdb/venv/bin/python -m line_profiler magnetdb_app.py.lprof
```

Remove the `@profile` decorator before committing.

### 3. memory_profiler — whole-session timeline

Better than cProfile for the "5 concurrent callbacks all cold-parsing the same file"
scenario described in [`PERFORMANCE_PLAN.md`](../PERFORMANCE_PLAN.md) — it plots RSS across
the *entire* server session, so concurrent parses show up as overlapping spikes instead of
isolated per-request numbers:

```bash
cd apps/dashboards/magnetdb/src
../../../to_duckdb/venv/bin/mprof run magnetdb_app.py
# exercise the comparison page, then Ctrl+C
../../../to_duckdb/venv/bin/mprof plot
```

Expected signature today (root cause B in `PERFORMANCE_PLAN.md`): 5 overlapping RSS spikes
per file-selection change. After the pre-loading-callback fix, that should collapse to one
sequential ramp.

### 4. py-spy — live attach, no restart, no code changes

Fastest way to sanity-check a hypothesis against a dashboard that's *already running*
(e.g. one a colleague has open): sample it from the outside.

```bash
to_duckdb/venv/bin/pip install py-spy   # standalone CLI, not a library import
py-spy record -o profile.svg --pid $(pgrep -f magnetdb_app.py)
```
Click around in the browser while it's recording, then open `profile.svg`
(flamegraph) in a browser.

---

## Profiling notebooks

Same tools, IPython-magic form. Load once per kernel session:

```python
%load_ext line_profiler
%load_ext memory_profiler
```

| Goal | Magic |
|---|---|
| Quick wall-time, repeated | `%timeit compute_field_signature(df)` |
| Single-run wall-time | `%time compute_field_signature(df)` |
| Line-by-line CPU time | `%lprun -f compute_field_signature compute_field_signature(df)` |
| Line-by-line memory | `%mprun -f compute_field_signature compute_field_signature(df)` |
| One-shot memory delta | `%memit compute_field_signature(df)` |

**Caveat:** `%lprun`/`%mprun` only print per-line detail for functions importable from a
`.py` file — a function defined directly in a notebook cell profiles as a single opaque
block. If you need line-level detail on a notebook-defined function, move it to a module
first (or temporarily paste it into a scratch `.py` file and `%load_ext autoreload`).

For CPU+memory sampled over a whole cell (useful when the work isn't one clean function
call, e.g. a duckdb query followed by a `groupby`), use a small `psutil`-based context
manager instead — see the `ResourceMonitor` pattern discussed alongside this doc; it has no
per-line detail but doesn't require refactoring code into a module first.

---

## Typical workflow

1. **Dashboard**: `MAGNETDB_PROFILE=1` + cProfile/snakeviz (or `py-spy record` if it's already
   running) to find which request/callback is slow.
2. **Notebook**: `%timeit`/`%time` first to confirm there's actually a problem worth
   chasing.
3. Narrow to a function with `line_profiler` (`%lprun` or `kernprof`).
4. If memory-bound, confirm with `memory_profiler` (`%mprun`/`%memit` or `mprof plot`).
5. Fix, re-profile to verify the fix actually moved the number.

## Known hot spots (update as discovered)

| Area | File | Symptom | Status |
|---|---|---|---|
| Comparison page pair-graphs | `src/pages/comparison.py` (`update_single_pair_graph`) | 19–192 s per callback, raw file re-parsed on every call | Root-caused in `PERFORMANCE_PLAN.md`; fix planned (Parquet cache + pre-loading callback) |
| `import_housing_summary.ipynb` | `to_duckdb/import_housing_summary.ipynb` (`compute_field_signature`) | TBD | Not yet profiled |
