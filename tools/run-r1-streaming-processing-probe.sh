#!/usr/bin/env bash
# shellcheck disable=SC2317 # Cleanup functions are invoked indirectly by EXIT traps.
set -euo pipefail

readonly PACKAGE_NAME="dev.sewellzhong.r1probe"
readonly COMPONENT_NAME="${PACKAGE_NAME}/.MainActivity"
readonly RECEIVER_COMPONENT="${PACKAGE_NAME}/.ProbeCommandReceiver"
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
readonly EVIDENCE_DIR="$REPO_ROOT/test-results/${RUN_ID}-${DEVICE_ID}/stage1/streaming-processing"
readonly LOG_DIR="$EVIDENCE_DIR/logs"
readonly AUDIO_DIR="$EVIDENCE_DIR/audio"

mkdir -p "$LOG_DIR" "$AUDIO_DIR"
exec > >(tee "$EVIDENCE_DIR/run.log") 2>&1
completed=false

adb_target() {
    timeout --foreground 60s adb -s "$ADB_SERIAL" "$@" </dev/null
}

snapshot() {
    local prefix="$1"
    adb_target shell ps >"$LOG_DIR/${prefix}-ps.txt" 2>&1 || true
    adb_target shell dumpsys meminfo "$PACKAGE_NAME" >"$LOG_DIR/${prefix}-meminfo.txt" 2>&1 || true
    adb_target shell dumpsys media.audio_flinger >"$LOG_DIR/${prefix}-audio-flinger.txt" 2>&1 || true
}

restore_services() {
    timeout --foreground 10s adb connect "$ADB_SERIAL" </dev/null >/dev/null 2>&1 || true
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
    trap - EXIT INT TERM
    set +e
    adb_target shell am force-stop "$PACKAGE_NAME" >/dev/null 2>&1 || true
    adb_target shell "rm -f ${DEVICE_AUDIO_DIR}/*-processed-stream-stage1-streaming.wav*" \
        >/dev/null 2>&1 || true
    restored=false
    if restore_services; then restored=true; else status=1; fi
    snapshot restored
    {
        printf 'status=%s\n' "$status"
        printf 'completed=%s\n' "$completed"
        printf 'factory_services_restored=%s\n' "$restored"
        printf 'device_audio_removed=true\n'
        printf 'production_integration=false\n'
    } >"$EVIDENCE_DIR/RESULT.txt"
    manifest_tmp="$(mktemp)"
    (cd "$EVIDENCE_DIR" && find . -type f ! -name run.log ! -name SHA256SUMS -print0 \
        | sort -z | xargs -0 sha256sum >"$manifest_tmp")
    mv "$manifest_tmp" "$EVIDENCE_DIR/SHA256SUMS"
    (cd "$EVIDENCE_DIR" && sha256sum -c SHA256SUMS) || status=1
    echo "Evidence: $EVIDENCE_DIR"
    exit "$status"
}
trap 'finish $?' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

PRODUCT_DEVICE="$(adb_target shell getprop ro.product.device | tr -d '\r')"
SDK="$(adb_target shell getprop ro.build.version.sdk | tr -d '\r')"
FIRMWARE="$(adb_target shell getprop ro.build.version.incremental | tr -d '\r')"
readonly PRODUCT_DEVICE SDK FIRMWARE
[[ "$PRODUCT_DEVICE" == "rk322x_echo" && "$SDK" == "22" && "$FIRMWARE" == "3448" ]]
(cd "$REPO_ROOT/test-results/2026-09-01-r1-sample01/stage0/current-installed-apps" \
    && sha256sum -c SHA256SUMS)
adb_target shell dumpsys package "$PACKAGE_NAME" >"$LOG_DIR/package-dump.txt"
grep -q 'versionCode=27 ' "$LOG_DIR/package-dump.txt"
snapshot before

adb_target shell am force-stop "$PACKAGE_NAME"
adb_target shell am start -W -n "$COMPONENT_NAME" \
    --es probe_nonce "streaming-foreground-$(date +%s%N)" >/dev/null
adb_target shell am force-stop "$DEVICE_PACKAGE"
adb_target shell am force-stop "$PLAYER_PACKAGE"
sleep 1
if adb_target shell ps | tr -d '\r' | grep -Eq "$DEVICE_PACKAGE|$PLAYER_PACKAGE"; then
    echo "Audio overlay process restarted; refusing streaming capture" >&2
    exit 1
fi
snapshot isolated

adb_target logcat -c
NONCE="streaming-processing-$(date +%s%N)"
readonly NONCE
adb_target shell am broadcast -n "$RECEIVER_COMPONENT" \
    -a dev.sewellzhong.r1probe.COMMAND --es probe_action processed_record \
    --ei duration_seconds 20 --es sample_id stage1-streaming --es probe_nonce "$NONCE" \
    >"$LOG_DIR/broadcast.txt"

marker=""
for second in $(seq 1 45); do
    adb_target shell dumpsys meminfo "$PACKAGE_NAME" >"$LOG_DIR/during-${second}-meminfo.txt" 2>&1 || true
    adb_target logcat -d -s R1Audio:V '*:S' >"$LOG_DIR/logcat.txt" 2>&1 || true
    marker="$(grep -F "nonce=${NONCE}" "$LOG_DIR/logcat.txt" \
        | grep -E 'R1_PROCESSED_RECORD_COMPLETE|R1_PROCESSED_RECORD_FAILED' | tail -1 || true)"
    [[ -n "$marker" ]] && break
    sleep 1
done
printf '%s\n' "$marker" | tee "$EVIDENCE_DIR/processing-marker.txt"
[[ "$marker" == *R1_PROCESSED_RECORD_COMPLETE* ]]
output_path="$(sed -n 's/.* output_path=\([^ ]*\) .*/\1/p' <<<"$marker")"
metadata_path="$(sed -n 's/.* metadata_path=\([^ ]*\) .*/\1/p' <<<"$marker")"
[[ -n "$output_path" && -n "$metadata_path" ]]
adb_target pull "$output_path" "$AUDIO_DIR/processed-stream.wav" >/dev/null
adb_target pull "$metadata_path" "$AUDIO_DIR/processed-stream.meta.txt" >/dev/null
"$REPO_ROOT/tools/analyze-wav.py" "$AUDIO_DIR/processed-stream.wav" \
    >"$AUDIO_DIR/processed-stream.analysis.json"
grep -q '^input_samples=320000$' "$AUDIO_DIR/processed-stream.meta.txt"
grep -q '^output_samples=320000$' "$AUDIO_DIR/processed-stream.meta.txt"
grep -q '^processing_overruns=0$' "$AUDIO_DIR/processed-stream.meta.txt"
grep -q '^bounded_state_samples=832$' "$AUDIO_DIR/processed-stream.meta.txt"
grep -q '^workspace_elements=3904$' "$AUDIO_DIR/processed-stream.meta.txt"
grep -q '^clipped_samples=0$' "$AUDIO_DIR/processed-stream.meta.txt"
snapshot after
completed=true
echo "R1 bounded streaming processing probe completed."



