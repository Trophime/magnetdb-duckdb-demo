# Project structure improvement plan

Status: proposal only — nothing in this document has been executed yet.
This plan captures the current-state analysis and a proposed migration path
for reorganizing the repository around its three deliverable types
(Jupyter/marimo notebooks, Voila apps, Dash dashboards) and for modernizing
dependency management.

**Follow-up (2026-08-21):** the `to_duckdb` + Dash-dashboard-consolidation
portion of this plan's target tree (§2, and §3 steps 4–5) is being realized
via [PLAN_magnetdb_duckdb_demo_extraction.md](PLAN_magnetdb_duckdb_demo_extraction.md)
— a history-preserving extraction of `to_duckdb/` and `stage/dashboard/`
into a new repo, `magnetdb-duckdb-demo` — rather than an in-place reorg
here. The remaining items below (§3 steps 1, 2, 6 — the `project2`/
`Project2` duplicate, `to_duckdb.old/`, stray root files) are not covered
by that extraction and may be moot if this repo is being retired; that's a
separate, still-open decision, not resolved by this note.

## 1. Current state

The three deliverable types exist, but are scattered rather than organized
around that structure:

- **Jupyter notebooks** live in `notebooks/` (including the Voila apps
  `voila-Bmap.ipynb`, `voila-Bmap-db.ipynb`), but also in
  `project1/src/main.ipynb`, `project3/src/*.ipynb`, and loose inside
  `to_duckdb/` itself (`import_housing_summary.ipynb`,
  `test_assembly_stats.ipynb`).
- **marimo** has a single app: `to_duckdb/marimo/select_assembly.py`.
- **Dash dashboards** are duplicated: `to_duckdb/dashboard/` and
  `stage/dashboard/` are two separate, independent Dash apps, each with
  their own `src/`, `tests/`, `Dockerfile`.

Additional issues found, independent of the notebook/marimo/dash split:

- `project2/` and `Project2/` are a **diverged duplicate** — different
  files exist under each `docs/` (e.g. `presentation-sarr.tex` and
  `report-sarr.tex` only exist under `Project2/docs/`; several PDFs/PNGs
  only exist under `project2/docs/`). This is a data-integrity risk, not
  a cosmetic one.
- `to_duckdb.old/` is a stale fork of `to_duckdb/` with committed venvs
  (`venv/`, `venv-systempackages/`), `.duckdb`/`.wal` database files,
  `__pycache__`, `.ruff_cache`, `.pytest_cache` — none of which belong in
  version control.
- Generated artifacts are committed both at the repo root
  (`my_plot.png`, `test*.png`, `test-magnetdb.duckdb`, `log`) and inside
  `to_duckdb/` (`*.duckdb`, `*.wal`, `Figure_1.png`, `schema_diagram.png`,
  etc.) instead of being gitignored.
- Stray editor/backup files at root: `start-venv.sh~`,
  `.devcontainer/devcontainer.json~`, `.devcontainer/setup.sh~`,
  `test-magnetrun.py~`, and a file literally named `-m`.
- Dependency management is inconsistent: the project's own code
  (`to_duckdb/`, `project1/`, `stage/dashboard/`) uses `requirements.txt`,
  while every vendored/submodule package (`python_magnetgeo`,
  `python_magnetrun`, `python_magnetcooling`, `python_magnetsetup`) uses
  `pyproject.toml`.

## 2. Proposed target tree

```
apps/
  notebooks/        # exploratory + Voila-servable notebooks
  marimo/            # marimo apps
  dashboards/
    <dashboard-name>/   # one self-contained Dash app per dashboard
      src/
      tests/
      Dockerfile
      pyproject.toml
to_duckdb/            # shared data/logic layer only — no notebooks, no app code
  ...
```

Principles:
- `to_duckdb/` becomes a pure library (schema, CRUD, stats computation)
  that the apps in `apps/` import — it does not host notebooks or Dash
  apps itself.
- Voila is a serving mode for notebooks already in `apps/notebooks/`, not
  a separate directory.
- Each Dash dashboard is self-contained under `apps/dashboards/<name>/`
  so it can have its own dependency set and Dockerfile without competing
  with another dashboard of the same shape (resolves the
  `to_duckdb/dashboard/` vs `stage/dashboard/` duplication).

## 3. Migration steps

Each step is independently reviewable/reversible. Phased so integrity
risks are resolved first, then cleanup, then the directory reshuffle.

1. **Reconcile `project2/` vs `Project2/`**
   → verify: `diff -rq project2 Project2` shows no remaining differences
   after merge; only one of the two directories remains in the tree.
2. **Resolve `to_duckdb.old/`** — decide keep-nothing/archive-outside-repo/
   delete, once confident `to_duckdb/` has fully superseded it.
   → verify: `git log --follow` on any file still uniquely present in
   `to_duckdb.old/` confirms it has no unique, needed content; directory
   removed from the working tree.
3. **Add `.gitignore` rules** for generated artifacts (`*.duckdb`,
   `*.duckdb.wal`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`,
   editor backups `*~`) and `git rm --cached` the currently tracked
   instances.
   → verify: `git status` after regenerating artifacts shows them as
   untracked/ignored, not modified.
4. **Consolidate the two Dash dashboards** into
   `apps/dashboards/<name>/`, one directory per dashboard, preserving
   each app's own `src/`, `tests/`, `Dockerfile`.
   → verify: each dashboard still starts (`python app.py` /
   `docker build`) from its new location.
5. **Move notebooks** into `apps/notebooks/`, marimo app into
   `apps/marimo/`, updating any relative imports/paths to `to_duckdb/`.
   → verify: each notebook runs top-to-bottom (`jupyter nbconvert
   --execute` or manual run) after the move.
6. **Clean stray root files** (`-m`, `*~` backups, ad-hoc `*.png`/`log`
   test outputs) — remove or relocate under an explicit `scratch/`
   directory that is gitignored.
   → verify: `git status` at root is clean of untracked clutter.

## 4. Packaging: `requirements.txt` vs `pyproject.toml`

**Recommendation:** move to one `pyproject.toml` per component (each
`apps/dashboards/<name>/`, `apps/marimo/`, and `to_duckdb/`), run via
`uv` — consistent with `.devcontainer/setup-uv.sh` already standardizing
on `uv`, and consistent with every vendored package in the repo already
using `pyproject.toml`. It also allows per-component
`[project.optional-dependencies]` groups instead of one flat
`requirements.txt` per folder.

**Tradeoff:** this is more upfront structure than the repo currently has
for what is largely student/notebook-stage code; if the internship
deliverable doesn't require packaging rigor, plain `requirements.txt`
per folder remains the lower-ceremony option and is easier for a new
intern to read at a glance. Revisit this once the dashboards/notebooks
in `apps/` stabilize.

## 5. Open questions (deferred to project owner)

- Which of `project2/` or `Project2/` is authoritative for the content
  that differs between them (presentation/report tex files vs.
  images/report PDF)?
- Can `to_duckdb.old/` be deleted outright, or should it be archived
  somewhere outside the git history first (e.g. a zip kept off-repo)?
- Final naming: `apps/` vs `interfaces/` vs something else, and naming
  for each dashboard subdirectory.
- Timing: execute this migration now, or defer until the dashboards in
  `to_duckdb/dashboard/` and `stage/dashboard/` stop actively changing?
