#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lib.sh"
load_config
require_command git
require_command python3
STRATA_REV=7ddc17a38fe7f31637e895ecfba58c2cd43d65ec
GGML_REV=3cf03257f219afbe7334045ff7c6a06ac68c627d
SRC="$ROOT_DIR/.work/src"
PATCH="$ROOT_DIR/patches/strata/0001-z100l-dtk.patch"
PATCH_HASH=$(sha256sum "$PATCH" | cut -d' ' -f1)
MANIFEST="$SRC/manifest.json"
verify_prepared() {
    [[ $(git -C "$SRC/Strata" rev-parse HEAD) == "$STRATA_REV" ]] || return 1
    [[ $(git -C "$SRC/llama.cpp" rev-parse HEAD) == "$GGML_REV" ]] || return 1
    [[ -f "$SRC/Strata/CMakeLists.txt" && -f "$SRC/llama.cpp/CMakeLists.txt" ]] || return 1
    git -C "$SRC/Strata" diff --cached --check || return 1
    local actual
    actual=$(git -C "$SRC/Strata" diff --cached --binary "$STRATA_REV" | sha256sum | cut -d' ' -f1)
    [[ "$actual" == "$PATCH_HASH" ]] || return 1
}
if [[ -f "$MANIFEST" ]] && python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d["strata_revision"]==sys.argv[2] and d["ggml_revision"]==sys.argv[3] and d["patch_sha256"]==sys.argv[4]' "$MANIFEST" "$STRATA_REV" "$GGML_REV" "$PATCH_HASH"; then
    verify_prepared || die "cached source does not match the pinned source and patch"
    info "source and patch already prepared"
    exit 0
fi
fetch() {
    local url=$1 revision=$2 destination=$3
    if [[ -e "$destination" ]]; then
        [[ -e "$destination/.git" ]] || die "$destination exists but is not a git checkout"
    else
        mkdir -p "$destination"
        git -C "$destination" init -q
        git -C "$destination" remote add origin "$url"
    fi
    if ! git -C "$destination" cat-file -e "$revision^{commit}" 2>/dev/null; then
        for attempt in 1 2 3; do
            if git -C "$destination" -c http.version=HTTP/1.1 fetch --depth 1 origin "$revision"; then
                break
            fi
            (( attempt < 3 )) || die "failed to fetch pinned source from $url"
            info "source download interrupted; retrying ($((attempt + 1))/3)"
            sleep "$((attempt * 2))"
        done
    fi
    git -C "$destination" diff --quiet || die "$destination has uncommitted changes; use a fresh source directory"
    git -C "$destination" checkout --detach --quiet "$revision"
    [[ $(git -C "$destination" rev-parse HEAD) == "$revision" ]] || die "source revision mismatch"
}
fetch https://github.com/Niko1221/Strata.git "$STRATA_REV" "$SRC/Strata"
fetch https://github.com/ggml-org/llama.cpp.git "$GGML_REV" "$SRC/llama.cpp"
if ! verify_prepared; then
    git -C "$SRC/Strata" apply --check "$PATCH"
    git -C "$SRC/Strata" apply --index "$PATCH"
fi
verify_prepared
python3 - "$MANIFEST" "$STRATA_REV" "$GGML_REV" "$PATCH_HASH" <<'PY'
import json
from pathlib import Path
import sys
path = Path(sys.argv[1])
path.parent.mkdir(parents=True, exist_ok=True)
value = {"strata_revision": sys.argv[2], "ggml_revision": sys.argv[3],
         "patch": "patches/strata/0001-z100l-dtk.patch", "patch_sha256": sys.argv[4]}
path.write_text(json.dumps(value, indent=2) + "\n")
PY
info "prepared Strata $STRATA_REV with the reviewed DTK patch"
