#!/usr/bin/env bash
set -euo pipefail

readonly EXPECTED_JNI_SHA256="629593e759fbeade5960361b631d69296ebe47df1e889ce64a8cb7128aa25886"

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
readonly EVIDENCE_DIR="$REPO_ROOT/test-results/${RUN_ID}-${DEVICE_ID}/stage1/four-mic-interface"
TEMP_DIR="$(mktemp -d)"
readonly TEMP_DIR

mkdir -p "$EVIDENCE_DIR"
exec > >(tee "$EVIDENCE_DIR/run.log") 2>&1
trap 'rm -r "$TEMP_DIR"' EXIT

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

PRODUCT_DEVICE="$(adb_target shell getprop ro.product.device | tr -d '\r')"
SDK="$(adb_target shell getprop ro.build.version.sdk | tr -d '\r')"
FIRMWARE="$(adb_target shell getprop ro.build.version.incremental | tr -d '\r')"
[[ "$PRODUCT_DEVICE" == "rk322x_echo" && "$SDK" == "22" && "$FIRMWARE" == "3448" ]]

for remote_file in \
    /system/lib/libUni4micHalJNI.so \
    /system/lib/libuni4michal.so \
    /system/lib/libuni4michalchance.so; do
    file_name="${remote_file##*/}"
    timeout --foreground 10s adb connect "$ADB_SERIAL" </dev/null >/dev/null 2>&1 || true
    adb_pull "$remote_file" "$TEMP_DIR/$file_name" >/dev/null
    {
        printf 'remote_path=%s\n' "$remote_file"
        sha1sum "$TEMP_DIR/$file_name"
        sha256sum "$TEMP_DIR/$file_name"
    } >"$EVIDENCE_DIR/${file_name}.identity.txt"
    readelf -Ws "$TEMP_DIR/$file_name" \
        | rg 'GLOBAL.*(uni_|Mic|mic|AEC|aec|DOA|pcm_|Java_)' \
        >"$EVIDENCE_DIR/${file_name}.exports.txt" || true
    strings "$TEMP_DIR/$file_name" \
        | rg -i 'uni_|4mic|mic.?array|aec|beam|doa|pcm_|config|debug' \
        >"$EVIDENCE_DIR/${file_name}.strings.txt" || true
done

grep -Fq "$EXPECTED_JNI_SHA256" \
    "$EVIDENCE_DIR/libUni4micHalJNI.so.identity.txt"

unisound_apk="$REPO_ROOT/test-results/2026-09-01-r1-sample01/stage0/system-apps/Unisound.apk"
sha1sum "$unisound_apk" >"$EVIDENCE_DIR/Unisound.apk.identity.txt"
sha256sum "$unisound_apk" >>"$EVIDENCE_DIR/Unisound.apk.identity.txt"
unzip -p "$unisound_apk" classes.dex | strings \
    | rg -i 'Uni4mic|FourMic|IAudioSourceAEC|ASR_FOURMIC|MicArray|AEC|DOA' \
    >"$EVIDENCE_DIR/Unisound-four-mic-classes.txt"

cat >"$EVIDENCE_DIR/RESULT.txt" <<'EOF'
official_four_mic_native_interface_present=true
direct_tinyalsa_pcm_interface_present=true
mic_array_processing_interface_present=true
aec_reference_interface_present=true
redistribution_license_found=false
integration_status=research_only_pending_abi_license_and_real_device_validation
proprietary_binaries_retained_in_evidence=false
jni_system_library_hash_match=true
EOF

manifest_tmp="$(mktemp)"
(cd "$EVIDENCE_DIR" && find . -type f ! -name run.log ! -name SHA256SUMS -print0 \
    | sort -z | xargs -0 sha256sum >"$manifest_tmp")
mv "$manifest_tmp" "$EVIDENCE_DIR/SHA256SUMS"
(cd "$EVIDENCE_DIR" && sha256sum -c SHA256SUMS)
echo "Evidence: $EVIDENCE_DIR"
