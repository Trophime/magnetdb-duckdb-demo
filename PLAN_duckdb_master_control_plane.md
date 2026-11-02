# DuckDB master, Postgres for control data (option F)

**Status:** proposal, awaiting approval (written 2026-10-28). Approving it
approves the direction and the order of the phases; each phase gets its own
detailed plan for approval before any work starts.
**Supersedes:** "Solution 1" in
[PLAN_duckdb_postgres_merge.md](PLAN_duckdb_postgres_merge.md) ("Follow-up
discussion").
**Related:** [PLAN_digital_twin_schema.md](PLAN_digital_twin_schema.md),
[NOTES_python_magnetdb_deployment.md](NOTES_python_magnetdb_deployment.md),
[PLAN_dashboard_server_deployment.md](PLAN_dashboard_server_deployment.md).

## Goal

DuckDB is the master for all magnet data; Postgres keeps only the shared,
multi-writer control data. python_magnetdb becomes a thin API over
`to_duckdb`. Roles include `simulator` and `robot`, and a robot service
compares online simulations with live operating data.

## Context and constraints

- One developer, plus students who add features. The priorities are a light
  stack, speed, and low dev time.
- Several tens of users, with different goals.
- Load measured from EXPERIENCES_LOG (DuckDB `users` table, duplicates
  removed, 2018–2026, `magnetdb-2026-10-08.duckdb`):
  - 317–630 sessions per year, about 1–2 per day, median length ~3 h;
  - 1,300–2,500 h of magnet time per year;
  - 370–740 experiments per year;
  - **at most 2 sessions at the same time**.
- `magnetdb-2026-10-08.duckdb` is 120 MB.

## Architecture

| Store | Content | Writers |
|---|---|---|
| **DuckDB** (one file) | materials, parts, magnets, assemblies, `magnet_parts`, `assembly_magnets`, `housing_config`, experiments, `operationaldata`, `overview_records`, proposal sessions, `operation_log`, all stats tables, comparison results (new) | the API process only |
| **Postgres** (Django) | `users` (role, api_key), `servers` (SSH keys), `simulations`, `simulation_currents`, `audit_logs`, attachment metadata | API + Celery worker, concurrently |
| **MinIO** | attachments, simulation outputs | API + worker |
| **Parquet** (rolling buffer) | live samples from the robot, last N hours | the robot service |

The rules:

1. **One process owns the DuckDB file.** DuckDB lets only one process open a
   file for writing, and while it is open, no other process can open it at
   all. So:
   - the API keeps one read-write connection and gives each request its own
     cursor;
   - the file belongs to the service account with mode `600`;
   - `ensure_schema` runs when the API starts.
2. **Jobs that write DuckDB** (`populate`, `compute_*_stats`, hoop stress) run
   as background jobs inside the API process. They already follow the right
   pattern ([parallel.py](to_duckdb/parallel.py): read once, run pure
   workers, write from the calling thread).
3. **The dashboards read a snapshot.** After each write batch, the API flushes
   the database to disk and copies it (120 MB, well under a second), replacing
   the old snapshot in one step.
4. **The CLI and python_magnetapi go through the API** with an `api_key`.
   Students work on a local copy of the file.
5. **Links between the two databases use names.** `simulations.magnet`/`site`
   and `simulation_currents.magnet` become magnet or assembly names; the API
   checks them (for example, it refuses to delete a magnet that still has
   simulations).
6. **Business rules live in `to_duckdb` only** (`crud.py`, `impact.py`,
   `checks.py`); python_magnetdb never runs its own schema changes on DuckDB.
   Stale hoop-stress tracking keeps using `impact.py`, with no triggers
   needed.
7. **Secrets never enter the DuckDB file.** SSH keys stay in Postgres, because
   the file gets copied for the dashboard and for students.

## Roles and actions

| Action | guest | user | simulator | designer | admin | robot |
|---|:-:|:-:|:-:|:-:|:-:|:-:|
| `read` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `update`, `delete` | | ✓ | ✓ | ✓ | ✓ | |
| `simulate` (create/run simulations, own servers) | | | ✓ | ✓ | ✓ | ✓ |
| `create` | | | | ✓ | ✓ | |
| `write_results` | | | | | ✓ | ✓ |
| `admin` (users, `populate`, stats) | | | | | ✓ | |

- There's one role per user, and the roles form a ladder (guest ⊂ user ⊂
  simulator ⊂ designer ⊂ admin); `robot` sits outside it. The robot logs in
  with its API key, never through LemonLDAP.
- **Behaviour change:** `user` accounts lose simulations, which they have
  today because `run` only requires `update`.
- **Bugs fixed in phase 1** (python_magnetdb, branch `vue3`):
  - any user can delete any simulation, because `destroy` only requires
    `read` (`routes/api/simulations.py:153`);
  - `run` accepts a `server_id` the user doesn't own
    (`routes/api/simulations.py:198-213`).

## Robot and live data

```
pupitre feed ──► adapter ┐
NI pigbrother ─► adapter ├─► common frame ─► plateau/window ─► simulate ─► compare ─► write_results
later source ──► adapter ┘        │                            (API)                   (API → DuckDB)
                                  └─► rolling Parquet ─► comparison dashboard (live curves)
```

- **Separate service:** the robot runs as its own process with the `robot`
  role. If a feed crashes, the API keeps running.
- **Adapters:** one per source. The common frame uses python_magnetrun's
  channel names (`*-defs.json`, housing formula maps).
- **Live samples never go into DuckDB.** Only comparison results do, one row
  per window. Even at one comparison every 5 minutes per session, that's at
  most 24 writes per hour.
- **Compute:** ≤ 2 simulations in parallel, one per active session.
- **Clock lag:** pupitre and pigbrother clocks differ. Use one source as the
  time reference and compare per plateau; that's simpler than estimating the
  lag live.
- **Comparison dashboard:** a dedicated Dash app (or page) reading the
  snapshot and the Parquet buffer.

## Phases

Estimates are full-time weeks for you. Student time isn't counted, only your
review time.

| # | Phase | Main files | Weeks | Verify |
|---|---|---|---|---|
| 0 | Decisions: Postgres-only columns to carry over (`inner_bore`, `outer_bore`, `flow_params`, `design_office_reference`, `angle`, offsets), fate of `probes`/`records`, part attachment references | this plan | 0.5 | Decisions written here |
| 1 | Roles and actions + the 2 bugs | python_magnetdb `models/user.py`, `dependencies.py`, `routes/api/{simulations,servers,admin/users}.py`, `web/src/filters.js`, `web/src/views/admin/users/show.vue`, `tests/test_roles.py` | 0.5–1 | Tests written first fail, then pass; route tests for both bugs |
| 2 | `crud.py`: `get_*` (return data) / `view_*` (print), progress messages moved to logging | `to_duckdb/crud.py`, `magnetdb.py`, `to_duckdb/tests/` | 1.5–2 | CLI output identical before/after on the test DB; new `get_*` tests |
| 3 | API owns the DuckDB file: connection, cursor per request, `ensure_schema` at startup, snapshot, background jobs | new module in python_magnetdb, `web.py`, `pyproject.toml` (to_duckdb dependency) | 1–1.5 | Concurrent read/write test; snapshot opens read-only during writes; a job runs while the API serves requests |
| 4 | Entity routes rebuilt on `crud.py`, with the site → assembly rename | `routes/api/{materials,parts,magnets,sites,site_magnets,magnet_parts,records}.py` (~1,150 lines), `serializers.py`, python_magnetapi | 2–3 | Route tests per entity; python_magnetapi commands work against staging |
| 5 | Links by name; Django entity models removed; Postgres-only data migrated | `models/simulation.py`, `simulation_current.py`, Django migration, migration script | 1–1.5 | Every simulation linked to an existing magnet or assembly; row counts before/after |
| 6 | Vue: ids → names, new fields (status history, dates, housing, experiments) | `web/src/router.js`, `web/src/views/{materials,parts,magnets,sites}/` | 2–4 | `npm run build`; manual check on staging |
| 7 | Dashboard on the snapshot; CLI through the API | `apps/dashboards/magnetdb` config, `to_duckdb/magnetdb.py` | 0.5–1 | 145 dashboard tests pass; CLI against staging |
| 8 | Tests, docs, cutover (freeze writes, final migration, switch) | READMEs, merge plan, `PLAN_digital_twin_schema.md:1087` | 1 | Checklist on staging, then production |
| | **Database + roles total** | | **≈ 10–15** | |
| 9 | Robot, parts that don't depend on the protocols: comparison tables, `write_results` endpoint, comparison dashboard | `to_duckdb/schema.py`, new route, new dashboard | ≈ 2–3 | Test writes from a fake robot appear on the dashboard |
| 10 | Robot, feed adapters and clock lag | new service | not estimated | Protocols needed first |

Order: 1 can start right away and doesn't depend on the rest;
2 → 3 → 4 → 5 → 6 → 7 → 8; 9 after 3; 10 after 9.

## Resources

| Kind | Need |
|---|---|
| **People** | You: phases 0, 1, 3, 5, 8, 10 (architecture, auth, migration, live feeds). Students, with your review: `get_*`/`view_*` per entity (2), entity routes once the first one is done as a model (4), Vue views (6), comparison dashboard (9), tests. Assumption: review takes about 20–30 % of their time |
| **Staging** | calcul22: NVMe with 328 GB free, 40 threads, 62 GB RAM |
| **Production** | kelvin: 563 GB free, 64 threads, 1.5 TB RAM; CPU limits so it doesn't compete with simulations |
| **Compute** | ≤ 2 simulations in parallel for the robot; cores per simulation to be decided |
| **Containers** | api (owns DuckDB), worker, nginx web, Postgres, Redis, MinIO, LemonLDAP, Traefik: ≈ 3.3–4.4 GB of images, the same as today ([NOTES_python_magnetdb_deployment.md](NOTES_python_magnetdb_deployment.md)), plus the dashboards and the robot |
| **Disk** | DuckDB 120 MB + snapshot 120 MB + Parquet buffer (size depends on the feed rates) |
| **Skills** | FastAPI, DuckDB, Vue 3; Django only for auth and simulations |
| **Maintenance afterwards** | One domain schema (`to_duckdb`) and one rules module; a small Django schema for control data |

## Comparison with the earlier alternatives

A–D come from [PLAN_duckdb_postgres_merge.md](PLAN_duckdb_postgres_merge.md);
E was discussed on 2026-10-28.

| | A. Partial merge | B. Full merge → Postgres | C. Postgres master rebuilt from DuckDB | D. DuckDB with Postgres for auth only | E. Lite, no Postgres | **F. This plan** |
|---|---|---|---|---|---|---|
| Source | merge plan, "Decision" | "Strategies" 1 | "Follow-up discussion" | "Strategies" 2 | discussed 2026-10-28 | — |
| Dev time (weeks) | not estimated | more than C | 14–21, + roles 0.5–1 | — | ≈ 9–14 (rough estimate) | **≈ 10–15**, robot extra |
| Entity writers | **two (they drift)** | one | one | one | one | one |
| Where the rules live | `crud.py` + Django | Django | Django; stats in to_duckdb | `crud.py` | `crud.py` | `crud.py` |
| Stats run on | DuckDB | Postgres (poor fit) | DuckDB via `ATTACH` | DuckDB | DuckDB | DuckDB, native |
| Dashboard | partly on Postgres | rewritten | ~100 queries via `ATTACH`; needs Postgres up | snapshot | snapshot | snapshot |
| Concurrent simulations | yes | yes | yes | **no** (API + worker) | limited (in-process) | yes (Postgres + Celery) |
| SSH keys outside DuckDB | yes | yes | yes | no | **no** | yes |
| Stale hoop-stress tracking | across databases | triggers | Postgres triggers | `impact.py` | `impact.py` | `impact.py`, as today |
| Existing stats ids | reconciled | migrated | kept (explicit ids) | unchanged | unchanged | unchanged |
| Student setup | full stack + DuckDB | full stack | full stack + DuckDB | `uv sync` + file | `uv sync` + file | `uv sync` + file (Postgres only for simulation work) |
| Reason not chosen | drift | schema churn, OLAP on a row store | rules in two places, heaviest | concurrent simulation writes | user count, keys, concurrency | — |

## Risks

- **Single API process:** a restart briefly stops writes and interrupts jobs
  running in-process, so job state must be stored and jobs resumed at
  startup.
- **Local disk only:** the DuckDB file must not sit on a network filesystem,
  because its locking isn't reliable there.
- **Snapshot lag:** the dashboard is a few seconds behind.
- **Names as URL keys:** names containing special characters need encoding.
- **CLI regressions during the `crud.py` split:** covered by comparing output
  before and after.
- **Migrating Postgres-only data:** the size of the current Postgres database
  is unknown.
- **Robot:** the feed protocols and the clock lag are still unknown.

## Open questions

1. Route tests: against the dev Postgres, or an SQLite test settings file?
2. Moving existing `user` accounts to `simulator`: a data migration, or by
   hand?
3. Delete a simulation: owner or admin only (suggested)?
4. Phase 0 decisions (columns, `probes`/`records`, attachments).
5. Pupitre feed and NI pigbrother streaming: protocols and rates.
6. One robot for all housings (suggested, since there are at most 2 sessions
   at once) or one per housing?
