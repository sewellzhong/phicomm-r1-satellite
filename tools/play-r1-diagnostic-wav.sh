#!/usr/bin/env bash
# shellcheck disable=SC2317 # Cleanup functions are invoked indirectly by EXIT traps.
set -euo pipefail

readonly PACKAGE_NAME="dev.sewellzhong.r1probe"
readonly COMPONENT_NAME="${PACKAGE_NAME}/.MainActivity"
readonly DEVICE_PACKAGE="com.phicomm.speaker.device"
readonly PLAYER_PACKAGE="com.phicomm.speaker.player"

usage() {
    echo "Usage: $0 <adb-serial> <test-results WAV> [gain-db]" >&2
    exit 64
}

[[ $# -ge 2 && $# -le 3 ]] || usage
readonly ADB_SERIAL="$1"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly REPO_ROOT
SOURCE_WAV="$(realpath "$2")"
readonly SOURCE_WAV
readonly GAIN_DB="${3:-0}"
[[ "$SOURCE_WAV" == "$REPO_ROOT/test-results/"*.wav ]] || {
    echo "Refusing playback outside test-results WAV files" >&2
    exit 65
}

readonly DEVICE_ID="${R1_DEVICE_ID:-r1-sample01}"
RUN_ID="$(date +%Y-%m-%dT%H%M%S)"
readonly RUN_ID
readonly EVIDENCE_DIR="${REPO_ROOT}/test-results/${RUN_ID}-${DEVICE_ID}/stage1/manual-intelligibility"
readonly REVIEW_WAV="${EVIDENCE_DIR}/review-plus-${GAIN_DB}db.wav"
readonly DEVICE_WAV="/sdcard/Android/data/${PACKAGE_NAME}/files/diagnostics/manual-review.wav"

mkdir -p "$EVIDENCE_DIR"
exec > >(tee "$EVIDENCE_DIR/run.log") 2>&1

adb_target() {
    timeout --foreground 30s adb -s "$ADB_SERIAL" "$@" </dev/null
}

restore_factory_services() {
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
    trap - EXIT
    set +e
    adb_target shell am force-stop "$PACKAGE_NAME" >/dev/null 2>&1
    adb_target shell rm -f "$DEVICE_WAV" >/dev/null 2>&1
    local restored="false"
    if restore_factory_services; then
        restored="true"
    else
        status=1
    fi
    adb_target shell ps >"$EVIDENCE_DIR/restored-ps.txt" 2>&1 || true
    {
        printf 'playback_status=%s\n' "$status"
        printf 'factory_services_restored=%s\n' "$restored"
        printf 'source=%s\n' "$SOURCE_WAV"
        printf 'gain_db=%s\n' "$GAIN_DB"
        printf 'intelligibility_confirmation=pending_user_confirmation\n'
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
adb_target shell dumpsys package "$PACKAGE_NAME" >"$EVIDENCE_DIR/package-dump.txt"
grep -q 'versionCode=27 ' "$EVIDENCE_DIR/package-dump.txt"

"$REPO_ROOT/tools/amplify-wav.py" "$SOURCE_WAV" "$REVIEW_WAV" --gain-db "$GAIN_DB"
"$REPO_ROOT/tools/analyze-wav.py" "$REVIEW_WAV" >"$EVIDENCE_DIR/analysis.json"
adb_target shell am force-stop "$PACKAGE_NAME"
adb_target shell am force-stop "$DEVICE_PACKAGE"
adb_target shell am force-stop "$PLAYER_PACKAGE"
adb_target shell mkdir -p "/sdcard/Android/data/${PACKAGE_NAME}/files/diagnostics"
adb_target push "$REVIEW_WAV" "$DEVICE_WAV" >/dev/null
adb_target logcat -c
NONCE="manual-review-$(date +%s%N)"
readonly NONCE
adb_target shell am start -W -n "$COMPONENT_NAME" \
    --es probe_action play --es file_path "$DEVICE_WAV" --es probe_nonce "$NONCE" \
    >"$EVIDENCE_DIR/activity.txt"

for _ in $(seq 1 20); do
    adb_target logcat -d -s R1Audio:V '*:S' >"$EVIDENCE_DIR/logcat.txt" 2>&1 || true
    marker="$(grep -F "nonce=${NONCE}" "$EVIDENCE_DIR/logcat.txt" \
        | grep -E 'R1_AUDIO_PLAYBACK_COMPLETE|R1_AUDIO_PLAYBACK_FAILED' | tail -1 || true)"
    if [[ -n "$marker" ]]; then
        printf '%s\n' "$marker" | tee "$EVIDENCE_DIR/playback-marker.txt"
        if grep -Fq R1_AUDIO_PLAYBACK_FAILED <<<"$marker"; then
            exit 1
        fi
        exit 0
    fi
    sleep 1
done
echo "Timed out waiting for diagnostic playback" >&2
exit 1
