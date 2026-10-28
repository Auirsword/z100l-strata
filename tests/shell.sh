#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd -- "$(dirname "$0")/.." && pwd)
for file in "$ROOT/install.sh" "$ROOT"/scripts/*.sh "$ROOT"/docker/*.sh "$ROOT/tests/shell.sh"; do
    bash -n "$file"
done
python3 -m compileall -q "$ROOT/scripts" "$ROOT/tests"
python3 -m unittest discover -s "$ROOT/tests" -v
if [[ ${Z100L_RUN_DOCKER_BUILD:-0} == 1 ]]; then
    "$ROOT/scripts/build.sh"
fi
printf 'shell/static checks: OK\n'
