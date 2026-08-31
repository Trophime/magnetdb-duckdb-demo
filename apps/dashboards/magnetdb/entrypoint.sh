#!/bin/sh
set -e

# magnetdb_app:server assumes magnetdb_app.py exposes `server = app.server`
exec gunicorn magnetdb_app:server \
    --bind 0.0.0.0:${PORT} \
    --workers ${WORKERS} \
    --threads ${THREADS} \
    --timeout ${TIMEOUT}
