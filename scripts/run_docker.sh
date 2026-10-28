#!/usr/bin/env bash
# Usage: run_docker.sh [IMAGE]   (IMAGE overrides $DOCKER_IMAGE)
set -euo pipefail

die() {
    echo "Error: $*" >&2
    exit 1
}

# --- Configuration (override via env vars) ---
: "${RECORDS_MOUNT:=$HOME/LNCMIG-Data/records}"
: "${DUCKDB_NAME:=magnetdb.duckdb}"
: "${DUCKDB_DIR:=$HOME/duckdb}"
: "${SUPERVISION_DATA_DIR:=$(dirname "$(readlink -f "$0")")/../Data}"
: "${DOCKER_REGISTRY:=}"
DOCKER_IMAGE="${1:-${DOCKER_IMAGE:-trophime/magnetdb-dashboard:dev}}"
IMAGE_REF="${DOCKER_REGISTRY:+${DOCKER_REGISTRY}/}${DOCKER_IMAGE}"

# need to get duckdb from nextcloud
# same for the supervision data directory (provided as tgz archive right now)

command -v docker >/dev/null 2>&1 || die "docker is not installed or not on PATH."

[ -f "$DUCKDB_DIR/$DUCKDB_NAME" ] || die "$DUCKDB_DIR/$DUCKDB_NAME not found."
[ -d "$DUCKDB_DIR/hoop_parquet" ] \
    || echo "Warning: $DUCKDB_DIR/hoop_parquet not found; part stats will show no hoop-stress history." >&2

# A locally built image (never pulled/pushed) has no RepoDigests: nothing to pull.
digests=$(docker image inspect -f '{{len .RepoDigests}}' "$IMAGE_REF" 2>/dev/null || true)
if [ "$digests" != "0" ]; then
    read -r -p "Check for a newer $IMAGE_REF? [y/N] " reply || reply=""
    case "$reply" in
        [yY]*)
            docker pull "$IMAGE_REF" || echo "Warning: docker pull failed; continuing with the local image (if any)." >&2
            ;;
        *)
            ;;
    esac
fi

# Already mounted (by rclone or anything else): nothing to start.
if ! mountpoint -q "$RECORDS_MOUNT"; then
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
fi

supervision_args=()
if [ -f "$SUPERVISION_DATA_DIR/bdd.csv" ]; then
    supervision_args=(
        -v "$SUPERVISION_DATA_DIR:/data/supervision:ro"
        -e "MAGNETDB_SUPERVISION_BDD_CSV=/data/supervision/bdd.csv"
    )
else
    echo "Warning: $SUPERVISION_DATA_DIR/bdd.csv not found; supervision panels will be empty." >&2
fi

# Optional site-wide style/group-order override; not mounted when absent,
# otherwise docker would create it root-owned.
config_args=()
if [ -d "$HOME/.config/magnetdb" ]; then
    config_args=(-v "$HOME/.config/magnetdb:/home/app/.config/magnetdb:ro")
fi

# Shared with scripts/run_traefik.sh, which reaches the dashboard by name.
docker network inspect magnetdb >/dev/null 2>&1 || docker network create magnetdb >/dev/null

echo "Dashboard starting — open http://localhost:8050/"

docker run --rm \
    --name magnetdb-dashboard \
    --network magnetdb \
    "${supervision_args[@]}" \
    "${config_args[@]}" \
    -e "MAGNETDB_DB_PATH=/data/duckdb/${DUCKDB_NAME}" \
    -e "MAGNETDB_DB_DIR=/data/duckdb" \
    -e "MAGNETDB_RECORDS_DIR=/mnt/LNCMIG-Data/records" \
    -v "$DUCKDB_DIR:/data/duckdb:ro" \
    -v "$RECORDS_MOUNT:/mnt/LNCMIG-Data/records:ro" \
    -p 127.0.0.1:8050:8050 \
    "$IMAGE_REF"
