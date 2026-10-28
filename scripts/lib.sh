#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
info() { printf '[z100l] %s\n' "$*"; }
die() { printf '[z100l] ERROR: %s\n' "$*" >&2; exit 1; }
require_command() { command -v "$1" >/dev/null 2>&1 || die "missing command: $1"; }

load_config() {
    # shellcheck disable=SC1091
    source "$ROOT_DIR/config/default.env"
    if [[ -f "$ROOT_DIR/.env" ]]; then
        # shellcheck disable=SC1091
        source "$ROOT_DIR/.env"
    fi
    DATA_DIR=${DATA_DIR:-"$HOME/.local/share/z100l-strata"}
    MODEL_DIR=${MODEL_DIR:-"$DATA_DIR/model"}
    [[ "$DATA_DIR" = /* ]] || die "DATA_DIR must be absolute"
    [[ "$MODEL_DIR" = /* ]] || die "MODEL_DIR must be absolute"
    [[ "$GPU_ID" =~ ^[0-9]+$ ]] || die "GPU_ID must be a non-negative integer"
    [[ "$PORT" =~ ^[0-9]+$ ]] || die "PORT must be an integer"
    (( PORT >= 1024 && PORT <= 65535 )) || die "PORT must be between 1024 and 65535"
    [[ "$BUILD_JOBS" =~ ^[1-9][0-9]*$ ]] || die "BUILD_JOBS must be positive"
    [[ "$PACK_JOBS" =~ ^[1-9][0-9]*$ ]] || die "PACK_JOBS must be positive"
    [[ "$STOP_TIMEOUT" =~ ^[1-9][0-9]*$ ]] || die "STOP_TIMEOUT must be positive"
    [[ "$CHECK_MODEL_HASH" == 0 || "$CHECK_MODEL_HASH" == 1 ]] || die "CHECK_MODEL_HASH must be 0 or 1"
    [[ "$DOCKER_APPARMOR" == default || "$DOCKER_APPARMOR" == unconfined || "$DOCKER_APPARMOR" == z100l-strata ]] ||
        die "DOCKER_APPARMOR must be z100l-strata, default or unconfined"
    [[ "$RESTART_POLICY" == no || "$RESTART_POLICY" == unless-stopped || "$RESTART_POLICY" == always ]] ||
        die "unsupported RESTART_POLICY"
    [[ "$PUBLISH_HOST" != *[[:space:]]* ]] || die "PUBLISH_HOST cannot contain whitespace"
    [[ "$DOCKER_NETWORK" == bridge || "$DOCKER_NETWORK" == host ]] || die "DOCKER_NETWORK must be bridge or host"
    export DATA_DIR MODEL_DIR IMAGE CONTAINER DTK_DIR HYHAL_DIR GPU_ID PUBLISH_HOST PORT
    export BUILD_JOBS PACK_JOBS STOP_TIMEOUT RESTART_POLICY DOCKER_APPARMOR SHM_SIZE PRESET DOCKER_NETWORK AMDGPU_TARGETS
}

container_exists() { docker container inspect "$CONTAINER" >/dev/null 2>&1; }
