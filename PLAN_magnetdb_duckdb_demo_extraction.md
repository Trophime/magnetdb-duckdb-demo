# Plan — extract `to_duckdb` + `stage/dashboard` into `magnetdb-duckdb-demo`

Status: proposed, not yet approved or executed.

## Goal

Produce a new public GitHub repository, `magnetdb-duckdb-demo`, carrying full
commit history for `to_duckdb/`, `stage/dashboard/` (renamed to
`apps/dashboards/magnetdb/`), and the pointer-bump history of the
`python_magnetrun`/`python_magnetgeo`/`python_magnetsetup` submodules — the
new home for this work going forward. `2026-m1-hifimagnet` (this repo) is
left untouched; the intent is to stop working in this repo once the new one
is up.

## Context

- `2026-m1-hifimagnet` is scoped as an internship-project repo
  (`hifi1-levchenko` main branch). The active roadmap work
  (`to_duckdb/ROADMAP.md`) and the dashboard (`stage/dashboard/`) are the
  parts worth carrying forward independently of that container.
- `PROJECT_STRUCTURE_PLAN.md` (repo root, proposal only, nothing executed)
  already designs a target layout — `apps/dashboards/<name>/` for Dash
  apps, `to_duckdb/` as a pure library — this extraction applies that target
  layout directly rather than reorganizing in place first and moving
  second.
- `to_duckdb/dashboard/` is a separate, stale duplicate mini-dashboard,
  already flagged in `PROJECT_STRUCTURE_PLAN.md` as a delete candidate — out
  of scope for this extraction.
- Confirmed by grep: both `to_duckdb/` and `stage/dashboard/` import
  `python_magnetrun`, `python_magnetgeo` (`Assembly`, `Bitters`, `Insert`,
  `Supras`, `deserialize`), and `python_magnetsetup` (`ana`, `config`).
  Neither imports `python_magnetcooling` — excluded from the new repo.

## Files/resources affected

- A disposable local clone of this repo (scratch path, discarded after
  push) — create.
- That clone's history — rewritten via `git filter-repo` (destructive, but
  only on the disposable clone, never this working repo).
- New GitHub repo `Trophime/magnetdb-duckdb-demo` (public) — create, push.
- `2026-m1-hifimagnet` — not modified by this operation.

## Approach

1. **Precondition — commit current in-flight work first.** The 11 modified
   files currently in the working tree, plus a short plan for the
   uncommitted `hoop_stress_fatigue_bins` schema change (see
   `to_duckdb/ROADMAP.md`'s 2026-08-21 snapshot), should land before
   extracting — migrating half-done, undocumented changes defeats the point
   of preserving clean history. Separate step, not part of the extraction
   itself.
2. Clone this repo to a scratch path.
3. Run `git filter-repo` in two passes on that clone:
   - **Include:** `--path to_duckdb --path stage/dashboard --path
     python_magnetgeo --path python_magnetrun --path python_magnetsetup
     --path-rename stage/dashboard:apps/dashboards/magnetdb`
   - **Exclude:** `--invert-paths --path to_duckdb/dashboard` — drops the
     stale duplicate mini-dashboard's history that the include pass would
     otherwise pull in under `to_duckdb`.
   `python_magnetcooling` deliberately left out (confirmed unused by either
   `to_duckdb` or `stage/dashboard`).
4. Inspect the result: commit count, `git log --follow` on a long-lived file
   in each area, and confirm the three submodules still show multiple
   pointer-bump commits (not a single flattened one).
5. Re-add `.gitmodules` in the filtered clone (same three URLs as this
   repo's current `.gitmodules`) — `git filter-repo` keeps the gitlink tree
   entries but not the modules file itself.
6. `gh repo create Trophime/magnetdb-duckdb-demo --public`, push the
   filtered history.
7. Fresh-clone the new repo and `git submodule update --init --recursive` to
   confirm it resolves end-to-end.

## Verification

- Commit counts for `to_duckdb`/`apps/dashboards/magnetdb` in the new repo
  roughly match `git log --oneline -- to_duckdb` / `-- stage/dashboard` in
  this repo today.
- `git log -- python_magnetgeo` (etc.) in the new repo shows the real
  pointer-bump history, not a single flattened commit.
- `git log --all -- to_duckdb/dashboard` in the new repo is empty.
- Fresh clone + submodule init succeeds; `to_duckdb` and the dashboard
  import cleanly against the vendored submodules.
- This repo's own `git log`/`git status` unchanged before and after.

## Follow-up

`to_duckdb/ROADMAP.md` moves across intact as part of this extraction (it
lives under `to_duckdb/`, included in the Approach step 3 filter, with its
own history preserved). Once the extraction lands, its `Next`/`Later`-phase
work continues in `magnetdb-duckdb-demo` rather than here: overview-record
signature/lag/plateaux, `populate all`, userdb multi-source, the scheduler,
EcoNRJ parameter inference, dashboard comparison-page performance, and the
not-yet-planned hoop-stress fatigue-bins matrix. This isn't a new roadmap —
just a note on where that existing one resumes.

## Assumptions & open questions

- Repo `magnetdb-duckdb-demo`, public, under `Trophime` (same account as
  the sibling repos found during earlier investigation — `python_magnetdb`,
  `python_magnetapi`, `hifimagnet-projects`) — confirm the account if it
  should go elsewhere.
- `to_duckdb/dashboard/` excluded from the extraction — confirmed to match
  stated scope ("to_duckdb and all stage/dashboard changes").
- `to_duckdb/` keeps its name at the new repo's root; only
  `stage/dashboard/` gets renamed, to `apps/dashboards/magnetdb/`.
- Retiring/archiving `2026-m1-hifimagnet` itself is a separate, later
  decision, not part of this plan.
