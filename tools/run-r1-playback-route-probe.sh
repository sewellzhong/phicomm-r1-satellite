#!/usr/bin/env bash
set -euo pipefail

readonly PACKAGE_NAME="dev.sewellzhong.r1probe"
readonly COMPONENT_NAME="${PACKAGE_NAME}/.MainActivity"
readonly DEVICE_PACKAGE="com.phicomm.speaker.device"
readonly PLAYER_PACKAGE="com.phicomm.speaker.player"
readonly DEVICE_AUDIO_DIR="/sdcard/Android/data/${PACKAGE_NAME}/files/diagnostics"

usage() {
    echo "Usage: $0 <adb-serial>" >&2
    exit 64
}

[[ $# -eq 1 ]] || usage
readonly ADB_SERIAL="$1"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly REPO_ROOT
readonly DEVICE_ID="${R1_DEVICE_ID:-r1-sample01}"
RUN_ID="$(date +%Y-%m-%dT%H%M%S)"
readonly RUN_ID
readonly EVIDENCE_DIR="${REPO_ROOT}/test-results/${RUN_ID}-${DEVICE_ID}/stage1/playback-route"
readonly DEVICE_TONE="${DEVICE_AUDIO_DIR}/route-probe-1khz-5s.wav"
readonly HOST_TONE="${EVIDENCE_DIR}/route-probe-1khz-5s.wav"

mkdir -p "$EVIDENCE_DIR"
exec > >(tee "$EVIDENCE_DIR/run.log") 2>&1

adb_target() {
    adb -s "$ADB_SERIAL" "$@"
}

snapshot() {
    local prefix="$1"
    adb_target shell ps >"$EVIDENCE_DIR/${prefix}-ps.txt" 2>&1 || true
    adb_target shell tinymix -D 2 >"$EVIDENCE_DIR/${prefix}-tinymix-card2.txt" 2>&1 || true
    adb_target shell dumpsys audio >"$EVIDENCE_DIR/${prefix}-dumpsys-audio.txt" 2>&1 || true
    adb_target shell dumpsys media.audio_flinger \
        >"$EVIDENCE_DIR/${prefix}-audio-flinger.txt" 2>&1 || true
}

restore_factory_services() {
    adb connect "$ADB_SERIAL" >/dev/null 2>&1 || true
    adb_target shell am startservice -n "$PLAYER_PACKAGE/.EchoService" >/dev/null 2>&1 || true
    adb_target shell am startservice -n "$DEVICE_PACKAGE/.ui.service.WindowsService" >/dev/null 2>&1 || true
    adb_target shell am start -n "$DEVICE_PACKAGE/.ui.MainActivity" >/dev/null 2>&1 || true
    for _ in $(seq 1 10); do
        if adb_target shell ps | tr -d '\r' | grep -q "$DEVICE_PACKAGE" \
            && adb_target shell ps | tr -d '\r' | grep -q "$PLAYER_PACKAGE"; then
            return 0
        fi
        sleep 1
    done
    return 1
}

finish() {
    local status="$1"
    trap - EXIT
    set +e
    adb_target shell am force-stop "$PACKAGE_NAME" >/dev/null 2>&1
    adb_target shell rm -f "$DEVICE_TONE" >/dev/null 2>&1
    local restored="false"
    if restore_factory_services; then
        restored="true"
    else
        status=1
    fi
    snapshot restored
    printf 'playback_status=%s\nfactory_services_restored=%s\naudible_confirmation=pending_user_confirmation\n' \
        "$status" "$restored" >"$EVIDENCE_DIR/RESULT.txt"
    local manifest_tmp
    manifest_tmp="$(mktemp)"
    (cd "$EVIDENCE_DIR" && find . -type f ! -name run.log ! -name SHA256SUMS -print0 \
        | sort -z | xargs -0 sha256sum >"$manifest_tmp")
    mv "$manifest_tmp" "$EVIDENCE_DIR/SHA256SUMS"
    (cd "$EVIDENCE_DIR" && sha256sum -c SHA256SUMS)
    echo "Evidence: $EVIDENCE_DIR"
    exit "$status"
}
trap 'finish $?' EXIT

PRODUCT_DEVICE="$(adb_target shell getprop ro.product.device | tr -d '\r')"
SDK="$(adb_target shell getprop ro.build.version.sdk | tr -d '\r')"
FIRMWARE="$(adb_target shell getprop ro.build.version.incremental | tr -d '\r')"
[[ "$PRODUCT_DEVICE" == "rk322x_echo" && "$SDK" == "22" && "$FIRMWARE" == "3448" ]]
adb_target shell dumpsys package "$PACKAGE_NAME" >"$EVIDENCE_DIR/package-dump.txt"
grep -q 'versionCode=27 ' "$EVIDENCE_DIR/package-dump.txt"

snapshot before-stop
adb_target shell am force-stop "$PACKAGE_NAME"
adb_target shell am force-stop "$DEVICE_PACKAGE"
adb_target shell am force-stop "$PLAYER_PACKAGE"
sleep 2
snapshot stopped

"$REPO_ROOT/tools/generate-test-tone.py" "$HOST_TONE" --duration 5
adb_target shell mkdir -p "$DEVICE_AUDIO_DIR"
adb_target push "$HOST_TONE" "$DEVICE_TONE" >/dev/null
adb_target logcat -c
NONCE="route-playback-$(date +%s%N)"
readonly NONCE
adb_target shell am start -W -n "$COMPONENT_NAME" \
    --es probe_action play --es file_path "$DEVICE_TONE" --es probe_nonce "$NONCE" \
    >"$EVIDENCE_DIR/playback-activity.txt"
sleep 1
snapshot during-playback
sleep 5
adb_target logcat -d -s R1Audio:V '*:S' >"$EVIDENCE_DIR/playback-logcat.txt"
grep -F "nonce=${NONCE}" "$EVIDENCE_DIR/playback-logcat.txt" \
    | grep -F R1_AUDIO_PLAYBACK_COMPLETE >"$EVIDENCE_DIR/playback-complete.txt"
snapshot after-playback
