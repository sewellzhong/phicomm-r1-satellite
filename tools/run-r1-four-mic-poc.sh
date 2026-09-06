#!/usr/bin/env bash
# shellcheck disable=SC2317 # Cleanup functions are invoked indirectly by EXIT traps.
set -euo pipefail

readonly PACKAGE_NAME="dev.sewellzhong.r1probe"
readonly COMPONENT_NAME="${PACKAGE_NAME}/.MainActivity"
readonly DEVICE_PACKAGE="com.phicomm.speaker.device"
readonly PLAYER_PACKAGE="com.phicomm.speaker.player"
readonly DEVICE_AUDIO_DIR="/sdcard/Android/data/${PACKAGE_NAME}/files/diagnostics"
readonly DEVICE_TONE="${DEVICE_AUDIO_DIR}/four-mic-cue.wav"
readonly PHRASE="请打开客厅的灯"

usage() {
    printf '%s\n' \
        "Usage:" \
        "  $0 <adb-serial> capabilities --confirm-device r1-sample01" \
        "  $0 <adb-serial> record --confirm-device r1-sample01 --confirm-temporary-disable" >&2
    exit 64
}

[[ $# -ge 4 ]] || usage
readonly ADB_SERIAL="$1"
readonly ACTION="$2"
shift 2

confirm_device=""
confirm_temporary_disable=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --confirm-device)
            [[ $# -ge 2 ]] || usage
            confirm_device="$2"
            shift 2
            ;;
        --confirm-temporary-disable)
            confirm_temporary_disable=true
            shift
            ;;
        *) usage ;;
    esac
done
[[ "$ACTION" == "capabilities" || "$ACTION" == "record" ]] || usage

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly REPO_ROOT
readonly DEVICE_ID="${R1_DEVICE_ID:-r1-sample01}"
RUN_ID="$(date +%Y-%m-%dT%H%M%S)"
readonly RUN_ID
readonly EVIDENCE_DIR="$REPO_ROOT/test-results/${RUN_ID}-${DEVICE_ID}/stage1/four-mic-${ACTION}"
readonly AUDIO_DIR="$EVIDENCE_DIR/audio"
readonly LOG_DIR="$EVIDENCE_DIR/logs"

mkdir -p "$AUDIO_DIR" "$LOG_DIR"
exec > >(tee "$EVIDENCE_DIR/run.log") 2>&1

change_started=false
device_initially_disabled=false
player_initially_disabled=false
device_disabled_by_run=false
player_disabled_by_run=false
completed=false

adb_target() {
    timeout --foreground 30s adb -s "$ADB_SERIAL" "$@" </dev/null
}

adb_pull() {
    local remote_path="$1"
    local local_path="$2"
    local remote_size
    remote_size="$(adb_target shell ls -l "$remote_path" | tr -d '\r' | awk '{print $4}')"
    [[ "$remote_size" =~ ^[0-9]+$ ]] || return 1
    timeout --foreground 180s adb -s "$ADB_SERIAL" pull "$remote_path" "$local_path" </dev/null &
    local pull_pid=$!
    for _ in $(seq 1 180); do
        if [[ -f "$local_path" && "$(wc -c <"$local_path")" == "$remote_size" ]]; then
            kill "$pull_pid" >/dev/null 2>&1 || true
            wait "$pull_pid" 2>/dev/null || true
            return 0
        fi
        kill -0 "$pull_pid" >/dev/null 2>&1 || break
        sleep 1
    done
    wait "$pull_pid" 2>/dev/null || true
    [[ -f "$local_path" && "$(wc -c <"$local_path")" == "$remote_size" ]]
}

pm_command() {
    local command_text="$1"
    adb_target shell "CLASSPATH=/system/framework/pm.jar app_process /system/bin com.android.commands.pm.Pm $command_text"
}

get_prop() {
    adb_target shell getprop "$1" | tr -d '\r'
}

package_is_disabled() {
    local package_name="$1"
    pm_command "list packages -d" | tr -d '\r' | grep -qx "package:${package_name}"
}

start_current_services() {
    timeout --foreground 10s adb connect "$ADB_SERIAL" </dev/null >/dev/null 2>&1 || true
    adb_target shell am startservice -n "$PLAYER_PACKAGE/.EchoService" >/dev/null 2>&1 || true
    adb_target shell am startservice -n "$DEVICE_PACKAGE/.ui.service.WindowsService" >/dev/null 2>&1 || true
    adb_target shell am start -n "$DEVICE_PACKAGE/.ui.MainActivity" >/dev/null 2>&1 || true
}

restore_package_state() {
    local restored=true
    timeout --foreground 10s adb connect "$ADB_SERIAL" </dev/null >/dev/null 2>&1 || true
    if [[ "$player_disabled_by_run" == true ]]; then
        pm_command "enable --user 0 $PLAYER_PACKAGE" >/dev/null 2>&1 || true
        package_is_disabled "$PLAYER_PACKAGE" && restored=false
    fi
    timeout --foreground 10s adb connect "$ADB_SERIAL" </dev/null >/dev/null 2>&1 || true
    if [[ "$device_disabled_by_run" == true ]]; then
        pm_command "enable --user 0 $DEVICE_PACKAGE" >/dev/null 2>&1 || true
        package_is_disabled "$DEVICE_PACKAGE" && restored=false
    fi
    if [[ "$player_initially_disabled" == false || "$device_initially_disabled" == false ]]; then
        start_current_services
        local process_state_ok=false
        for _ in $(seq 1 10); do
            process_state_ok=true
            if [[ "$player_initially_disabled" == false ]] \
                && ! adb_target shell ps | tr -d '\r' | grep -q "$PLAYER_PACKAGE"; then
                process_state_ok=false
            fi
            if [[ "$device_initially_disabled" == false ]] \
                && ! adb_target shell ps | tr -d '\r' | grep -q "$DEVICE_PACKAGE"; then
                process_state_ok=false
            fi
            [[ "$process_state_ok" == true ]] && break
            sleep 1
        done
        [[ "$process_state_ok" == true ]] || restored=false
    fi
    [[ "$restored" == true ]]
}

snapshot() {
    local prefix="$1"
    timeout --foreground 10s adb connect "$ADB_SERIAL" </dev/null >/dev/null 2>&1 || true
    adb_target shell ps >"$LOG_DIR/${prefix}-ps.txt" 2>&1 || true
    adb_target shell dumpsys media.audio_flinger >"$LOG_DIR/${prefix}-audio-flinger.txt" 2>&1 || true
    adb_target shell dumpsys audio >"$LOG_DIR/${prefix}-dumpsys-audio.txt" 2>&1 || true
    adb_target shell tinymix -D 1 >"$LOG_DIR/${prefix}-tinymix-rkma4.txt" 2>&1 || true
    adb_target shell tinymix -D 2 >"$LOG_DIR/${prefix}-tinymix-ak7755.txt" 2>&1 || true
    adb_target shell cat /proc/asound/pcm >"$LOG_DIR/${prefix}-asound-pcm.txt" 2>&1 || true
    adb_target shell dumpsys meminfo "$PACKAGE_NAME" >"$LOG_DIR/${prefix}-probe-meminfo.txt" 2>&1 || true
    adb_target shell dmesg >"$LOG_DIR/${prefix}-dmesg.txt" 2>&1 || true
}

write_manifest() {
    local manifest_tmp
    manifest_tmp="$(mktemp)"
    (
        cd "$EVIDENCE_DIR"
        find . -type f ! -name run.log ! -name SHA256SUMS -print0 \
            | sort -z | xargs -0 sha256sum >"$manifest_tmp"
    )
    mv "$manifest_tmp" "$EVIDENCE_DIR/SHA256SUMS"
    (cd "$EVIDENCE_DIR" && sha256sum -c SHA256SUMS)
}

finish() {
    local status="$1"
    trap - EXIT INT TERM
    set +e
    timeout --foreground 10s adb connect "$ADB_SERIAL" </dev/null >/dev/null 2>&1 || true
    adb_target shell am force-stop "$PACKAGE_NAME" >/dev/null 2>&1 || true
    adb_target shell rm -f "$DEVICE_TONE" >/dev/null 2>&1 || true
    adb_target shell "rm -f ${DEVICE_AUDIO_DIR}/*-stage1-four-mic-*.wav*" >/dev/null 2>&1 || true
    local restored="not_needed"
    if [[ "$change_started" == true ]]; then
        restored=false
        if restore_package_state; then
            restored=true
        else
            status=1
        fi
        snapshot restored
    fi
    {
        printf 'action=%s\n' "$ACTION"
        printf 'status=%s\n' "$status"
        printf 'completed=%s\n' "$completed"
        printf 'temporary_package_change=%s\n' "$change_started"
        printf 'device_disabled_by_run=%s\n' "$device_disabled_by_run"
        printf 'player_disabled_by_run=%s\n' "$player_disabled_by_run"
        printf 'original_package_state_restored=%s\n' "$restored"
        printf 'uninstall_performed=false\n'
        printf 'root_used=false\n'
        printf 'system_files_modified=false\n'
        printf 'phrase=%s\n' "$PHRASE"
        printf 'intelligibility_confirmation=pending_user_review\n'
    } >"$EVIDENCE_DIR/RESULT.txt"
    write_manifest || status=1
    echo "Evidence: $EVIDENCE_DIR"
    exit "$status"
}
trap 'finish $?' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

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

run_capabilities() {
    local nonce
    nonce="four-mic-capabilities-$(date +%s%N)"
    adb_target shell am force-stop "$PACKAGE_NAME"
    adb_target logcat -c
    adb_target shell am start -W -n "$COMPONENT_NAME" \
        --es probe_action four_mic_capabilities --es probe_nonce "$nonce" \
        >"$LOG_DIR/capabilities-activity.txt"
    wait_for_marker "$nonce" R1_FOUR_MIC_CAPABILITIES R1_FOUR_MIC_CAPABILITIES_FAILED 8 \
        "$LOG_DIR/capabilities-logcat.txt" | tee "$EVIDENCE_DIR/capabilities-marker.txt"
}

record_sample() {
    local route="$1"
    local kind="$2"
    local nonce
    nonce="four-mic-${kind}-${route}-$(date +%s%N)"
    local action="four_mic_record"
    local success="R1_FOUR_MIC_RECORD_COMPLETE"
    local failure="R1_FOUR_MIC_RECORD_FAILED"
    local source_args=()
    if [[ "$route" == "voice_communication" ]]; then
        action="record"
        success="R1_AUDIO_RECORD_COMPLETE"
        failure="R1_AUDIO_RECORD_FAILED"
        source_args=(--ei audio_source 7)
    fi
    adb_target shell am force-stop "$PACKAGE_NAME"
    adb_target logcat -c
    adb_target shell am start -W -n "$COMPONENT_NAME" \
        --es probe_action "$action" "${source_args[@]}" \
        --ei duration_seconds 10 --es sample_id "stage1-four-mic-${kind}-${route}" \
        --es probe_nonce "$nonce" >"$LOG_DIR/${kind}-${route}-activity.txt"
    local marker
    marker="$(wait_for_marker "$nonce" "$success" "$failure" 20 \
        "$LOG_DIR/${kind}-${route}-logcat.txt")"
    adb_target logcat -d >"$LOG_DIR/${kind}-${route}-full-logcat.txt" 2>&1 || true
    printf '%s\n' "$marker" | tee "$EVIDENCE_DIR/${kind}-${route}-marker.txt"
    local device_wav
    device_wav="$(sed -n 's/.* path=\([^ ]*\.wav\) .*/\1/p' <<<"$marker")"
    [[ -n "$device_wav" ]]
    local host_wav="$AUDIO_DIR/${kind}-${route}.wav"
    adb_pull "$device_wav" "$host_wav" >/dev/null
    adb_pull "${device_wav}.meta.txt" "${host_wav}.meta.txt" >/dev/null
    "$REPO_ROOT/tools/analyze-wav.py" "$host_wav" >"$AUDIO_DIR/${kind}-${route}.analysis.json"
    adb_target shell rm -f "$device_wav" "${device_wav}.meta.txt"
}

play_cue() {
    local cue_name="$1"
    local frequency="$2"
    local host_tone="$AUDIO_DIR/cue-${cue_name}.wav"
    "$REPO_ROOT/tools/generate-test-tone.py" "$host_tone" --duration 5 --frequency "$frequency"
    adb_target shell mkdir -p "$DEVICE_AUDIO_DIR"
    adb_target push "$host_tone" "$DEVICE_TONE" >/dev/null
    local nonce
    nonce="four-mic-cue-${cue_name}-$(date +%s%N)"
    adb_target shell am force-stop "$PACKAGE_NAME"
    adb_target logcat -c
    adb_target shell am start -W -n "$COMPONENT_NAME" \
        --es probe_action play --es file_path "$DEVICE_TONE" --es probe_nonce "$nonce" \
        >"$LOG_DIR/cue-${cue_name}-activity.txt"
    wait_for_marker "$nonce" R1_AUDIO_PLAYBACK_COMPLETE R1_AUDIO_PLAYBACK_FAILED 12 \
        "$LOG_DIR/cue-${cue_name}-logcat.txt" >"$EVIDENCE_DIR/cue-${cue_name}-marker.txt"
}

echo "Evidence: $EVIDENCE_DIR"
[[ "$confirm_device" == "$DEVICE_ID" ]] || {
    echo "Refusing operation: --confirm-device must equal $DEVICE_ID" >&2
    exit 65
}
if [[ "$ACTION" == "record" && "$confirm_temporary_disable" != true ]]; then
    echo "Refusing record: --confirm-temporary-disable is required" >&2
    exit 65
fi

PRODUCT_DEVICE="$(get_prop ro.product.device)"
SDK="$(get_prop ro.build.version.sdk)"
FIRMWARE="$(get_prop ro.build.version.incremental)"
readonly PRODUCT_DEVICE SDK FIRMWARE
printf 'Target: serial=%s device=%s sdk=%s firmware=%s\n' \
    "$ADB_SERIAL" "$PRODUCT_DEVICE" "$SDK" "$FIRMWARE"
[[ "$PRODUCT_DEVICE" == "rk322x_echo" && "$SDK" == "22" && "$FIRMWARE" == "3448" ]] || {
    echo "Refusing four-microphone PoC: unexpected target identity" >&2
    exit 65
}

"$REPO_ROOT/tools/audit-r1-audio-provenance.sh" "$ADB_SERIAL"
"$REPO_ROOT/tools/audit-r1-four-mic-interface.sh" "$ADB_SERIAL"
adb_target shell dumpsys package "$PACKAGE_NAME" >"$LOG_DIR/package-dump.txt"
grep -q 'versionCode=27 ' "$LOG_DIR/package-dump.txt" || {
    echo "R1 audio probe versionCode 27 is not installed" >&2
    exit 65
}

snapshot before
run_capabilities
if [[ "$ACTION" == "capabilities" ]]; then
    snapshot after-capabilities
    completed=true
    exit 0
fi

if package_is_disabled "$DEVICE_PACKAGE"; then device_initially_disabled=true; fi
if package_is_disabled "$PLAYER_PACKAGE"; then player_initially_disabled=true; fi
change_started=true
adb_target shell am force-stop "$DEVICE_PACKAGE"
adb_target shell am force-stop "$PLAYER_PACKAGE"
pm_command "disable-user --user 0 $DEVICE_PACKAGE" | tee "$EVIDENCE_DIR/disable-device.txt"
package_is_disabled "$DEVICE_PACKAGE" || {
    echo "Temporary disable was rejected for $DEVICE_PACKAGE; refusing to assume isolation" >&2
    exit 1
}
device_disabled_by_run=true
timeout --foreground 10s adb connect "$ADB_SERIAL" </dev/null >/dev/null 2>&1 || true
pm_command "disable-user --user 0 $PLAYER_PACKAGE" | tee "$EVIDENCE_DIR/disable-player.txt"
package_is_disabled "$PLAYER_PACKAGE" || {
    echo "Temporary disable was rejected for $PLAYER_PACKAGE; refusing to assume isolation" >&2
    exit 1
}
player_disabled_by_run=true
sleep 2
snapshot isolated
if adb_target shell ps | tr -d '\r' | grep -Eq "$DEVICE_PACKAGE|$PLAYER_PACKAGE"; then
    echo "Audio overlay process remained active after temporary disable" >&2
    exit 1
fi

printf '%s\n' \
    "保持安静：先采集四麦和标准 AudioRecord 各 10 秒静音基线。" \
    "随后每条路径会播放 5 秒嗡声；嗡声结束后，以正常交谈音量持续重复：${PHRASE}"
{
    printf 'purpose=R1 stage1 vendor four microphone versus AudioRecord comparison\n'
    printf 'distance_m=1\n'
    printf 'environment=quiet\n'
    printf 'phrase=%s\n' "$PHRASE"
    printf 'speech_level=normal_conversational_voice_not_whispering_or_shouting\n'
    printf 'native_library_bundled=false\n'
    printf 'privacy=device_audio_deleted_after_pull;local_wav_ignored_by_git\n'
} >"$EVIDENCE_DIR/TEST-INSTRUCTIONS.txt"

record_sample vendor_four_mic silence
record_sample voice_communication silence
echo "四麦路径：嗡声结束后开始重复固定短语。"
play_cue vendor-four-mic 1000
record_sample vendor_four_mic speech
echo "标准路径：嗡声结束后开始重复固定短语。"
play_cue voice-communication 1000
record_sample voice_communication speech
play_cue finished 500

for route in vendor_four_mic voice_communication; do
    "$REPO_ROOT/tools/compare-wav-levels.py" \
        "$AUDIO_DIR/silence-${route}.wav" "$AUDIO_DIR/speech-${route}.wav" \
        >"$AUDIO_DIR/${route}.comparison.json"
done
snapshot after-recordings
completed=true
echo "Four-microphone PoC capture completed; intelligibility review remains manual."
