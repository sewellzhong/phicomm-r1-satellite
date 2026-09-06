#!/usr/bin/env bash
# shellcheck disable=SC2317 # Cleanup functions are invoked indirectly by EXIT traps.
set -euo pipefail

readonly PACKAGE_NAME="dev.sewellzhong.r1probe"
readonly RECEIVER_COMPONENT="${PACKAGE_NAME}/.ProbeCommandReceiver"
readonly DEVICE_AUDIO_DIR="/sdcard/Android/data/${PACKAGE_NAME}/files/diagnostics"
readonly DEVICE_NOISE="$DEVICE_AUDIO_DIR/benchmark-noise.wav"
readonly DEVICE_INPUT="$DEVICE_AUDIO_DIR/benchmark-input.wav"

usage() {
    echo "Usage: $0 <adb-serial>" >&2
    exit 64
}

[[ $# -eq 1 ]] || usage
readonly ADB_SERIAL="$1"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly REPO_ROOT
readonly DEVICE_ID="${R1_DEVICE_ID:-r1-sample01}"
readonly RAW_SOURCE="$REPO_ROOT/test-results/2026-09-02T023041-r1-sample01/stage1/stereo-channel-controlled"
readonly PYTHON_REFERENCE="$REPO_ROOT/test-results/2026-09-02T024909-r1-sample01/stage1/offline-adaptive-gain"
RUN_ID="$(date +%Y-%m-%dT%H%M%S)"
readonly RUN_ID
readonly EVIDENCE_DIR="$REPO_ROOT/test-results/${RUN_ID}-${DEVICE_ID}/stage1/processing-benchmark"
readonly LOG_DIR="$EVIDENCE_DIR/logs"
readonly AUDIO_DIR="$EVIDENCE_DIR/audio"

mkdir -p "$LOG_DIR" "$AUDIO_DIR"
exec > >(tee "$EVIDENCE_DIR/run.log") 2>&1
completed=false

adb_target() {
    timeout --foreground 60s adb -s "$ADB_SERIAL" "$@" </dev/null
}

finish() {
    local status="$1"
    trap - EXIT INT TERM
    set +e
    adb_target shell "rm -f $DEVICE_NOISE $DEVICE_INPUT ${DEVICE_AUDIO_DIR}/*-processed-stage1-benchmark.wav*" \
        >/dev/null 2>&1 || true
    {
        printf 'status=%s\n' "$status"
        printf 'completed=%s\n' "$completed"
        printf 'production_integration=false\n'
        printf 'device_audio_removed=true\n'
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

(cd "$RAW_SOURCE" && sha256sum -c SHA256SUMS >/dev/null)
(cd "$PYTHON_REFERENCE" && sha256sum -c SHA256SUMS >/dev/null)
PRODUCT_DEVICE="$(adb_target shell getprop ro.product.device | tr -d '\r')"
SDK="$(adb_target shell getprop ro.build.version.sdk | tr -d '\r')"
FIRMWARE="$(adb_target shell getprop ro.build.version.incremental | tr -d '\r')"
readonly PRODUCT_DEVICE SDK FIRMWARE
[[ "$PRODUCT_DEVICE" == "rk322x_echo" && "$SDK" == "22" && "$FIRMWARE" == "3448" ]]
adb_target shell dumpsys package "$PACKAGE_NAME" >"$LOG_DIR/package-dump.txt"
grep -q 'versionCode=27 ' "$LOG_DIR/package-dump.txt"

adb_target shell mkdir -p "$DEVICE_AUDIO_DIR"
adb_target push "$RAW_SOURCE/audio/silence-average.wav" "$DEVICE_NOISE" >/dev/null
adb_target push "$RAW_SOURCE/audio/speech-average.wav" "$DEVICE_INPUT" >/dev/null
adb_target logcat -c
NONCE="processing-benchmark-$(date +%s%N)"
readonly NONCE
adb_target shell am broadcast -n "$RECEIVER_COMPONENT" \
    -a dev.sewellzhong.r1probe.COMMAND --es probe_action process_wav \
    --es noise_path "$DEVICE_NOISE" --es input_path "$DEVICE_INPUT" \
    --es sample_id stage1-benchmark --es probe_nonce "$NONCE" \
    >"$LOG_DIR/broadcast.txt"

marker=""
for second in $(seq 1 120); do
    adb_target shell dumpsys meminfo "$PACKAGE_NAME" >"$LOG_DIR/meminfo-${second}.txt" 2>&1 || true
    adb_target logcat -d -s R1Audio:V '*:S' >"$LOG_DIR/logcat.txt" 2>&1 || true
    marker="$(grep -F "nonce=${NONCE}" "$LOG_DIR/logcat.txt" \
        | grep -E 'R1_PROCESSING_COMPLETE|R1_PROCESSING_FAILED' | tail -1 || true)"
    [[ -n "$marker" ]] && break
    sleep 1
done
printf '%s\n' "$marker" | tee "$EVIDENCE_DIR/processing-marker.txt"
[[ "$marker" == *R1_PROCESSING_COMPLETE* ]]
output_path="$(sed -n 's/.* output_path=\([^ ]*\) .*/\1/p' <<<"$marker")"
metadata_path="$(sed -n 's/.* metadata_path=\([^ ]*\) .*/\1/p' <<<"$marker")"
[[ -n "$output_path" && -n "$metadata_path" ]]
adb_target pull "$output_path" "$AUDIO_DIR/java-processed.wav" >/dev/null
adb_target pull "$metadata_path" "$AUDIO_DIR/java-processed.meta.txt" >/dev/null
"$REPO_ROOT/tools/analyze-wav.py" "$AUDIO_DIR/java-processed.wav" \
    >"$AUDIO_DIR/java-processed.analysis.json"
"$REPO_ROOT/tools/compare-processed-wav.py" \
    "$PYTHON_REFERENCE/audio/speech-balanced-agc.wav" "$AUDIO_DIR/java-processed.wav" \
    >"$AUDIO_DIR/python-java-comparison.json"
completed=true
echo "R1 Java processing benchmark completed."



