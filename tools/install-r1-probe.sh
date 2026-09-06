#!/usr/bin/env bash
set -euo pipefail

readonly PACKAGE_NAME="dev.sewellzhong.r1probe"
readonly COMPONENT_NAME="${PACKAGE_NAME}/.MainActivity"
readonly REMOTE_APK="/data/local/tmp/r1-probe-debug.apk"

usage() {
    echo "Usage: $0 <adb-serial> <apk-path>" >&2
    exit 64
}

[[ $# -eq 2 ]] || usage

readonly ADB_SERIAL="$1"
readonly APK_PATH="$(realpath "$2")"
readonly REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly DEVICE_ID="${R1_DEVICE_ID:-r1-sample01}"
readonly RUN_ID="$(date +%Y-%m-%dT%H%M%S)"
readonly EVIDENCE_DIR="${REPO_ROOT}/test-results/${RUN_ID}-${DEVICE_ID}/stage0/apk-install"

[[ -f "$APK_PATH" ]] || {
    echo "APK not found: $APK_PATH" >&2
    exit 66
}

# Reject public host-only packages before any ADB call or evidence mutation.
python3 - "$APK_PATH" <<'PY_CHECK'
import sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as apk:
    if "assets/HOST_CHECK_ONLY" in apk.namelist():
        raise SystemExit("host_check_apk_not_deployable")
PY_CHECK

mkdir -p "$EVIDENCE_DIR"
exec > >(tee "$EVIDENCE_DIR/install.log") 2>&1

adb_target() {
    adb -s "$ADB_SERIAL" "$@"
}

get_prop() {
    adb_target shell getprop "$1" | tr -d '\r'
}

cleanup() {
    adb_target shell rm -f "$REMOTE_APK" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "Evidence: $EVIDENCE_DIR"
echo "APK SHA-256: $(sha256sum "$APK_PATH")"

readonly PRODUCT_DEVICE="$(get_prop ro.product.device)"
readonly MODEL="$(get_prop ro.product.model)"
readonly SDK="$(get_prop ro.build.version.sdk)"
readonly FIRMWARE="$(get_prop ro.build.version.incremental)"

printf 'Target: serial=%s device=%s model=%s sdk=%s firmware=%s\n' \
    "$ADB_SERIAL" "$PRODUCT_DEVICE" "$MODEL" "$SDK" "$FIRMWARE"

[[ "$PRODUCT_DEVICE" == "rk322x_echo" ]] || {
    echo "Refusing install: unexpected device '$PRODUCT_DEVICE'" >&2
    exit 65
}
[[ "$SDK" == "22" ]] || {
    echo "Refusing install: unexpected API '$SDK'" >&2
    exit 65
}
[[ "$FIRMWARE" == "3448" ]] || {
    echo "Refusing install: unexpected firmware '$FIRMWARE'" >&2
    exit 65
}

set +e
timeout --foreground 15s adb -s "$ADB_SERIAL" install -r "$APK_PATH" \
    >"$EVIDENCE_DIR/standard-install.txt" 2>&1
STANDARD_STATUS=$?
set -e
tail -20 "$EVIDENCE_DIR/standard-install.txt"

if [[ $STANDARD_STATUS -ne 0 ]] || ! grep -q '^Success' "$EVIDENCE_DIR/standard-install.txt"; then
    echo "Standard adb install failed; using explicit API 22 package-manager entrypoint."
    adb_target push "$APK_PATH" "$REMOTE_APK"
    adb_target shell \
        "CLASSPATH=/system/framework/pm.jar app_process /system/bin com.android.commands.pm.Pm install -r $REMOTE_APK" \
        | tee "$EVIDENCE_DIR/fallback-install.txt"
else
    echo "Standard adb install succeeded."
fi

adb_target shell \
    "CLASSPATH=/system/framework/pm.jar app_process /system/bin com.android.commands.pm.Pm list packages" \
    | tr -d '\r' \
    | tee "$EVIDENCE_DIR/packages.txt" \
    | grep -qx "package:${PACKAGE_NAME}"

readonly NONCE="$(date +%s%N)"
adb_target shell am force-stop "$PACKAGE_NAME"
adb_target shell am start -W -n "$COMPONENT_NAME" --es probe_nonce "$NONCE" \
    | tee "$EVIDENCE_DIR/activity-start.txt"
sleep 1
adb_target logcat -d -s R1Probe:I '*:S' \
    | tee "$EVIDENCE_DIR/logcat.txt"
grep -Fq "R1_PROBE_READY nonce=${NONCE}" "$EVIDENCE_DIR/logcat.txt"

echo "R1 probe install and launch verified successfully."
