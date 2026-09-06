#!/usr/bin/env bash
# shellcheck disable=SC2317 # Cleanup functions are invoked indirectly by EXIT traps.
set -euo pipefail

readonly PACKAGE_NAME="dev.sewellzhong.r1probe"
readonly COMPONENT_NAME="${PACKAGE_NAME}/.MainActivity"
readonly RECEIVER_COMPONENT="${PACKAGE_NAME}/.ProbeCommandReceiver"
readonly DEVICE_PACKAGE="com.phicomm.speaker.device"
readonly PLAYER_PACKAGE="com.phicomm.speaker.player"
readonly DEVICE_AUDIO_DIR="/sdcard/Android/data/${PACKAGE_NAME}/files/diagnostics"
readonly DEVICE_CUE="${DEVICE_AUDIO_DIR}/processed-acceptance-cue.wav"
readonly PHRASE="请打开客厅的灯"

usage() {
    echo "Usage: $0 <adb-serial> --confirm-device r1-sample01 --confirm-recording" >&2
    exit 64
}

[[ $# -eq 4 ]] || usage
readonly ADB_SERIAL="$1"
[[ "$2" == "--confirm-device" && "$3" == "r1-sample01" \
    && "$4" == "--confirm-recording" ]] || usage

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly REPO_ROOT
RUN_ID="$(date +%Y-%m-%dT%H%M%S)"
readonly RUN_ID
readonly EVIDENCE_DIR="$REPO_ROOT/test-results/${RUN_ID}-r1-sample01/stage1/processed-speech-acceptance"
readonly AUDIO_DIR="$EVIDENCE_DIR/audio"
readonly LOG_DIR="$EVIDENCE_DIR/logs"
readonly BACKUP_DIR="$REPO_ROOT/test-results/2026-09-01-r1-sample01/stage0/current-installed-apps"

mkdir -p "$AUDIO_DIR" "$LOG_DIR"
exec > >(tee "$EVIDENCE_DIR/run.log") 2>&1
completed=false

adb_target() {
    timeout --foreground 60s adb -s "$ADB_SERIAL" "$@" </dev/null
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
    adb_target shell rm -f "$DEVICE_CUE" >/dev/null 2>&1 || true
    adb_target shell "rm -f ${DEVICE_AUDIO_DIR}/*-stage1-processed-ab-*.wav*" \
        >/dev/null 2>&1 || true
    restored=false
    if restore_services; then restored=true; else status=1; fi
    adb_target shell ps >"$LOG_DIR/restored-ps.txt" 2>&1 || true
    {
        printf 'status=%s\n' "$status"
        printf 'completed=%s\n' "$completed"
        printf 'factory_services_restored=%s\n' "$restored"
        printf 'device_audio_removed=true\n'
        printf 'phrase=%s\n' "$PHRASE"
        printf 'intelligibility_confirmation=pending_user_confirmation\n'
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

capture_pair() {
    local kind="$1"
    local duration="$2"
    local cue_path="${3:-}"
    local nonce marker raw_path processed_path metadata_path
    nonce="processed-ab-${kind}-$(date +%s%N)"
    cue_args=()
    if [[ -n "$cue_path" ]]; then cue_args=(--es cue_path "$cue_path"); fi
    adb_target logcat -c
    adb_target shell am broadcast -n "$RECEIVER_COMPONENT" \
        -a dev.sewellzhong.r1probe.COMMAND --es probe_action processed_compare \
        --ei duration_seconds "$duration" --es sample_id "stage1-processed-ab-${kind}" \
        --es probe_nonce "$nonce" "${cue_args[@]}" >"$LOG_DIR/${kind}-broadcast.txt"
    adb_target logcat -d -s R1Audio:V '*:S' >"$LOG_DIR/${kind}-logcat.txt"
    marker="$(grep -F "nonce=${nonce}" "$LOG_DIR/${kind}-logcat.txt" \
        | grep -E 'R1_PROCESSED_COMPARE_COMPLETE|R1_PROCESSED_COMPARE_FAILED' | tail -1 || true)"
    printf '%s\n' "$marker" | tee "$EVIDENCE_DIR/${kind}-marker.txt"
    [[ "$marker" == *R1_PROCESSED_COMPARE_COMPLETE* ]]
    raw_path="$(sed -n 's/.* raw_path=\([^ ]*\) processed_path=.*/\1/p' <<<"$marker")"
    processed_path="$(sed -n 's/.* processed_path=\([^ ]*\) metadata_path=.*/\1/p' <<<"$marker")"
    metadata_path="$(sed -n 's/.* metadata_path=\([^ ]*\) input_samples=.*/\1/p' <<<"$marker")"
    [[ -n "$raw_path" && -n "$processed_path" && -n "$metadata_path" ]]
    adb_target pull "$raw_path" "$AUDIO_DIR/${kind}-raw.wav" >/dev/null
    adb_target pull "$processed_path" "$AUDIO_DIR/${kind}-processed.wav" >/dev/null
    adb_target pull "$metadata_path" "$AUDIO_DIR/${kind}.meta.txt" >/dev/null
    adb_target shell rm -f "$raw_path" "$processed_path" "$metadata_path"
    "$REPO_ROOT/tools/analyze-wav.py" "$AUDIO_DIR/${kind}-raw.wav" \
        >"$AUDIO_DIR/${kind}-raw.analysis.json"
    "$REPO_ROOT/tools/analyze-wav.py" "$AUDIO_DIR/${kind}-processed.wav" \
        >"$AUDIO_DIR/${kind}-processed.analysis.json"
}

PRODUCT_DEVICE="$(adb_target shell getprop ro.product.device | tr -d '\r')"
SDK="$(adb_target shell getprop ro.build.version.sdk | tr -d '\r')"
FIRMWARE="$(adb_target shell getprop ro.build.version.incremental | tr -d '\r')"
readonly PRODUCT_DEVICE SDK FIRMWARE
[[ "$PRODUCT_DEVICE" == "rk322x_echo" && "$SDK" == "22" && "$FIRMWARE" == "3448" ]]
(cd "$BACKUP_DIR" && sha256sum -c SHA256SUMS)
adb_target shell dumpsys package "$PACKAGE_NAME" >"$LOG_DIR/package-dump.txt"
grep -q 'versionCode=27 ' "$LOG_DIR/package-dump.txt"

cat >"$EVIDENCE_DIR/TEST-INSTRUCTIONS.txt" <<EOF
purpose=R1 stage1 same-capture raw versus processed speech acceptance
source=VOICE_COMMUNICATION
distance_m=1
environment=quiet
phrase=$PHRASE
speech_level=normal_conversational_voice_not_whispering_or_shouting
sequence=remain silent through baseline and speech calibration; after the 5-second 1kHz cue ends, repeat the phrase for 10 seconds
privacy=device WAV files deleted after verified pull; local WAV excluded by .gitignore
EOF

"$REPO_ROOT/tools/generate-test-tone.py" "$AUDIO_DIR/start-cue.wav" \
    --duration 5 --frequency 1000
adb_target shell mkdir -p "$DEVICE_AUDIO_DIR"
adb_target push "$AUDIO_DIR/start-cue.wav" "$DEVICE_CUE" >/dev/null
adb_target shell am force-stop "$PACKAGE_NAME"
adb_target shell am start -W -n "$COMPONENT_NAME" \
    --es probe_nonce "processed-ab-foreground-$(date +%s%N)" >/dev/null
adb_target shell am force-stop "$DEVICE_PACKAGE"
adb_target shell am force-stop "$PLAYER_PACKAGE"
sleep 2
if adb_target shell ps | tr -d '\r' | grep -Eq "$DEVICE_PACKAGE|$PLAYER_PACKAGE"; then
    echo "Audio overlay process restarted; refusing controlled recording" >&2
    exit 1
fi

echo "保持安静：开始 2 秒校准和 5 秒静音基线。"
capture_pair silence 5
echo "继续保持安静，直到 5 秒嗡声完全结束；随后用正常交谈音量持续重复：${PHRASE}"
capture_pair speech 10 "$DEVICE_CUE"

"$REPO_ROOT/tools/compare-wav-levels.py" "$AUDIO_DIR/silence-raw.wav" \
    "$AUDIO_DIR/speech-raw.wav" >"$AUDIO_DIR/raw.comparison.json"
"$REPO_ROOT/tools/compare-wav-levels.py" "$AUDIO_DIR/silence-processed.wav" \
    "$AUDIO_DIR/speech-processed.wav" >"$AUDIO_DIR/processed.comparison.json"
completed=true
echo "Same-capture raw/processed controlled speech recording completed."
