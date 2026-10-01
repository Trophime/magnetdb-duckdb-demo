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
