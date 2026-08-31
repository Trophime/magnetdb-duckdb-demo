# ---- Dockerfile ----
# NOTE: build context must be the repo root, since this image needs the
# python_magnetrun / python_magnetcooling git submodules alongside it:
#   docker build -f apps/dashboards/magnetdb/Dockerfile -t magnetdb-dashboard .
ARG BASE_IMAGE=trophime/magnettools:trixie
FROM ${BASE_IMAGE}

# get the default from BASE_IMAGE (trophime/magnetdb)
ARG USERNAME=jovyan
ARG USER_UID=1000
ARG USER_GID=100

# The base image may already default to a non-root user; regain root for
# package installs and user/group administration below.
USER root

# Keep Python from writing .pyc files / buffering stdout (cleaner logs)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# System deps only if needed (e.g. for pandas/numpy wheels on slim images)
# Uncomment if you hit build errors on numpy/pandas:
# RUN apt-get update && apt-get install -y --no-install-recommends \
#     build-essential \
#     && rm -rf /var/lib/apt/lists/*

# Create group/user first so the venv and all installs are owned by the app user
RUN if ! getent group "${USERNAME}" > /dev/null 2>&1; then \
        groupadd --non-unique --gid "${USER_GID}" "${USERNAME}"; \
    fi && \
    if ! id "${USERNAME}" > /dev/null 2>&1; then \
        useradd --non-unique --uid "${USER_UID}" --gid "${USER_GID}" --create-home "${USERNAME}"; \
    fi && \
    mkdir -p /app && chown "${USER_UID}:${USER_GID}" /app

USER ${USERNAME}
WORKDIR /app

# venv owned by the app user; pip and egg_info writes succeed without privilege issues
RUN python3 -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

# Install deps first so Docker caches this layer when only app code changes
COPY --chown=${USERNAME}:${USERNAME} apps/dashboards/magnetdb/pyproject.toml .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir . gunicorn

# python_magnetrun depends on python_magnetcooling[fitting]; install it first
# from the local submodule so python_magnetrun's install doesn't try (and fail)
# to fetch it from PyPI.
COPY --chown=${USERNAME}:${USERNAME} python_magnetcooling/ ./python_magnetcooling/
RUN pip install --no-cache-dir "./python_magnetcooling[fitting]"

COPY --chown=${USERNAME}:${USERNAME} python_magnetrun/ ./python_magnetrun/
RUN pip install --no-cache-dir "./python_magnetrun[signal,dash,hybrid]"

# Now copy the actual app code
COPY --chown=${USERNAME}:${USERNAME} apps/dashboards/magnetdb/src/ ./src/
WORKDIR /app/src

COPY --chown=${USERNAME}:${USERNAME} apps/dashboards/magnetdb/entrypoint.sh .
RUN chmod +x entrypoint.sh

ENV PORT=8050 \
    WORKERS=1 \
    THREADS=4 \
    TIMEOUT=120

EXPOSE 8050

# MAGNETDB_DB_PATH and MAGNETDB_RECORDS_DIR must be supplied at `docker run`
# time (-e MAGNETDB_DB_PATH=... -v host/duckdb:...  -v host/records:/mnt/...)
# since the duckdb file and the records tree are data, not image content.
# PORT, WORKERS, THREADS, and TIMEOUT are also runtime-overridable via -e,
# e.g. -e WORKERS=3 -e THREADS=2; defaults above match prior fixed values.

# entrypoint.sh execs gunicorn so it stays PID 1 and receives SIGTERM directly
ENTRYPOINT ["./entrypoint.sh"]
