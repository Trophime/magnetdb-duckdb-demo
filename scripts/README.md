# Scripts

Helper scripts for building, checking and serving the MagnetDB DuckDB
database. Python-based scripts need the project `.venv` active; all of them
can be started from any directory.

## `build_from_scratch.sh`

Rebuilds the database from scratch, into `to_duckdb/magnetdb-<YYYY-MM-DD>.duckdb`.

```bash
source .venv/bin/activate
scripts/build_from_scratch.sh [--from STEP] [--to STEP] [--db FILE]
```

`--from` / `--to` run only the steps between them (both included); the other
steps are listed as `not run`. Starting after `create` needs an existing
database: `--db` names it (default: today's file in `to_duckdb/`; a relative
path is taken from the current directory). `--help` lists the options.

| Step ID | Step |
|---|---|
| `create` | Create database |
| `assemblies` | Load assemblies |
| `statuses` | Set known magnet statuses |
| `check` | Check database consistency |
| `experiments` | Populate experiments |
| `exp-stats` | Ingest per-experiment statistics |
| `operationaldata` | Populate operationaldata |
| `op-stats` | Ingest per-file operational statistics |
| `overview-json` | Load overview records from JSON |
| `overview-infer` | Consolidate overview records |
| `export` | Export source data |
| `users` | Build users table |
| `link-users` | Link users |
| `unlinked-users` | List unlinked users |

Example, re-running the export and the user tables on an existing database:

```bash
scripts/build_from_scratch.sh --from export --db to_duckdb/magnetdb-2026-10-08.duckdb
```

Paths (`JSON`, `RECORDS`, `DATA_DIR`) are set at the top of the script.
The data-export section needs `USERDB_API_KEY` and the `MYSQL_*` variables,
loaded by direnv from `~/github/python_magnetrun/examples/.envrc`.

Each step prints its title and a status: `OK`, `FAILED` (the build stops,
except for the consistency check and individual assembly files) or `SKIPPED`
(data export without credentials). Command output goes to
`to_duckdb/magnetdb-<YYYY-MM-DD>.duckdb.log`.

## `check_and_fix_geometry.sh`

Runs `magnetdb.py check`, then `check --fix` to fill missing part/magnet
`geometry_data`, then `check` again. Exits 0 only if the final check is clean.

```bash
scripts/check_and_fix_geometry.sh [DB]
```

`DB` defaults to `magnetdb.duckdb` in `to_duckdb/`; a relative path given on
the command line is taken from the current directory.

## `run_docker.sh`

Starts the dashboard container on <http://localhost:8050/>. It needs `docker`,
the `rclone-mount.service` user unit (which only mounts the records tree on an
LNCMI VLAN or the LNCMI VPN), and asks whether to pull a newer image first.

Configuration through environment variables:

| Variable | Default |
|---|---|
| `DUCKDB_DIR` | `~/duckdb` |
| `DUCKDB_NAME` | `magnetdb.duckdb` |
| `RECORDS_MOUNT` | `~/LNCMIG-Data/records` |
| `SUPERVISION_DATA_DIR` | `~/github/magnetdb-duckdb-demo/Data` |
| `DOCKER_REGISTRY` | *(empty)* |
| `DOCKER_IMAGE` | `trophime/magnetdb-dashboard:dev` |

To serve a database built by `build_from_scratch.sh`, copy it into
`$DUCKDB_DIR` or point `DUCKDB_DIR` / `DUCKDB_NAME` at it.

## `list_assembly_configs.sh`

Lists the assembly JSON files (`<housing>_A<YYMMDD>_<n>.json`) of a
directory, sorted by their embedded date. Used by `build_from_scratch.sh`.

```bash
scripts/list_assembly_configs.sh [CONFIG_DIR]   # default: ~/github/hifimagnet-projects/magnetdb.json
```

## `sort_summary_by_year.sh`

Lists the `M*_summary-<YYYY>.json` files of a directory, sorted by year.
Prints file names only, not full paths. Used by `build_from_scratch.sh`.

```bash
scripts/sort_summary_by_year.sh [DATA_DIR]   # default: Data/
```
