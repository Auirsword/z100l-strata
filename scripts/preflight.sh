#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lib.sh"
load_config
for command in docker git python3 curl sha256sum; do require_command "$command"; done
[[ $(uname -m) == x86_64 ]] || die "this release requires x86_64 Linux"
[[ $(uname -s) == Linux ]] || die "this release requires Linux"
[[ -f "$DTK_DIR/env.sh" ]] || die "DTK env.sh not found under DTK_DIR"
[[ -x "$DTK_DIR/llvm/bin/clang++" ]] || die "DTK clang++ not found"
[[ -d "$HYHAL_DIR" ]] || die "HYHAL_DIR is not a directory"
if [[ ${Z100L_TEST_NO_GPU:-0} != 1 ]]; then
    [[ -e /dev/kfd ]] || die "/dev/kfd is missing; check the DCU driver"
    [[ -e /dev/mkfd ]] || die "/dev/mkfd is missing; check the DCU driver"
    [[ -d /dev/dri ]] || info "warning: /dev/dri is absent; displayless systems may still work"
fi
docker info --format '{{.ServerVersion}}' >/dev/null
[[ -d "$DATA_DIR" ]] || die "run scripts/configure.sh first"
[[ -f "$DATA_DIR/config/serve.json" ]] || die "run scripts/configure.sh first"
info "host prerequisites OK; GPU/memory tests and model checks are separate"
