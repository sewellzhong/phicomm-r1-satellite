#!/usr/bin/env bash
set -euo pipefail

usage() {
    echo "Usage: $0 <adb-serial> --confirm-device r1-sample01" >&2
    exit 64
}
[[ $# -eq 3 && "$2" == "--confirm-device" && "$3" == "r1-sample01" ]] || usage

readonly ADB_SERIAL="$1"
readonly PACKAGE="dev.sewellzhong.r1probe"
readonly COMPONENT="${PACKAGE}/.MainActivity"
readonly REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
readonly RUN_ID="$(date +%Y-%m-%dT%H%M%S)"
readonly EVIDENCE_DIR="${REPO_ROOT}/test-results/${RUN_ID}-r1-sample01/stage1/alexa-kws/microwakeword-load"
readonly APK="${REPO_ROOT}/android/r1-probe/app/build/outputs/apk/debug/app-debug.apk"
readonly MODEL="${REPO_ROOT}/local-deps/alexa-microwakeword-r1/assets/alexa_microwakeword.tflite"
mkdir -p "$EVIDENCE_DIR"

adb_target() { timeout --foreground 60s adb -s "$ADB_SERIAL" "$@" </dev/null; }
[[ "$(adb_target shell getprop ro.product.device | tr -d '\r')" == "rk322x_echo" ]]
[[ "$(adb_target shell getprop ro.build.version.sdk | tr -d '\r')" == "22" ]]
[[ "$(adb_target shell getprop ro.build.version.incremental | tr -d '\r')" == "3448" ]]
adb_target shell getprop >"$EVIDENCE_DIR/getprop.txt"
adb_target shell dumpsys package "$PACKAGE" >"$EVIDENCE_DIR/package.txt"
grep -Eq 'versionCode=(31|32|33|34) ' "$EVIDENCE_DIR/package.txt"
sha256sum "$APK" "$MODEL" >"$EVIDENCE_DIR/artifact-sha256.txt"

readonly NONCE="microwakeword-load-$(date +%s%N)"
adb_target shell am force-stop "$PACKAGE"
adb_target shell am start -W -n "$COMPONENT" --es probe_action microwakeword_load \
    --es probe_nonce "$NONCE" >"$EVIDENCE_DIR/activity.txt"
adb_target logcat -d -s R1Audio:V '*:S' >"$EVIDENCE_DIR/logcat.txt"
adb_target shell dumpsys meminfo "$PACKAGE" >"$EVIDENCE_DIR/meminfo.txt"
marker="$(grep -F "nonce=${NONCE}" "$EVIDENCE_DIR/logcat.txt" \
    | grep -E 'R1_MICROWAKEWORD_LOAD_COMPLETE|R1_MICROWAKEWORD_LOAD_FAILED' \
    | tail -1 || true)"
printf '%s\n' "$marker" >"$EVIDENCE_DIR/result-marker.txt"
status=fail
[[ "$marker" == *R1_MICROWAKEWORD_LOAD_COMPLETE* ]] && status=pass
printf '%s\n' "status=${status}" \
    'scope=api22_model_load_microfrontend_and_streaming_inference_smoke' \
    'model=alexa_pretrained_v2' \
    'accuracy_claim=not_tested_on_r1' \
    'blind_testing=not_started' >"$EVIDENCE_DIR/RESULT.txt"
(cd "$EVIDENCE_DIR" && find . -type f ! -name SHA256SUMS -print0 \
    | sort -z | xargs -0 sha256sum >SHA256SUMS && sha256sum -c SHA256SUMS)
echo "Evidence: $EVIDENCE_DIR"
[[ "$status" == pass ]]
