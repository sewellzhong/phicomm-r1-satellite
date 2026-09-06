#!/usr/bin/env bash
set -euo pipefail

readonly PACKAGE_NAME="dev.sewellzhong.r1probe"
readonly COMPONENT_NAME="${PACKAGE_NAME}/.MainActivity"
readonly DEVICE_AUDIO_DIR="/sdcard/Android/data/${PACKAGE_NAME}/files/diagnostics"

usage() {
    echo "Usage: $0 <adb-serial>" >&2
    exit 64
}

[[ $# -eq 1 ]] || usage

readonly ADB_SERIAL="$1"
readonly REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly DEVICE_ID="${R1_DEVICE_ID:-r1-sample01}"
readonly RUN_ID="$(date +%Y-%m-%dT%H%M%S)"
readonly EVIDENCE_DIR="${REPO_ROOT}/test-results/${RUN_ID}-${DEVICE_ID}/stage1/audio-probe"
readonly AUDIO_DIR="${EVIDENCE_DIR}/audio"
readonly LOG_DIR="${EVIDENCE_DIR}/logs"
readonly SYNTHETIC_TONE="${AUDIO_DIR}/synthetic-1khz-2s.wav"
readonly DEVICE_TONE="${DEVICE_AUDIO_DIR}/synthetic-1khz-2s.wav"

mkdir -p "$AUDIO_DIR" "$LOG_DIR"
exec > >(tee "$EVIDENCE_DIR/run.log") 2>&1

adb_target() {
    adb -s "$ADB_SERIAL" "$@"
}

get_prop() {
    adb_target shell getprop "$1" | tr -d '\r'
}

cleanup() {
    adb_target shell am force-stop "$PACKAGE_NAME" >/dev/null 2>&1 || true
    adb_target shell rm -f "$DEVICE_TONE" >/dev/null 2>&1 || true
    adb_target shell "rm -f ${DEVICE_AUDIO_DIR}/*-stage1-*.wav*" >/dev/null 2>&1 || true
}
trap cleanup EXIT

wait_for_audio_marker() {
    local nonce="$1"
    local success_marker="$2"
    local failure_marker="$3"
    local timeout_seconds="$4"
    local log_file="$5"
    local line=""
    local second

    for ((second = 0; second < timeout_seconds; second++)); do
        adb_target logcat -d -s R1Audio:V '*:S' >"$log_file" 2>&1 || true
        line="$(grep -F "nonce=${nonce}" "$log_file" \
            | grep -E "${success_marker}|${failure_marker}" \
            | tail -1 || true)"
        if [[ -n "$line" ]]; then
            printf '%s\n' "$line"
            if grep -Fq "$failure_marker" <<<"$line"; then
                return 1
            fi
            return 0
        fi
        sleep 1
    done

    echo "Timed out waiting for $success_marker (nonce=$nonce)" >&2
    return 1
}

start_probe_activity() {
    adb_target shell am force-stop "$PACKAGE_NAME"
    adb_target shell am start -W -n "$COMPONENT_NAME" "$@"
}

echo "Evidence: $EVIDENCE_DIR"
readonly PRODUCT_DEVICE="$(get_prop ro.product.device)"
readonly SDK="$(get_prop ro.build.version.sdk)"
readonly FIRMWARE="$(get_prop ro.build.version.incremental)"
printf 'Target: serial=%s device=%s sdk=%s firmware=%s\n' \
    "$ADB_SERIAL" "$PRODUCT_DEVICE" "$SDK" "$FIRMWARE"

[[ "$PRODUCT_DEVICE" == "rk322x_echo" && "$SDK" == "22" && "$FIRMWARE" == "3448" ]] || {
    echo "Refusing audio test: unexpected target identity" >&2
    exit 65
}

adb_target shell dumpsys package "$PACKAGE_NAME" >"$LOG_DIR/package-dump.txt"
grep -q 'versionCode=27 ' "$LOG_DIR/package-dump.txt" || {
    echo "R1 audio probe versionCode 27 is not installed" >&2
    exit 65
}

readonly CAPABILITY_NONCE="capabilities-$(date +%s%N)"
start_probe_activity \
    --es probe_action capabilities \
    --es probe_nonce "$CAPABILITY_NONCE" \
    | tee "$LOG_DIR/capabilities-activity.txt"
wait_for_audio_marker \
    "$CAPABILITY_NONCE" R1_AUDIO_CAPABILITIES R1_AUDIO_CAPABILITIES_FAILED 5 \
    "$LOG_DIR/capabilities-logcat.txt" \
    | tee "$EVIDENCE_DIR/capabilities.txt"

record_source() {
    local source_name="$1"
    local source_id="$2"
    local nonce="record-${source_name}-$(date +%s%N)"
    local log_file="$LOG_DIR/${source_name}-logcat.txt"
    local marker_line
    local device_wav
    local host_wav="$AUDIO_DIR/${source_name}.wav"

    echo "Recording source=$source_name for 10 seconds"
    start_probe_activity \
        --es probe_action record \
        --ei audio_source "$source_id" \
        --ei duration_seconds 10 \
        --es sample_id "stage1-${source_name}" \
        --es probe_nonce "$nonce" \
        | tee "$LOG_DIR/${source_name}-activity.txt"

    if ! marker_line="$(wait_for_audio_marker \
        "$nonce" R1_AUDIO_RECORD_COMPLETE R1_AUDIO_RECORD_FAILED 20 "$log_file")"; then
        echo "Capture failed for source=$source_name; see $log_file" >&2
        return 1
    fi
    printf '%s\n' "$marker_line"
    device_wav="$(sed -n 's/.* path=\([^ ]*\.wav\) .*/\1/p' <<<"$marker_line")"
    [[ -n "$device_wav" ]] || {
        echo "Could not parse WAV path for $source_name" >&2
        return 1
    }

    adb_target pull "$device_wav" "$host_wav"
    adb_target pull "${device_wav}.meta.txt" "${host_wav}.meta.txt"
    "$REPO_ROOT/tools/analyze-wav.py" "$host_wav" \
        | tee "$AUDIO_DIR/${source_name}.analysis.json"
    sha256sum "$host_wav" "${host_wav}.meta.txt" \
        | tee "$AUDIO_DIR/${source_name}.sha256"

    # The verified local copy is retained for analysis; remove captured speech
    # from the R1 to minimize unnecessary diagnostic audio retention.
    adb_target shell rm -f "$device_wav" "${device_wav}.meta.txt"
}

r1_capture_failures=0
record_source voice_communication 7 || r1_capture_failures=$((r1_capture_failures + 1))
sleep 2
record_source voice_recognition 6 || r1_capture_failures=$((r1_capture_failures + 1))
sleep 2
record_source mic 1 || r1_capture_failures=$((r1_capture_failures + 1))

"$REPO_ROOT/tools/generate-test-tone.py" "$SYNTHETIC_TONE"
"$REPO_ROOT/tools/analyze-wav.py" "$SYNTHETIC_TONE" \
    | tee "$AUDIO_DIR/synthetic-1khz-2s.analysis.json"
adb_target shell mkdir -p "$DEVICE_AUDIO_DIR"
adb_target push "$SYNTHETIC_TONE" "$DEVICE_TONE"

readonly PLAYBACK_NONCE="playback-$(date +%s%N)"
start_probe_activity \
    --es probe_action play \
    --es file_path "$DEVICE_TONE" \
    --es probe_nonce "$PLAYBACK_NONCE" \
    | tee "$LOG_DIR/playback-activity.txt"
r1_playback_failures=0
if ! wait_for_audio_marker \
    "$PLAYBACK_NONCE" R1_AUDIO_PLAYBACK_COMPLETE R1_AUDIO_PLAYBACK_FAILED 10 \
    "$LOG_DIR/playback-logcat.txt" \
    | tee "$EVIDENCE_DIR/playback.txt"; then
    r1_playback_failures=1
fi

readonly MANIFEST_TMP="$(mktemp)"
(cd "$EVIDENCE_DIR" && { \
    find audio logs -type f -print0; \
    find . -maxdepth 1 -type f ! -name SHA256SUMS ! -name run.log -print0; \
} | sort -z | xargs -0 sha256sum >"$MANIFEST_TMP")
mv "$MANIFEST_TMP" "$EVIDENCE_DIR/SHA256SUMS"
(cd "$EVIDENCE_DIR" && sha256sum -c SHA256SUMS)

echo "R1 three-source capture and synthetic WAV playback completed."
if [[ $r1_capture_failures -ne 0 ]]; then
    echo "Audio capture failures: $r1_capture_failures of 3 sources" >&2
fi
if [[ $r1_playback_failures -ne 0 ]]; then
    echo "Audio playback failures: $r1_playback_failures" >&2
fi
if [[ $r1_capture_failures -ne 0 || $r1_playback_failures -ne 0 ]]; then
    exit 2
fi
