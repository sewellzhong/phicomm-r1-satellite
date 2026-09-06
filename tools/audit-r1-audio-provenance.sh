#!/usr/bin/env bash
set -euo pipefail

usage() {
    echo "Usage: $0 <adb-serial>" >&2
    exit 64
}

[[ $# -eq 1 ]] || usage
readonly ADB_SERIAL="$1"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly REPO_ROOT
readonly REFERENCE_FILE="$REPO_ROOT/docs/references/r1-3448-provenance.json"
readonly DEVICE_ID="${R1_DEVICE_ID:-r1-sample01}"
RUN_ID="$(date +%Y-%m-%dT%H%M%S)"
readonly RUN_ID
readonly EVIDENCE_DIR="$REPO_ROOT/test-results/${RUN_ID}-${DEVICE_ID}/stage0/provenance"
TEMP_DIR="$(mktemp -d)"
readonly TEMP_DIR

mkdir -p "$EVIDENCE_DIR"
exec > >(tee "$EVIDENCE_DIR/run.log") 2>&1

cleanup() {
    rm -r "$TEMP_DIR"
}
trap cleanup EXIT

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

get_prop() {
    adb_target shell getprop "$1" | tr -d '\r'
}

PRODUCT_DEVICE="$(get_prop ro.product.device)"
SDK="$(get_prop ro.build.version.sdk)"
FIRMWARE="$(get_prop ro.build.version.incremental)"
FINGERPRINT="$(get_prop ro.build.fingerprint)"
KERNEL_VERSION="$(adb_target shell cat /proc/version | tr -d '\r')"
readonly PRODUCT_DEVICE SDK FIRMWARE FINGERPRINT KERNEL_VERSION

[[ "$PRODUCT_DEVICE" == "rk322x_echo" && "$SDK" == "22" && "$FIRMWARE" == "3448" ]] || {
    echo "Refusing provenance audit: unexpected target identity" >&2
    exit 65
}

python3 - "$REFERENCE_FILE" >"$TEMP_DIR/official-files.tsv" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    reference = json.load(source)
for item in reference["official_files"]:
    print("\t".join((item["id"], item["remote_path"], item["ota_target_sha1"],
                     item["known_sha256"])))
PY

: >"$TEMP_DIR/observed.tsv"
official_failures=0
while IFS=$'\t' read -r item_id remote_path expected_sha1 expected_sha256; do
    local_copy="$TEMP_DIR/$item_id"
    timeout --foreground 10s adb connect "$ADB_SERIAL" </dev/null >/dev/null 2>&1 || true
    if adb_pull "$remote_path" "$local_copy" >/dev/null 2>&1; then
        actual_sha1="$(sha1sum "$local_copy" | awk '{print $1}')"
        actual_sha256="$(sha256sum "$local_copy" | awk '{print $1}')"
        status="match"
        if [[ "$actual_sha1" != "$expected_sha1" || "$actual_sha256" != "$expected_sha256" ]]; then
            status="mismatch"
            official_failures=$((official_failures + 1))
        fi
    else
        actual_sha1=""
        actual_sha256=""
        status="missing"
        official_failures=$((official_failures + 1))
    fi
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
        "$item_id" "$remote_path" "$expected_sha1" "$actual_sha1" \
        "$expected_sha256" "$actual_sha256" "$status" >>"$TEMP_DIR/observed.tsv"
done <"$TEMP_DIR/official-files.tsv"

expected_fingerprint="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["source"]["post_build"])' "$REFERENCE_FILE")"
fingerprint_status="match"
if [[ "$FINGERPRINT" != "$expected_fingerprint" ]]; then
    fingerprint_status="mismatch"
    official_failures=$((official_failures + 1))
fi
kernel_status="phicomm_lineage"
if [[ "$KERNEL_VERSION" != *"jenkins@phicomm"* ]]; then
    kernel_status="unverified"
    official_failures=$((official_failures + 1))
fi

python3 - "$REFERENCE_FILE" >"$TEMP_DIR/overlay-files.tsv" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    reference = json.load(source)
for item in reference["current_overlays"]:
    print("\t".join((item["package"], item["expected_sha256"], item["classification"])))
PY

: >"$TEMP_DIR/overlays.tsv"
overlay_warning_count=0
while IFS=$'\t' read -r package_name expected_overlay_sha256 classification; do
    timeout --foreground 10s adb connect "$ADB_SERIAL" </dev/null >/dev/null 2>&1 || true
    package_dump="$TEMP_DIR/${package_name}.dump"
    adb_target shell dumpsys package "$package_name" >"$package_dump"
    code_path="$(sed -n 's/^[[:space:]]*codePath=//p' "$package_dump" | head -1 | tr -d '\r')"
    overlay_status="missing"
    actual_overlay_sha256=""
    if [[ -n "$code_path" ]]; then
        timeout --foreground 10s adb connect "$ADB_SERIAL" </dev/null >/dev/null 2>&1 || true
        if adb_pull "$code_path/base.apk" "$TEMP_DIR/${package_name}.apk" >/dev/null 2>&1; then
            actual_overlay_sha256="$(sha256sum "$TEMP_DIR/${package_name}.apk" | awk '{print $1}')"
            overlay_status="match"
            if [[ "$actual_overlay_sha256" != "$expected_overlay_sha256" ]]; then
                overlay_status="changed"
            fi
        fi
    fi
    if [[ "$overlay_status" != "match" ]]; then
        overlay_warning_count=$((overlay_warning_count + 1))
    fi
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$package_name" "$code_path" \
        "$expected_overlay_sha256" "$actual_overlay_sha256" "$overlay_status" "$classification" \
        >>"$TEMP_DIR/overlays.tsv"
done <"$TEMP_DIR/overlay-files.tsv"

python3 - "$REFERENCE_FILE" "$TEMP_DIR/observed.tsv" "$TEMP_DIR/overlays.tsv" \
    "$EVIDENCE_DIR/report.json" <<PY
import json
import sys

reference_path, observed_path, overlays_path, output_path = sys.argv[1:]
with open(reference_path, encoding="utf-8") as source:
    reference = json.load(source)
files = []
with open(observed_path, encoding="utf-8") as source:
    for line in source:
        item_id, remote_path, expected_sha1, actual_sha1, expected_sha256, actual_sha256, status = line.rstrip("\n").split("\t")
        files.append({
            "id": item_id,
            "remote_path": remote_path,
            "expected_ota_target_sha1": expected_sha1,
            "actual_sha1": actual_sha1,
            "expected_known_sha256": expected_sha256,
            "actual_sha256": actual_sha256,
            "status": status,
        })
overlays = []
with open(overlays_path, encoding="utf-8") as source:
    for line in source:
        package_name, code_path, expected_sha256, actual_sha256, status, classification = line.rstrip("\n").split("\t")
        overlays.append({
            "package": package_name,
            "active_code_path": code_path,
            "expected_sha256": expected_sha256,
            "actual_sha256": actual_sha256,
            "status": status,
            "classification": classification,
        })
report = {
    "device_id": "$DEVICE_ID",
    "serial": "$ADB_SERIAL",
    "identity": {
        "product_device": "$PRODUCT_DEVICE",
        "sdk": "$SDK",
        "firmware": "$FIRMWARE",
        "fingerprint": "$FINGERPRINT",
        "fingerprint_status": "$fingerprint_status",
        "kernel_version": "$KERNEL_VERSION",
        "kernel_status": "$kernel_status",
    },
    "reference": reference["source"],
    "official_files": files,
    "active_application_overlays": overlays,
    "official_failure_count": $official_failures,
    "overlay_warning_count": $overlay_warning_count,
    "conclusion": "official_3448_audio_base_with_third_party_application_overlays" if $official_failures == 0 else "provenance_mismatch",
}
with open(output_path, "w", encoding="utf-8") as output:
    json.dump(report, output, ensure_ascii=False, indent=2, sort_keys=True)
    output.write("\n")
PY

cp "$REFERENCE_FILE" "$EVIDENCE_DIR/reference.json"
{
    printf 'official_failure_count=%s\n' "$official_failures"
    printf 'fingerprint_status=%s\n' "$fingerprint_status"
    printf 'kernel_status=%s\n' "$kernel_status"
    printf 'overlay_warning_count=%s\n' "$overlay_warning_count"
} >"$EVIDENCE_DIR/RESULT.txt"

manifest_tmp="$(mktemp)"
(cd "$EVIDENCE_DIR" && find . -type f ! -name run.log ! -name SHA256SUMS -print0 \
    | sort -z | xargs -0 sha256sum >"$manifest_tmp")
mv "$manifest_tmp" "$EVIDENCE_DIR/SHA256SUMS"
(cd "$EVIDENCE_DIR" && sha256sum -c SHA256SUMS)

echo "Evidence: $EVIDENCE_DIR"
[[ $official_failures -eq 0 && $overlay_warning_count -eq 0 ]]
