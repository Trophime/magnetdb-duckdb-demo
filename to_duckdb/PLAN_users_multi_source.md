M# Plan — pluggable data sources for users_table_demo.py (CSV / SUPERVISION MySQL / userdb API)

Status: pending approval (not yet implemented) — blocked on open questions below

## Goal

Decouple `build_users`'s join/dedup logic (in `to_duckdb/demos/users_table_demo.py`)
from its CSV-specific loading, so the same pipeline can be fed from three
sources: local CSVs (today), the SUPERVISION MySQL DB, and the EMFL userdb
REST API. Matches this repo's existing `populate <entity>[-from-<source>]`
convention (`populate overview-records` vs. `populate overview-records-from-json`,
`magnetdb.py:1372-1389`). Eventually exposed as `magnetdb.py populate
users-from-csv` / `-from-mysql` / `-from-api`, per the `* userdb` TODO.

## Why this shape works

`build_users` already treats its two inputs independently — session data
(from `load_log`, keyed by `UserCode`/`Magnet`/`HStart`/`HStop`/`timestamp`)
and proposal data (from `load_proposals`, keyed by `Acronym`/`Research Area`/
`Call Number`/`Access Mode`/`Type`/`Experiment Start Date`/`Experiment End
Date`/`Experiment Year`). If both loaders keep returning the same shapes they
do today, none of the join logic, dedup, `sync_users`, `replace_all_users`,
`update_experiments_ids`, or `update_overview_records_ids` needs to change.

## Files affected

- `to_duckdb/demos/users_table_demo.py` — edit: extract the join logic out of
  `build_users`, add new loaders, extend the CLI.
- `to_duckdb/demos/README.md` — edit: document the new source options.
- `to_duckdb/magnetdb.py` — **not touched in this pass**; wiring into
  `populate users-from-*` subcommands is Phase 4, deferred until this plan
  itself is approved and implemented.

## Approach

Phased, because two things are genuinely unknown (see open questions).

**Phase 1 — refactor for pluggability (buildable now, no unknowns):**
1. Split `build_users(log_path, proposals_path, cutoff, fuzzy_cutoff)` into a
   source-agnostic core `build_users(sessions, timestamps, acronym_rows,
   fuzzy_cutoff) -> (users, match_counts)` plus a thin
   `build_users_from_csv(log_path, proposals_path, cutoff, fuzzy_cutoff)`
   wrapper that calls today's `load_log`/`load_proposals` and then the core —
   preserves current behavior exactly.
2. Extend `main()`'s CLI with a source selector (shape depends on open
   question 3 below).

**Phase 2 — MySQL SUPERVISION loader (blocked on schema access):**
3. `load_log_from_mysql(mysql_params, cutoff) -> (sessions, timestamps,
   n_total, n_discarded)` — attach via DuckDB's `mysql_scanner` extension
   exactly as `python_magnetrun/examples/mysql_connect.py`'s `_build_dsn`/
   `_attach_mysql` do (confirmed working in this environment: `INSTALL mysql;
   LOAD mysql;` succeeds), query the SUPERVISION table, reshape rows into the
   same `(housing, variant, hstart, hstop)` structure `load_log` builds today.
4. Credentials via the env vars `mysql_connect.py` already defines —
   `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DB` —
   plus matching CLI flags, so nothing new is invented.

**Phase 3 — userdb API loader (blocked on response shape):**
5. `load_proposals_from_api(api_params, cutoff) -> (acronym_rows, n_total,
   n_discarded, n_ignored)` — `GET {server}/api/proposals-for-ct` via
   `requests` (already installed), paginated with `limit`/`offset` per
   `python_magnetrun/examples/userdb.py`, reshaped into the same
   dict-of-row structure `load_proposals` builds today.
6. Credentials via `USERDB_SERVER` / `USERDB_API_KEY` (already established in
   `userdb.py`), plus matching CLI flags.

**Phase 4 — later:** wire the three modes into `magnetdb.py` as `populate
users-from-csv` / `-from-mysql` / `-from-api`, following the
`overview-records-from-json` precedent exactly (own subparser, thin
`cmd_populate_users_from_*(args)` handler, `ensure_schema` + shared insert
path).

## Verification

- Phase 1: rerun the same before/after parity check used for the earlier
  `users_table_demo.py` refactor (identical stats on a scratch DB copy) —
  zero unknowns here, verifiable independently.
- Phase 2/3: cannot be verified without live credentials. Verification means
  a first *read-only* pass (`mysql_connect.py --mode live` equivalent; one
  small `--limit` GET) to confirm field mapping *before* wiring the write
  path.
- `to_duckdb/tests` suite stays green throughout.

## Assumptions & open questions

1. **SUPERVISION schema is unknown.** No host, database, table, or column
   names for it exist anywhere in this repo (checked via repo-wide grep).
   Need either read-only credentials to inspect it directly, or the
   table/column names given directly — not to be guessed at production data.
2. **userdb API response shape is unknown.** `userdb.py` only shows the
   query-string filters, not a sample JSON body. Need a sample response or
   API docs to map fields reliably.
3. **Source-combination model:** does `-from-mysql` replace *only* the
   session-log side (proposals still from `--proposals` CSV), and `-from-api`
   replace *only* the proposals side (sessions still from `--log` CSV) —
   matching how `-from-json` swaps just one input in the existing precedent?
   Or is a mode needed where both sides are live at once? Default: one swap
   per mode, matching precedent.
4. **Cutoff pushdown:** filter `--from` in the SQL/API query itself, or
   fetch-all-then-filter client-side like the CSV path does today? Default:
   client-side for parity, unless SUPERVISION's row count makes a full pull
   impractical (unknown).
5. **Credential env-var names:** reusing `mysql_connect.py`/`userdb.py`'s
   existing names as-is — flag if they should be namespaced differently to
   avoid clashing with another MySQL server.
