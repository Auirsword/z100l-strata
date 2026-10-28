#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

# shellcheck source=lib.sh
source "${REPO_ROOT}/scripts/lib.sh"
load_config

exec python3 "${REPO_ROOT}/scripts/model.py" download --model-dir "${MODEL_DIR}"
