#!/usr/bin/env bash
# Usage: run_traefik.sh   HTTPS + login in front of the dashboard started by run_docker.sh
set -euo pipefail

die() {
    echo "Error: $*" >&2
    exit 1
}

# --- Configuration (override via env vars) ---
TRAEFIK_DIR="$(dirname "$(readlink -f "$0")")/traefik"
: "${TRAEFIK_IMAGE:=traefik:v3.6.7}"
: "${TRAEFIK_PORT:=8443}"

command -v docker >/dev/null 2>&1 || die "docker is not installed or not on PATH."

[ -s "$TRAEFIK_DIR/htpasswd" ] \
    || die "$TRAEFIK_DIR/htpasswd not found or empty. Create it with: printf '%s:%s\n' <user> \"\$(openssl passwd -apr1)\" > $TRAEFIK_DIR/htpasswd"

# Shared with run_docker.sh: the dashboard is reached by its container name.
docker network inspect magnetdb >/dev/null 2>&1 || docker network create magnetdb >/dev/null

echo "Proxy starting — open https://<this machine's IP>:${TRAEFIK_PORT}/ (stop: docker stop magnetdb-traefik)"

docker run --rm \
    --name magnetdb-traefik \
    --network magnetdb \
    -v "$TRAEFIK_DIR:/etc/traefik:ro" \
    -p "${TRAEFIK_PORT}:8443" \
    "$TRAEFIK_IMAGE"
