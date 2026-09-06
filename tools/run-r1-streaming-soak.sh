#!/usr/bin/env bash
# shellcheck disable=SC2317 # Cleanup functions are invoked indirectly by EXIT traps.
set -euo pipefail

readonly PACKAGE_NAME="dev.sewellzhong.r1probe"
readonly COMPONENT_NAME="${PACKAGE_NAME}/.MainActivity"
readonly SOAK_COMPONENT="${PACKAGE_NAME}/.ProcessedAudioSoakService"
readonly DEVICE_PACKAGE="com.phicomm.speaker.device"
readonly PLAYER_PACKAGE="com.phicomm.speaker.player"
readonly DEVICE_AUDIO_DIR="/sdcard/Android/data/${PACKAGE_NAME}/files/diagnostics"
usage() {
    echo "Usage: $0 <adb-serial> --confirm-device r1-sample01 --confirm-temporary-disable [--smoke]" >&2
    exit 64
}

[[ $# -eq 4 || $# -eq 5 ]] || usage
readonly ADB_SERIAL="$1"
[[ "$2" == "--confirm-device" && "$3" == "r1-sample01" \
    && "$4" == "--confirm-temporary-disable" ]] || usage
MODE="soak"
DURATION_SECONDS=1800
MINIMUM_PSS_SAMPLES=25
if [[ $# -eq 5 ]]; then
    [[ "$5" == "--smoke" ]] || usage
    MODE="smoke"
    DURATION_SECONDS=20
    MINIMUM_PSS_SAMPLES=1
fi
readonly MODE DURATION_SECONDS MINIMUM_PSS_SAMPLES

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly REPO_ROOT
readonly DEVICE_ID="r1-sample01"
RUN_ID="$(date +%Y-%m-%dT%H%M%S)"
readonly RUN_ID
readonly EVIDENCE_DIR="$REPO_ROOT/test-results/${RUN_ID}-${DEVICE_ID}/stage1/streaming-${MODE}"
readonly LOG_DIR="$EVIDENCE_DIR/logs"
readonly METADATA_DIR="$EVIDENCE_DIR/metadata"
readonly METRICS_FILE="$EVIDENCE_DIR/pss-timeline.tsv"

mkdir -p "$LOG_DIR" "$METADATA_DIR"
exec > >(tee "$EVIDENCE_DIR/run.log") 2>&1
printf 'elapsed_seconds\tepoch_seconds\tpid\tpss_kb\n' >"$METRICS_FILE"
completed=false

adb_target() {
    timeout --foreground 60s adb -s "$ADB_SERIAL" "$@" </dev/null
}

snapshot() {
    local label="$1"
    local elapsed="$2"
    local record_metric="${3:-false}"
    local epoch pid pss
    epoch="$(date +%s)"
    adb_target shell ps >"$LOG_DIR/${label}-ps.txt" 2>&1 || true
    pid="$(tr -d '\r' <"$LOG_DIR/${label}-ps.txt" \
        | awk -v package="$PACKAGE_NAME" '$0 ~ package {print $2; exit}')"
    adb_target shell dumpsys meminfo "$PACKAGE_NAME" \
        >"$LOG_DIR/${label}-meminfo.txt" 2>&1 || true
    pss="$(awk '$1 == "TOTAL" {print $2; exit}' "$LOG_DIR/${label}-meminfo.txt")"
    adb_target shell dumpsys media.audio_flinger \
        >"$LOG_DIR/${label}-audio-flinger.txt" 2>&1 || true
    if [[ "$record_metric" == true ]]; then
        printf '%s\t%s\t%s\t%s\n' "$elapsed" "$epoch" "$pid" "$pss" >>"$METRICS_FILE"
    fi
}

restore_services() {
    timeout --foreground 10s adb connect "$ADB_SERIAL" </dev/null >/dev/null 2>&1 || true
    adb_target shell am startservice -n "$PLAYER_PACKAGE/.EchoService" >/dev/null 2>&1 || true
    adb_target shell am startservice -n "$DEVICE_PACKAGE/.ui.service.WindowsService" \
        >/dev/null 2>&1 || true
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
    adb_target shell "rm -f ${DEVICE_AUDIO_DIR}/*-processed-soak-*.meta.txt" \
        >/dev/null 2>&1 || true
    restored=false
    if restore_services; then restored=true; else status=1; fi
    snapshot restored "$DURATION_SECONDS" false
    {
        printf 'status=%s\n' "$status"
        printf 'completed=%s\n' "$completed"
        printf 'factory_services_restored=%s\n' "$restored"
        printf 'device_metadata_removed=true\n'
        printf 'audio_retained=false\n'
        printf 'formal_soak=%s\n' "$([[ "$MODE" == soak ]] && echo true || echo false)"
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
snapshot before 0 false

adb_target shell am force-stop "$PACKAGE_NAME"
adb_target shell am start -W -n "$COMPONENT_NAME" \
    --es probe_nonce "soak-foreground-$(date +%s%N)" >/dev/null
adb_target shell am force-stop "$DEVICE_PACKAGE"
adb_target shell am force-stop "$PLAYER_PACKAGE"
sleep 1
if adb_target shell ps | tr -d '\r' | grep -Eq "$DEVICE_PACKAGE|$PLAYER_PACKAGE"; then
    echo "Audio overlay process restarted; refusing streaming soak" >&2
    exit 1
fi
snapshot isolated 0 false

adb_target logcat -c
NONCE="streaming-${MODE}-$(date +%s%N)"
readonly NONCE
adb_target shell am startservice -n "$SOAK_COMPONENT" \
    --ei duration_seconds "$DURATION_SECONDS" --es sample_id "stage1-${MODE}" \
    --es probe_nonce "$NONCE" >"$LOG_DIR/start-service.txt"

marker=""
started_epoch="$(date +%s)"
deadline_epoch="$((started_epoch + DURATION_SECONDS + 120))"
next_snapshot_elapsed=0
snapshot_index=0
while (( $(date +%s) <= deadline_epoch )); do
    elapsed="$(( $(date +%s) - started_epoch ))"
    if (( elapsed >= next_snapshot_elapsed )); then
        snapshot "sample-${snapshot_index}" "$elapsed" true
        snapshot_index="$((snapshot_index + 1))"
        next_snapshot_elapsed="$((next_snapshot_elapsed + 60))"
        while (( next_snapshot_elapsed <= elapsed )); do
            next_snapshot_elapsed="$((next_snapshot_elapsed + 60))"
        done
    fi
    adb_target logcat -d -v threadtime -s R1Audio:I art:I AndroidRuntime:E '*:S' \
        >"$LOG_DIR/logcat.txt" 2>&1 || true
    marker="$(grep -F "nonce=${NONCE}" "$LOG_DIR/logcat.txt" \
        | grep -E 'R1_PROCESSED_SOAK_COMPLETE|R1_PROCESSED_SOAK_FAILED' | tail -1 || true)"
    [[ -n "$marker" ]] && break
    sleep 10
done
printf '%s\n' "$marker" | tee "$EVIDENCE_DIR/processing-marker.txt"
[[ "$marker" == *R1_PROCESSED_SOAK_COMPLETE* ]]
metadata_path="$(sed -n 's/.* metadata_path=\([^ ]*\) .*/\1/p' <<<"$marker")"
[[ -n "$metadata_path" ]]
adb_target pull "$metadata_path" "$METADATA_DIR/processed-soak.meta.txt" >/dev/null
"$REPO_ROOT/tools/analyze-r1-streaming-soak.py" "$METRICS_FILE" \
    "$METADATA_DIR/processed-soak.meta.txt" "$LOG_DIR/logcat.txt" \
    --require-duration "$DURATION_SECONDS" --minimum-pss-samples "$MINIMUM_PSS_SAMPLES" \
    >"$EVIDENCE_DIR/soak-analysis.json"
snapshot after "$(( $(date +%s) - started_epoch ))" false
completed=true
echo "R1 bounded streaming processing ${MODE} completed."



