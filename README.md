# MagnetDB DuckDB Demo

Tooling and apps for building, querying, and visualizing a standalone
[DuckDB](https://duckdb.org/) database of MagnetDB data — magnets,
assemblies, experiments, operational statistics, and hoop-stress analysis.

No Django, PostgreSQL, MinIO, or any other MagnetDB service needs to be
running. The result is a single portable `.duckdb` file that can be queried
directly from Python, Jupyter, or the included dashboard.

This repository was extracted from the `2026-m1-hifimagnet` project to
isolate the DuckDB-based tooling and demo apps.

## Repository layout

| Path | Description |
|---|---|
| [`to_duckdb/`](to_duckdb/README.md) | Core library + `magnetdb.py` CLI for building, populating, and querying the DuckDB database |
| [`apps/dashboards/magnetdb/`](apps/dashboards/magnetdb/README.md) | Dash web dashboard for browsing assemblies, experiments, and statistics |
| `apps/notebooks/` | Jupyter notebooks, including Voila-servable apps (`voila-Bmap.ipynb`, `voila-Bmap-db.ipynb`) |
| `apps/marimo/` | Interactive [marimo](https://marimo.io/) app for browsing assemblies |
| [`apps/tutorials/`](apps/tutorials/README.md) | Standalone demo scripts and student tutorials |
| [`scripts/`](scripts/README.md) | Database build script and shell utilities (geometry checks, dashboard Docker launcher, config listing, summary sorting) |
| `python_magnetrun/`, `python_magnetgeo/`, `python_magnetsetup/`, `python_magnetcooling/` | Git submodules — vendored MagnetDB Python packages |

## Getting started

This repo ships two VS Code dev containers (*Reopen in Container* asks which one):

| Dev container | For | MagnetTools | Data |
|---|---|---|---|
| `.devcontainer/devcontainer.json` — "MagnetDB duckdb demonstrator (no magnettools)" | students, interns | no (hoop-stress commands unavailable) | provided by LNCMI staff, see below |
| `.devcontainer/local/devcontainer.json` — "Magnet DuckDB Dashboard demo (LNCMI, local mount)" | LNCMI staff | yes, from the local `magnettools-db:trixie-1.2.6` image | LNCMI records (rclone mount), `~/duckdb` |

**Windows:** install WSL2 (Ubuntu), clone the repo *inside* WSL and open it
from there (`code .` in the WSL shell). The dev containers need a Linux or
macOS host shell; a clone in a Windows folder will not work.

```bash
git clone --recurse-submodules https://github.com/Trophime/magnetdb-duckdb-demo.git
# or, in an existing clone:
git submodule update --init --recursive
```

### Data for the student dev container

Ask LNCMI staff for:

- `Data-csv.tgz` — CSV data, including SUPERVISION `Data/bdd.csv`;
  extract it at the repo root: `tar -xzf Data-csv.tgz`
- a `.duckdb` file → `~/magnetdb-duckdb-data/duckdb/`
- records archives `<magnet>.tar.xz` →
  `tar -xJf <magnet>.tar.xz -C ~/magnetdb-duckdb-data/records`

Files added later show up in the running container immediately; no rebuild needed.

The container creates its venv in `/home/myuser/.venvs/magnetdb`
(`.devcontainer/setup-uv.sh`); see the welcome message for details.

For the database CLI and schema reference, see
[to_duckdb/README.md](to_duckdb/README.md).

## Building the database

[`scripts/build_from_scratch.sh`](scripts/build_from_scratch.sh) rebuilds the
database from scratch into `to_duckdb/magnetdb-<YYYY-MM-DD>.duckdb`: it loads
the assemblies, magnet statuses, experiments, operational data and their
statistics, overview records and the users table. Each step prints `OK`,
`FAILED` or `SKIPPED`; the command output goes to `<database>.log`.

```bash
source .venv/bin/activate
scripts/build_from_scratch.sh
```

It needs the assembly JSON files (`~/github/hifimagnet-projects/magnetdb.json`)
and the records tree (`~/LNCMIG-Data/records`). Refreshing the source CSVs in
`Data/` needs credentials loaded by direnv from
`~/github/python_magnetrun/examples/.envrc`; without them that step is skipped
and the existing files are used.

To re-run part of a build on an existing database:

```bash
scripts/build_from_scratch.sh --from export --db to_duckdb/magnetdb-2026-10-08.duckdb
```

See [scripts/README.md](scripts/README.md) for the step IDs and the other
helper scripts.

## Running the dashboard

Recommended (production-style): build and run via Docker from the repo root,
since the image needs the `python_magnetrun`/`python_magnetcooling`
submodules alongside it:

```bash
docker build -f apps/dashboards/magnetdb/Dockerfile -t magnetdb-dashboard .
docker run \
    -e MAGNETDB_DB_PATH=/data/duckdb/test-magnetdb.duckdb \
    -e MAGNETDB_DB_DIR=/data/duckdb \
    -e MAGNETDB_RECORDS_DIR=/data/records \
    -v /path/to/to_duckdb:/data/duckdb \
    -v /path/to/records:/data/records \
    -p 8050:8050 \
    magnetdb-dashboard
```

Then open `http://localhost:8050/`.

For interactive development instead (Debian/WSL only), see
[apps/dashboards/magnetdb/README.md](apps/dashboards/magnetdb/README.md).
