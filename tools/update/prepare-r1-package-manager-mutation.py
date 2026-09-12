#!/usr/bin/env python3
"""Seal a fail-closed R1 package-manager mutation evidence plan.

This tool is deliberately host-only.  It validates the candidate, the exact
installed-version rollback APK, and prior read-only device evidence.  It never
invokes adb or changes the device.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys


DEVICE_ID = "r1-sample01"
PACKAGE_NAME = "dev.sewellzhong.r1probe"
FIRMWARE = "3448"
SDK = "22"
MIN_APK_BYTES = 4096
MAX_APK_BYTES = 64 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
BADGING_RE = re.compile(
    r"^package: name='([^']+)' versionCode='([0-9]+)' versionName='([^']*)'"
)
CERT_RE = re.compile(
    r"^Signer #([0-9]+) certificate SHA-256 digest: ([0-9a-f]{64})$", re.MULTILINE
)


class PlanError(RuntimeError):
    pass


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_regular_private_input(path, label):
    path = Path(path)
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise PlanError(f"{label}_not_regular_file")
    if not MIN_APK_BYTES <= info.st_size <= MAX_APK_BYTES:
        raise PlanError(f"{label}_size_invalid")
    return path.resolve(strict=True), info.st_size


def run_tool(tool, arguments, runner=subprocess.run):
    completed = runner(
        [str(tool), *map(str, arguments)], capture_output=True, text=True,
        timeout=30, check=False, shell=False,
    )
    if completed.returncode != 0:
        raise PlanError(f"apk_inspection_failed:{Path(tool).name}:{completed.returncode}")
    return completed.stdout.replace("\r", "")


def inspect_apk(path, aapt, apksigner, runner=subprocess.run):
    badging = run_tool(aapt, ["dump", "badging", path], runner)
    first = badging.splitlines()[0] if badging else ""
    match = BADGING_RE.match(first)
    if not match:
        raise PlanError("apk_badging_invalid")
    certs = run_tool(apksigner, ["verify", "--print-certs", path], runner)
    signers = CERT_RE.findall(certs)
    if len(signers) != 1 or signers[0][0] != "1":
        raise PlanError("apk_single_signer_required")
    with path.open("rb") as stream:
        # Host-check artifacts include this literal ZIP entry name.  Searching
        # the bounded APK avoids importing zip metadata before signature verify.
        if b"assets/HOST_CHECK_ONLY" in stream.read():
            raise PlanError("host_check_apk_not_deployable")
    return {
        "package_name": match.group(1),
        "version_code": int(match.group(2)),
        "version_name": match.group(3),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "signer_sha256": signers[0][1],
    }


def load_device_evidence(path):
    path = Path(path).resolve(strict=True)
    value = json.loads(path.read_text())
    if value.get("status") not in {"pass", "pass_with_access_limits"}:
        raise PlanError("device_evidence_not_passed")
    if value.get("operation") != "read_only_package_manager_evidence":
        raise PlanError("device_evidence_operation_invalid")
    if value.get("device_id") != DEVICE_ID or value.get("package_name") != PACKAGE_NAME:
        raise PlanError("device_evidence_target_invalid")
    identity = value.get("identity", {})
    if identity.get("ro.build.version.incremental") != FIRMWARE:
        raise PlanError("device_evidence_firmware_invalid")
    if identity.get("ro.build.version.sdk") != SDK:
        raise PlanError("device_evidence_sdk_invalid")
    if value.get("adb_context", {}).get("selinux") != "Enforcing":
        raise PlanError("device_evidence_selinux_invalid")
    package = value.get("installed_package", {})
    installed_hash = package.get("apk_sha256")
    if not isinstance(package.get("version_code"), int) or not SHA256_RE.fullmatch(
        installed_hash or ""
    ):
        raise PlanError("device_evidence_installed_identity_incomplete")
    return path, value


def resolve_tool(value, label):
    candidate = shutil.which(str(value)) if Path(value).name == str(value) else str(value)
    if not candidate:
        raise FileNotFoundError(value)
    path = Path(candidate).resolve(strict=True)
    if not path.is_file():
        raise PlanError(f"{label}_invalid")
    return path


def write_json_exclusive(path, value):
    payload = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def prepare_plan(candidate, rollback, evidence, output, confirm_device, aapt,
                 apksigner, runner=subprocess.run):
    if confirm_device != DEVICE_ID:
        raise PlanError("device_confirmation_required")
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    candidate, _ = require_regular_private_input(candidate, "candidate")
    rollback, _ = require_regular_private_input(rollback, "rollback")
    evidence_path, device = load_device_evidence(evidence)
    aapt = resolve_tool(aapt, "aapt")
    apksigner = resolve_tool(apksigner, "apksigner")
    candidate_info = inspect_apk(candidate, aapt, apksigner, runner)
    rollback_info = inspect_apk(rollback, aapt, apksigner, runner)
    installed = device["installed_package"]

    if candidate_info["package_name"] != PACKAGE_NAME:
        raise PlanError("candidate_package_mismatch")
    if rollback_info["package_name"] != PACKAGE_NAME:
        raise PlanError("rollback_package_mismatch")
    if rollback_info["version_code"] != installed["version_code"]:
        raise PlanError("rollback_version_not_current")
    if rollback_info["sha256"] != installed["apk_sha256"]:
        raise PlanError("rollback_hash_not_current")
    if candidate_info["version_code"] <= installed["version_code"]:
        raise PlanError("candidate_version_not_newer")
    if candidate_info["signer_sha256"] != rollback_info["signer_sha256"]:
        raise PlanError("candidate_signer_mismatch")

    sealed = {
        "schema_version": 1,
        "operation": "package_manager_upgrade_and_explicit_downgrade_evidence",
        "device_id": DEVICE_ID,
        "firmware": FIRMWARE,
        "package_name": PACKAGE_NAME,
        "adb_serial": device.get("adb_serial"),
        "device_evidence": {
            "path": str(evidence_path),
            "sha256": sha256_file(evidence_path),
            "status": device["status"],
            "fingerprint": device.get("identity", {}).get("ro.build.fingerprint"),
        },
        "candidate": {"path": str(candidate), **candidate_info},
        "rollback": {"path": str(rollback), **rollback_info},
        "execution_contract": {
            "default_mode": "no_device_mutation",
            "required_live_checks": [
                "same_adb_serial_and_3448_identity", "selinux_enforcing",
                "installed_version_and_hash_equal_rollback",
                "candidate_and_rollback_hashes_recomputed",
            ],
            "ordered_steps": [
                "capture_before_identity_hash_and_avc",
                "stage_candidate_to_fixed_private_path",
                "invoke_fixed_package_manager_upgrade_argv",
                "capture_upgrade_return_identity_hash_and_avc",
                "stage_rollback_to_fixed_private_path",
                "invoke_fixed_package_manager_downgrade_argv",
                "capture_rollback_return_identity_hash_and_avc",
                "require_exact_rollback_version_hash_and_signer",
                "remove_staged_files",
            ],
            "stop_conditions": [
                "identity_or_hash_changed", "candidate_or_rollback_revalidation_failed",
                "upgrade_not_independently_observed", "rollback_not_independently_observed",
                "unexpected_reboot_or_selinux_state", "unbounded_or_unexpected_package_manager_output",
            ],
            "success_boundary": "backend_evidence_only_not_ota_delivery",
        },
    }
    canonical = json.dumps(sealed, sort_keys=True, separators=(",", ":")).encode()
    plan_id = hashlib.sha256(canonical).hexdigest()
    sealed["plan_id"] = plan_id
    sealed["execution_confirmation"] = (
        f"{DEVICE_ID}:{FIRMWARE}:v{rollback_info['version_code']}->"
        f"v{candidate_info['version_code']}->v{rollback_info['version_code']}:"
        f"{plan_id[:16]}"
    )
    sealed["created_at"] = datetime.now(timezone.utc).isoformat()
    write_json_exclusive(output, sealed)
    return sealed


def parser():
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--candidate", required=True, type=Path)
    value.add_argument("--rollback", required=True, type=Path)
    value.add_argument("--device-evidence", required=True, type=Path)
    value.add_argument("--output", required=True, type=Path)
    value.add_argument("--confirm-device", required=True)
    value.add_argument("--aapt", default="aapt", type=Path)
    value.add_argument("--apksigner", default="apksigner", type=Path)
    return value


def main():
    args = parser().parse_args()
    try:
        result = prepare_plan(
            args.candidate, args.rollback, args.device_evidence, args.output,
            args.confirm_device, args.aapt, args.apksigner,
        )
    except (PlanError, FileExistsError, FileNotFoundError, json.JSONDecodeError) as error:
        print(f"stopped: {error}", file=sys.stderr)
        return 2
    print(json.dumps({
        "status": "sealed_no_device_mutation",
        "plan_id": result["plan_id"],
        "execution_confirmation": result["execution_confirmation"],
        "output": str(args.output),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
