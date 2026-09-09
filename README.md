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
| `scripts/` | Misc shell utilities (geometry checks, config listing, summary sorting) |
| `python_magnetrun/`, `python_magnetgeo/`, `python_magnetsetup/`, `python_magnetcooling/` | Git submodules — vendored MagnetDB Python packages |

## Getting started

This repo is set up as a VS Code dev container.

```bash
git submodule update --init --recursive
```

Then reopen the folder in the dev container, or run the setup script
manually:

```bash
./.devcontainer/setup-basic.sh
source .venv/bin/activate
```

For the database CLI and schema reference, see
[to_duckdb/README.md](to_duckdb/README.md).

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
