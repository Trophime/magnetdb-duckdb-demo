#!/usr/bin/env bash
set -euo pipefail

# Host-side checks run by local/devcontainer.json's initializeCommand, before
# the container is created; mirrors the checks in scripts/run_docker.sh.
# The records location comes from the python_magnetrun user setup
# (MAGNETRUN_*_DATA_DIR env vars > ~/.config/python_magnetrun/data_dirs.json
# > built-in defaults), resolved by running its data_dirs.py.

die() {
    echo "Error: $*" >&2
    exit 1
}

REPO_DIR="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"

# --- Configuration (must match the mounts in local/devcontainer.json) ---
RECORDS_MOUNT="$HOME/LNCMIG-Data/records"
DUCKDB_DIR="$HOME/duckdb"
: "${DUCKDB_NAME:=magnetdb.duckdb}"
SUPERVISION_DATA_DIR="$REPO_DIR/Data"
MAGNETDB_CONFIG_DIR="$HOME/.config/magnetdb"

command -v python3 >/dev/null 2>&1 || die "python3 is required to read the python_magnetrun data_dirs setup."

data_dirs_py="$REPO_DIR/python_magnetrun/python_magnetrun/data_dirs.py"
[ -f "$data_dirs_py" ] || die "$data_dirs_py not found — run: git submodule update --init"

resolved=$(python3 -I - "$data_dirs_py" <<'EOF'
import runpy
import sys

dirs = runpy.run_path(sys.argv[1])
for key in ("PUPITRE_DATA_DIR", "PIGBROTHER_DATA_DIR", "HYBRID_DATA_DIR"):
    print(dirs[key])
EOF
) || die "cannot resolve the python_magnetrun data directories from $data_dirs_py."

{ read -r pupitre_dir; read -r pigbrother_dir; read -r hybrid_dir; } <<< "$resolved"

# The container mounts only the records root and expects magnetrun's default
# sub-directory names below it (see MAGNETRUN_*_DATA_DIR in containerEnv).
records_dir="$(dirname "$pupitre_dir")"
for pair in "$pupitre_dir:srv-data-install" "$pigbrother_dir:pbsurv" "$hybrid_dir:CEA"; do
    dir="${pair%:*}"
    name="${pair##*:}"
    [ "$(dirname "$dir")" = "$records_dir" ] \
        || die "$dir is not under $records_dir — the pupitre, pigbrother and hybrid data dirs must share one records root. Check MAGNETRUN_*_DATA_DIR / ~/.config/python_magnetrun/data_dirs.json."
    [ "$(basename "$dir")" = "$name" ] \
        || die "$dir must be named '$name'. Check MAGNETRUN_*_DATA_DIR / ~/.config/python_magnetrun/data_dirs.json."
done

[ "$records_dir" = "$RECORDS_MOUNT" ] \
    || die "python_magnetrun records root is $records_dir but the devcontainer mounts $RECORDS_MOUNT. Check ~/.config/python_magnetrun/data_dirs.json."

for dir in "$records_dir" "$pupitre_dir" "$pigbrother_dir" "$hybrid_dir"; do
    [ -d "$dir" ] \
        || die "$dir not found. Start rclone-mount.service (systemctl --user start rclone-mount.service); it only works when connected to an LNCMI VLAN or the LNCMI VPN."
done

[ -f "$DUCKDB_DIR/$DUCKDB_NAME" ] || die "$DUCKDB_DIR/$DUCKDB_NAME not found."

if [ ! -f "$SUPERVISION_DATA_DIR/bdd.csv" ]; then
    echo "Warning: $SUPERVISION_DATA_DIR/bdd.csv not found; supervision panels will be empty." >&2
fi

if [ ! -d "$MAGNETDB_CONFIG_DIR" ]; then
    echo "Warning: $MAGNETDB_CONFIG_DIR not found; creating it empty." >&2
    mkdir -p "$MAGNETDB_CONFIG_DIR"
fi

echo "Host data checks passed (records: $records_dir, duckdb: $DUCKDB_DIR/$DUCKDB_NAME)."
