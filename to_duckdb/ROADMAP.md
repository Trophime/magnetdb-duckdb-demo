# to_duckdb — Roadmap

Status: draft — 3 open questions block finalization (see "Open Questions" below)

Phased roadmap synthesizing `TODOs.md` plus the planning discussions that
produced `PLAN_overview_records_pupitre_dedup.md`, `PLAN_hoop_stress_history.md`,
`PLAN_scheduled_populate.md`, `PLAN_econrj_parameter_inference.md`,
`PLAN_users_multi_source.md`, and `PLAN_populate_all.md`. Phases are ordered
by dependency, not calendar date; effort is relative (S = small, M = medium,
L = large, ? = not yet sizeable).

## Snapshot (2026-08-14)

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
- `PLAN_lifecycle_status.md` — **approved (2026-08-14), not yet
  implemented**. Covers the `TODOs.md` "New features" line *"work on life
  cycle of magnets and parts..."*. Scope grew during scoping to include
  `sites` (derived status from `decommissioned_at`, per-housing no-overlap,
  auto-close-on-add) since site disassembly is what triggers the
  magnet→part status cascade; also touches `magnets`/`parts` status
  validation, a `status_history` JSON log on all three tables, and a
  dead-magnet-requires-a-dead-part invariant. Two small flagged assumptions
  carried into implementation as current defaults (see the plan's own
  "Assumptions & open questions" and the carried-forward opens below).
- `stage/dashboard/PLAN_dashboard_hierarchy_rework.md` — **new
  (2026-08-14), pending approval**. Covers the `TODOs.md` "New features"
  line *"rework dashboards to start with housing and then go down to
  magnet..."* — but only the hierarchy/navigation piece: `housing_stats`
  landing page, a new overview-records file-viewer page, site/magnet/part
  accordion links (Overview records + Experiments) and ordered history
  drill-downs, DB-wide summary counts. Deliberately excludes stress/fatigue
  linking, so unlike the original `TODOs.md` line it does **not** depend on
  Open Question 3 (processing-status flag) below — that dependency now
  applies only to the stress/fatigue-linking remainder, still in `Later`.
  Adds `magnets.created_at` to `to_duckdb/schema.py`, which overlaps with
  `PLAN_lifecycle_status.md`'s planned `magnets`/`parts` schema changes —
  sequence the two together to avoid separate uncoordinated
  `ALTER TABLE magnets` passes. Also touches `site_stats.py` (nav/labels),
  which now also collides with `PLAN_site_to_assembly_rename.md` below —
  see that entry.
- `PLAN_site_to_assembly_rename.md` (repo root, not `to_duckdb`-local) —
  **new (2026-08-14), pending approval**. Not triggered by a `TODOs.md`
  line — user-initiated terminology cleanup: the "Site"/`MSite` concept
  (a magnet geometry assembly, e.g. `"M9"`) is being renamed to `Assembly`
  across the whole ecosystem, because "site" collides with unrelated
  meanings in sibling packages (`housing`, a lab/geographic location, and
  the word "site" as in "website"). Full multi-repo plan lives in that
  file; **only the `to_duckdb`/`stage/dashboard` slice (its Phases 3–4)
  belongs on this roadmap** — Phases 1/2/5/6/7 touch `python_magnetgeo`,
  `python_magnetsetup`, `python_magnetrun`, `python_magnetcooling`, and a
  "Track B" in `~/github/python_magnetdb`/`~/github/python_magnetapi`
  (separate repos, backported later, no roadmap of their own currently).
  **Directly collides with two items already in this roadmap**:
  - `PLAN_lifecycle_status.md` (below, `Now`, approved but not yet
    implemented) adds substantial *new* `sites`/`site_magnets` surface —
    a `SiteStatus` enum, `decommission_site()`, `check_sites()`, a
    `magnetdb.py site decommission` subcommand, `"site"` added to
    `check --entity` choices — none of which exists yet. Writing that
    today under the old vocabulary just means renaming it again almost
    immediately. Recommend implementing `PLAN_lifecycle_status.md`
    directly against `Assembly`/`assemblies`/`assembly_magnets` naming
    from the start, i.e. do (or at least lock in the naming from) the
    `to_duckdb` schema/CRUD rename first, or fold the two into one
    coordinated pass.
  - `PLAN_dashboard_hierarchy_rework.md` (above, `Next`, pending approval)
    edits `site_stats.py` — same file the rename's Phase 4 touches
    (ids, labels, query functions). Sequence so that file is only touched
    once.

## Phase: Now — scoped, ready to execute

| Item | Effort | Notes |
|---|---|---|
| Execute `PLAN_hoop_stress_history.md` Phases 4–5 | S–M | Phases 1–3 implemented, verified, and committed 2026-08-13 (compute pipeline correctness, Parquet part-name columns, `part-history` command). Remaining: per-part stats/fatigue tests (Phase 4), fatigue-additivity question (Phase 5). |
| Housing-summary notebook fixes | S | Fix `h.site`→`h.housing` in cell `1387a3c9` (still present as of 2026-08-13); re-run notebook end-to-end for consistent outputs; decide fate of the `PROPOSALS` dead-end section. |
| Site→Assembly rename — `to_duckdb`/dashboard slice (`PLAN_site_to_assembly_rename.md` Phases 3–4) | M | Pending approval. Recommend sequencing **before or together with** `PLAN_lifecycle_status.md` below — that plan is about to add new `sites`/`site_magnets` code (`SiteStatus` enum, `decommission_site()`, `check_sites()`, `site decommission` CLI) that doesn't exist yet; better to write it once, directly as `Assembly`/`assemblies`/`assembly_magnets`, than rename it again immediately after. Rest of that plan (`python_magnetgeo`/`python_magnetsetup`/`python_magnetrun`/`python_magnetcooling`, plus the separate-repo `python_magnetdb`/`python_magnetapi` backport) is outside this roadmap's scope. |
| Execute `PLAN_lifecycle_status.md` | L | Approved 2026-08-14. Phase A (site lifecycle) → Phase B (magnet/part status + cascades) → Phase C (docs/cleanup); no external unknowns, two small opens carried as defaults (see plan). **Sequencing note:** see the rename row above — worth deciding vocabulary before writing Phase A's new `sites`-table code. |

## Phase: Next — needs a short scoping pass, or has a design sketch with opens to close

| Item | Effort | Notes |
|---|---|---|
| Dashboard hierarchy rework (`stage/dashboard/PLAN_dashboard_hierarchy_rework.md`) | M | Pending approval, but not blocked on anything else in this roadmap — scoped independently of the processing-status flag/hoop-stress dependency that gates the stress/fatigue-linking remainder in `Later`. Touches `to_duckdb/schema.py` (`magnets.created_at`) — sequence with `PLAN_lifecycle_status.md`'s magnet/part schema work to avoid duplicate migrations. Also edits `site_stats.py` — sequence after the `Now`-phase Site→Assembly rename lands so that file isn't touched under both vocabularies. |
| overview-record: signature (Field for classification, Ref currents for ODE, A1–A2/Iddct1–4 for lag) | M | Builds on the now-committed dedup schema. Signature and lag are related — worth scoping together. |
| overview-record: lag | M | Blocked on open question 1 below. |
| overview-record: plateaux | M | Blocked on open question 2 below. |
| `overview-records-from-json` completion | S | In progress since 2026-08-11 (`c5cfd7c`); finish and land the accompanying `test_magnetdb.py` coverage already started. |
| `populate all` composite (`PLAN_populate_all.md`) | S | Design is concrete (wraps `experiments`→`overview-records`→`overview-records-infer` in one process invocation). Sequence after the items above and `PLAN_hoop_stress_history.md` land, since it wraps those exact commands. Two small opens carried from that plan (see below). |
| userdb: pluggable sources (`PLAN_users_multi_source.md`) | M | Phase 1 (refactor `build_users` for pluggability) is buildable now, no unknowns. Phases 2–3 (SUPERVISION MySQL loader, userdb API loader) are blocked on schema/response-shape access — see that plan's open questions, carried below. Resolves the housing-summary notebook's dead end (current CSV export has `Magnet Sites` entirely null) once the API loader lands. |
| Processing-status flag on experiments/overview-records | M | Sequence after `PLAN_hoop_stress_history.md` lands, so the flag's vocabulary matches the finished pipeline. Design blocked on open question 3 below. |
| Scheduler (`PLAN_scheduled_populate.md`) | S–M | Design is concrete (systemd timer + `--settle-seconds` threaded through `scan_tdms_subdir`). Sequence after `PLAN_hoop_stress_history.md` lands, since it schedules exactly those scripts (dedup already landed). Opens carried from that plan (see below). |
| EcoNRJ parameter inference (`PLAN_econrj_parameter_inference.md`) | M | Fitting recipe and implementation checklist already exist, wraps `piecewise_regression` on `python_magnetrun/examples/corr_Ih_Ib.py`. Independent of the duckdb/dashboard track — can run in parallel. Opens carried from that plan (see below). |

## Phase: Later — larger scope, external dependencies, or currently underspecified

| Item | Effort | Why it's later |
|---|---|---|
| Dashboard rework: stress/fatigue linking (remaining piece — hierarchy/navigation and the overview-records viewer moved to `Next`, see `PLAN_dashboard_hierarchy_rework.md`) | M | Blocked on the processing-status flag (Open Question 3) and `PLAN_hoop_stress_history.md` Phases 4–5. |
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
| Hoop-stress Phases 4–5 | Aug 18 – Sep 8 |
| Housing-summary notebook fixes | Sep 8 – Sep 22 |
| Site→Assembly rename (`to_duckdb`/dashboard slice) | Sep 22 – Oct 20 |
| `PLAN_lifecycle_status.md` | Oct 20 – late Dec | Largest single item (L); dominates this phase. |

### Next — unblocked items (late Dec 2026 – late Apr 2027)

| Item | Window |
|---|---|
| Dashboard hierarchy rework | late Dec – late Jan |
| `overview-records-from-json` completion | late Jan – early Feb |
| `populate all` composite | early Feb – late Feb |
| userdb Phase 1 (pluggability refactor only) | late Feb – mid-Mar |
| Scheduler | mid-Mar – late Mar |
| EcoNRJ parameter inference | late Mar – late Apr |

### Next — blocked on an open question or external access (no calendar slot yet)

| Item | Size once unblocked | Blocker |
|---|---|---|
| Signature + lag (scoped together) | ~M + M (~8wk) | Open Question 1 — Wolali discussion outcome |
| Plateaux | ~M (~4wk) | Open Question 2 — needs a definition |
| Processing-status flag | ~M (~4wk) | Open Question 3 — design choice |
| userdb Phases 2–3 (SUPERVISION/API loaders) | unsized | SUPERVISION DB schema access, userdb API response shape |

### Later

Still mostly `?` effort — not sizeable at this granularity. At this pace,
realistically doesn't start before ~mid-2027, once the Next-phase backlog
above clears. Revisit sizing once Now/Next close out.

## Open Questions (blocking finalization)

### 1. Lag — needs the Wolali discussion's outcome

`TODOs.md` lists lag under overview-record with only *"see Wolali and Me"* —
no summary of that discussion is captured anywhere in this repo. Per
`TODOs.md`'s signature section, the relevant source columns are already
identified (currents A1 to A2 from pigbrother, and Iddct1 to Iddct4), but
what "lag" should actually compute from them (a time offset? a fitted decay
constant? something else) is undefined. This blocks writing any plan for the
lag item, and indirectly blocks fully scoping the signature item since the
two share source columns. **Needed:** a summary of the Wolali conversation,
or a fresh conversation with them, before this can move to "Now."

Related but separate track: `stage/dashboard/PLAN_signature_regime_robustness.md`
(methodology approved 2026-08-11, revised 2026-08-12) is characterizing
signature-regime detection for pupitre/pigbrother sync QA, and may inform
what "lag" should compute — but it lives in a different subproject and
doesn't itself resolve this question.

### 2. Plateaux — needs a definition

`TODOs.md` has only the bare word *"plateaux"* under overview-record, with
no detection criteria, source signal, or downstream consumer specified.
**Needed:** what counts as a plateau (e.g. a field/current stability window
above some duration/tolerance threshold), which signal it's detected on, and
what it should be recorded as (a count? start/end timestamps? a JSON list
per overview-record row, similar to how other JSON columns are handled?).

### 3. Processing-status flag — needs a design choice

Two concrete options for tracking what processing (stress, fatigue, etc.)
has been done on an experiment/overview-record:

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

This choice affects both the `overview_records`/`experiments` schema and the
later dashboard rework (which needs to display per-stage status), so it's
worth deciding before either of those is scoped further.

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
- **`PLAN_lifecycle_status.md`**: whether `site_magnets.decommissioned_at`
  should auto-close alongside the site's own `decommissioned_at` during a
  disassembly cascade (added during scoping, not explicitly requested), and
  whether linking a magnet to a site (or a part to a magnet) should ever
  auto-promote status upward — current design says no, only explicit
  `update-status` calls move status up.
