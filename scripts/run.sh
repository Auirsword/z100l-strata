#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lib.sh"
load_config
[[ -f "$DATA_DIR/config/serve.json" ]] || die "run scripts/configure.sh first"
if container_exists; then
    [[ $(docker inspect -f '{{.State.Running}}' "$CONTAINER") == true ]] && { info "$CONTAINER is already running"; exit 0; }
    die "a stopped container named $CONTAINER exists; use scripts/stop.sh to remove it cleanly"
fi
python3 "$ROOT_DIR/scripts/model.py" pack-info --model-dir "$MODEL_DIR"
devices=(--device=/dev/kfd --device=/dev/mkfd)
if [[ -n ${GPU_RENDER_DEVICE:-} ]]; then
    [[ -e "$GPU_RENDER_DEVICE" ]] || die "GPU_RENDER_DEVICE does not exist"
    devices+=(--device="$GPU_RENDER_DEVICE")
else
    for device in /dev/dri/card* /dev/dri/renderD*; do
        [[ -e "$device" ]] && devices+=(--device="$device")
    done
fi
"$ROOT_DIR/scripts/apparmor.sh"
security=(--cap-drop ALL --security-opt no-new-privileges:true)
if [[ "$DOCKER_APPARMOR" == unconfined ]]; then
    info "AppArmor unconfined selected explicitly; seccomp remains enabled"
    security+=(--security-opt apparmor=unconfined)
elif [[ "$DOCKER_APPARMOR" != default ]]; then
    security+=(--security-opt "apparmor=$DOCKER_APPARMOR")
fi
[[ "$PUBLISH_HOST" == 127.0.0.1 || "$PUBLISH_HOST" == ::1 ]] ||
    info "warning: the unauthenticated development endpoint will listen on $PUBLISH_HOST"
groups=()
if gid=$(getent group video | cut -d: -f3) && [[ $gid =~ ^[0-9]+$ ]]; then
    groups+=(--group-add "$gid")
fi
if gid=$(getent group render | cut -d: -f3) && [[ $gid =~ ^[0-9]+$ ]]; then
    groups+=(--group-add "$gid")
fi
publish_binding="$PUBLISH_HOST:$PORT:18080"
[[ "$PUBLISH_HOST" != *:* ]] || publish_binding="[$PUBLISH_HOST]:$PORT:18080"
network=(--network "$DOCKER_NETWORK")
[[ "$DOCKER_NETWORK" != bridge ]] || network+=(--publish "$publish_binding")
exec docker run -d --name "$CONTAINER" --restart "$RESTART_POLICY" \
    "${network[@]}" \
    --ipc private --shm-size "$SHM_SIZE" --pids-limit 512 --ulimit memlock=-1 \
    --read-only --tmpfs /tmp:rw,noexec,nosuid,size=2g \
    --tmpfs /var/log/hylog:rw,nosuid,size=64m \
    "${security[@]}" "${devices[@]}" "${groups[@]}" \
    --mount "type=bind,source=$DTK_DIR,target=/opt/dtk,readonly" \
    --mount "type=bind,source=$HYHAL_DIR,target=/opt/hyhal,readonly" \
    --mount "type=bind,source=$MODEL_DIR,target=/model,readonly" \
    --mount "type=bind,source=$DATA_DIR,target=/state" \
    --env "HIP_VISIBLE_DEVICES=$GPU_ID" --env "CUDA_VISIBLE_DEVICES=$GPU_ID" \
    --env "AMDGPU_TARGETS=$AMDGPU_TARGETS" \
    --log-opt max-size=32m --log-opt max-file=2 \
    "$IMAGE"
