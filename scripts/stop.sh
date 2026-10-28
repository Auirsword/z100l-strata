#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lib.sh"
load_config
container_exists || { info "$CONTAINER does not exist"; exit 0; }
if [[ $(docker inspect -f '{{.State.Running}}' "$CONTAINER") == true ]]; then
    info "sending SIGTERM to $CONTAINER; waiting up to $STOP_TIMEOUT seconds"
    docker kill --signal=SIGTERM "$CONTAINER" >/dev/null
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
