#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lib.sh"
load_config
[[ -f "$ROOT_DIR/.work/src/manifest.json" ]] || "$ROOT_DIR/scripts/prepare-source.sh"
docker build --file "$ROOT_DIR/docker/Dockerfile" \
    --tag "$IMAGE" --build-arg "BUILD_JOBS=$BUILD_JOBS" \
    --build-context "dtk=$DTK_DIR" --build-context "hyhal=$HYHAL_DIR" "$ROOT_DIR"
info "built $IMAGE; the DTK is mounted at build/run time, not included in the image"
