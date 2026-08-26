# ---- Dockerfile ----
# NOTE: build context must be the repo root, since this image needs the
# python_magnetrun / python_magnetcooling git submodules alongside it:
#   docker build -f apps/dashboards/magnetdb/Dockerfile -t magnetdb-dashboard .
FROM python:3.13-slim

# Keep Python from writing .pyc files / buffering stdout (cleaner logs)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps only if needed (e.g. for pandas/numpy wheels on slim images)
# Uncomment if you hit build errors on numpy/pandas:
# RUN apt-get update && apt-get install -y --no-install-recommends \
#     build-essential \
#     && rm -rf /var/lib/apt/lists/*

# Install deps first so Docker caches this layer when only app code changes
COPY apps/dashboards/magnetdb/pyproject.toml .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir . gunicorn

# python_magnetrun depends on python_magnetcooling[fitting]; install it first
# from the local submodule so python_magnetrun's install doesn't try (and fail)
# to fetch it from PyPI.
COPY python_magnetcooling/ ./python_magnetcooling/
RUN pip install --no-cache-dir "./python_magnetcooling[fitting]"

COPY python_magnetrun/ ./python_magnetrun/
RUN pip install --no-cache-dir ./python_magnetrun

# Now copy the actual app code
COPY apps/dashboards/magnetdb/src/ ./src/
WORKDIR /app/src

# Run as non-root for basic hardening
RUN useradd --create-home appuser && chown -R appuser /app
USER appuser

EXPOSE 8050

# MAGNETDB_DB_PATH and MAGNETDB_RECORDS_DIR must be supplied at `docker run`
# time (-e MAGNETDB_DB_PATH=... -v host/duckdb:...  -v host/records:/mnt/...)
# since the duckdb file and the records tree are data, not image content.

# magnetdb_app:server assumes magnetdb_app.py exposes `server = app.server`
CMD ["gunicorn", "magnetdb_app:server", \
     "--bind", "0.0.0.0:8050", \
     "--workers", "2", \
     "--threads", "4", \
     "--timeout", "120"]
