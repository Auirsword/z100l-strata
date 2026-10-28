#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lib.sh"
load_config
require_command python3
exec python3 "$ROOT_DIR/scripts/configure.py" "$@"
