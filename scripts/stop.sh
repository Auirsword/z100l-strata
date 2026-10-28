#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lib.sh"
load_config
container_exists || { info "$CONTAINER does not exist"; exit 0; }
if [[ $(docker inspect -f '{{.State.Running}}' "$CONTAINER") == true ]]; then
    if docker exec "$CONTAINER" bash -c 'for comm in /proc/[0-9]*/comm; do
        if [[ $(<"$comm") == strata-host ]]; then
            pid=${comm#/proc/}
            printf "STOP\nQUIT\n" > "/proc/${pid%/comm}/fd/0"
            exit 0
        fi
    done
    exit 1' >/dev/null 2>&1; then
        info "sent native STOP/QUIT to $CONTAINER"
    else
        info "native control unavailable; sending SIGTERM to $CONTAINER"
        docker kill --signal=SIGTERM "$CONTAINER" >/dev/null
    fi
    info "waiting up to $STOP_TIMEOUT seconds for $CONTAINER to exit"
    for ((elapsed = 0; elapsed < STOP_TIMEOUT; elapsed++)); do
        [[ $(docker inspect -f '{{.State.Running}}' "$CONTAINER") == true ]] || break
        sleep 1
    done
    if [[ $(docker inspect -f '{{.State.Running}}' "$CONTAINER") == true ]]; then
        die "$CONTAINER is still running; timeout reached, no forced kill was used"
    fi
fi
docker rm "$CONTAINER" >/dev/null
info "$CONTAINER removed; no GPU reset or forced process kill was used"
