#!/usr/bin/env bash
# Temporary app-layer isolation, matching the established R1 audio test route.
set -euo pipefail
[[ ( $# -eq 3 || $# -eq 4 ) && "$2" == "--confirm-device" && "$3" == "r1-sample01" ]] || {
    echo "Usage: $0 <adb-serial> --confirm-device r1-sample01 [--human-test|--cue-check]" >&2
    exit 64
}
MODE=smoke
SECONDS_TO_RUN=20
if [[ $# -eq 4 ]]; then
    case "$4" in
        --human-test) MODE=human; SECONDS_TO_RUN=90 ;;
        --cue-check) MODE=cue-check; SECONDS_TO_RUN=5 ;;
        *) exit 64 ;;
    esac
fi
readonly MODE SECONDS_TO_RUN
readonly SERIAL="$1"
readonly ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
readonly PACKAGE=dev.sewellzhong.r1probe
readonly DEVICE=com.phicomm.speaker.device
readonly PLAYER=com.phicomm.speaker.player
readonly EVIDENCE="$ROOT/test-results/$(date +%Y-%m-%dT%H%M%S)-r1-sample01/stage1/alexa-kws/isolation"
adb_target() { timeout --foreground 30s adb -s "$SERIAL" "$@" </dev/null; }
[[ "$(adb_target shell getprop ro.product.device | tr -d '\r')" == rk322x_echo ]]
[[ "$(adb_target shell getprop ro.build.version.sdk | tr -d '\r')" == 22 ]]
[[ "$(adb_target shell getprop ro.build.version.incremental | tr -d '\r')" == 3448 ]]
mkdir -p "$EVIDENCE"
printf 'mode=%s\nduration_seconds=%s\naudio_retained=false\n' "$MODE" "$SECONDS_TO_RUN" > "$EVIDENCE/session-plan.txt"
(cd "$ROOT/test-results/2026-09-01-r1-sample01/stage0/current-installed-apps" && sha256sum -c SHA256SUMS) > "$EVIDENCE/backup-check.txt"
adb_target shell ps > "$EVIDENCE/before-ps.txt"
# This runner restores the running overlay state, so reject a different initial state.
grep -q "$DEVICE" "$EVIDENCE/before-ps.txt"
grep -q "$PLAYER" "$EVIDENCE/before-ps.txt"
finish() {
    local status=$?
    trap - EXIT INT TERM
    set +e
    adb_target shell am force-stop "$PACKAGE" > "$EVIDENCE/probe-stop.txt" 2>&1
    adb_target shell am startservice -n "$PLAYER/.EchoService" > "$EVIDENCE/restore-player.txt" 2>&1
    adb_target shell am startservice -n "$DEVICE/.ui.service.WindowsService" > "$EVIDENCE/restore-device.txt" 2>&1
    adb_target shell am start -n "$DEVICE/.ui.MainActivity" > "$EVIDENCE/restore-activity.txt" 2>&1
    local restored=false
    for attempt in {1..10}; do
        adb_target shell ps > "$EVIDENCE/restored-ps.txt"
        if grep -q "$DEVICE" "$EVIDENCE/restored-ps.txt" && grep -q "$PLAYER" "$EVIDENCE/restored-ps.txt"; then
            restored=true
            break
        fi
        sleep 1
    done
    [[ "$restored" == true ]] || status=1
    printf 'exit_status=%s\nservices_restored=%s\naudio_retained=false\n' "$status" "$restored" > "$EVIDENCE/RESULT.txt"
    (cd "$EVIDENCE" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)
    echo "Isolation evidence: $EVIDENCE"
    exit "$status"
}
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
adb_target shell am force-stop "$PACKAGE"
adb_target shell am start -W -n "$PACKAGE/.MainActivity" --es probe_nonce alexa-isolation > "$EVIDENCE/foreground.txt"
adb_target shell am force-stop "$DEVICE"
adb_target shell am force-stop "$PLAYER"
sleep 1
adb_target shell ps > "$EVIDENCE/isolated-ps.txt"
if grep -Eq "$DEVICE|$PLAYER" "$EVIDENCE/isolated-ps.txt"; then
    echo "Audio overlay restarted; aborting." >&2
    exit 1
fi
python3 "$ROOT/tools/kws/run-r1-alexa-listen.py" "$SERIAL" --confirm-device r1-sample01 --seconds "$SECONDS_TO_RUN" | tee "$EVIDENCE/listen.txt"
if [[ "$MODE" != smoke ]]; then
    exit 0
fi
# Explicit stop and duplicate-start checks on the same service after a completed session.
readonly NONCE="alexa-lifecycle-$(date +%s%N)"
adb_target shell am startservice -n "$PACKAGE/.AlexaListeningService" --es probe_nonce "$NONCE" --ei duration_seconds 60 > "$EVIDENCE/lifecycle-start.txt"
sleep 3
adb_target shell am startservice -n "$PACKAGE/.AlexaListeningService" --es probe_nonce "$NONCE-duplicate" > "$EVIDENCE/duplicate-start.txt"
adb_target shell am startservice -n "$PACKAGE/.AlexaListeningService" -a stop > "$EVIDENCE/explicit-stop.txt"
sleep 2
adb_target logcat -d -s R1Audio:V '*:S' > "$EVIDENCE/lifecycle-logcat.txt"
grep -F "R1_ALEXA_STOPPED nonce=$NONCE " "$EVIDENCE/lifecycle-logcat.txt"
grep -F 'R1_ALEXA_REJECTED reason=already_running' "$EVIDENCE/lifecycle-logcat.txt"
adb_target shell dumpsys activity services "$PACKAGE/.AlexaListeningService" > "$EVIDENCE/services-after-stop.txt"
if grep -q 'isForeground=true' "$EVIDENCE/services-after-stop.txt"; then
    echo "Listener still foreground after stop" >&2
    exit 1
fi
