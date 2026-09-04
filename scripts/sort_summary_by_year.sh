#!/usr/bin/env bash
# List summary files (e.g. M9_summary-2025.json) sorted by embedded year.
set -euo pipefail

DATA_DIR="${1:-$(dirname "$0")/../Data}"

for path in "$DATA_DIR"/M*_summary-*.json; do
    [ -e "$path" ] || continue
    name=$(basename "$path")
    if [[ $name =~ ^M.+_summary-([0-9]{4})\.json$ ]]; then
        printf '%s\t%s\n' "${BASH_REMATCH[1]}" "$name"
    fi
done | sort -t $'\t' -k1,1n -k2,2 | cut -f2
