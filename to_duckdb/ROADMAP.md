# to_duckdb — Roadmap

Status: draft — all 3 open questions now have a concrete path forward (see
"Open Questions" below), none is a true blocker anymore: processing-status
flag (Q3) and plateaux (Q2, direction decided, a few implementation details
left) were decided 2026-08-17; lag (Q1) turned out to be a choice between
two already-working implementations rather than a missing definition — it
needs a head-to-head comparison and wiring, not a design discussion.

Phased roadmap synthesizing `TODOs.md` plus the planning discussions that
produced `PLAN_overview_records_pupitre_dedup.md`, `PLAN_hoop_stress_history.md`
(now an index over per-phase plans: `PLAN_hoop_stress_parquet_columns.md`,
`PLAN_hoop_stress_part_history.md`, `PLAN_hoop_stress_per_part_tests.md`,
`PLAN_hoop_stress_fatigue_additivity.md`), `PLAN_scheduled_populate.md`,
`PLAN_econrj_parameter_inference.md`, `PLAN_users_multi_source.md`,
`PLAN_populate_all.md`, `PLAN_lifecycle_status.md`,
`stage/dashboard/PLAN_dashboard_hierarchy_rework.md`, and (repo root)
`PLAN_site_to_assembly_rename.md`. Phases are ordered by dependency, not
calendar date; effort is relative (S = small, M = medium, L = large, ? =
not yet sizeable).

## Snapshot (2026-08-17)

- Open Question 2 (plateaux) — **direction decided**: detect plateaux with
  `nplateaus()` (`python_magnetrun/processing/plateaux.py` — note the file
  and function are both plural, `plateaux`/`nplateaus`, not `plateau`),
  run per-file over the `sources_pupitre` (pupitre `Field`, unit tesla) and
  `sources_overview` (pigbrother `Courants_Alimentations/Champ_magn`, unit
  millitesla) arrays already on each `overview_records` row
  (`to_duckdb/schema.py:140,142`) — the two channels are already
  cross-referenced via the `aliases` mechanism in
  `pupitre-defs.json`/`pigbrother-defs.json` (the same mechanism
  `python_magnetrun/field_defs.py`'s `match_channels_across_formats()`,
  above, generalizes). Storage target
  is also already reserved: `overview_records.plateaux JSON DEFAULT '{}'`
  exists in the schema, unpopulated. A near-identical prototype already
  exists to adapt: `get_plateaux_per_pupitre()` in
  `stage/dashboard/tests/lag_test_discovery.py:185` iterates
  `record.sources.pupitre`, loads each file, and calls `nplateaus()` per
  file — same shape as what this item needs, just for pupitre only and
  living in a dashboard test script rather than the `to_duckdb` pipeline.
  See the "Open Questions" section below for the 2–3 details still open
  before this is fully closed (per-source threshold tuning, matplotlib
  side effects in `nplateaus()`, one-file-vs-row-concatenated handling).
- Open Question 3 (processing-status flag) — **decided**: per-stage
  timestamp columns (e.g. `stress_processed_at`, `fatigue_processed_at`),
  not the single tombstone-style column alternative. See the "Open
  Questions" section below for the updated writeup. Design decided, not yet
  implemented or backed by its own plan file — still sequenced after
  `PLAN_hoop_stress_history.md` lands so the columns' vocabulary matches
  the finished pipeline.
- `PLAN_site_to_assembly_rename.md` — **Track A (Phases 1–7, this
  workspace) implemented and committed, 2026-08-18** (`0ee0d80`, `1131649`,
  `b79632b`, `78a288c`, `c111577`, `ce672ff`, `53f2ea0`, `c4b9054`).
  Upgraded from "approved, nothing yet implemented" — all seven phases
  landed the same day: `python_magnetgeo`'s `Assembly` class (with a
  deprecated `MSite` alias), `python_magnetsetup`'s `assembly_setup`,
  `to_duckdb`'s `assemblies`/`assembly_magnets` schema + CRUD + migration
  script, `stage/dashboard`'s `assembly_stats.py` and friends,
  `python_magnetrun`'s `getAssembly`/`setAssembly`, `python_magnetcooling`'s
  `--assembly` flag, and Phase 7 cleanup (`stage/dash_site_stats.py`
  deleted, `select_site.py`→`select_assembly.py`, etc.). One residual gap:
  this workspace's submodule pointers for `python_magnetgeo`,
  `python_magnetrun`, `python_magnetsetup` aren't committed yet (`git
  status` shows them locally modified past their pinned commit) — only
  `python_magnetcooling`'s pointer landed, in `c4b9054`. Track B (separate
  repos) execution remains intentionally deferred, unaffected by Track A's
  completion. `PLAN_lifecycle_status.md` and
  `stage/dashboard/PLAN_dashboard_hierarchy_rework.md` (both referenced in
  the `Now`/`Next`-phase rows below) have been updated to `Assembly`
  vocabulary to match — see their own status lines.
- `PLAN_hoop_stress_history.md` — Phase 4 (per-part stats/history tests,
  `PLAN_hoop_stress_per_part_tests.md`) **written and passing in isolation**
  (`f582871`, 2026-08-14, still uncommitted per the plan's own status line
  despite the commit — the commit added the test file and updated the plan
  docs, not a completion marker). Blocked on `magnettools` not being
  installed in this machine's `to_duckdb/venv`: 6 pre-existing orchestration
  tests + `test_stress_map.py` fail to collect for that reason (confirmed
  unrelated to Phase 4's own changes), and a real-DB cross-check against
  `test-magnetdb.duckdb` still needs it too. **Decided, 2026-08-17: on this
  machine, finalize Phases 4–5 via the local devcontainer** (rebuilt onto
  `trophime/magnettools:trixie`, `7066831`) rather than the office machine —
  no longer just a "possibly unblocked, worth verifying" note from the
  earlier snapshot; this is now the chosen path. Concretely still needed:
  rebuild the local devcontainer, confirm `magnettools` is actually present
  and importable inside it, then re-run the blocked orchestration tests
  (`test_compute_hoop_stats.py -k hoop`, `test_stress_map.py`) and the
  real-DB cross-check against `test-magnetdb.duckdb` from inside it. Also
  corrected in this pass: Phase 3
  (`PLAN_hoop_stress_part_history.md`) had already landed (`c975a5d`) even
  though tracking docs still said "not started." Phase 5
  (`PLAN_hoop_stress_fatigue_additivity.md`, the fatigue-additivity
  question) remains pending approval, not started — its Phase 3 dependency
  is now satisfied. The umbrella plan is now split across four per-phase
  files (`PLAN_hoop_stress_parquet_columns.md` = Phase 2,
  `PLAN_hoop_stress_part_history.md` = Phase 3,
  `PLAN_hoop_stress_per_part_tests.md` = Phase 4,
  `PLAN_hoop_stress_fatigue_additivity.md` = Phase 5); `PLAN_hoop_stress_history.md`
  itself is now the index/overview. Phases 1–4 are **all still uncommitted**.
- Open Question 1 (lag) — **sharpened, 2026-08-17: this is a head-to-head
  robustness comparison between two already-working implementations, not a
  missing definition.** Corrects the previous snapshot entry, which
  mis-attributed Wolali's FFT approach to `synchronization.py` — that file
  (`python_magnetrun/analysis/synchronization.py`) is actually the
  **other**, pre-existing side of the comparison: `compute_lag()`/
  `compute_lag_interpolated()`, already wired into `OverviewRecord.sync_info`
  via `_compute_lag_correlation()` (`analysis/processing.py:1145-1192`), and
  already reaches the DB — `to_duckdb/crud.py` writes `record.sync_info`
  straight into `overview_records.sync_info` (`schema.py:153`). But it's
  gated behind `ProcessingConfig.compute_lag`, which **defaults to
  `False`** and is never turned on by `to_duckdb/magnetdb.py`'s populate
  call (`magnetdb.py:968`, all-default `ProcessingConfig`) — so today,
  already-populated `overview_records` rows have `sync_info["timeshift"]`
  (from `synchronize_data()`, on by default) but **not** the per-channel
  `sync_info["lag_<key>"]` values, since that half is switched off.
  Wolali's FFT-cross-correlation-on-normalized-derivatives approach lives
  in a shared `get_lag()`, reimplemented identically across three
  decision-support scripts added to `stage/dashboard/tests/`
  (`lag_test_file.py` — explicit file args; `lag_test.py` — reads a real
  row's `sources_pupitre`/`sources_overview`/`sources_archive` straight
  from the `overview_records` DuckDB table; `lag_test_discovery.py` — disk
  auto-discovery via `FileDiscovery`, mirroring the analysis submodule's
  own discovery path) — built specifically to run this comparison against
  real data. Scope home is `stage/dashboard/PLAN_signature_regime_robustness.md`,
  whose "Existing tooling to build on" section already cites both sides
  (`synchronization.py`'s `find_best_matching_regime`/`check_lag_reliability`
  and `lag_test_discovery.py`). See "Open Questions" below for what's left
  before `sync_info` actually carries real lag data.
- `stage/dashboard/FIELD_DEFS_MIGRATION_PLAN.md` — **corrected 2026-08-19:
  already implemented and committed** (`e345feb`, "up dashboard",
  2026-07-28) — three weeks *before* this roadmap's 2026-08-17 snapshot
  mis-tracked it as "new, no plan approval recorded yet." The plan file
  itself no longer exists on disk. `python_magnetrun/field_defs.py` already
  defines `match_channels_across_formats()`;
  `stage/dashboard/src/magnetdb_analysis.py` already imports and delegates
  to it directly (`get_comparable_pairs_for_group()`); the old inline
  alias-matching logic it replaced is gone, and the
  `MAGNETDB_PIGBROTHER_DEF`/`MAGNETDB_PUPITRE_DEF` env-var overrides it made
  unused don't appear anywhere in the codebase anymore. Removed from the
  `Next`-phase tables below — nothing left to schedule.
- `stage/dashboard/PERFORMANCE_PLAN.md` — **new (2026-08-17), untracked, no
  plan approval recorded yet**: comparison-page pair-graph callbacks take
  19–192s per invocation because `load_data`/`load_mrun_object` each
  independently re-parse the same file with separate `lru_cache` keys; plan
  adds a shared on-disk Parquet cache, expected warm-run time < 2s;
  includes a scoped-out future S3 migration note. Reads as concrete and
  independently implementable, not blocked on anything else here.
- `stage/dashboard/src/pages/overview-record.py` — **new, untracked file**
  registering a `/overviews` "Overview Records" page. This appears to
  overlap with `PLAN_dashboard_hierarchy_rework.md`'s still-**unapproved**
  "overview-record file-viewer page" item (that plan's status line
  explicitly says "do not implement until explicitly approved"). Flagging
  so this draft isn't lost or duplicated when/if that plan is later
  approved — worth reconciling the two before either moves further.
- `PLAN_users_multi_source.md` — still pending approval, but active
  exploratory work is happening outside any plan file: root-level
  untracked `unmatch-users.py` + `log`/`user_log` (2026-08-17) are scratch
  output from fuzzy-matching unmatched `users.acronym` values against the
  proposals table (e.g. `'GA S03-117'` → `'GAS03-117'`). Not yet folded
  into the plan's design; worth checking in on before Phase 1 scoping.
- Root `TODO.md` (untracked, personal) — a broader "pre-process" list
  overlapping `to_duckdb/TODOs.md`'s overview-record section (signature,
  plateaux, lag) plus items not yet represented anywhere on this roadmap:
  S3 storage for raw operational data with a JS-frontend plotting
  demonstrator, power-installation PID/`Ivar` waterflow params, and
  busbar/pump heat-dissipation-into-room-volume calculations. None of these
  are backed by a plan file yet — flagging as a signal of where scope may
  expand next, not sizing them here.
- `PLAN_overview_records_pupitre_dedup.md` — **implemented and committed**
  (`290b114`, 2026-08-07), with a follow-up fix (`1e79d8a`, 2026-08-10).
  Covers the `TODOs.md` line *"concat entries that share one pupitre file."*
- `PLAN_hoop_stress_history.md` — **Phases 1–3 implemented, verified, and
  committed** (`e26e05b`/`c26d74f`/`c975a5d`, 2026-08-13). Phase 1 (compute
  pipeline correctness): real-data verification surfaced and fixed a chain
  of previously-hidden bugs beyond the original Bitter/Supra regex scope —
  see the plan file's "Phase 1 — done" section for the full list. Phase 2:
  Parquet columns renamed to part names. Phase 3: `part_history_stats()`/
  `build_part_history_series()` and the new `hoop-stress part-history`
  command; `experiments.status` now tracks hoop-stress completion
  (appended alongside `exp-stats compute`'s `STATS DONE`, not overwriting
  it); `--records-base` default inconsistency across hoop-stress
  subcommands fixed. Verified end-to-end against `test-magnetdb.duckdb`
  (72 experiments across 2 sites for one shared part; row counts and
  chronological ordering cross-checked against manual queries). Phases 4–5
  (per-part stats/fatigue tests, fatigue-additivity question) not yet
  started. Covers the `TODOs.md` stress line *"compute and persist
  hoop-stress bin stats + fatigue."*
- `PLAN_scheduled_populate.md` — **design sketch, not implemented**. Covers
  the `TODOs.md` line *"add a scheduler to run the above scripts on a
  regular basis."*
- `PLAN_econrj_parameter_inference.md` — **design sketch, not implemented**.
  Covers the `TODOs.md` line *"compute ECCO params."*
- `PLAN_populate_all.md` — **new (2026-08-12), design sketch, not
  implemented**. One composite `populate all` subcommand wrapping
  `experiments` → `overview-records` → `overview-records-infer`; feeds
  `PLAN_scheduled_populate.md`.
- `PLAN_users_multi_source.md` — **new, pending approval**, blocked on two
  unknowns (SUPERVISION DB schema, userdb API response shape). Covers the
  `TODOs.md` `userdb` section, which now links to it directly. Prep work
  already landed: users-table experiments/overview-records ID-linking
  (`b460c48`) and an EMFL-DB duplicate-acronym helper
  (`Data/find_duplicate_acronyms.py`, `118246c`).
- `overview-records-from-json` — **in progress** (`c5cfd7c`, 2026-08-11),
  not yet backed by a formal plan file.
- `notebook_review_import_housing_summary.md` — review notes (not a formal
  plan) with 3 concrete next steps, feeding the `userdb` TODO item.
- `PLAN_lifecycle_status.md` — **implemented, Phases A+B+C complete
  (2026-08-19)**. Covers the `TODOs.md` "New features" line *"work on life
  cycle of magnets and parts..."*. Assembly status is now derived from
  `decommissioned_at` (per-housing no-overlap; auto-close-on-add now fully
  cascades — closes the superseded assembly's `assembly_magnets` links and
  pushes its magnets to `in_stock`, not just a status flip). Magnet/part
  status defaults to `in_stock` on insert and is validated against
  `LifecycleStatus`; linking a magnet to an active assembly commissions it
  (and its parts) to `in_operation` — the one deliberate exception to "no
  upward cascade," resolved during implementation. A dead magnet requires
  naming at least one dead part in the same call; every entity carries an
  append-only `status_history` JSON log. New `assembly decommission`,
  `part view`/`update-status`, `magnet update-status` CLI subcommands, a
  `check --entity assembly` audit, and full test coverage. Documented in
  [to_duckdb/docs/schema.md](docs/schema.md#lifecycle) (with a mermaid
  diagram) and checked off in `TODOs.md`.
- `stage/dashboard/PLAN_dashboard_hierarchy_rework.md` — **new
  (2026-08-14), pending approval**. Covers the `TODOs.md` "New features"
  line *"rework dashboards to start with housing and then go down to
  magnet..."* — but only the hierarchy/navigation piece: `housing_stats`
  landing page, a new overview-records file-viewer page, site/magnet/part
  accordion links (Overview records + Experiments) and ordered history
  drill-downs, DB-wide summary counts. Deliberately excludes stress/fatigue
  linking, so unlike the original `TODOs.md` line it does **not** depend on
  the processing-status flag (Open Question 3, decided 2026-08-17 but not
  yet implemented) — that dependency now applies only to the
  stress/fatigue-linking remainder, still in `Later`.
  Adds `magnets.created_at` to `to_duckdb/schema.py`, which overlaps with
  `PLAN_lifecycle_status.md`'s planned `magnets`/`parts` schema changes —
  sequence the two together to avoid separate uncoordinated
  `ALTER TABLE magnets` passes. Also touches `site_stats.py` (nav/labels),
  which now also collides with `PLAN_site_to_assembly_rename.md` below —
  see that entry.
- `PLAN_site_to_assembly_rename.md` (repo root, not `to_duckdb`-local) —
  **Track A implemented and committed 2026-08-18** (see the snapshot entry
  above). Not triggered by a `TODOs.md` line — user-initiated terminology
  cleanup: the "Site"/`MSite` concept (a magnet geometry assembly, e.g.
  `"M9"`) has been renamed to `Assembly` across the whole ecosystem,
  because "site" collided with unrelated meanings in sibling packages
  (`housing`, a lab/geographic location, and the word "site" as in
  "website"). Full multi-repo plan lives in that file; **only the
  `to_duckdb`/`stage/dashboard` slice (its Phases 3–4) belongs on this
  roadmap**, and both have landed — Phases 1/2/5/6/7 touch
  `python_magnetgeo`, `python_magnetsetup`, `python_magnetrun`,
  `python_magnetcooling` (also all landed), and a "Track B" in
  `~/github/python_magnetdb`/`~/github/python_magnetapi` (separate repos,
  still deferred, no roadmap of their own currently).
  **Previously collided with two items on this roadmap — both resolved
  now that the rename has landed**:
  - `PLAN_lifecycle_status.md` (below, `Now`) has been updated to reference
    `Assembly`/`assemblies`/`assembly_magnets` throughout — see its own
    status line. Not yet implemented, but no longer at risk of being
    written under vocabulary that would need renaming again immediately.
  - `PLAN_dashboard_hierarchy_rework.md` (above, `Next`, pending approval)
    was already rewritten to `Assembly` vocabulary as part of the rename's
    Phase 4 commit (`c111577`) — it edits `assembly_stats.py` (the renamed
    `site_stats.py`), touched exactly once, under the new vocabulary.

## Phase: Now — scoped, ready to execute

| Item | Effort | Notes |
|---|---|---|
| Execute `PLAN_hoop_stress_history.md` Phases 4–5 | S–M | **Done — implemented, verified, and committed 2026-08-18** (`00f8636`), on top of Phases 1–3 (committed 2026-08-13). Phase 4: full-suite re-verification (34/34 `-k hoop`, `test_stress_map.py` 12/12) and a real-DB cross-check against `test-magnetdb.duckdb` (part `H21102801`, 71 experiments) — see `PLAN_hoop_stress_per_part_tests.md`. Phase 5 (fatigue-additivity question): checked against 3 real parts/71 experiments (`sum_range3` additive to float precision, `n_cycles` has a small ~0.003% boundary-residual discrepancy), 2 new tests, finding documented in `docs/hoop-stress.md` — see `PLAN_hoop_stress_fatigue_additivity.md`. Note: both of those per-phase plan files still say "uncommitted" in their own status lines — that wording is stale, `git log`/`git status` confirm the code and tests landed in `00f8636`. |
| Housing-summary notebook fixes | S | Partially done, **uncommitted**: `h.site`→`h.housing` fix in cell `1387a3c9` and a full top-to-bottom re-run (large diff, `638 insertions(+), 380 deletions(-)`) are both present in the current working-tree edit of `stage/import_housing_summary.ipynb`, but not yet committed. Still open: deciding the fate of the `PROPOSALS` dead-end section (`Magnet Sites` column still entirely null) — that section is untouched by the re-run. |
| Site→Assembly rename — `to_duckdb`/dashboard slice (`PLAN_site_to_assembly_rename.md` Phases 3–4) | M | **Done — implemented and committed 2026-08-18** (`78a288c`, `c111577`), landed in under a day. `PLAN_lifecycle_status.md` below has been updated to reference `Assembly`/`assemblies`/`assembly_magnets` directly, so it no longer needs to write `sites`/`site_magnets` code first. Rest of the original plan (`python_magnetgeo`/`python_magnetsetup`/`python_magnetrun`/`python_magnetcooling` — also all landed the same day, see `PLAN_site_to_assembly_rename.md` — plus the separate-repo `python_magnetdb`/`python_magnetapi` backport) was outside this roadmap's scope; Track B remains deferred. |
| Execute `PLAN_lifecycle_status.md` | L | **Done — implemented, verified, and committed 2026-08-19.** All three phases landed in one pass: assembly status derivation/overlap/auto-close + cascades (Phase A), magnet/part status defaults/validation/commissioning-cascade/dead-invariant + CLI (Phase B), `docs/schema.md` lifecycle section + `TODOs.md` checkoff (Phase C). Full test suite green throughout. |

## Phase: Next — needs a short scoping pass, or has a design sketch with opens to close

| Item | Effort | Notes |
|---|---|---|
| Dashboard hierarchy rework (`stage/dashboard/PLAN_dashboard_hierarchy_rework.md`) | M | Pending approval, but not blocked on anything else in this roadmap — scoped independently of the processing-status flag/hoop-stress dependency that gates the stress/fatigue-linking remainder in `Later`. Touches `to_duckdb/schema.py` (`magnets.created_at`) — sequence with `PLAN_lifecycle_status.md`'s magnet/part schema work to avoid duplicate migrations. Also edits `assembly_stats.py` (the renamed `site_stats.py`) — the
  `Now`-phase Site→Assembly rename has already landed (2026-08-18) and this
  plan was updated to the new vocabulary as part of that commit, so no
  further sequencing is needed here. **New:** an untracked draft `/overviews` page (`stage/dashboard/src/pages/overview-record.py`) already exists and overlaps this plan's overview-record viewer item — reconcile before formal approval/implementation so the draft isn't duplicated or lost. |
| overview-record: signature (Field for classification, Ref currents for ODE, A1–A2/Iddct1–4 for lag) | M | Builds on the now-committed dedup schema. Signature and lag are related — worth scoping together. |
| overview-record: lag | M | Blocked on open question 1 below — sharpened 2026-08-17: two working lag implementations already exist (`python_magnetrun/analysis/synchronization.py`'s `compute_lag`/`compute_lag_interpolated`, already wired to `overview_records.sync_info` but switched off by default; Wolali's FFT-cross-correlation `get_lag()` in `stage/dashboard/tests/lag_test*.py`, validated but not wired in). Needs a head-to-head comparison (tooling for it already exists), not a design discussion. |
| overview-record: plateaux | S–M | **Direction decided 2026-08-17** — `nplateaus()` over `sources_pupitre`/`sources_overview` into the already-reserved `overview_records.plateaux` column, adapting the existing `get_plateaux_per_pupitre()` prototype (see Open Question 2). Downgraded from `M` since the algorithm, storage column, and a near-complete prototype already exist; kept at S–M rather than S because per-source threshold tuning and the one-file-vs-row-list decision (see Open Question 2) still need closing first. |
| `overview-records-from-json` completion | S | In progress since 2026-08-11 (`c5cfd7c`); finish and land the accompanying `test_magnetdb.py` coverage already started. |
| `populate all` composite (`PLAN_populate_all.md`) | S | Design is concrete (wraps `experiments`→`overview-records`→`overview-records-infer` in one process invocation). Sequence after the items above and `PLAN_hoop_stress_history.md` land, since it wraps those exact commands. Two small opens carried from that plan (see below). |
| userdb: pluggable sources (`PLAN_users_multi_source.md`) | M | Phase 1 (refactor `build_users` for pluggability) is buildable now, no unknowns. Phases 2–3 (SUPERVISION MySQL loader, userdb API loader) are blocked on schema/response-shape access — see that plan's open questions, carried below. Resolves the housing-summary notebook's dead end (current CSV export has `Magnet Sites` entirely null) once the API loader lands. Active scratch investigation already underway (root `unmatch-users.py`/`log`/`user_log`, 2026-08-17) fuzzy-matching unmatched acronyms against proposals — not yet folded into the plan. |
| Processing-status flag on experiments/overview-records | M | **Design decided 2026-08-17** — per-stage timestamp columns (e.g. `stress_processed_at`, `fatigue_processed_at`), not a single tombstone-style column (see Open Question 3). No longer blocked on the design choice, just sequencing: land after `PLAN_hoop_stress_history.md` so the columns' naming matches the finished pipeline's actual stages. Still needs its own plan file (exact column set, which tables, who sets each timestamp). |
| Scheduler (`PLAN_scheduled_populate.md`) | S–M | Design is concrete (systemd timer + `--settle-seconds` threaded through `scan_tdms_subdir`). Sequence after `PLAN_hoop_stress_history.md` lands, since it schedules exactly those scripts (dedup already landed). Opens carried from that plan (see below). |
| EcoNRJ parameter inference (`PLAN_econrj_parameter_inference.md`) | M | Fitting recipe and implementation checklist already exist, wraps `piecewise_regression` on `python_magnetrun/examples/corr_Ih_Ib.py`. Independent of the duckdb/dashboard track — can run in parallel. Opens carried from that plan (see below). |
| Dashboard comparison-page performance (`stage/dashboard/PERFORMANCE_PLAN.md`) | S | **New (2026-08-17), no plan approval recorded yet.** Concrete, self-contained design: shared on-disk Parquet cache fixes duplicate re-parsing (19–192s per pair-graph today) and cross-callback cache misses; expected warm-run time < 2s. No dependencies on other roadmap items. |

## Phase: Later — larger scope, external dependencies, or currently underspecified

| Item | Effort | Why it's later |
|---|---|---|
| Dashboard rework: stress/fatigue linking (remaining piece — hierarchy/navigation and the overview-records viewer moved to `Next`, see `PLAN_dashboard_hierarchy_rework.md`) | M | Blocked on the processing-status flag landing (design decided 2026-08-17 — per-stage timestamp columns, see Open Question 3 — but not yet implemented) and `PLAN_hoop_stress_history.md` Phases 4–5. |
| Commissioning data structure (site/assembly → propagate to magnets) in duckdb | L | New schema domain; touches the same site/housing concepts as the userdb work, sequence after userdb reduces rework. |
| Cooling models (M1 student's primary heat-exchanger work) | M | External dependency — availability/completeness of that student's models isn't in your control. |
| Fix/update `python_magnetrun/examples/bilan.py` | ? | Needs a look at current state before it can be sized. |
| Update numerical commissioning | ? | Bare TODO line, no spec yet. |
| duckdb schema cleanup | ? | New `TODOs.md` section: update schema to reflect the overview-record changes above, and drop unneeded `operationaldata` table + `sum_x2_dt` columns (hoop proxy). Also a candidate: `magnets.geometry_data` — vestigial under the hoop-stress pipeline's on-the-fly-from-parts design (magnet/site geometry is always rebuilt from `parts.geometry_data`; see `docs/hoop-stress.md`); still has real writers (`magnet add --geometry`, `check --fix`) so dropping it needs its own scoping pass, not bundled into `PLAN_hoop_stress_history.md`. Needs a look at current schema usage before sizing. |
| Site/assembly setup for M7, M8 (`hifimagnet-projects`) | ? | Cross-project link, cf. cahier E. Verney. Not yet scoped in this repo. |
| Field validation stats for M8–M10 | ? | Review `Field == Supra_Field + Total_Field` per Xavier's M9/M10 experience; watch for early hybrid-test records where `Supra_Field` was hardcoded. |
| Pre-2022 pigbrother data | ? | Open question, not yet scoped — availability/usability unknown. |
| Special-experiment handling | ? | e.g. M19 (M9 at 18 MW + M10 at 10 MW simultaneously), Mateo's experiments with negative IH/IB current — needs a design for how these fit the standard schema. |

## Rough Timeline (dev capacity assumption)

**Assumptions:** 1 developer, part-time (~1–2 days/week), starting
2026-08-18. This converts the effort labels above (relative, not calendar
time) into elapsed calendar windows at that pace — treat every date as
rough, not a commitment. Items blocked on an open question or external
access get no calendar slot until that blocker clears.

Effort → elapsed time at this pace:

| Effort | Elapsed time |
|---|---|
| S | ~2 weeks |
| S–M | ~3 weeks |
| M | ~4 weeks |
| L | ~10–12 weeks |
| ? | not sizeable yet |

### Now (Aug 2026 – late Dec 2026)

| Item | Window |
|---|---|
| Hoop-stress Phases 4–5 | **Done — landed 2026-08-18** | Landed same-day, ~3 weeks ahead of this window. |
| Housing-summary notebook fixes | **Mostly done, uncommitted** | 2 of 3 items done in the working tree (2026-08-18); `PROPOSALS` section fate still open. |
| Site→Assembly rename (`to_duckdb`/dashboard slice) | **Done — landed 2026-08-18** | Landed same-day, ~5 weeks ahead of this window. |
| `PLAN_lifecycle_status.md` | **Done — landed 2026-08-19** | Landed same-pass, ~9 weeks ahead of this window. |

### Next — unblocked items (late Aug 2026 – late Feb 2027)

| Item | Window |
|---|---|
| Dashboard hierarchy rework | late Aug – late Sep |
| `overview-records-from-json` completion | late Sep – early Oct |
| `populate all` composite | early Oct – mid-Oct |
| userdb Phase 1 (pluggability refactor only) | mid-Oct – early Nov |
| Scheduler | early Nov – late Nov |
| EcoNRJ parameter inference | late Nov – late Dec |
| Dashboard comparison-page performance | late Dec – early Jan |
| Processing-status flag (design decided 2026-08-17; needs its own plan file, then sequence after hoop-stress) | early Jan – early Feb |
| overview-record: plateaux (direction decided 2026-08-17; a few small implementation details to close first, see Open Question 2) | early Feb – late Feb |

### Next — blocked on an open question or external access (no calendar slot yet)

| Item | Size once unblocked | Blocker |
|---|---|---|
| Signature + lag (scoped together) | ~M + M (~8wk) | Open Question 1 — sharpened 2026-08-17 to "run the Side A vs. Side B lag comparison in `PLAN_signature_regime_robustness.md`'s scope, then wire the winner into `to_duckdb` and flip `compute_lag` on" (see Open Questions below) |
| userdb Phases 2–3 (SUPERVISION/API loaders) | unsized | SUPERVISION DB schema access, userdb API response shape |

### Later

Still mostly `?` effort — not sizeable at this granularity. At this pace,
realistically doesn't start before ~early 2027, once the Next-phase backlog
above clears. Revisit sizing once Now/Next close out.

## Open Questions (former finalization blockers — now scoped)

### 1. Lag — sharpened (2026-08-17): pick the more robust of two working implementations, then wire it in

`TODOs.md` lists lag under overview-record with only *"see Wolali and Me"* —
no summary of that discussion was captured anywhere in this repo. That
originally read as "no definition exists yet." It's actually the opposite
problem: **two** implementations already exist and compute lag differently;
the open question is which one to trust, not what lag should mean.

**Side A — "envisioned," already wired to the DB but switched off.**
`python_magnetrun/analysis/synchronization.py`'s `compute_lag()`
("resample_1s": correct when the pigbrother source is ~1 Hz Overview data,
imprecise otherwise) and `compute_lag_interpolated()` (interpolates both
series onto a common fine grid first, giving correct sub-second precision
against 120 Hz Archive data too — see `field_comparison.py`'s
`lag_method` doc). `_compute_lag_correlation()`
(`analysis/processing.py:1145-1192`) already calls `compute_lag()` and
writes `sync_info["lag_<key>"]`/`sync_info["lag_<key>_seconds"]` onto
`OverviewRecord.sync_info`, which `to_duckdb/crud.py` already inserts
straight into the `overview_records.sync_info` JSON column
(`schema.py:153`) — the plumbing is complete end to end. The catch:
`ProcessingConfig.compute_lag` defaults to `False`
(`analysis/processing.py:125`), and `to_duckdb/magnetdb.py`'s
`overview-records` populate call (`magnetdb.py:968`) constructs
`ProcessingConfig` with no override, so this path has never actually run
in production. `synchronize=True` *is* the default, so
`sync_info["timeshift"]`/`["timeshift_seconds"]` (a coarser, different
computation via `synchronize_data()`) likely already exists on populated
rows today — but not the per-channel cross-correlation lag.

**Side B — Wolali's approach, validated but not wired to the DB.** A
shared `get_lag()` (FFT cross-correlation on normalized derivatives),
implemented identically across three new decision-support scripts in
`stage/dashboard/tests/`: `lag_test_file.py` (explicit file args),
`lag_test.py` (reads a real `overview_records` row's
`sources_pupitre`/`sources_overview`/`sources_archive` straight from the
DuckDB table — both merged-across-files and per-file-pair variants), and
`lag_test_discovery.py` (disk auto-discovery via `FileDiscovery`, no DB).
This is the same approach her thesis (`Koffi-Wolali.tex`, filled in as of
`a053155`) validated with RMSE/MAE/Pearson correlation. These scripts exist
specifically to run Side A vs. Side B against real data — that comparison
hasn't been run yet, as far as anything in this repo shows.

**Scope home:** `stage/dashboard/PLAN_signature_regime_robustness.md`
(methodology approved 2026-08-11, revised 2026-08-12) — its "Existing
tooling to build on" section already cites both `synchronization.py`'s
`find_best_matching_regime`/`check_lag_reliability` (Side A's neighborhood)
and `lag_test_discovery.py` (Side B), so this comparison is part of that
plan's remit rather than a separate question. That plan's own Tier
1/2 metrics (stability, cross-system regime agreement) are a reasonable
basis for the comparison, on the small varied file set its Step 1 already
calls for.

**Needed, to close this out:**
1. Run Side A vs. Side B on a few real file pairs (varied: clean profile,
   fast-oscillation profile, a second acquisition session) and pick a
   winner — or confirm they agree closely enough that it doesn't matter.
2. Wire the winner into `_compute_lag_correlation()` (or call the
   dashboard's `get_lag()` from the `to_duckdb` pipeline directly) and flip
   `compute_lag=True` in `to_duckdb/magnetdb.py`'s populate call (likely
   worth a CLI flag rather than an unconditional default, given it's
   presumably slower per file).
3. Backfill `sync_info` for rows already populated before this lands, since
   they currently have `timeshift` but not `lag_<key>`.

### 2. Plateaux — direction decided (2026-08-17), a few implementation details remain

`TODOs.md` has only the bare word *"plateaux"* under overview-record, with
no detection criteria, source signal, or downstream consumer specified.

**Decided:** detect plateaux in the magnetic field using `nplateaus()`
(`python_magnetrun/processing/plateaux.py`), sourced from either
`sources_pupitre` (pupitre `Field` column, tesla) or `sources_overview`
(pigbrother `Courants_Alimentations/Champ_magn`, millitesla) attached to
each `overview_records` row — the two are already cross-referenced via each
format's `aliases` entry. Output goes into the existing (currently unused)
`overview_records.plateaux` JSON column. `nplateaus()` already returns a
list of `{"start", "end", "value"}` dicts per file, and a working prototype
already does almost exactly this shape of iteration —
`get_plateaux_per_pupitre()` in `stage/dashboard/tests/lag_test_discovery.py`
— just for pupitre only, and living in a dashboard test script rather than
`to_duckdb`.

**Still open** before this can move to a formal plan:
- **Per-source threshold tuning.** `nplateaus()`'s defaults
  (`threshold=2.0e-2`, `num_points_threshold=600`) were evidently tuned
  against one source's units/sampling rate. Pupitre `Field` is in tesla and
  pigbrother `Champ_magn` is in millitesla — a 1000x scale difference — so
  the same `threshold` value would behave very differently on the two
  sources; each likely needs its own tuned value (and possibly its own
  `num_points_threshold`, given pigbrother's much higher sampling rate).
- **`nplateaus()`'s matplotlib side effects.** It unconditionally builds a
  full plot (`plt.plot`/`plt.legend`/`plt.grid`, closed at the end via
  `plt.close()`) even when called with `show=False, save=False` — fine for
  interactive/exploratory use, wasteful when run in a batch backfill over
  every `overview_records` row. Worth a small refactor (or a
  plotting-optional fast path) before wiring this into a populate command,
  especially alongside the dashboard's own `PERFORMANCE_PLAN.md` (above)
  which is already fixing a related "redundant repeated work per callback"
  problem.
- **One file vs. a row's full source list.** `sources_pupitre`/
  `sources_overview` are arrays — a row can have multiple files (see
  `PLAN_overview_records_pupitre_dedup.md`, which already handles the
  "multiple pupitre files share one row" case for other columns). Undecided
  whether `plateaux` should store one list of plateau-dicts per file (array
  of arrays, keyed by filename) or concatenate/dedupe across a row's files
  the way `part_history` does for hoop-stress — needs a small decision, not
  a full design pass.

### 3. Processing-status flag — decided (2026-08-17): per-stage timestamp columns

Two concrete options were on the table for tracking what processing
(stress, fatigue, etc.) has been done on an experiment/overview-record:

- **Single nullable tombstone-style column** — following the `merged_into`
  pattern from `PLAN_overview_records_pupitre_dedup.md` (e.g. a
  `processing_status` column, NULL/value meaning unprocessed/processed).
  Simple, but doesn't distinguish which stages ran if there end up being
  more than one (stress vs. fatigue vs. future additions).
- **Per-stage timestamp columns** — e.g. `stress_processed_at`,
  `fatigue_processed_at`, one per pipeline stage. More columns, but each
  stage's status and recency is independently queryable, and it composes
  better once `PLAN_hoop_stress_history.md`'s `part-history` command and the
  dashboard rework need to know "is this specific stage done."

**Decided:** per-stage timestamp columns. Design choice made, not yet
implemented and not yet backed by its own plan file — writing that plan
(exact column set, which tables, how each stage's compute path sets its
timestamp) is now unblocked and can proceed. Still worth sequencing after
`PLAN_hoop_stress_history.md` lands (see the `Next`-phase table) so the
`stress_processed_at`/`fatigue_processed_at` naming matches the finished
pipeline's actual stage boundaries rather than guessing ahead of it. This
choice affects both the `overview_records`/`experiments` schema and the
later dashboard rework (which needs to display per-stage status).

### Carried-forward opens from existing design-sketch plans

These are not duplicated in full here — see the referenced plan files:

- **`PLAN_scheduled_populate.md`**: default `--settle-seconds` value (needs
  measuring actual TDMS write/flush timing), ingest→infer timer offset,
  whether `populate experiments`/`operationaldata` need the same
  `--settle-seconds` flag, where systemd unit files should live in the repo.
- **`PLAN_econrj_parameter_inference.md`**: whether `Tr` means the Helix
  current at threshold or the threshold field `BTr` itself (needs
  cross-checking against a real site config), and whether the fit should be
  done per-site, per-housing, or per-run.
- **`PLAN_populate_all.md`**: whether per-file errors should be promoted to
  a hard failure for the scheduled/email-notification use case, and whether
  `--reprocess` should apply uniformly across all three wrapped phases or
  needs independent control.
- **`PLAN_users_multi_source.md`**: SUPERVISION DB schema access (no host,
  database, table, or column names exist in this repo), userdb API response
  shape (no sample JSON body available), the source-combination model (does
  `-from-mysql`/`-from-api` swap only one side, or is a both-live mode
  needed), cutoff pushdown (server-side filter vs. client-side), and
  credential env-var naming.
