#!/usr/bin/env bash
# Check a magnetdb DuckDB for problems, attempt to auto-fix any part/magnet
# geometry_data gaps, then re-check and report what (if anything) remains.
#
# `check` intentionally exits non-zero when it finds unresolved problems, so
# this script does not use `set -e` around the check/fix calls below — that
# exit status is expected output, not a script failure. The script's own
# exit code is that of the final check: 0 iff the DB is clean afterward.

DB="${1:-magnetdb.duckdb}"
if [ -n "$1" ] && [ "${DB#/}" = "$DB" ]; then
    DB="$PWD/$DB"
fi

cd "$(dirname "$0")/../to_duckdb" || exit 1

echo "=== check (before fix) ==="
python magnetdb.py check --db "$DB"

echo
echo "=== check --fix (repair part/magnet geometry_data) ==="
python magnetdb.py check --db "$DB" --fix

echo
echo "=== check (after fix) ==="
python magnetdb.py check --db "$DB"
