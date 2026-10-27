# ---- Dockerfile ----
# Build context must be the repo root (needs the python_magnetcooling /
# python_magnetrun submodules):
#   docker build -f apps/dashboards/magnetdb/Dockerfile -t magnetdb-dashboard .
ARG BASE_IMAGE=python:3.13-slim-trixie
FROM ${BASE_IMAGE}

ARG APP_UID=1000
ARG APP_GID=100

COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /uvx /bin/

# git: python_magnetrun pulls nptdms from a git URL
RUN apt-get update && apt-get install -y --no-install-recommends git git-lfs \
    && rm -rf /var/lib/apt/lists/*

# No named user: the app only needs a writable $HOME (~/.config/magnetdb,
# matplotlib cache); 1777 so any --user override still works
ENV HOME=/home/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_NO_CACHE=1 \
    UV_PYTHON_DOWNLOADS=never \
    VIRTUAL_ENV=/app/venv \
    PATH="/app/venv/bin:$PATH"
RUN mkdir -p /home/app && chmod 1777 /home/app

WORKDIR /app

# Isolated venv (no system site-packages): only what is installed below is visible
RUN uv venv --python /usr/local/bin/python3 /app/venv

# magnetcooling listed explicitly so magnetrun's python_magnetcooling[fitting]
# dep resolves to the local submodule instead of PyPI
COPY apps/dashboards/magnetdb/pyproject.toml ./dashboard/
COPY python_magnetcooling/ ./python_magnetcooling/
COPY python_magnetrun/ ./python_magnetrun/
RUN uv pip install ./dashboard gunicorn \
    "./python_magnetcooling[fitting]" \
    "./python_magnetrun[signal,dash,hybrid]"

COPY apps/dashboards/magnetdb/src/ ./src/
COPY --chmod=755 apps/dashboards/magnetdb/entrypoint.sh ./src/
WORKDIR /app/src

USER ${APP_UID}:${APP_GID}

ENV PORT=8050 \
    WORKERS=1 \
    THREADS=4 \
    TIMEOUT=120

EXPOSE 8050

# MAGNETDB_DB_PATH and MAGNETDB_RECORDS_DIR must be supplied at `docker run`
# time since the duckdb file and the records tree are data, not image content
# (see README). PORT, WORKERS, THREADS, and TIMEOUT are runtime-overridable via -e.

# entrypoint.sh execs gunicorn so it stays PID 1 and receives SIGTERM directly
ENTRYPOINT ["./entrypoint.sh"]
