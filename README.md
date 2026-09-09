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
[to_duckdb/README.md](to_duckdb/README.md). For the dashboard, see
[apps/dashboards/magnetdb/README.md](apps/dashboards/magnetdb/README.md).
