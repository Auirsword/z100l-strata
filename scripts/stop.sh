#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lib.sh"
load_config
container_exists || { info "$CONTAINER does not exist"; exit 0; }
if [[ $(docker inspect -f '{{.State.Running}}' "$CONTAINER") == true ]]; then
    info "stopping $CONTAINER gracefully; waiting up to $STOP_TIMEOUT seconds"
    docker stop --time "$STOP_TIMEOUT" "$CONTAINER"
fi
docker rm "$CONTAINER" >/dev/null
info "$CONTAINER removed; no GPU reset or forced process kill was used"
