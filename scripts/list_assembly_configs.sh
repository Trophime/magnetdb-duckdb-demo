#!/usr/bin/env bash
# List assembly files (e.g. M10_A180220_00.json) sorted by embedded YYMMDD date.
set -euo pipefail

CONFIG_DIR="${1:-$HOME/github/hifimagnet-projects/magnetdb.json}"

for path in "$CONFIG_DIR"/*.json; do
    [ -e "$path" ] || continue
    name=$(basename "$path")
    if [[ $name =~ ^.+_A([0-9]{6})_[0-9]+\.json$ ]]; then
        printf '%s\t%s\n' "${BASH_REMATCH[1]}" "$name"
    fi
done | sort -t $'\t' -k1,1n -k2,2 | cut -f2
