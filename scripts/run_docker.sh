#!/usr/bin/env bash
set -euo pipefail

die() {
    echo "Error: $*" >&2
    exit 1
}

# --- Configuration (override via env vars) ---
: "${RECORDS_MOUNT:=$HOME/LNCMIG-Data/records}"
: "${DUCKDB_NAME:=magnetdb.duckdb}"
: "${DOCKER_REGISTRY:=}"
: "${DOCKER_IMAGE:=trophime/magnetdb-dashboard:dev}"
IMAGE_REF="${DOCKER_REGISTRY:+${DOCKER_REGISTRY}/}${DOCKER_IMAGE}"

command -v docker >/dev/null 2>&1 || die "docker is not installed or not on PATH."

[ -f "$HOME/duckdb/$DUCKDB_NAME" ] || die "$HOME/duckdb/$DUCKDB_NAME not found."

read -r -p "Check for a newer $IMAGE_REF? [y/N] " reply || reply=""
case "$reply" in
    [yY]*)
        docker pull "$IMAGE_REF" || echo "Warning: docker pull failed; continuing with the local image (if any)." >&2
        ;;
    *)
        ;;
esac

[ "$(systemctl --user show -p LoadState --value rclone-mount.service)" = "loaded" ] \
    || die "rclone-mount.service is not installed for this user (systemctl --user). It's required to mount $RECORDS_MOUNT — set it up first."

systemctl --user start rclone-mount.service

mounted=0
for _ in $(seq 1 10); do
    if mountpoint -q "$RECORDS_MOUNT"; then
        mounted=1
        break
    fi
    sleep 1
done
[ "$mounted" -eq 1 ] \
    || die "$RECORDS_MOUNT is not mounted. rclone-mount.service only works when connected to an LNCMI VLAN or the LNCMI VPN — check your connection and try again."

echo "Dashboard starting — open http://localhost:8050/"

docker run --rm \
    -e "MAGNETDB_DB_PATH=/data/duckdb/${DUCKDB_NAME}" \
    -e "MAGNETDB_DB_DIR=/data/duckdb" \
    -e "MAGNETDB_RECORDS_DIR=/mnt/LNCMIG-Data/records" \
    -v "$HOME/duckdb:/data/duckdb" \
    -v "$RECORDS_MOUNT:/mnt/LNCMIG-Data/records" \
    -v "$HOME/.config/magnetdb:/home/jovyan/.config/magnetdb" \
    -p 8050:8050 \
    "$IMAGE_REF"
