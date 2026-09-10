# Plan — M1 project note: sort and proposed order

Status: **reference document** (2026-08-31) — a sort/prioritization of ideas,
not itself a plan to implement. No code changes are proposed by this file;
individual items still need their own scoping/approval when picked up.

Source: [`M1project_from_iphone.txt`](M1project_from_iphone.txt) (50
freeform, mostly-French, dictated project-idea items). Cross-checked against
[`to_duckdb/ROADMAP.md`](to_duckdb/ROADMAP.md),
[`to_duckdb/TODOs.md`](to_duckdb/TODOs.md), and
[`python_magnetrun/prompts/ROADMAP.md`](python_magnetrun/prompts/ROADMAP.md).
Item numbers below refer to line numbers in the source note.

## Section 0 — Already done, no action needed

| Note item | What | Evidence |
|---|---|---|
| 5 (overlay line part) | Overlay line on all plots | commit `c60cba4` |
| 36 | from/to date filters, experiments + overview-records tables | commit `d1bfc37` |
| 37 | Keep part `in_operation` while magnet is `in_stock` | commit `03decab` — note wording is stale, this landed |
| 8 | "Redo duckdb from scratch" | this whole repo *is* that redo |
| 9c | Site→Assembly rename | `PLAN_site_to_assembly_rename.md`, Track A landed 2026-08-18 |
| 15 | "Redo lifecycle — cf autre note" | confirmed: no follow-up needed to `to_duckdb/PLAN_lifecycle_status.md` |

## Section 1 — Already scoped in the existing roadmaps

Execute from the referenced plan/roadmap files rather than re-deriving
design here:

- **2 (signatures), 5 (lag part), 7 (lag comparison), 27 (more overview/
  stress in duckdb)** → Open Questions 1–3 in `to_duckdb/ROADMAP.md`. Lag
  is the sharpest: two working implementations exist (own vs. Wolali's FFT
  approach), needs a head-to-head run; scope home is
  `apps/dashboards/magnetdb/PLAN_signature_regime_robustness.md`. Item 27
  confirmed to mean "add more" — reinforces this as priority, not a
  separate task.
- **31 (incident table)** → `to_duckdb/PLAN_incident_tracking.md`, drafted
  2026-08-28, proposed but not approved. Already answers the note's own
  cardinality question (add incident on every disassembly, or only on
  retire/dead?) — models incidents as standalone, not auto-triggered by
  lifecycle events.
- **40 (Total Field validity for hybrid)** → `to_duckdb/ROADMAP.md` Later
  phase, "Field validation stats for M8–M10."
- **43 (pigbrother NAS 2018–2021)** → Later phase, "Pre-2022 pigbrother
  data."
- **48 (cooling model dashboard)** → Later phase, "Cooling models (M1
  student's work)."
- **24, 3d (S3 + parquet for magnetdata)** → `python_magnetrun/prompts/
  ROADMAP.md` Stream 4.7, fully phased (Phases 1–7, D1–D8 design decisions
  made, `pyarrow`/S3-via-`rustfs/magnetfs` chosen). Best "shovel-ready"
  item — design cost already paid.
- **25 (polars/narwhals for tdms)** → Stream 4.3, marked XL, explicitly
  deferred/optional ("package fully functional without this").
- **33 (drop hoop-stress proxy / fatigue proxy / operationaldata /
  housing_summary)** → Later phase, "duckdb schema cleanup," partially
  tracked as a follow-up in `apps/dashboards/magnetdb/
  PLAN_part_stats_hoop_stress.md`.

## Section 2 — New ideas, grouped thematically

**A. Dashboard quick wins** (small, additive, no new schema)
- 13: show pigbrother `Champ_magn` in overview-records dashboard
- 26 / 30: fault annotations from pupitre/pigbrother logs in overview-record
  + file-viewer + experiments dashboard
- 38 / 39: field-bin-history-colored magnet-time plots (year/month), pie
  charts (circular/horizontal)

**3b — nanoplot/great_tables question, explored in depth:**
Dashboards currently use Dash's `dash_table.DataTable` throughout
(`housing_stats.py`, `part_stats.py`, `assembly_stats.py`,
`magnet_stats.py`, `stats_research_area.py`); no `great_tables` dependency
or nanoplot support exists yet. Three options surfaced, not yet decided
between:
1. **great_tables' native `nanoplot`** — lowest-effort path ("nanoplot" is
   literally a great_tables feature, not a generic term). Tradeoff: renders
   static HTML, loses `DataTable`'s native client-side sort/filter/
   pagination unless reimplemented. Recommended selectively — for detail/
   history tables where a trend column earns its keep — not a wholesale
   `DataTable` replacement.
2. **Keep `DataTable`, fake it with markdown+base64 images** — a
   `presentation: 'markdown'` column whose cell value is a base64-encoded
   PNG, pre-rendered per row. Works, but static (no hover/tooltip),
   row-height/column-width need manual CSS tuning, per-row image
   precomputed rather than free.
3. **Switch to `dash-ag-grid`** — has a native sparkline cell renderer, but
   it's an AG Grid **Enterprise** feature, not in the free Community
   edition — a licensing blocker.

**B. duckdb data-model additions** (schema changes, sequence carefully)
- 6: populate conflict policy — what happens when a record exists with
  *different* field values (excluding derived/computed ones)? No design
  exists yet anywhere.
- 34: fold `to_duckdb` demo scripts into `magnetdb.py` (at least the users
  ones) — aligns with the userdb Phase 1 refactor already in `Next`.
- 35: experiments-table "didn't end properly" status flag (distinct from
  the already-decided processing-status flag) + duration/plateaux filters.

**C. New standalone dashboards**
- 44 waterflow, 45 commissioning (exp + numerical), 46 magnet-scipy
  comparison (Currents/Tensions/Temperatures exp vs overview), 47 energy
  balance — four independent dashboard builds, each depends on data
  existing first (commissioning data model for 45, in particular).

**D. Commissioning objects + digital twins** (new domain, larger)
- 19/20: `assembly_commissioning`/`magnet_commissioning` — field factor,
  resistance, inductance, bprofile (points to Kevin's measurements)
- 21: digital twins of both
- 23: cross-check field factors against commissioning data once "mode" is
  determined
- Overlaps the roadmap's Later-phase "Commissioning data structure" item —
  merge with it, don't run as a separate track.

**E. B-profile → currents inversion & experiment planning optimization**
(largest, most uncertain item in the whole note)
- 11: derive currents from B-profile (pupitre `Field` / pigbrother
  `Champ_magn`) — formula to get from Cedric/Romain
- 12: full planning optimizer — power/cost estimates, minimizing magnet
  swaps, assembly creation, dilution changes, personal-constraint
  scheduling
- Research-grade sub-project in its own right, gated on getting the formula
  from Cedric/Romain first. No existing scaffolding in either roadmap.

**F. External integrations**
- 4: magnetapi bulk-import test (Track B of the assembly rename, currently
  deferred, separate repo)
- 29 + 50: rework `python_magnetrun/requests` to read *and write*
  material/part data directly against Cedric's database, plus generate
  M7/M8 assembly configs — write access to an external DB is a bigger
  authorization/safety question than the rest of the note
- 42: Engie API, link to experiments — no existing scaffolding
- 17/18: bitter-magnet status cleanup in `hifimagnet-projects` (external
  repo)

**G. Naming follow-up**
- 16: bitter magnet naming convention (`Byyddmm00` → `Myyddmm00`?)

**H. Exploratory / low-confidence**
- 10: "Ggsql" — resolved: [ggsql](https://github.com/posit-dev/ggsql), a
  SQL extension (`VISUALISE`/`DRAW`/`SCALE`/`LABEL` clauses) targeting
  DuckDB/SQLite, Grammar-of-Graphics style, alpha stage, compiles to Vega-
  Lite via WASM. Not a fit for the production dashboards (custom logic:
  great_tables, accordions, lifecycle-aware filtering), but worth a spike
  for ad-hoc exploration or as the query layer for item 49's querychat
  demonstrator.
- 49: querychat demonstrator over local LLM via Ollama — model choice not
  decided in the note.

**I. Performance / process**
- 3c: python_magnetrun memory/CPU optimization — Stream 1 ongoing
  background work
- 9a/9e: process notes ("stop free-form Claude sessions, use the
  packages"; "get authorization to use Claude to finish the to_duckdb
  demonstrator") — not code tasks
- 9d: Postgres backport — no existing plan, not mentioned elsewhere
- 14/32: Valentin's coverage redo, housing-dashboard "total Energy" sum
  validation — verification tasks, cheap to schedule early

## Proposed order

Reasoning: finish what's already in flight and cheaply scoped before
opening new domains; the two big new research items (E, and F's
write-to-Cedric-DB) need external input before they can even be sized.

1. **Finish existing `Next`-phase roadmap items already in progress** — lag
   comparison (Open Q1), plateaux (Open Q2), hoop-stress fatigue-bins
   matrix, `overview-records-from-json`. (covers note items 2/7/27)
2. **Approve and land `PLAN_incident_tracking.md`** (item 31) — design
   already done, just needs sign-off.
3. **Dashboard quick wins (A)** — 13, 26/30, 38/39: small, additive, no
   schema risk, high visible value.
4. **Execute the already-designed S3+parquet work** (`python_magnetrun`
   Stream 4.7) — covers items 24/3d, design cost already sunk.
5. **duckdb data-model additions (B)** — 6, 35, 34 — do together since
   they touch overlapping tables/CLI surface.
6. **Verification tasks (14, 32)** — cheap, can slot in anywhere, worth
   doing before trusting downstream dashboard numbers.
7. **Naming follow-up (G)** — item 16.
8. **New standalone dashboards (C)** — waterflow first (44+22,
   self-contained), then energy balance (47); commissioning (45) and
   magnet-scipy (46) wait on item 9 below.
9. **Commissioning objects + digital twins (D)** — merge with the
   roadmap's existing "Commissioning data structure" Later item rather
   than running separately.
10. **External integrations (F)** — Engie API and magnetapi bulk-import
    test are self-contained, can go anytime; the Cedric-DB write-access
    rework should wait for an explicit conversation about scope/
    authorization (see Open Questions below).
11. **B-profile → currents / planning optimizer (E)** — last, blocked on
    getting the formula from Cedric/Romain; size it only once that's in
    hand.
12. **Exploratory items (H)** — opportunistic, no dependencies block
    anything else, so they can slot in whenever there's slack.

## Open questions

- **Items 29/50** — is write access to Cedric's external database actually
  something to pursue, given the data-integrity/authorization stakes? This
  changes how item F above should be scoped. Not yet answered.
- **Item 3b** — which of the three table-tech options (great_tables
  selectively, DataTable+base64, ag-grid Enterprise) to pursue, and for
  which tables specifically. Not yet decided; see Section 2/A above.
