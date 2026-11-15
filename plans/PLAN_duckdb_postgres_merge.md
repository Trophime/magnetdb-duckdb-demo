# DuckDB / PostgreSQL merge strategy

**Status:** Discussion / decision recorded — not yet an approved implementation
plan. See "Open question" below for what's still unresolved before this can
be turned into an execution plan.

## Context

The DuckDB schema in `to_duckdb/schema.py` was originally designed from the
PostgreSQL schema backing `../python_magnetdb` (Django models under
`python_magnetdb/python_magnetdb/models/`). The two have since diverged:
DuckDB grew a large analytics layer that Postgres never had, and Postgres
has application-level tables (attachments, simulations, audit log, auth)
that were never carried into DuckDB. This note records a comparison of the
two schemas and the resulting discussion about how (or whether) to
reconcile them.

## Schema comparison summary

**Tables only in PostgreSQL** (`python_magnetdb/python_magnetdb/models/`):
- `audit_logs`, `cad_attachments`, `mesh_attachments`, `storage_attachments`
  — generic audit trail + S3-backed file attachment models. DuckDB has no
  attachment abstraction; it stores plain file paths instead.
- `servers`, `simulations`, `simulation_currents` — compute-server /
  simulation-job orchestration, written concurrently by the FastAPI app and
  Celery workers (`worker.py`, `management/commands/celery_worker.py`).
- `records` — generic file record tied to a site; DuckDB replaces this with
  purpose-built `experiments`, `operationaldata`, `overview_records`.
- `probes` — voltage-tap/temperature/B-field probe geometry.
- Application `users` (auth: `role`, `api_key`) — unrelated to DuckDB's
  same-named `users` table (see below).

**Tables only in DuckDB** (`to_duckdb/schema.py`):
- `housing_config` — new concept, no Postgres equivalent.
- `experiments`, `operationaldata`, `overview_records` — file-tracking
  tables standing in for Postgres's generic `records`.
- All stats tables: `op_stats_processed`, `op_run_scalars`,
  `op_assembly_bin_stats`, `op_part_bin_stats`, `exp_stats_processed`,
  `exp_run_scalars`, `exp_assembly_bin_stats`, `exp_part_bin_stats`,
  `hoop_stress_processed`, `hoop_stress_bin_stats`, `hoop_stress_fatigue`,
  `hoop_stress_fatigue_bins` — derived/computed OLAP data, produced by this
  project's own batch scripts (`compute_op_stats.py`, `compute_exp_stats.py`,
  `compute_hoop_stats.py`), never sourced from Postgres.
- `users` — same name as Postgres's `users`, but a completely different
  table: one row per EXPERIENCES_LOG proposal session
  (`acronym`, `research_area`, `hstart`/`hstop`, …), not an auth table.

**Renamed tables:** `sites` → `assemblies`, `site_magnets` →
`assembly_magnets` (mid-rename on branch `msite_to_assembly`, see
`PLAN_site_to_assembly_rename.md` and
`to_duckdb/migrations/migrate_rename_site_to_assembly.py`).

**Primary-key strategy (core structural difference):** every Postgres table
uses a `BigAutoField` surrogate `id` plus `created_at`/`updated_at`
auditing. DuckDB drops both for its core entity tables and uses the natural
name as PK instead (`materials.name`, `parts.name`, `magnets.name`,
`assemblies.name`), with FKs referencing those names directly instead of
integer ids.

**Column-level diffs on shared tables:**
- `parts`: Postgres has required `material` FK, `geometry_config` JSONField,
  and three attachment FKs (`hts_attachment`, `modelaxi_attachment`,
  `shape_attachment`) + generic `metadata`. DuckDB has nullable
  `material_name`, splits geometry into `geometry` (type/class) +
  `geometry_data` (JSON), has no attachment FKs (just a bare `cad` path),
  and adds `status_history` JSON + `manufactured_at`.
- `magnets`: Postgres has `inner_bore`/`outer_bore` and `flow_params` —
  absent in DuckDB. DuckDB adds `status_history` + `assembled_at`.
- `magnet_parts`: Postgres tracks `commissioned_at`/`decommissioned_at`/
  `angle`/`metadata`; DuckDB instead tracks `rank`/`coil_index` — no
  lifecycle timestamps at this level at all. Biggest semantic divergence
  found on a same-named table.
- `assemblies`/`sites`: Postgres has `config_attachment`; DuckDB adds
  `housing` FK + `commissioned_at`/`decommissioned_at` directly on the
  assembly (Postgres only tracks those two on the join table). Status vocab
  differs too: Postgres uses one flat `Status` enum for parts/magnets/sites;
  DuckDB splits into `AssemblyStatus` and `LifecycleStatus` with different
  value sets per entity.

## Strategies considered

1. **Merge DuckDB → Postgres (full):** port every DuckDB-only table into
   Postgres. Pro: one source of truth. Con: heavy schema churn (PK
   reconciliation, status-vocab reconciliation), and moves large OLAP
   bin-stats tables onto a row store that's the wrong tool for that
   aggregate workload.

2. **Merge Postgres → DuckDB ("DuckDB as internal DB"):** move everything
   except user/role/auth into DuckDB, keep Postgres just for auth. Central
   risk: Postgres currently exists partly because of concurrent multi-writer
   load — the FastAPI API routes and Celery workers both write to
   `simulations`, `simulation_currents`, `servers`, `audit_logs` from
   separate processes simultaneously. DuckDB is single-writer; relocating
   those tables would require enforcing non-concurrent access (a serializing
   dispatcher/queue in front of DuckDB), which is a real architectural
   commitment, not just "avoid running two copies."

3. **Partial merge (chosen direction, see Decision below).**

## Decision

Partial merge, DuckDB → Postgres, limited scope:

- **Move to Postgres:** `housing_config`, `experiments`, `operationaldata`,
  `overview_records` — these are low-write, single-actor-updates-status
  tracking tables, the same kind of data Postgres already handles fine
  elsewhere. Only these four tables need PK/FK reconciliation (DuckDB's
  natural-key style vs. Postgres's surrogate-id style).
- **Keep in DuckDB only:** all OLAP/stats tables (`op_*_bin_stats`,
  `exp_*_bin_stats`, `hoop_stress_*`, and their `*_processed`/`*_run_scalars`
  companions) — computed by the existing batch scripts, no live concurrent
  writes involved, exactly the aggregate workload DuckDB is good at.
- **Leave untouched in Postgres:** `simulations`, `simulation_currents`,
  `servers`, `audit_logs`, auth (`users`/role/api_key). This avoids the
  concurrency problem entirely rather than needing to enforce non-concurrent
  access anywhere — job orchestration and audit logging stay exactly where
  concurrent multi-writer semantics already work.

This was preferred over strategy 2 because it requires no new
non-concurrency guarantee anywhere: the tables that actually need concurrent
writes (job orchestration, audit log) simply never move.

## Open question

Once `experiments`/`operationaldata` live in Postgres, DuckDB's stats tables
still key off `experiment_id`/`operationaldata_id` as integers. Two ways to
keep that working, not yet decided between:

1. **Synced read-only mirror** — Postgres stays the writer; a sync step
   refreshes DuckDB's copy of `experiments`/`operationaldata` before each
   stats run.
2. **Direct query** — the stats-computation scripts (`compute_op_stats.py`,
   `compute_exp_stats.py`, `compute_hoop_stats.py`) query Postgres directly
   for the id↔file mapping and only write aggregate rows into DuckDB.

This needs to be resolved before writing a concrete step-by-step
implementation plan (Django migrations, ETL script, ongoing sync mechanism).

## Follow-up discussion (2026-10-28)

Not a decision: direction and costs, to settle before an execution plan.

### Earlier question: one master per table group

`materials`, `parts`, `magnets` and `assemblies`/`sites` exist in **both**
databases, with different keys and status vocabularies; python_magnetdb's web
UI writes them in Postgres, `to_duckdb` (`magnet add`, `assembly add`, …) in
DuckDB. With two writers they drift, whatever happens to `experiments`. The
Decision above only covers four tables.

**Direction discussed (solution 1):** Postgres is the master of every entity
and tracking table (concurrent writers, web UI, auth, audit); DuckDB keeps the
stats tables only and reads entities from Postgres.

### Third option for the open question: DuckDB `postgres` extension

`ATTACH '…' (TYPE postgres, READ_ONLY)`: stats scripts and dashboard join the
DuckDB stats tables with live Postgres tables. No sync job, no mirror. Costs:
the dashboard depends on Postgres being up; the extension must be installed in
the image at build time; deployment needs network access to Postgres (one host,
one front: option A of `PLAN_dashboard_server_deployment.md`). The extension
can also **write**: pointing `crud.py` at Postgres is a possible bridge, not an
end state (two code paths with the same rules, writes bypass `audit_logs`).

### Approach: rebuild Postgres from DuckDB

DuckDB holds the consolidated data, so a **new** Postgres database is seeded
from it rather than reconciled row by row with the current one.

| Tool | Use |
|---|---|
| Seed script (`manage.py seed_from_duckdb`) | Initial load: DuckDB read-only, Django `bulk_create`, one transaction, re-runnable (drop + reseed) |
| `magnetdb.py` features as API endpoints | Ongoing writes after the load; the business rules go into python_magnetdb (routes/actions), python_magnetapi (a REST client) gets the CLI wrappers |

Phases:

1. **A**: DuckDB stays master; Postgres is rebuilt from it on demand; entity tables read-only in the web UI.
2. **B**: write commands ported to the API one by one.
3. **C** (cutover): freeze `to_duckdb` writes, final seed, Postgres becomes master.

Rebuilding also turns python_magnetdb's site → assembly rename
(`prompts/plan-site-to-assembly-magnetdb.md`) into a schema change only, and
allows one new initial migration instead of the 24 existing ones.

### What moves to Postgres

| Feature | DuckDB | Postgres today |
|---|---|---|
| Status | `LifecycleStatus`, `AssemblyStatus` (incl. `disassembled`) | One flat `Status` |
| History | `status_history` JSON on parts, magnets, assemblies | None |
| Entity dates | `parts.manufactured_at`, `magnets.assembled_at`, `assemblies.commissioned_at/decommissioned_at` | None |
| Membership dates | `assembly_magnets.commissioned_at/decommissioned_at`; `magnet_parts` has `rank`/`coil_index`, no dates | `magnet_parts` and `site_magnets` both dated; `angle`, offsets |
| Housing | `housing_config` + `assemblies.housing` | None |
| Tracking | `experiments`, `operationaldata`, `overview_records` | Generic `records` |
| Sessions | `users` (EXPERIENCES_LOG proposal sessions) | `users` = auth accounts |
| Audit | `operation_log` | `audit_logs` |

### `to_duckdb` features to port (`crud.py`, ~4000 lines)

python_magnetapi today: `list`, `view`, `create`, `delete`, `setup`, `run`,
`compute`, `process`, `site status`. Missing:

- `update_*_from_json` with `--dry-run`;
- `update_part_status`, `update_magnet_status`, `decommission_assembly` (+ report), `assembly update-magnet`;
- date inference from names (`manufactured_at_from_name`, `assembled_at_from_name`, `resolve_*`);
- housing import from python_magnetrun / export to JSON;
- `populate` (`find_and_register_pupitre`/`tdms`, `infer_overview_record_fields`, `merge_duplicate_pupitre_records`): needs the records mount → Celery task in the worker, plus bulk endpoints (6483 experiments);
- `check_*` (+ `--fix`) → model validation on the server.

Stays in `to_duckdb`: `compute_op_stats`, `compute_exp_stats`,
`compute_hoop_stats` (magnettools) and the stats tables.

### Stale hoop-stress results across the two databases

`impact.py`'s `HOOP_STRESS_INPUTS` already lists the source columns (material
properties; `parts.material_name`, `geometry_data`; `magnets.geometry_data`;
`assembly_magnets.z_offset`, `commissioned_at`).

- **Change log by Postgres triggers (preferred):** `AFTER UPDATE … WHEN OLD.col IS DISTINCT FROM NEW.col` on those columns only, writing `change_events` (id, ts, table, key, fields, user). Catches every writer (web UI, API, SQL, seed). User: Django runs `SET LOCAL app.user = …` per transaction, the trigger reads `current_setting('app.user', true)`. `hoop-stress compute` reads the events since its cursor (kept in DuckDB), then runs the existing `affected_assemblies` / `mark_hoop_stale` with `stale_reason` = event id. Dry-run impact preview: an API endpoint, from Postgres alone (entities and experiments live there).
- **Input fingerprint (alternative or safety net):** each `hoop_stress_processed` row stores a hash of its inputs; the stats job recomputes it from Postgres (`ATTACH`) and marks mismatches. No triggers, no reason recorded.
- Not recommended: `updated_at` comparison (too coarse), Django signals only (miss bulk/SQL writes), `LISTEN/NOTIFY` (needs a daemon).

### Step 0b: target schema mapping

A table-by-table, column-by-column mapping DuckDB → Postgres, written before
any Django code; it drives the models, the seed and the query rewrites.
Postgres becomes a superset of the DuckDB entity/tracking schema; Postgres-only
columns (`inner_bore`, `outer_bore`, `flow_params`, `design_office_reference`,
`angle`, offsets, `metadata`, attachment FKs) stay, nullable.

| Topic | To decide |
|---|---|
| Keys | `BigAutoField id` everywhere; natural `name` → `UNIQUE NOT NULL`; FKs by id, resolved by the seed |
| Experiment ids | **Keep DuckDB's** `experiments`/`operationaldata` ids (explicit insert + sequence reset): existing stats stay valid without recomputation |
| Timestamps | DuckDB naive `TIMESTAMP` (read as Europe/Paris by `populate.as_aware`) → `timestamptz`, converted explicitly |
| Status | `enums.py` → Django `TextChoices`; mapping of old Postgres values |
| `status_history` | JSON field, or a `status_events` table |
| Lifecycle level | Which level is authoritative (entity vs membership); what fills `magnet_parts.commissioned_at` |
| Nullability | Each DuckDB-nullable / Postgres-required column (`parts.material`, …): relax, or a seed fill rule |
| Names | `sites` → `assemblies`, `site_magnets` → `assembly_magnets`; DuckDB `users` → e.g. `proposal_sessions` |
| New tables | `housing_config`, `experiments`, `operationaldata`, `overview_records`, `change_events` + watched columns |
| Postgres-only tables | Simulations, attachments (218 MB MinIO on calcul22), probes, servers, `audit_logs`, `records`: keep, re-link by name, or drop |

Deliverable: the mapping plus an ER diagram of the target
(`to_duckdb/schema_diagram.py` draws the DuckDB side).

### Rough estimate

Full-time weeks, one developer who knows both codebases; excludes packaging,
images and deployment.

| Step | Weeks |
|---|---|
| 0. Decisions (status vocabulary, lifecycle level, Postgres-only data, naming) | 0.5–1 |
| 0b. Target schema mapping | ~1 |
| 1. New Django schema + `change_events` triggers, one initial migration | 1.5–2.5 |
| 2. `seed_from_duckdb` + verification + kept Postgres-only data | 1.5–2.5 |
| 3. DuckDB side: compute scripts and `stress_map.py` (~40 entity-table queries), dashboard (~100 in 5 files) via `ATTACH`, names → ids, stale tracking from `change_events` | 2–3 |
| **Milestone A: Postgres rebuilt from DuckDB, stats and dashboard on it** | **≈ 6.5–10** |
| 4. API + python_magnetapi write commands, impact preview | 3–4 |
| 5. `populate` as a worker task + bulk endpoints | 1.5–2 |
| 6. Vue 3 web UI for the new fields | 2–4 |
| 7. Cutover, tests, docs | 1 |
| **Total** | **≈ 14–21** |

Main uncertainties: the web UI, how much of `crud.py` is rules vs display, the
fate of Postgres-only data; python_magnetdb has only 7 test files.

### Open decisions

1. Solution 1 confirmed (Postgres master for entities and tracking)?
2. Fate of the Postgres-only data (step 0).
3. Stale tracking: triggers, fingerprint, or both.
4. Step 0b topics above.
