#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR=$(cd -- "$(dirname "$0")" && pwd)
DOWNLOAD=0
BUILD_ONLY=0
CONFIGURE_ARGS=()
while (($#)); do
    case "$1" in
        --download-model) DOWNLOAD=1; shift ;;
        --build-only) BUILD_ONLY=1; shift ;;
        --preset|--model-dir|--data-dir|--max-context)
            (($# >= 2)) || { echo "missing value for $1" >&2; exit 2; }
            CONFIGURE_ARGS+=("$1" "$2"); shift 2 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
done
source "$ROOT_DIR/scripts/lib.sh"
load_config
if [[ ! -f "$ROOT_DIR/.env" || ${#CONFIGURE_ARGS[@]} -gt 0 ]]; then
    "$ROOT_DIR/scripts/configure.sh" "${CONFIGURE_ARGS[@]}"
    load_config
fi
"$ROOT_DIR/scripts/preflight.sh"
"$ROOT_DIR/scripts/prepare-source.sh"
"$ROOT_DIR/scripts/build.sh"
(( BUILD_ONLY == 0 )) || { info "build-only completed; no model or service was started"; exit 0; }
if (( DOWNLOAD )); then
    "$ROOT_DIR/scripts/download-model.sh"
fi
model_hash_args=()
[[ "$CHECK_MODEL_HASH" == 0 ]] || model_hash_args=(--hash)
if ! python3 "$ROOT_DIR/scripts/model.py" check --model-dir "$MODEL_DIR" "${model_hash_args[@]}"; then
    die "model files are missing or failed verification; use --download-model or --model-dir PATH"
fi
if ! python3 "$ROOT_DIR/scripts/model.py" pack-info --model-dir "$MODEL_DIR" >/dev/null 2>&1; then
    "$ROOT_DIR/scripts/pack-model.sh"
fi
"$ROOT_DIR/scripts/run.sh"
python3 "$ROOT_DIR/scripts/smoke.py" --wait "${STARTUP_TIMEOUT:-900}"
info "local endpoint: http://127.0.0.1:$PORT (no API gateway or public forwarding included)"
