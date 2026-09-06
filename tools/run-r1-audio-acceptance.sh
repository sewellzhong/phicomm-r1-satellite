#!/usr/bin/env bash
set -euo pipefail

readonly PACKAGE_NAME="dev.sewellzhong.r1probe"
readonly COMPONENT_NAME="${PACKAGE_NAME}/.MainActivity"
readonly DEVICE_PACKAGE="com.phicomm.speaker.device"
readonly PLAYER_PACKAGE="com.phicomm.speaker.player"
readonly DEVICE_AUDIO_DIR="/sdcard/Android/data/${PACKAGE_NAME}/files/diagnostics"
readonly PHRASE="请打开客厅的灯"

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
readonly EVIDENCE_DIR="${REPO_ROOT}/test-results/${RUN_ID}-${DEVICE_ID}/stage1/audio-acceptance"
readonly AUDIO_DIR="${EVIDENCE_DIR}/audio"
readonly LOG_DIR="${EVIDENCE_DIR}/logs"
readonly BACKUP_DIR="${REPO_ROOT}/test-results/2026-09-01-r1-sample01/stage0/current-installed-apps"
readonly DEVICE_TONE="${DEVICE_AUDIO_DIR}/acceptance-cue.wav"

mkdir -p "$AUDIO_DIR" "$LOG_DIR"
exec > >(tee "$EVIDENCE_DIR/run.log") 2>&1

adb_target() {
    adb -s "$ADB_SERIAL" "$@"
}

get_prop() {
    adb_target shell getprop "$1" | tr -d '\r'
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
    adb connect "$ADB_SERIAL" >/dev/null 2>&1 || true
    adb_target shell am startservice -n "$PLAYER_PACKAGE/.EchoService" >/dev/null 2>&1 || true
    adb_target shell am startservice -n "$DEVICE_PACKAGE/.ui.service.WindowsService" >/dev/null 2>&1 || true
    adb_target shell am start -n "$DEVICE_PACKAGE/.ui.MainActivity" >/dev/null 2>&1 || true
    for _ in $(seq 1 10); do
        if adb_target shell ps | tr -d '\r' | grep -q "$DEVICE_PACKAGE" \
            && adb_target shell ps | tr -d '\r' | grep -q "$PLAYER_PACKAGE"; then
            restored=1
            break
        fi
        sleep 1
    done
    capture_factory_state restored
    [[ $restored -eq 1 ]]
}

write_manifest() {
    local manifest_tmp
    manifest_tmp="$(mktemp)"
    (
        cd "$EVIDENCE_DIR"
        find audio logs -type f -print0
        find . -maxdepth 1 -type f \
            ! -name run.log ! -name SHA256SUMS ! -name SHA256SUMS.tmp -print0
    ) | sort -z | (
        cd "$EVIDENCE_DIR"
        xargs -0 sha256sum >"$manifest_tmp"
    )
    mv "$manifest_tmp" "$EVIDENCE_DIR/SHA256SUMS"
    (cd "$EVIDENCE_DIR" && sha256sum -c SHA256SUMS)
}

finish() {
    local status="$1"
    trap - EXIT
    set +e
    adb_target shell am force-stop "$PACKAGE_NAME" >/dev/null 2>&1
    adb_target shell rm -f "$DEVICE_TONE" >/dev/null 2>&1
    adb_target shell "rm -f ${DEVICE_AUDIO_DIR}/*-stage1-acceptance-*.wav*" >/dev/null 2>&1
    local restored="false"
    if restore_factory_services; then
        restored="true"
    else
        status=1
    fi
    {
        printf 'capture_status=%s\n' "$status"
        printf 'factory_services_restored=%s\n' "$restored"
        printf 'audible_confirmation=pending_user_confirmation\n'
        printf 'phrase=%s\n' "$PHRASE"
    } >"$EVIDENCE_DIR/RESULT.txt"
    if ! write_manifest; then
        status=1
    fi
    echo "Evidence: $EVIDENCE_DIR"
    exit "$status"
}
trap 'finish $?' EXIT

wait_for_marker() {
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
            | grep -E "${success_marker}|${failure_marker}" | tail -1 || true)"
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

record_sample() {
    local source_name="$1"
    local source_id="$2"
    local sample_kind="$3"
    local duration_seconds="$4"
    local nonce
    nonce="acceptance-${sample_kind}-${source_name}-$(date +%s%N)"
    local log_file="$LOG_DIR/${sample_kind}-${source_name}-logcat.txt"
    local marker_line
    local device_wav
    local host_wav="$AUDIO_DIR/${sample_kind}-${source_name}.wav"

    start_probe_activity \
        --es probe_action record \
        --ei audio_source "$source_id" \
        --ei duration_seconds "$duration_seconds" \
        --es sample_id "stage1-acceptance-${sample_kind}-${source_name}" \
        --es probe_nonce "$nonce" \
        >"$LOG_DIR/${sample_kind}-${source_name}-activity.txt"
    marker_line="$(wait_for_marker "$nonce" R1_AUDIO_RECORD_COMPLETE \
        R1_AUDIO_RECORD_FAILED "$((duration_seconds + 10))" "$log_file")"
    printf '%s\n' "$marker_line"
    device_wav="$(sed -n 's/.* path=\([^ ]*\.wav\) .*/\1/p' <<<"$marker_line")"
    [[ -n "$device_wav" ]]
    adb_target pull "$device_wav" "$host_wav"
    adb_target pull "${device_wav}.meta.txt" "${host_wav}.meta.txt"
    "$REPO_ROOT/tools/analyze-wav.py" "$host_wav" \
        >"$AUDIO_DIR/${sample_kind}-${source_name}.analysis.json"
    adb_target shell rm -f "$device_wav" "${device_wav}.meta.txt"
}

play_cue() {
    local cue_name="$1"
    local frequency="$2"
    local host_tone="$AUDIO_DIR/cue-${cue_name}.wav"
    "$REPO_ROOT/tools/generate-test-tone.py" "$host_tone" \
        --duration 5 --frequency "$frequency"
    "$REPO_ROOT/tools/analyze-wav.py" "$host_tone" \
        >"$AUDIO_DIR/cue-${cue_name}.analysis.json"
    adb_target shell mkdir -p "$DEVICE_AUDIO_DIR"
    adb_target push "$host_tone" "$DEVICE_TONE" >/dev/null
    local nonce
    nonce="acceptance-playback-${cue_name}-$(date +%s%N)"
    start_probe_activity --es probe_action play --es file_path "$DEVICE_TONE" \
        --es probe_nonce "$nonce" >"$LOG_DIR/playback-${cue_name}-activity.txt"
    wait_for_marker "$nonce" R1_AUDIO_PLAYBACK_COMPLETE R1_AUDIO_PLAYBACK_FAILED 10 \
        "$LOG_DIR/playback-${cue_name}-logcat.txt" \
        | tee "$EVIDENCE_DIR/playback-${cue_name}.txt"
}

echo "Evidence: $EVIDENCE_DIR"
PRODUCT_DEVICE="$(get_prop ro.product.device)"
readonly PRODUCT_DEVICE
SDK="$(get_prop ro.build.version.sdk)"
readonly SDK
FIRMWARE="$(get_prop ro.build.version.incremental)"
readonly FIRMWARE
printf 'Target: serial=%s device=%s sdk=%s firmware=%s\n' \
    "$ADB_SERIAL" "$PRODUCT_DEVICE" "$SDK" "$FIRMWARE"
[[ "$PRODUCT_DEVICE" == "rk322x_echo" && "$SDK" == "22" && "$FIRMWARE" == "3448" ]]
(cd "$BACKUP_DIR" && sha256sum -c SHA256SUMS)
adb_target shell dumpsys package "$PACKAGE_NAME" >"$LOG_DIR/package-dump.txt"
grep -q 'versionCode=27 ' "$LOG_DIR/package-dump.txt"

cat >"$EVIDENCE_DIR/TEST-INSTRUCTIONS.txt" <<EOF
purpose=R1 stage1 controlled speech intelligibility and speaker audibility
distance_m=1
environment=quiet
phrase=$PHRASE
speech_level=normal_conversational_voice_not_whispering_or_shouting
sequence=remain silent during three baselines; each source has a 5-second 1 kHz start cue followed by a 10-second speech window; a final 500 Hz cue means stop
privacy=device copies deleted after verified pull; local WAV excluded by .gitignore
EOF

capture_factory_state before-stop
adb_target shell am force-stop "$PACKAGE_NAME"
adb_target shell am force-stop "$DEVICE_PACKAGE"
adb_target shell am force-stop "$PLAYER_PACKAGE"
sleep 2
capture_factory_state stopped
if adb_target shell ps | tr -d '\r' | grep -q "$DEVICE_PACKAGE"; then
    echo "Factory device package restarted during acceptance setup" >&2
    exit 1
fi
if adb_target shell ps | tr -d '\r' | grep -q "$PLAYER_PACKAGE"; then
    echo "Factory player package restarted during acceptance setup" >&2
    exit 1
fi

echo "保持安静：正在采集三路静音基线，约 20 秒。"
record_sample voice_communication 7 silence 5
record_sample voice_recognition 6 silence 5
record_sample mic 1 silence 5

echo "每一路开始前会播放 5 秒嗡声；嗡声结束后持续重复固定短语，直到下一次嗡声。"
for source_spec in "voice_communication:7" "voice_recognition:6" "mic:1"; do
    source_name="${source_spec%%:*}"
    source_id="${source_spec##*:}"
    echo "下一轮输入源：${source_name}。嗡声结束后说：${PHRASE}"
    play_cue "start-${source_name}" 1000
    record_sample "$source_name" "$source_id" speech 10
done
echo "播放 500 Hz 结束提示音；听到后无需继续说话。"
play_cue finished 500

for source_name in voice_communication voice_recognition mic; do
    "$REPO_ROOT/tools/compare-wav-levels.py" \
        "$AUDIO_DIR/silence-${source_name}.wav" \
        "$AUDIO_DIR/speech-${source_name}.wav" \
        >"$AUDIO_DIR/${source_name}.comparison.json"
done

echo "Controlled capture and AudioTrack playback completed; audible and intelligibility confirmation remain manual."



