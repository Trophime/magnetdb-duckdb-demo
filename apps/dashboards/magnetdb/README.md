# MagnetDB dashboard

A [Dash](https://dash.plotly.com/) app for browsing MagnetDB duckdb data:
magnet/part records, experiment overviews, and per-file signal plots.

## Running interactively

### Setup

From the repo root, the quickest path is the devcontainer setup script,
which initializes submodules and creates a venv with everything installed:

```bash
.devcontainer/setup-basic.sh
source .venv/bin/activate
```

If you already have a venv set up, the dashboard's own dependencies (plus
its `python_magnetcooling`/`python_magnetrun` siblings) install with:

```bash
pip install "./python_magnetcooling[fitting]"
pip install "./python_magnetrun[signal,dash,hybrid]"
pip install "./apps/dashboards/magnetdb[test]"
```

See [pyproject.toml](pyproject.toml) for notes on the `magnettools`
dependency (Debian package vs. local source build).

> [!IMPORTANT] This setup is intended for development and interactive use on Debian-based systems or WSL only.
>  For production deployment, consider using the Docker setup described below.

### Environment variables

Required, before launching:

| Variable | Purpose |
|---|---|
| `MAGNETDB_DB_PATH` | Path to the duckdb file to open by default |
| `MAGNETDB_DB_DIR` | Directory the "available databases" dropdown scans |
| `MAGNETDB_RECORDS_DIR` | Root directory of the raw records tree |

Optional:

| Variable | Purpose |
|---|---|
| `MAGNETDB_DISPLAY_TZ` | Timezone for displayed timestamps (default `Europe/Paris`) |
| `MAGNETDB_PROFILE` | Set to enable per-request cProfile — see [PROFILING.md](PROFILING.md) |
| `MAGNETDB_FILE_TYPE_STYLES` | Override path for file-type plot style config |

Example (adapt the paths to your machine):

```bash
export MAGNETDB_DB_PATH=/path/to/to_duckdb/test-magnetdb.duckdb
export MAGNETDB_DB_DIR=/path/to/to_duckdb
export MAGNETDB_RECORDS_DIR=/path/to/records
```

### User config files

Two optional files under `~/.config/magnetdb/` let you override in-repo
defaults without editing tracked files:

| File | Controls | Resolution order |
|---|---|---|
| `~/.config/magnetdb/style.json` | Per-file-type plot styling | `$MAGNETDB_FILE_TYPE_STYLES` → this file → bundled `style.json` → in-code defaults |
| `~/.config/magnetdb/group_order.json` | Sensor-group display order | this file → bundled `group_order.json` → no reordering |

Scaffold either one from a sensible starting point rather than writing it
by hand:

```bash
python scripts/init_style_config.py          # writes today's in-code style defaults
python scripts/init_group_order.py --file <FILENAME>   # derives group names from a real record
```

See [PLOT_STYLE.md](PLOT_STYLE.md) and `PLAN_group_order.md` for details on
each file's format.

When running in Docker, `~/.config/magnetdb/` resolves inside the
container (the app user's home there), so a host override only takes
effect if you mount it in, e.g.
`-v ~/.config/magnetdb:/home/jovyan/.config/magnetdb`.

### Launch

```bash
cd apps/dashboards/magnetdb/src
python magnetdb_app.py
```

Flags (all optional):

| Flag | Default | Purpose |
|---|---|---|
| `--host` | `0.0.0.0` | Bind address |
| `--port` | `8050` | Bind port |
| `--debug` / `--no-debug` | `--debug` | Dash debug mode (auto-reload, error overlay) |
| `--dev-tools-ui` | off | Dash dev tools UI panel |

Then open `http://localhost:8050/` in a browser.

## Running with Docker

> [!NOTE] On Windows, use Docker Desktop (WSL2 backend recommended). Two
> things differ from the examples below: volume host paths (use Windows-style
> paths from PowerShell/cmd, e.g. `-v C:\Users\you\to_duckdb:/data/duckdb`, or
> Linux-style paths like `/mnt/c/...` if invoking `docker` from inside WSL)
> and line continuation (PowerShell uses `` ` `` instead of `\`, cmd uses `^`
> — or just write the command on one line).

The build context must be the **repo root**, since the image needs the
`python_magnetrun`/`python_magnetcooling` git submodules alongside it:

```bash
docker build -f apps/dashboards/magnetdb/Dockerfile -t magnetdb-dashboard .
```

The build accepts these `--build-arg` overrides:

| Arg | Default | Purpose |
|---|---|---|
| `BASE_IMAGE` | `trophime/magnettools:trixie` | Base image to build from |
| `USERNAME` | `jovyan` | App user created in the image |
| `USER_UID` | `1000` | UID for that user |
| `USER_GID` | `100` | GID for that user |

```bash
docker build -f apps/dashboards/magnetdb/Dockerfile \
    --build-arg BASE_IMAGE=trophime/magnettools:bookworm \
    -t magnetdb-dashboard .
```

> [!CAUTION] Do nothange build arguments unless you know what you are doing.

`MAGNETDB_DB_PATH` and `MAGNETDB_RECORDS_DIR` are data, not image content —
supply them at `docker run` time, mounting the host paths in:

```bash
docker run \
    -e MAGNETDB_DB_PATH=/data/duckdb/test-magnetdb.duckdb \
    -e MAGNETDB_DB_DIR=/data/duckdb \
    -e MAGNETDB_RECORDS_DIR=/data/records \
    -v /path/to/to_duckdb:/data/duckdb \
    -v /path/to/records:/data/records \
    -p 8050:8050 \
    magnetdb-dashboard
```

The container serves the app with gunicorn, tunable at `docker run` time
via `-e` (defaults shown):

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | `8050` | Bind port |
| `WORKERS` | `1` | Gunicorn worker processes |
| `THREADS` | `4` | Threads per worker |
| `TIMEOUT` | `120` | Worker timeout (seconds) |

```bash
docker run \
    -e WORKERS=3 -e THREADS=2 -e TIMEOUT=60 -e PORT=9000 \
    ... \
    -p 9000:9000 \
    magnetdb-dashboard
```

See [entrypoint.sh](entrypoint.sh) for how these expand.

## See also

- [PROFILING.md](PROFILING.md) — profiling slow callbacks/requests.
- [PLOT_STYLE.md](PLOT_STYLE.md) — per-file-type plot style configuration.
