#!/usr/bin/env bash
# shellcheck disable=SC2317 # Cleanup functions are invoked indirectly by EXIT traps.
set -euo pipefail

readonly PACKAGE_NAME="dev.sewellzhong.r1probe"
readonly COMPONENT_NAME="${PACKAGE_NAME}/.MainActivity"
readonly RECEIVER_COMPONENT="${PACKAGE_NAME}/.ProbeCommandReceiver"
readonly DEVICE_PACKAGE="com.phicomm.speaker.device"
readonly PLAYER_PACKAGE="com.phicomm.speaker.player"
readonly DEVICE_AUDIO_DIR="/sdcard/Android/data/${PACKAGE_NAME}/files/diagnostics"
readonly DEVICE_TONE="${DEVICE_AUDIO_DIR}/stereo-channel-cue.wav"
readonly PHRASE="请打开客厅的灯"

usage() {
    echo "Usage: $0 <adb-serial> <smoke|controlled>" >&2
    exit 64
}

[[ $# -eq 2 ]] || usage
readonly ADB_SERIAL="$1"
readonly MODE="$2"
[[ "$MODE" == "smoke" || "$MODE" == "controlled" ]] || usage

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly REPO_ROOT
readonly DEVICE_ID="${R1_DEVICE_ID:-r1-sample01}"
RUN_ID="$(date +%Y-%m-%dT%H%M%S)"
readonly RUN_ID
readonly EVIDENCE_DIR="$REPO_ROOT/test-results/${RUN_ID}-${DEVICE_ID}/stage1/stereo-channel-${MODE}"
readonly AUDIO_DIR="$EVIDENCE_DIR/audio"
readonly LOG_DIR="$EVIDENCE_DIR/logs"

mkdir -p "$AUDIO_DIR" "$LOG_DIR"
exec > >(tee "$EVIDENCE_DIR/run.log") 2>&1
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
    timeout --foreground 60s adb -s "$ADB_SERIAL" pull "$remote_path" "$local_path" </dev/null &
    local pull_pid=$!
    for _ in $(seq 1 60); do
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

snapshot() {
    local prefix="$1"
    adb_target shell ps >"$LOG_DIR/${prefix}-ps.txt" 2>&1 || true
    adb_target shell dumpsys media.audio_flinger >"$LOG_DIR/${prefix}-audio-flinger.txt" 2>&1 || true
    adb_target shell dumpsys audio >"$LOG_DIR/${prefix}-dumpsys-audio.txt" 2>&1 || true
    adb_target shell tinymix -D 1 >"$LOG_DIR/${prefix}-tinymix-rkma4.txt" 2>&1 || true
    adb_target shell tinymix -D 2 >"$LOG_DIR/${prefix}-tinymix-ak7755.txt" 2>&1 || true
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

write_manifest() {
    local manifest_tmp
    manifest_tmp="$(mktemp)"
    (cd "$EVIDENCE_DIR" && find . -type f ! -name run.log ! -name SHA256SUMS -print0 \
        | sort -z | xargs -0 sha256sum >"$manifest_tmp")
    mv "$manifest_tmp" "$EVIDENCE_DIR/SHA256SUMS"
    (cd "$EVIDENCE_DIR" && sha256sum -c SHA256SUMS)
}

finish() {
    local status="$1"
    trap - EXIT INT TERM
    set +e
    adb_target shell am force-stop "$PACKAGE_NAME" >/dev/null 2>&1 || true
    adb_target shell rm -f "$DEVICE_TONE" >/dev/null 2>&1 || true
    adb_target shell "rm -f ${DEVICE_AUDIO_DIR}/*-stage1-stereo-*.wav*" >/dev/null 2>&1 || true
    adb_target shell "rm -f ${DEVICE_AUDIO_DIR}/*-stereo-stage1-stereo-*.meta.txt" >/dev/null 2>&1 || true
    local restored=false
    if restore_services; then
        restored=true
    else
        status=1
    fi
    snapshot restored
    {
        printf 'mode=%s\n' "$MODE"
        printf 'status=%s\n' "$status"
        printf 'completed=%s\n' "$completed"
        printf 'factory_services_restored=%s\n' "$restored"
        printf 'production_format_changed=false\n'
        printf 'device_audio_removed=true\n'
    } >"$EVIDENCE_DIR/RESULT.txt"
    write_manifest || status=1
    echo "Evidence: $EVIDENCE_DIR"
    exit "$status"
}
trap 'finish $?' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

isolate_audio_apps() {
    adb_target shell am force-stop "$PACKAGE_NAME"
    adb_target shell am start -S -W -n "$COMPONENT_NAME" \
        --es probe_nonce "isolation-foreground-$(date +%s%N)" >/dev/null
    adb_target shell am force-stop "$DEVICE_PACKAGE"
    adb_target shell am force-stop "$PLAYER_PACKAGE"
    sleep 1
    if adb_target shell ps | tr -d '\r' | grep -Eq "$DEVICE_PACKAGE|$PLAYER_PACKAGE"; then
        echo "Audio overlay process restarted; refusing stereo capture" >&2
        return 1
    fi
}

wait_for_marker() {
    local nonce="$1"
    local success="$2"
    local failure="$3"
    local timeout_seconds="$4"
    local log_file="$5"
    local line=""
    local second
    for ((second = 0; second < timeout_seconds; second++)); do
        adb_target logcat -d -s R1Audio:V '*:S' >"$log_file" 2>&1 || true
        line="$(grep -F "nonce=${nonce}" "$log_file" \
            | grep -E "${success}|${failure}" | tail -1 || true)"
        if [[ -n "$line" ]]; then
            printf '%s\n' "$line"
            grep -Fq "$failure" <<<"$line" && return 1
            return 0
        fi
        sleep 1
    done
    return 1
}

record_stereo() {
    local kind="$1"
    local duration="$2"
    local cue_path="${3:-}"
    local cue_args=()
    if [[ -n "$cue_path" ]]; then
        cue_args=(--es cue_path "$cue_path")
    fi
    local nonce
    nonce="stereo-${kind}-$(date +%s%N)"
    isolate_audio_apps
    adb_target logcat -c
    adb_target shell am broadcast -n "$RECEIVER_COMPONENT" \
        -a dev.sewellzhong.r1probe.COMMAND \
        --es probe_action stereo_record --ei audio_source 7 --ei duration_seconds "$duration" \
        "${cue_args[@]}" \
        --es sample_id "stage1-stereo-${kind}" --es probe_nonce "$nonce" \
        >"$LOG_DIR/${kind}-activity.txt"
    local marker
    marker="$(wait_for_marker "$nonce" R1_STEREO_RECORD_COMPLETE R1_STEREO_RECORD_FAILED \
        "$((duration + 10))" "$LOG_DIR/${kind}-logcat.txt")"
    adb_target logcat -d >"$LOG_DIR/${kind}-full-logcat.txt" 2>&1 || true
    printf '%s\n' "$marker" | tee "$EVIDENCE_DIR/${kind}-marker.txt"
    local key remote_path host_path
    for key in stereo left right average difference; do
        remote_path="$(sed -n "s/.* ${key}_path=\\([^ ]*\\) .*/\\1/p" <<<"$marker")"
        [[ -n "$remote_path" ]]
        host_path="$AUDIO_DIR/${kind}-${key}.wav"
        adb_pull "$remote_path" "$host_path" >/dev/null
        "$REPO_ROOT/tools/analyze-wav.py" "$host_path" >"$AUDIO_DIR/${kind}-${key}.analysis.json"
        if [[ "$key" == "stereo" ]]; then
            "$REPO_ROOT/tools/compare-stereo-channels.py" "$host_path" \
                >"$AUDIO_DIR/${kind}-stereo-channels.json"
        fi
        adb_target shell rm -f "$remote_path"
    done
    remote_path="$(sed -n 's/.* metadata_path=\([^ ]*\) .*/\1/p' <<<"$marker")"
    [[ -n "$remote_path" ]]
    adb_pull "$remote_path" "$AUDIO_DIR/${kind}.meta.txt" >/dev/null
    adb_target shell rm -f "$remote_path"
}

play_cue() {
    local frequency="$1"
    local cue_name="$2"
    local host_tone="$AUDIO_DIR/cue-${cue_name}.wav"
    "$REPO_ROOT/tools/generate-test-tone.py" "$host_tone" --duration 5 --frequency "$frequency"
    adb_target shell mkdir -p "$DEVICE_AUDIO_DIR"
    adb_target push "$host_tone" "$DEVICE_TONE" >/dev/null
    local nonce
    nonce="stereo-cue-${cue_name}-$(date +%s%N)"
    isolate_audio_apps
    adb_target logcat -c
    adb_target shell am broadcast -n "$RECEIVER_COMPONENT" \
        -a dev.sewellzhong.r1probe.COMMAND --es probe_action play \
        --es file_path "$DEVICE_TONE" --es probe_nonce "$nonce" >"$LOG_DIR/cue-${cue_name}.txt"
    wait_for_marker "$nonce" R1_AUDIO_PLAYBACK_COMPLETE R1_AUDIO_PLAYBACK_FAILED 12 \
        "$LOG_DIR/cue-${cue_name}-logcat.txt" >"$EVIDENCE_DIR/cue-${cue_name}-marker.txt"
}

prepare_start_cue() {
    local host_tone="$AUDIO_DIR/cue-speech-start.wav"
    "$REPO_ROOT/tools/generate-test-tone.py" "$host_tone" --duration 5 --frequency 1000
    adb_target shell mkdir -p "$DEVICE_AUDIO_DIR"
    adb_target push "$host_tone" "$DEVICE_TONE" >/dev/null
}

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

if [[ "$MODE" == "smoke" ]]; then
    record_stereo smoke 2
else
    {
        printf 'purpose=diagnose framework stereo to mono downmix and channel cancellation\n'
        printf 'distance_m=1\n'
        printf 'phrase=%s\n' "$PHRASE"
        printf 'production_format_changed=false\n'
        printf 'privacy=device_audio_deleted_after_pull;local_wav_ignored_by_git\n'
    } >"$EVIDENCE_DIR/TEST-INSTRUCTIONS.txt"
    echo "保持安静：正在采集 5 秒双声道静音基线。"
    record_stereo silence 5
    echo "录音初始化完成后会播放 5 秒嗡声；结束后正常音量重复：$PHRASE"
    prepare_start_cue
    record_stereo speech 10 "$DEVICE_TONE"
    play_cue 500 finished
    for channel in left right average difference; do
        "$REPO_ROOT/tools/compare-wav-levels.py" \
            "$AUDIO_DIR/silence-${channel}.wav" "$AUDIO_DIR/speech-${channel}.wav" \
            >"$AUDIO_DIR/${channel}.comparison.json"
    done
fi
snapshot after
completed=true
echo "Stereo channel probe completed."



