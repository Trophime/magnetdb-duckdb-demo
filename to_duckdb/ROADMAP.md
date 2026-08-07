# to_duckdb — Roadmap

Status: draft — 3 open questions block finalization (see "Open Questions" below)

Phased roadmap synthesizing `TODOs.md` plus the planning discussions that
produced `PLAN_overview_records_pupitre_dedup.md`, `PLAN_hoop_stress_history.md`,
`PLAN_scheduled_populate.md`, and `PLAN_econrj_parameter_inference.md`. Phases
are ordered by dependency, not calendar date; effort is relative
(S = small, M = medium, L = large, ? = not yet sizeable).

## Snapshot (2026-08-07)

- `PLAN_overview_records_pupitre_dedup.md` — **implemented**, matches
  uncommitted changes in `crud.py`, `schema.py`, `magnetdb.py`,
  `demos/users_table_demo.py`, `tests/test_crud.py`. Covers the `TODOs.md`
  line *"concat entries that share one pupitre file."* Not yet committed.
- `PLAN_hoop_stress_history.md` — **pending approval**, fully scoped. Covers
  the `TODOs.md` stress line *"compute and persist hoop-stress bin stats +
  fatigue."*
- `PLAN_scheduled_populate.md` — **design sketch, not implemented**. Covers
  the `TODOs.md` line *"add a scheduler to run the above scripts on a
  regular basis."*
- `PLAN_econrj_parameter_inference.md` — **design sketch, not implemented**.
  Covers the `TODOs.md` line *"compute ECCO params."*
- `notebook_review_import_housing_summary.md` — review notes (not a formal
  plan) with 3 concrete next steps, feeding the `userdb` TODO item.

## Phase: Now — scoped, ready to execute

| Item | Effort | Notes |
|---|---|---|
| Commit the dedup work | S | Run the test suite first (`MPLBACKEND=Agg`, project venv), then commit — implemented but uncommitted. |
| Execute `PLAN_hoop_stress_history.md` | M | Already has an approved-shape plan (Goal/Files/Approach/Verification). Needs go-ahead to execute. |
| Housing-summary notebook fixes | S | Fix `h.site`→`h.housing` in cell `1387a3c9`; re-run notebook end-to-end for consistent outputs; decide fate of the `PROPOSALS` dead-end section. |

## Phase: Next — needs a short scoping pass, or has a design sketch with opens to close

| Item | Effort | Notes |
|---|---|---|
| overview-record: signature (Field for classification, Ref currents for ODE, A1–A2/Iddct1–4 for lag) | M | Builds on the now-committed dedup schema. Signature and lag are related — worth scoping together. |
| overview-record: lag | M | Blocked on open question 1 below. |
| overview-record: plateaux | M | Blocked on open question 2 below. |
| userdb: default-exclude entries before first commissioned date | S | Straightforward once `site` table's first-commissioned-date is confirmed as source of truth. |
| userdb: load EXPERIENCES_LOG data directly from SUPERVISION DB | M | Integration work (DB connection/access), independent of other userdb lines. |
| userdb: load proposal table from EMFL user DB API | M | Resolves the housing-summary notebook's dead end (current CSV export has `Magnet Sites` entirely null). |
| Processing-status flag on experiments/overview-records | M | Sequence after `PLAN_hoop_stress_history.md` lands, so the flag's vocabulary matches the finished pipeline. Design blocked on open question 3 below. |
| Scheduler (`PLAN_scheduled_populate.md`) | S–M | Design is concrete (systemd timer + `--settle-seconds` threaded through `scan_tdms_subdir`). Sequence after `PLAN_hoop_stress_history.md` and the dedup commit land, since it schedules exactly those scripts. Opens carried from that plan (see below). |
| EcoNRJ parameter inference (`PLAN_econrj_parameter_inference.md`) | M | Fitting recipe and implementation checklist already exist, wraps `piecewise_regression` on `python_magnetrun/examples/corr_Ih_Ib.py`. Independent of the duckdb/dashboard track — can run in parallel. Opens carried from that plan (see below). |

## Phase: Later — larger scope, external dependencies, or currently underspecified

| Item | Effort | Why it's later |
|---|---|---|
| Dashboard rework (housing → magnet, linked to overview-records/stress/fatigue) | L | Capstone/integration item — blocked on the processing-status flag and hoop-stress history existing first. |
| Commissioning data structure (site/assembly → propagate to magnets) in duckdb | L | New schema domain; touches the same site/housing concepts as the userdb work, sequence after userdb reduces rework. |
| Cooling models (M1 student's primary heat-exchanger work) | M | External dependency — availability/completeness of that student's models isn't in your control. |
| Fix/update `python_magnetrun/examples/bilan.py` | ? | Needs a look at current state before it can be sized. |
| Update numerical commissioning | ? | Bare TODO line, no spec yet. |

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
