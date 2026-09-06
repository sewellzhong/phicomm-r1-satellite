#!/usr/bin/env bash
# shellcheck disable=SC2317 # Cleanup functions are invoked indirectly by EXIT traps.
set -euo pipefail

readonly PACKAGE_NAME="dev.sewellzhong.r1probe"
readonly COMPONENT_NAME="${PACKAGE_NAME}/.MainActivity"
readonly DEVICE_PACKAGE="com.phicomm.speaker.device"
readonly PLAYER_PACKAGE="com.phicomm.speaker.player"
readonly DEVICE_AUDIO_DIR="/sdcard/Android/data/${PACKAGE_NAME}/files/diagnostics"

usage() {
    echo "Usage: $0 <adb-serial> <voice_communication|voice_recognition|mic>" >&2
    exit 64
}

[[ $# -eq 2 ]] || usage
readonly ADB_SERIAL="$1"
readonly SOURCE_NAME="$2"
case "$SOURCE_NAME" in
    voice_communication) readonly SOURCE_ID=7 ;;
    voice_recognition) readonly SOURCE_ID=6 ;;
    mic) readonly SOURCE_ID=1 ;;
    *) usage ;;
esac

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly REPO_ROOT
readonly DEVICE_ID="${R1_DEVICE_ID:-r1-sample01}"
RUN_ID="$(date +%Y-%m-%dT%H%M%S)"
readonly RUN_ID
readonly EVIDENCE_DIR="$REPO_ROOT/test-results/${RUN_ID}-${DEVICE_ID}/stage1/capture-route-${SOURCE_NAME}"
readonly LOG_DIR="$EVIDENCE_DIR/logs"
readonly AUDIO_DIR="$EVIDENCE_DIR/audio"

mkdir -p "$LOG_DIR" "$AUDIO_DIR"
exec > >(tee "$EVIDENCE_DIR/run.log") 2>&1

adb_target() {
    adb -s "$ADB_SERIAL" "$@"
}

snapshot() {
    local prefix="$1"
    adb_target shell ps >"$EVIDENCE_DIR/${prefix}-ps.txt" 2>&1 || true
    adb_target shell dumpsys media.audio_flinger >"$EVIDENCE_DIR/${prefix}-audio-flinger.txt" 2>&1 || true
    adb_target shell dumpsys audio >"$EVIDENCE_DIR/${prefix}-dumpsys-audio.txt" 2>&1 || true
    adb_target shell tinymix -D 1 >"$EVIDENCE_DIR/${prefix}-tinymix-rkma4.txt" 2>&1 || true
    adb_target shell tinymix -D 2 >"$EVIDENCE_DIR/${prefix}-tinymix-ak7755.txt" 2>&1 || true
    adb_target shell cat /proc/asound/pcm >"$EVIDENCE_DIR/${prefix}-asound-pcm.txt" 2>&1 || true
    adb_target shell getprop >"$EVIDENCE_DIR/${prefix}-getprop.txt" 2>&1 || true
    rg 'persist\.route|audio|mic|ak7755' "$EVIDENCE_DIR/${prefix}-getprop.txt" \
        >"$EVIDENCE_DIR/${prefix}-audio-properties.txt" || true
}

restore_current_services() {
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
    adb_target shell "rm -f ${DEVICE_AUDIO_DIR}/*-stage1-route-*.wav*" >/dev/null 2>&1
    local restored="false"
    if restore_current_services; then
        restored="true"
    else
        status=1
    fi
    snapshot restored
    {
        printf 'capture_status=%s\n' "$status"
        printf 'source=%s\n' "$SOURCE_NAME"
        printf 'factory_services_restored=%s\n' "$restored"
        printf 'device_audio_removed=true\n'
    } >"$EVIDENCE_DIR/RESULT.txt"
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
(cd "$REPO_ROOT/test-results/2026-09-01-r1-sample01/stage0/current-installed-apps" \
    && sha256sum -c SHA256SUMS)
adb_target shell dumpsys package "$PACKAGE_NAME" >"$LOG_DIR/package-dump.txt"
grep -q 'versionCode=27 ' "$LOG_DIR/package-dump.txt"

snapshot current-overlays-active
adb_target shell am force-stop "$PACKAGE_NAME"
adb_target shell am force-stop "$DEVICE_PACKAGE"
adb_target shell am force-stop "$PLAYER_PACKAGE"
sleep 2
snapshot isolated-before-capture

adb_target logcat -c
NONCE="capture-route-${SOURCE_NAME}-$(date +%s%N)"
readonly NONCE
adb_target shell am start -W -n "$COMPONENT_NAME" \
    --es probe_action record --ei audio_source "$SOURCE_ID" --ei duration_seconds 10 \
    --es sample_id "stage1-route-${SOURCE_NAME}" --es probe_nonce "$NONCE" \
    >"$LOG_DIR/activity.txt"
sleep 1
snapshot during-capture

marker_line=""
for _ in $(seq 1 20); do
    adb_target logcat -d -s R1Audio:V '*:S' >"$LOG_DIR/logcat.txt" 2>&1 || true
    marker_line="$(grep -F "nonce=${NONCE}" "$LOG_DIR/logcat.txt" \
        | grep -E 'R1_AUDIO_RECORD_COMPLETE|R1_AUDIO_RECORD_FAILED' | tail -1 || true)"
    [[ -n "$marker_line" ]] && break
    sleep 1
done
printf '%s\n' "$marker_line" | tee "$EVIDENCE_DIR/capture-marker.txt"
[[ "$marker_line" == *R1_AUDIO_RECORD_COMPLETE* ]]
device_wav="$(sed -n 's/.* path=\([^ ]*\.wav\) .*/\1/p' <<<"$marker_line")"
[[ -n "$device_wav" ]]
host_wav="$AUDIO_DIR/${SOURCE_NAME}.wav"
adb_target pull "$device_wav" "$host_wav"
adb_target pull "${device_wav}.meta.txt" "${host_wav}.meta.txt"
"$REPO_ROOT/tools/analyze-wav.py" "$host_wav" >"$AUDIO_DIR/${SOURCE_NAME}.analysis.json"
adb_target shell rm -f "$device_wav" "${device_wav}.meta.txt"
snapshot isolated-after-capture
