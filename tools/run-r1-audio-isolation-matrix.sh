#!/usr/bin/env bash
set -euo pipefail

readonly DEVICE_PACKAGE="com.phicomm.speaker.device"
readonly PLAYER_PACKAGE="com.phicomm.speaker.player"

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
readonly EVIDENCE_DIR="${REPO_ROOT}/test-results/${RUN_ID}-${DEVICE_ID}/stage1/isolation-matrix"
readonly BACKUP_DIR="${REPO_ROOT}/test-results/2026-09-01-r1-sample01/stage0/current-installed-apps"

mkdir -p "$EVIDENCE_DIR"
exec > >(tee "$EVIDENCE_DIR/run.log") 2>&1

adb_target() {
    adb -s "$ADB_SERIAL" "$@"
}

capture_state() {
    local prefix="$1"
    adb_target shell ps >"$EVIDENCE_DIR/${prefix}-ps.txt" 2>&1 || true
    adb_target shell dumpsys activity services "$DEVICE_PACKAGE" \
        >"$EVIDENCE_DIR/${prefix}-device-services.txt" 2>&1 || true
    adb_target shell dumpsys activity services "$PLAYER_PACKAGE" \
        >"$EVIDENCE_DIR/${prefix}-player-services.txt" 2>&1 || true
}

restore_factory_services() {
    adb connect "$ADB_SERIAL" >/dev/null 2>&1 || true
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
    local restored="false"
    if restore_factory_services; then
        restored="true"
    else
        status=1
    fi
    capture_state final-restored
    printf 'script_status=%s\nfactory_services_restored=%s\n' "$status" "$restored" \
        >>"$EVIDENCE_DIR/RESULT.txt"
    local manifest_tmp
    manifest_tmp="$(mktemp)"
    (
        cd "$EVIDENCE_DIR"
        find . -type f ! -name run.log ! -name SHA256SUMS -print0 \
            | sort -z | xargs -0 sha256sum >"$manifest_tmp"
    )
    mv "$manifest_tmp" "$EVIDENCE_DIR/SHA256SUMS"
    (cd "$EVIDENCE_DIR" && sha256sum -c SHA256SUMS)
    echo "Evidence: $EVIDENCE_DIR"
    exit "$status"
}
trap 'finish $?' EXIT

run_scenario() {
    local scenario="$1"
    local stop_package="$2"
    echo "Scenario: $scenario"
    restore_factory_services
    sleep 2
    adb_target shell am force-stop "$stop_package"
    sleep 2
    capture_state "$scenario"

    local expected_running expected_stopped
    if [[ "$stop_package" == "$DEVICE_PACKAGE" ]]; then
        expected_running="$PLAYER_PACKAGE"
        expected_stopped="$DEVICE_PACKAGE"
    else
        expected_running="$DEVICE_PACKAGE"
        expected_stopped="$PLAYER_PACKAGE"
    fi

    local state="stable"
    if adb_target shell ps | tr -d '\r' | grep -q "$expected_stopped"; then
        state="stopped_package_restarted"
    fi
    if ! adb_target shell ps | tr -d '\r' | grep -q "$expected_running"; then
        state="peer_package_not_running"
    fi

    local child_status=125
    if [[ "$state" == "stable" ]]; then
        set +e
        R1_DEVICE_ID="$DEVICE_ID" "$REPO_ROOT/tools/run-r1-audio-probe.sh" "$ADB_SERIAL" \
            >"$EVIDENCE_DIR/${scenario}-audio-probe.log" 2>&1
        child_status=$?
        set -e
    fi
    printf '%s state=%s audio_probe_exit=%s\n' "$scenario" "$state" "$child_status" \
        | tee -a "$EVIDENCE_DIR/RESULT.txt"
}

PRODUCT_DEVICE="$(adb_target shell getprop ro.product.device | tr -d '\r')"
readonly PRODUCT_DEVICE
SDK="$(adb_target shell getprop ro.build.version.sdk | tr -d '\r')"
readonly SDK
FIRMWARE="$(adb_target shell getprop ro.build.version.incremental | tr -d '\r')"
readonly FIRMWARE
[[ "$PRODUCT_DEVICE" == "rk322x_echo" && "$SDK" == "22" && "$FIRMWARE" == "3448" ]]
(cd "$BACKUP_DIR" && sha256sum -c SHA256SUMS)
capture_state initial

run_scenario device-stopped "$DEVICE_PACKAGE"
run_scenario player-stopped "$PLAYER_PACKAGE"

echo "Isolation matrix completed; scenario failures are recorded as evidence, not hidden."
