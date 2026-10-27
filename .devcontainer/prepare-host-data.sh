#!/usr/bin/env bash
set -euo pipefail

# Host-side preparation run by devcontainer.json's initializeCommand (student
# devcontainer), before the container is created. Creates the bind-mounted
# data dirs so the container always starts, and only warns about data still
# missing: it can be added later, without a rebuild.
# The LNCMI staff devcontainer uses check-host-data.sh instead.

warn() {
    echo "Warning: $*" >&2
}

REPO_DIR="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"

# --- Configuration (must match the mounts in devcontainer.json) ---
DATA_ROOT="$HOME/magnetdb-duckdb-data"
RECORDS_DIR="$DATA_ROOT/records"
DUCKDB_DIR="$DATA_ROOT/duckdb"
: "${DUCKDB_NAME:=magnetdb.duckdb}"
SUPERVISION_BDD_CSV="$REPO_DIR/Data/bdd.csv"

mkdir -p "$RECORDS_DIR" "$DUCKDB_DIR"

if [ ! -f "$DUCKDB_DIR/$DUCKDB_NAME" ]; then
    warn "$DUCKDB_DIR/$DUCKDB_NAME not found; the dashboard has no database. A .duckdb file is needed: ask LNCMI staff, then copy it to $DUCKDB_DIR/."
fi

if [ -z "$(ls -A "$RECORDS_DIR")" ]; then
    warn "$RECORDS_DIR is empty; no records to view. Records archives are needed: ask LNCMI staff, then run tar -xJf <magnet>.tar.xz -C $RECORDS_DIR"
fi

if [ ! -f "$SUPERVISION_BDD_CSV" ]; then
    warn "$SUPERVISION_BDD_CSV not found; supervision panels will be empty. Data-csv.tgz is needed: ask LNCMI staff, then run tar -xzf Data-csv.tgz at the repo root ($REPO_DIR)."
fi

echo "Host data dirs ready (records: $RECORDS_DIR, duckdb: $DUCKDB_DIR)."
