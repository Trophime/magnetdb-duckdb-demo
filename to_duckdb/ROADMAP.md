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

## Phase: Now — scoped, ready to execute

| Item | Effort | Notes |
|---|---|---|
| Execute `PLAN_hoop_stress_history.md` Phases 4–5 | S–M | Phases 1–3 implemented, verified, and committed 2026-08-13 (compute pipeline correctness, Parquet part-name columns, `part-history` command). Remaining: per-part stats/fatigue tests (Phase 4), fatigue-additivity question (Phase 5). |
| Housing-summary notebook fixes | S | Fix `h.site`→`h.housing` in cell `1387a3c9` (still present as of 2026-08-13); re-run notebook end-to-end for consistent outputs; decide fate of the `PROPOSALS` dead-end section. |
| Execute `PLAN_lifecycle_status.md` | L | Approved 2026-08-14. Phase A (site lifecycle) → Phase B (magnet/part status + cascades) → Phase C (docs/cleanup); no external unknowns, two small opens carried as defaults (see plan). |

## Phase: Next — needs a short scoping pass, or has a design sketch with opens to close

| Item | Effort | Notes |
|---|---|---|
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
| Dashboard rework (housing → magnet, linked to overview-records/stress/fatigue) | L | Capstone/integration item — blocked on the processing-status flag and hoop-stress history existing first. |
| Commissioning data structure (site/assembly → propagate to magnets) in duckdb | L | New schema domain; touches the same site/housing concepts as the userdb work, sequence after userdb reduces rework. |
| Cooling models (M1 student's primary heat-exchanger work) | M | External dependency — availability/completeness of that student's models isn't in your control. |
| Fix/update `python_magnetrun/examples/bilan.py` | ? | Needs a look at current state before it can be sized. |
| Update numerical commissioning | ? | Bare TODO line, no spec yet. |
| duckdb schema cleanup | ? | New `TODOs.md` section: update schema to reflect the overview-record changes above, and drop unneeded `operationaldata` table + `sum_x2_dt` columns (hoop proxy). Also a candidate: `magnets.geometry_data` — vestigial under the hoop-stress pipeline's on-the-fly-from-parts design (magnet/site geometry is always rebuilt from `parts.geometry_data`; see `docs/hoop-stress.md`); still has real writers (`magnet add --geometry`, `check --fix`) so dropping it needs its own scoping pass, not bundled into `PLAN_hoop_stress_history.md`. Needs a look at current schema usage before sizing. |
| Site/assembly setup for M7, M8 (`hifimagnet-projects`) | ? | Cross-project link, cf. cahier E. Verney. Not yet scoped in this repo. |
| Field validation stats for M8–M10 | ? | Review `Field == Supra_Field + Total_Field` per Xavier's M9/M10 experience; watch for early hybrid-test records where `Supra_Field` was hardcoded. |
| Pre-2022 pigbrother data | ? | Open question, not yet scoped — availability/usability unknown. |
| Special-experiment handling | ? | e.g. M19 (M9 at 18 MW + M10 at 10 MW simultaneously), Mateo's experiments with negative IH/IB current — needs a design for how these fit the standard schema. |

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
