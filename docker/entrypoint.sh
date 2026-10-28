#!/usr/bin/env bash
set -euo pipefail
if [[ -r /opt/dtk/env.sh ]]; then
    # shellcheck disable=SC1091
    set +u
    source /opt/dtk/env.sh >/dev/null 2>&1
    set -u
fi
export LD_LIBRARY_PATH="/opt/dtk/lib:/opt/dtk/hip/lib:/opt/dtk/hsa/lib:${LD_LIBRARY_PATH:-}"
mkdir -p /state/logs /state/conversations
exec "$@"
