# Plan: deploy the MagnetDB dashboard on a remote server

Status: **approved 2026-10-22 — not started**. Only this file was written
on approval; Phase 0 starts on a separate go.

Follow-up plans (not written yet): LAN access with TLS + login; automatic
backups of the server database; portable geometry paths (A11 #6).

## Goal

The Dash app (`apps/dashboards/magnetdb`) runs on a remote server under
**rootless Podman** as a dedicated user `magnetdb`, starts at boot, and
listens on `127.0.0.1:8050` (reached through an SSH tunnel). The same
container runs the `to_duckdb` CLI through `podman exec` against the
server's database, which is the **master copy** from seeding onwards.
Everything is built from committed, pushed code and published on Docker Hub
under a version tag.

## Decisions (2026-10-22)

| Topic | Decision |
|---|---|
| Target | Remote server, distinct from the dev machine |
| Runtime | **Podman, rootless**, run as a systemd user service through a Quadlet unit |
| Account | Dedicated local user **`magnetdb`** (no sudo, SSH key login, linger on). Not the maintainer's personal account: that one holds SSH keys, git and sftp credentials, and expires with the AD account |
| Access, phase 1 | `127.0.0.1:8050` only, via `ssh -L 8050:localhost:8050 magnetdb@server`. Not opened to the LAN until the follow-up plan adds TLS and login, because the dashboard has no login and exposes experiment data, records and `users` acronyms |
| TLS / login | Follow-up plan: a reverse proxy in front of `127.0.0.1:8050`, routed by host name (no path prefix, so no change to Dash). Do not copy python_magnetdb's `docker.sock` mount, `api.insecure: true` or mkcert certificates |
| Image transport | Docker Hub, `trophime/magnetdb-dashboard:<YYYY.MM.DD>` (the repo already exists and is public; the image carries code only, no data) |
| Data transport | rsync from the dev machine |
| Database | Existing `to_duckdb/magnetdb-2026-10-08.duckdb`, checkpointed copy |
| `hoop_parquet/` | Ship as is (files dated 2026-08-31) if the consistency check in step 4 passes |
| python_magnetrun | Stays on `spike/tdms-polars-benchmark` (resolves ROADMAP Q1) |
| Exec in container | Yes: `to_duckdb` CLI (`magnet add`, `assembly add`, …) inside the dashboard image |
| Master database | **Option A: the server**. The database goes dev → server **once** (seeding). Afterwards it only moves server → dev |
| Input files | `hifimagnet-projects` cloned on the server (public, HTTPS, branch `magnetgeo-1.0.0`) and mounted read-only at the absolute path the JSONs use (see Findings) |

## Findings (2026-10-22)

### Dashboard and image

| Item | Value |
|---|---|
| Launch | `apps/dashboards/magnetdb/Dockerfile` (gunicorn via `entrypoint.sh`); `scripts/run_docker.sh` wraps `docker run` with the rclone mount, `bdd.csv` and `~/.config/magnetdb` |
| Docker Hub | `trophime/magnettools:trixie` (base), `trophime/magnetdb-dashboard:dev` / `:test` present; `:dev` is amd64, 5.4 GB (about 1.2 GB to download), built 2026-10-15 from the working tree |
| DuckDB access | All dashboard connections are `read_only=True`; pint registry race fixed in python_magnetrun `6e22643`, so `THREADS=4` is safe |
| Runtime data read | `MAGNETDB_DB_PATH`; `<db dir>/hoop_parquet/parts/*.parquet` (`magnetdb_analysis.py:779`); `bdd.csv` via `MAGNETDB_SUPERVISION_BDD_CSV`; records tree via `MAGNETDB_RECORDS_DIR`; `~/.config/magnetdb/{style,group_order}.json` (written from the UI) |
| Not needed by the dashboard | `magnettools`, `python_magnetsetup`, `to_duckdb`, every other file in `Data/` (build inputs, already in the database) |
| Database dropdown | `glob("*.duckdb")` in `MAGNETDB_DB_DIR`, top level only |
| Container user | `jovyan`, uid 1000, gid 100, `HOME=/home/jovyan` |
| Image secrets | None: `python_magnetrun/.envrc` is tracked and only has `dotenv_if_exists .env`, no `.env` in the image |
| Image clutter | 15 `python_magnetrun/M*_20xx.log` tool logs (contain home paths) and `data/*.tdms`; build context also sends `Data/` (1.8 GB) |

### Problems found

| # | Problem | Effect |
|---|---|---|
| P1 | python_magnetrun: 1 commit not pushed (`909b2c6`), 6 uncommitted files (`csv_readers`, `validation`, polars/pandas magnetdata, 2 tests). Superproject pointer still at `077800f`, superproject 5 commits not pushed | A fresh clone gets older code than the one tested |
| P2 | Uncommitted `to_duckdb/schema.py`, `crud.py`, `compute_exp_stats.py` (adds `header_class`, `file_integrity`, `file_checks`, `file_checked_at` to `experiments`); `compute_exp_stats.py --reprocess` was running on the database (PID 1326853) | The seeded database would come from uncommitted code, and a copy taken now catches a write in progress |
| P3 | `*.mo` gitignored (`.gitignore:55`), `i18n.py` uses `fallback=True` | Image built from a fresh clone is English-only, with no error |
| P4 | `magnetdb-2026-10-08.duckdb` has a growing `.wal` | Unsafe to copy as is |
| P5 | `hoop_parquet/` (325 MB, 76 + 4 files) dated 2026-08-31, older than the database, shared by all databases in `to_duckdb/` | Part stats may show history that doesn't match the database |
| P6 | `Data/bdd.csv` is 1.16 GB, untracked; each new time window reads the whole file through `read_csv_auto` (cached per window, `lru_cache(64)`) | Must be transferred; first view of a window may take seconds |
| P7 | `.dockerignore` lacks `Data/`, `*.tgz`, python_magnetrun logs/data | About 2 GB build context; logs in the public image |
| P8 | Records only through `rclone-mount.service` (sftp remote `srv-data-install`, 147.173.88.250, `--allow-other`), LNCMI VLAN/VPN only | Server needs its own credential and network access |
| P9 | python_magnetrun depends on `nptdms @ git+https://github.com/Trophime/npTDMS.git@cc79e1be` | Building needs GitHub access; pulling does not |

### `scripts/run_docker.sh` review

| # | Problem | Fix |
|---|---|---|
| R1 | Container uid 1000 vs host uid (here 1966201125): saving styles/group order through the UI fails on `~/.config/magnetdb` (`magnetdb_plot.py:328`, `magnetdb_analysis.py:1376`) | Docker: `--user "$(id -u):$(id -g)" -e HOME=/home/jovyan` (`--user` alone gives `HOME=/`). Podman: `--userns=keep-id:uid=1000,gid=100` |
| R2 | No check that `hoop_parquet/` sits next to the database | Warn when missing |
| R3 | `--rm`, no `--name`, foreground only | `--name magnetdb-dashboard` (service mode is the Quadlet unit) |
| R4 | `-p 8050:8050` listens on every interface (Docker bypasses ufw) | `-p 127.0.0.1:8050:8050` |
| R5 | Records mounted read-write | Records `:ro`. The database folder stays read-write (option A) |
| R6 | Checks `SUPERVISION_DATA_DIR` exists, not `bdd.csv` | Test the file |
| R7 | Default image `:dev` built from uncommitted code | Pass a version tag through `DOCKER_IMAGE=` |
| R8 | A missing `~/.config/magnetdb` gets created root-owned by Docker | `mkdir -p` before `run` |
| R9 | Hard requirement on `rclone-mount.service` | Skip rclone when `$RECORDS_MOUNT` is already a mountpoint |
| R10 | `SUPERVISION_DATA_DIR` defaults to the dev repo's `Data/` | Default `$HOME/magnetdb-data/supervision` |

A stale copy of the script exists at `~/duckdb/run.sh` (before `DUCKDB_DIR` and supervision support). Not touched.

### CLI in the container (option A)

| Item | Value |
|---|---|
| Image content | `.dockerignore` excludes `to_duckdb/`; `python_magnetgeo`, `python_magnetsetup` not installed |
| magnettools | In the base image's system Python 3.13 (`/usr/lib/python3/dist-packages/magnettools`), but `/app/venv` has `include-system-site-packages = false`, so `import magnettools` fails in the image. Needed by `hoop-stress compute` (`stress_map.py`) |
| Imports | `to_duckdb` modules import flatly (`from schema import …`), so the CLI must run from its own folder |
| Default DB | `config.DEFAULT_DB = "test-magnetdb.duckdb"` (relative): always pass `--db` |
| Locking | DuckDB allows one read-write process **or** several read-only ones. While the CLI writes, the dashboard's read-only connections fail with a lock error |
| Backups | The CLI makes none (no `.bak` logic in `magnetdb.py` / `crud.py`) |
| Audit | `operation_log.user` comes from `getpass.getuser()`, which reads `USER` first: use `podman exec -e USER=<you>` |
| Login | Rootless Podman needs the user's systemd session: use `ssh magnetdb@server` or `sudo machinectl shell magnetdb@`, not `sudo -iu magnetdb` |

### Input files (`hifimagnet-projects`)

| Item | Value |
|---|---|
| Remote | `github.com/Trophime/hifimagnet-projects`, readable anonymously over HTTPS; dev checkout on `magnetgeo-1.0.0` (also `develop`) |
| Size | 66 MB checkout, 262 MB `.git`: use `--depth 1` |
| Absolute paths | 144 of the 298 files in `magnetdb.json/` set `"geometry"` to `/home/LNCMI-G/christophe.trophime/github/hifimagnet-projects/...yaml` |
| Failure mode | `load_geometry_json` (`crud.py:386-414`) prints `[WARN] Could not serialize geometry` and inserts the part with `geometry_data = NULL`; the command still succeeds and hoop stress can no longer be computed for that part |
| Workaround here | Mount the clone at that same absolute path, read-only. Removed by A11 #6 (`PLAN_update_impact_tracking.md`, follow-up 6) |

## Files affected

| Path | Action |
|---|---|
| `python_magnetrun` (submodule) | commit the 6 files on `spike/tdms-polars-benchmark`; push |
| superproject | commit the submodule pointer; maintainer commits the `to_duckdb` changes; push `msite_to_assembly` |
| `apps/dashboards/magnetdb/Dockerfile` | edit: venv with `--system-site-packages`; install `python_magnetgeo`, `python_magnetsetup` and the `to_duckdb` dependencies; copy `to_duckdb/*.py`; `pybabel compile -d src/locales -D magnetdb`; install the `magnetdb` wrapper on `PATH` |
| `apps/dashboards/magnetdb/magnetdb` | create: wrapper `cd /app/to_duckdb && exec python magnetdb.py "$@"` |
| `.dockerignore` | edit: exclude `Data/`, `*.tgz`, `python_magnetrun/*.log`, `python_magnetrun/data/`, `**/tests/*.tdms`; narrow `to_duckdb/` so only `*.py`, `pyproject.toml` and data files they load get in (never `*.duckdb*`, `hoop_parquet/`, `*.log`) |
| `scripts/run_docker.sh` | edit: R1–R10, `CONTAINER_ENGINE=docker\|podman`, `HIFIMAGNET_PROJECTS_DIR` mount (default `$HOME/github/hifimagnet-projects`). Used for the dev test and for running by hand |
| `scripts/systemd/magnetdb-dashboard.container` | create: Quadlet unit — `UserNS=keep-id:uid=1000,gid=100`, `PublishPort=127.0.0.1:8050:8050`, volumes and environment from the layout below, `Requires=`/`After=rclone-mount.service`, `Restart=always`, `WantedBy=default.target` |
| `scripts/systemd/rclone-mount.service` | create: the maintainer's unit with `%h` instead of the home path |
| `scripts/README.md` | edit: "Deploy on a server" (admin request, setup, seeding) and "Operate" (exec, backup, long jobs, pulling the database back) |

## Server layout (home of `magnetdb`)

| Path on the server | In the container | Mode | Filled by |
|---|---|---|---|
| `~/duckdb/magnetdb-2026-10-08.duckdb` + `~/duckdb/hoop_parquet/` | `/data/duckdb` | rw | rsync once (seeding), then the CLI |
| `~/duckdb/backups/`, `~/duckdb/work/` | (same mount) | rw | backups, long jobs (not listed by the dropdown) |
| `~/magnetdb-data/supervision/bdd.csv` | `/data/supervision/bdd.csv` | `:ro` | rsync from dev |
| `~/hifimagnet-projects` | `/home/LNCMI-G/christophe.trophime/github/hifimagnet-projects` | `:ro` | `git clone --depth 1 -b magnetgeo-1.0.0 https://github.com/Trophime/hifimagnet-projects.git`, then `git pull` |
| `~/LNCMIG-Data/records` | `/mnt/LNCMIG-Data/records` | `:ro` | rclone sftp mount |
| `~/.config/magnetdb/` | `/home/jovyan/.config/magnetdb` | rw | seeded once, then edited through the UI |

Environment: `MAGNETDB_DB_PATH=/data/duckdb/magnetdb-2026-10-08.duckdb`,
`MAGNETDB_DB_DIR=/data/duckdb`, `MAGNETDB_RECORDS_DIR=/mnt/LNCMIG-Data/records`,
`MAGNETDB_SUPERVISION_BDD_CSV=/data/supervision/bdd.csv`.

## Approach

Every `git push` and the Docker Hub push get a separate confirmation at the
time they run, even under this approval.

### Phase 0 — prerequisites (dev machine)

1. python_magnetrun: run `pytest`, commit the 6 files on the spike branch, push; commit the submodule pointer in the superproject
   → verify: `git submodule status` shows no `+`; `git -C python_magnetrun status -sb` shows nothing ahead or modified
2. Once `compute_exp_stats.py` has finished, maintainer commits the `to_duckdb` changes; push `msite_to_assembly`. **Any write to the dev database after the seed snapshot does not reach the server**
   → verify: `fuser to_duckdb/magnetdb-2026-10-08.duckdb*` prints nothing; `to_duckdb` tests pass; `git status` clean for `to_duckdb/*.py`
3. Image changes: Dockerfile, `magnetdb` wrapper, `.dockerignore`
   → verify, on an image built from a fresh `git clone --recursive` in the scratchpad: `python -c "import magnettools, python_magnetsetup, python_magnetgeo"` works; `magnetdb --help` works; `/app/src/locales/*/LC_MESSAGES/magnetdb.mo` present; `find /app -name '*.log' -o -name '*.duckdb'` prints nothing; build context in the tens of MB
4. Snapshot: copy the database and its `.wal` to a staging folder, `CHECKPOINT` **the copy** (the dev database is not touched), add `hoop_parquet/`
   → verify: no `.wal` in staging; read-only open gives non-zero counts for `experiments`, `magnets`, `assemblies`; every `hoop_stress_processed` entry has a matching parquet file
5. Dashboard tests
   → verify: `pytest apps/dashboards/magnetdb/tests` passes
6. Test before deploying: `CONTAINER_ENGINE=podman DUCKDB_DIR=<staging> scripts/run_docker.sh`, page smoke test (assembly/magnet/part/housing stats, Overview records, File viewer on one pupitre, one TDMS and one archive file, Defaults & Spikes, Research area, About, language switch, database dropdown, style save through the gear icon); then `podman exec -e USER=$USER magnetdb-dashboard magnetdb magnet add M10_Bi.json --input-dir /home/LNCMI-G/christophe.trophime/github/hifimagnet-projects/magnetdb.json --db /data/duckdb/magnetdb-2026-10-08.duckdb --dry-run`
   → verify: no callback errors in the logs; `~/.config/magnetdb/style.json` updated on the host; dry run prints its preview with no `[WARN] Could not serialize geometry`

### Phase 1 — publish (dev machine)

7. Tag `trophime/magnetdb-dashboard:<YYYY.MM.DD>` and push to Docker Hub
   → verify: `podman manifest inspect docker.io/trophime/magnetdb-dashboard:<tag>` finds it

### Phase 2 — server (maintainer and admin; Claude has no access)

- T0. Admin request: user `magnetdb` (no sudo, SSH key login), `/etc/subuid` and `/etc/subgid` entries, `loginctl enable-linger magnetdb`, `podman` and `rclone` installed, `user_allow_other` in `/etc/fuse.conf`. Same request, for the TLS follow-up: a DNS name, an institutional certificate, and whether the proxy on 80/443 is an admin-managed system package or rootless (sysctl)
  → verify: `ssh magnetdb@server podman info` shows `rootless: true`
- T1. rclone: remote `srv-data-install` with `magnetdb`'s **own read-only** sftp credential; unit from `scripts/systemd/rclone-mount.service`
  → verify: `nc -z 147.173.88.250 22`; `mountpoint ~/LNCMIG-Data/records`
- T2. Seed: rsync staging → `~/duckdb/` (**once**), `Data/bdd.csv` → `~/magnetdb-data/supervision/`, optional `style.json`/`group_order.json` → `~/.config/magnetdb/`; clone `hifimagnet-projects`
  → verify: `ls ~/duckdb ~/duckdb/hoop_parquet/parts ~/magnetdb-data/supervision` shows the files and no `.wal`
- T3. Install the Quadlet unit in `~/.config/containers/systemd/`, `systemctl --user daemon-reload && systemctl --user start magnetdb-dashboard`
  → verify: `curl -sf http://localhost:8050/` returns 200; `podman ps` lists the container; `podman exec magnetdb-dashboard ls /home/LNCMI-G/christophe.trophime/github/hifimagnet-projects/M10Bitters/M10_Bi.yaml` finds the file; after a reboot the dashboard is back
- T4. From the maintainer's PC: `ssh -L 8050:localhost:8050 magnetdb@server`, smoke test as in step 6; then a real write: backup, `podman exec -e USER=<you> magnetdb-dashboard magnetdb magnet add …`
  → verify: the new magnet appears in the dashboard; `magnetdb log view` shows the maintainer's name; no geometry warning

## Operating procedures (to document in `scripts/README.md`)

- **Short write** (`magnet add`, `assembly add`, `material update`, …): `cp` the database to `~/duckdb/backups/<name>.<timestamp>`; run with `--dry-run`; run for real. During the write (seconds) the dashboard may show a lock error; a reload fixes it.
- **Long job** (`populate`, `compute_exp_stats.py`, `hoop-stress compute`): copy the database to `~/duckdb/work/`, run on the copy, `CHECKPOINT`, `mv` over the live file. The rename is atomic; the dashboard opens a new connection per query.
- **New magnet config**: on dev, add JSON + YAML to `hifimagnet-projects`, commit, push; on the server, `git -C ~/hifimagnet-projects pull`, then the short-write procedure.
- **Dev copy of the database**: rsync server → dev while no command writes. **Never** push the database dev → server after T2.
- **`bdd.csv`**: re-export on dev, rsync dev → server.
- **New code**: repeat steps 1–7 with a new tag; on the server change `Image=` in the Quadlet unit, `daemon-reload`, restart. Rollback: previous tag.

## Out of scope / follow-ups

- LAN access: reverse proxy with TLS and login (own plan).
- Automatic backups of the server database — recommended next, since the server holds the master copy.
- A11 #6 portable geometry paths — removes the same-path mount of `hifimagnet-projects`.
- `bdd.csv` → Parquet to avoid reading 1.16 GB per new time window.
- Scheduled `populate` on the server (A7/A8).
- ROADMAP: mark Q1 resolved (stay on spike), add a deployment track.
- Not needed for this deployment: E1/A2 (M8 hoop stress stays missing until they land), F1–F4, track B, C1–C6, D2–D16.

## Assumptions

- The server is Debian (or similar) on amd64, inside the LNCMI network, with no SELinux (no `:Z` on volumes).
- `hifimagnet-projects` branch `magnetgeo-1.0.0`, the one the dev checkout uses.
- Dashboard listens on `127.0.0.1` until the TLS/login follow-up is done.
