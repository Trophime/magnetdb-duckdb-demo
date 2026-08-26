# Profiling the dashboard

Two layers, from coarse to fine.

## 1. Per-callback timing (always on)

`magnetdb_analysis.chrono_callback` wraps most comparison-page callbacks and
prints wall-clock time to stdout on every invocation:

```
Callback 'update_group_dropdown' exécuté en 15555.91 ms
Callback 'generate_pair_blocks' exécuté en 4.52 ms
```

No setup needed — just read server stdout. Good for spotting *which*
callback is slow and how often it fires, not *why*.

## 2. Per-request cProfile (opt-in)

`magnetdb_app.py` wires in Werkzeug's `ProfilerMiddleware` behind an env
var, so it's zero-cost unless explicitly enabled:

```bash
cd apps/dashboards/magnetdb/src
MAGNETDB_PROFILE=1 python magnetdb_app.py
```

Reproduce the slow interaction in the browser, then check
`apps/dashboards/magnetdb/src/profiles/` — one `.prof` file per Dash callback POST
(`/_dash-update-component`), timestamped. Match the slow one against the
`chrono_callback` prints in stdout, then inspect it:

```bash
pip install snakeviz          # into the venv used to run the dashboard
snakeviz profiles/<file>.prof # flamegraph in the browser
# or, stdlib-only:
python -m pstats profiles/<file>.prof
```

This is the tool for "where inside `load_mrun`/`getTdmsData`/downsampling is
the time actually going" — the level `chrono_callback` can't see.

Requires `werkzeug` (already a transitive Dash/Flask dependency, pinned
explicitly in `requirements.txt` since it's now imported directly).

## 3. Zero-code-change alternative: py-spy

For a one-off look without touching any file:

```bash
pip install py-spy
python apps/dashboards/magnetdb/src/magnetdb_app.py    # leave running
ps aux | grep magnetdb_app                    # debug=True forks a reloader —
                                               # two processes show up, profile
                                               # the one actually serving requests
py-spy record -o profile.svg --pid <worker-PID>
```

Reproduce the slow interaction while it records, then Ctrl+C and open
`profile.svg` — a flamegraph, no code changes, no restart needed.

## Which one to reach for

- Something feels slow, don't know which callback: read stdout (layer 1).
- Know which callback, want to know which function inside it: `MAGNETDB_PROFILE=1` (layer 2) for a saved, repeatable profile — best when comparing before/after a fix.
- Want an instant answer against the currently running process, no restart: py-spy (layer 3).
