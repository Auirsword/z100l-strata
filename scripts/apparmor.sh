#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lib.sh"
load_config
[[ "$DOCKER_APPARMOR" == z100l-strata ]] || exit 0
docker info --format '{{json .SecurityOptions}}' | grep -q 'name=apparmor' || {
    info "AppArmor is not active; keeping Docker's seccomp profile"
    exit 0
}
require_command apparmor_parser
PROFILE="$ROOT_DIR/security/z100l-strata.apparmor"
FEATURES=/sys/kernel/security/apparmor/features
[[ -d "$FEATURES" ]] || die "AppArmor kernel features are unavailable at $FEATURES"
if (( EUID == 0 )); then
    apparmor_parser --replace --skip-cache --features-file "$FEATURES" "$PROFILE"
else
    info "loading the least-privilege DTK AppArmor profile; sudo may request your password"
    sudo apparmor_parser --replace --skip-cache --features-file "$FEATURES" "$PROFILE"
fi
