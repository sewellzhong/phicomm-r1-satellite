#!/usr/bin/env bash
set -euo pipefail

readonly DEVICE_PACKAGE="com.phicomm.speaker.device"
readonly PLAYER_PACKAGE="com.phicomm.speaker.player"

usage() {
    echo "Usage: $0 <adb-serial>" >&2
    exit 64
}

[[ $# -eq 1 ]] || usage

readonly ADB_SERIAL="$1"
readonly REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly DEVICE_ID="${R1_DEVICE_ID:-r1-sample01}"
readonly RUN_ID="$(date +%Y-%m-%dT%H%M%S)"
readonly EVIDENCE_DIR="${REPO_ROOT}/test-results/${RUN_ID}-${DEVICE_ID}/stage1/isolation-control"
readonly BACKUP_DIR="${REPO_ROOT}/test-results/2026-09-01-r1-sample01/stage0/current-installed-apps"

mkdir -p "$EVIDENCE_DIR"
exec > >(tee "$EVIDENCE_DIR/control.log") 2>&1

adb_target() {
    adb -s "$ADB_SERIAL" "$@"
}

capture_factory_state() {
    local prefix="$1"
    adb_target shell ps >"$EVIDENCE_DIR/${prefix}-ps.txt" 2>&1 || true
    adb_target shell dumpsys activity services "$DEVICE_PACKAGE" \
        >"$EVIDENCE_DIR/${prefix}-device-services.txt" 2>&1 || true
    adb_target shell dumpsys activity services "$PLAYER_PACKAGE" \
        >"$EVIDENCE_DIR/${prefix}-player-services.txt" 2>&1 || true
}

restore_factory_services() {
    local restored=0
    echo "Restoring factory services..."
    adb connect "$ADB_SERIAL" >/dev/null 2>&1 || true
    adb_target shell am startservice -n "$PLAYER_PACKAGE/.EchoService" || true
    adb_target shell am startservice -n "$DEVICE_PACKAGE/.ui.service.WindowsService" || true
    adb_target shell am start -n "$DEVICE_PACKAGE/.ui.MainActivity" || true

    for r1_attempt in $(seq 1 10); do
        if adb_target shell ps | tr -d '\r' \
            | grep -q "$DEVICE_PACKAGE" \
            && adb_target shell ps | tr -d '\r' \
            | grep -q "$PLAYER_PACKAGE"; then
            restored=1
            break
        fi
        sleep 1
    done
    capture_factory_state restored
    if [[ $restored -eq 1 ]]; then
        echo "Factory device and player processes restored."
    else
        echo "WARNING: factory process restoration could not be verified." >&2
    fi

    local manifest_tmp
    manifest_tmp="$(mktemp)"
    (cd "$EVIDENCE_DIR" && find . -type f ! -name SHA256SUMS \
        ! -name control.log ! -name run.log -print0 \
        | sort -z | xargs -0 sha256sum >"$manifest_tmp")
    mv "$manifest_tmp" "$EVIDENCE_DIR/SHA256SUMS"
}
trap restore_factory_services EXIT

echo "Evidence: $EVIDENCE_DIR"
(cd "$BACKUP_DIR" && sha256sum -c SHA256SUMS)

readonly PRODUCT_DEVICE="$(adb_target shell getprop ro.product.device | tr -d '\r')"
readonly SDK="$(adb_target shell getprop ro.build.version.sdk | tr -d '\r')"
readonly FIRMWARE="$(adb_target shell getprop ro.build.version.incremental | tr -d '\r')"
printf 'Target: device=%s sdk=%s firmware=%s\n' "$PRODUCT_DEVICE" "$SDK" "$FIRMWARE"
[[ "$PRODUCT_DEVICE" == "rk322x_echo" && "$SDK" == "22" && "$FIRMWARE" == "3448" ]] || {
    echo "Refusing isolation test: unexpected target identity" >&2
    exit 65
}

capture_factory_state before-stop
adb_target shell am force-stop dev.sewellzhong.r1probe
adb_target shell am force-stop "$DEVICE_PACKAGE"
adb_target shell am force-stop "$PLAYER_PACKAGE"
sleep 2
capture_factory_state stopped

if adb_target shell ps | tr -d '\r' | grep -q "$DEVICE_PACKAGE"; then
    echo "Factory device package restarted during isolation setup" >&2
    exit 1
fi
if adb_target shell ps | tr -d '\r' | grep -q "$PLAYER_PACKAGE"; then
    echo "Factory player package restarted during isolation setup" >&2
    exit 1
fi
echo "Factory audio packages are stopped; starting isolated probe."

set +e
R1_DEVICE_ID="$DEVICE_ID" "$REPO_ROOT/tools/run-r1-audio-probe.sh" "$ADB_SERIAL" \
    2>&1 | tee "$EVIDENCE_DIR/audio-probe-child.log"
r1_child_status=${PIPESTATUS[0]}
set -e

echo "Isolated audio probe exit code: $r1_child_status"
exit "$r1_child_status"
