#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

# shellcheck source=lib.sh
source "${REPO_ROOT}/scripts/lib.sh"
load_config

FIRST_SHARD="IQ3_S/Qwen3.8-Flash-Next-GSQ-RCO-abliterated-IQ3_S-00001-of-00002.gguf"
model_hash_args=()
[[ "$CHECK_MODEL_HASH" == 0 ]] || model_hash_args=(--hash)
python3 "${REPO_ROOT}/scripts/model.py" check --model-dir "${MODEL_DIR}" "${model_hash_args[@]}"

docker run --rm --network none \
  --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,nodev \
  --cpus "${PACK_JOBS}" \
  --volume "${MODEL_DIR}:/model:rw" \
  --entrypoint /opt/venv/bin/python \
  "${IMAGE}" \
  /opt/strata/src/tools/iq_pack.py \
  --gguf "/model/${FIRST_SHARD}" \
  --out /model/pack/iq3_s

python3 "${REPO_ROOT}/scripts/model.py" pack-info --model-dir "${MODEL_DIR}"
