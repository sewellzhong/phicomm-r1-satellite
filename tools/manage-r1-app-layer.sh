#!/usr/bin/env bash
# shellcheck disable=SC2317 # Rollback is invoked indirectly by EXIT traps.
set -euo pipefail

readonly DEVICE_PACKAGE="com.phicomm.speaker.device"
readonly PLAYER_PACKAGE="com.phicomm.speaker.player"
readonly EXPECTED_DEVICE_SHA256="d98ff6aeab80c562498f42b45ddf4bb58eae318d64e47cecca7355799cee6542"
readonly EXPECTED_PLAYER_SHA256="eee63585effda9697c6fb1da5ae82ddf0fc41566aa8462841e407f15aae6fdc8"

usage() {
    cat >&2 <<'EOF'
Usage:
  manage-r1-app-layer.sh status <adb-serial>
  manage-r1-app-layer.sh disable <adb-serial> --confirm-device <device-id> --replacement-package <package>
  manage-r1-app-layer.sh restore <adb-serial> --confirm-device <device-id>

This tool never uninstalls packages. The disable action is intentionally gated.
EOF
    exit 64
}

[[ $# -ge 2 ]] || usage
readonly ACTION="$1"
readonly ADB_SERIAL="$2"
shift 2

confirm_device=""
replacement_package=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --confirm-device)
            [[ $# -ge 2 ]] || usage
            confirm_device="$2"
            shift 2
            ;;
        --replacement-package)
            [[ $# -ge 2 ]] || usage
            replacement_package="$2"
            shift 2
            ;;
        *) usage ;;
    esac
done
[[ "$ACTION" == "status" || "$ACTION" == "disable" || "$ACTION" == "restore" ]] || usage

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly REPO_ROOT
readonly DEVICE_ID="${R1_DEVICE_ID:-r1-sample01}"
RUN_ID="$(date +%Y-%m-%dT%H%M%S)"
readonly RUN_ID
readonly EVIDENCE_DIR="$REPO_ROOT/test-results/${RUN_ID}-${DEVICE_ID}/stage1/app-layer-${ACTION}"
TEMP_DIR="$(mktemp -d)"
readonly TEMP_DIR
change_started=false
completed=false

mkdir -p "$EVIDENCE_DIR"
exec > >(tee "$EVIDENCE_DIR/run.log") 2>&1

adb_target() {
    adb -s "$ADB_SERIAL" "$@"
}

pm_command() {
    local command_text="$1"
    adb_target shell "CLASSPATH=/system/framework/pm.jar app_process /system/bin com.android.commands.pm.Pm $command_text"
}

start_current_services() {
    adb connect "$ADB_SERIAL" >/dev/null 2>&1 || true
    adb_target shell am startservice -n "$PLAYER_PACKAGE/.EchoService" >/dev/null 2>&1 || true
    adb_target shell am startservice -n "$DEVICE_PACKAGE/.ui.service.WindowsService" >/dev/null 2>&1 || true
    adb_target shell am start -n "$DEVICE_PACKAGE/.ui.MainActivity" >/dev/null 2>&1 || true
}

restore_packages() {
    adb connect "$ADB_SERIAL" >/dev/null 2>&1 || true
    pm_command "enable --user 0 $PLAYER_PACKAGE" >/dev/null 2>&1 || true
    adb connect "$ADB_SERIAL" >/dev/null 2>&1 || true
    pm_command "enable --user 0 $DEVICE_PACKAGE" >/dev/null 2>&1 || true
    start_current_services
}

snapshot() {
    local prefix="$1"
    adb connect "$ADB_SERIAL" >/dev/null 2>&1 || true
    adb_target shell ps >"$EVIDENCE_DIR/${prefix}-ps.txt" 2>&1 || true
    adb_target shell dumpsys package "$DEVICE_PACKAGE" >"$EVIDENCE_DIR/${prefix}-device-package.txt" 2>&1 || true
    adb_target shell dumpsys package "$PLAYER_PACKAGE" >"$EVIDENCE_DIR/${prefix}-player-package.txt" 2>&1 || true
    [[ -z "$replacement_package" ]] || adb_target shell dumpsys package "$replacement_package" \
        >"$EVIDENCE_DIR/${prefix}-replacement-package.txt" 2>&1 || true
}

finish() {
    local status="$1"
    trap - EXIT
    set +e
    if [[ "$change_started" == true && "$completed" != true ]]; then
        echo "Incomplete app-layer change detected; restoring current packages." >&2
        restore_packages
        snapshot rollback-restored
        status=1
    fi
    {
        printf 'action=%s\n' "$ACTION"
        printf 'status=%s\n' "$status"
        printf 'change_started=%s\n' "$change_started"
        printf 'completed=%s\n' "$completed"
        printf 'uninstall_performed=false\n'
    } >"$EVIDENCE_DIR/RESULT.txt"
    local manifest_tmp
    manifest_tmp="$(mktemp)"
    (cd "$EVIDENCE_DIR" && find . -type f ! -name run.log ! -name SHA256SUMS -print0 \
        | sort -z | xargs -0 sha256sum >"$manifest_tmp")
    mv "$manifest_tmp" "$EVIDENCE_DIR/SHA256SUMS"
    (cd "$EVIDENCE_DIR" && sha256sum -c SHA256SUMS)
    rm -r "$TEMP_DIR"
    echo "Evidence: $EVIDENCE_DIR"
    exit "$status"
}
trap 'finish $?' EXIT

PRODUCT_DEVICE="$(adb_target shell getprop ro.product.device | tr -d '\r')"
SDK="$(adb_target shell getprop ro.build.version.sdk | tr -d '\r')"
FIRMWARE="$(adb_target shell getprop ro.build.version.incremental | tr -d '\r')"
[[ "$PRODUCT_DEVICE" == "rk322x_echo" && "$SDK" == "22" && "$FIRMWARE" == "3448" ]] || {
    echo "Refusing app-layer operation: unexpected target identity" >&2
    exit 65
}
snapshot before

if [[ "$ACTION" == "status" ]]; then
    completed=true
    echo "Status captured. No package state was changed."
    exit 0
fi

[[ "$confirm_device" == "$DEVICE_ID" ]] || {
    echo "Refusing $ACTION: --confirm-device must equal $DEVICE_ID" >&2
    exit 65
}

(cd "$REPO_ROOT/test-results/2026-09-01-r1-sample01/stage0/current-installed-apps" \
    && sha256sum -c SHA256SUMS)
for package_spec in \
    "$DEVICE_PACKAGE:$EXPECTED_DEVICE_SHA256" \
    "$PLAYER_PACKAGE:$EXPECTED_PLAYER_SHA256"; do
    IFS=: read -r package_name expected_hash <<<"$package_spec"
    package_dump="$TEMP_DIR/${package_name}.verify.dump"
    adb_target shell dumpsys package "$package_name" >"$package_dump"
    code_path="$(sed -n 's/^[[:space:]]*codePath=//p' "$package_dump" | head -1 | tr -d '\r')"
    [[ "$code_path" == /data/app/* ]] || {
        echo "Refusing $ACTION: active overlay path is unexpected for $package_name" >&2
        exit 65
    }
    remote_apk="$code_path/base.apk"
    local_apk="$TEMP_DIR/${package_name}.apk"
    adb connect "$ADB_SERIAL" >/dev/null 2>&1 || true
    adb_target pull "$remote_apk" "$local_apk" >/dev/null
    actual_hash="$(sha256sum "$local_apk" | awk '{print $1}')"
    [[ "$actual_hash" == "$expected_hash" ]] || {
        echo "Refusing $ACTION: live overlay hash changed for $package_name" >&2
        exit 65
    }
done

if [[ "$ACTION" == "restore" ]]; then
    change_started=true
    restore_packages
    sleep 2
    snapshot restored
    adb_target shell ps | tr -d '\r' | grep -q "$DEVICE_PACKAGE"
    adb_target shell ps | tr -d '\r' | grep -q "$PLAYER_PACKAGE"
    completed=true
    echo "Current third-party application layer restored."
    exit 0
fi

[[ -n "$replacement_package" ]] || {
    echo "Refusing disable: --replacement-package is required" >&2
    exit 65
}
replacement_dump="$TEMP_DIR/replacement-package.txt"
adb_target shell dumpsys package "$replacement_package" >"$replacement_dump"
grep -q 'codePath=' "$replacement_dump" || {
    echo "Refusing disable: replacement package is not installed" >&2
    exit 65
}
adb_target shell ps | tr -d '\r' | grep -q "$replacement_package" || {
    echo "Refusing disable: replacement package is not running" >&2
    exit 65
}

R1_DEVICE_ID="$DEVICE_ID" "$REPO_ROOT/tools/audit-r1-audio-provenance.sh" "$ADB_SERIAL"
change_started=true
pm_command "disable-user --user 0 $DEVICE_PACKAGE" | tee "$EVIDENCE_DIR/disable-device.txt"
adb connect "$ADB_SERIAL" >/dev/null 2>&1 || true
pm_command "disable-user --user 0 $PLAYER_PACKAGE" | tee "$EVIDENCE_DIR/disable-player.txt"
sleep 2
snapshot disabled
if adb_target shell ps | tr -d '\r' | grep -q "$DEVICE_PACKAGE" \
    || adb_target shell ps | tr -d '\r' | grep -q "$PLAYER_PACKAGE"; then
    echo "Disable verification failed: current audio process still running" >&2
    exit 1
fi
adb_target shell ps | tr -d '\r' | grep -q "$replacement_package" || {
    echo "Replacement package stopped after cutover" >&2
    exit 1
}
completed=true
echo "Current third-party packages disabled; no package was uninstalled."
