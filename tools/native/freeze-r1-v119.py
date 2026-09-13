#!/usr/bin/env python3
"""Freeze the exact v119 device/boot/source tuple before core regression."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = "dev.sewellzhong.r1probe"
FINGERPRINT = "Android/rk322x_echo/rk322x_echo:5.1.1/LMY49F/3448:user/release-keys"
APK_SHA256 = "b1368d2bed2c1f0f8f210628ca8c215a955550f274f96f623c8483e50cb2b9c7"
SIGNER_SHA256 = "0be7a3643442658354c185ec53cb50e73bc1516a56f2760ca46f2c932c1d2639"
BOOT_SHA256 = "fce6776789944d086421eb72799043649d9ba72c80d1e4a3058e3d5bc3d3837b"
SOURCE_COMMIT = "e670f86f508eb155632d3d90efb1057420e01d6c"


def run(command, timeout=60):
    return subprocess.run(command, check=True, capture_output=True, text=True,
                          timeout=timeout).stdout.strip()


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def require(value, message):
    if not value:
        raise RuntimeError(message)


def freeze(args):
    require(args.confirm_device == "r1-sample01", "device_confirmation_required")
    adb = ["adb", "-s", args.serial]
    require(run(adb + ["shell", "getprop", "ro.build.fingerprint"]) == FINGERPRINT,
            "device_fingerprint_mismatch")
    require(run(adb + ["shell", "getenforce"]) == "Enforcing",
            "selinux_not_enforcing")
    require(run(adb + ["shell", "getprop", "init.svc.r1_update"]) == "running",
            "update_supervisor_not_running")
    require(run(adb + ["shell", "getprop", "init.svc.r1_factory_audio"]) == "running",
            "factory_audio_agent_not_running")
    require(run(adb + ["shell", "getprop", "init.svc.r1_update_fault"]) == "",
            "temporary_fault_helper_still_installed")
    package = run(adb + ["shell", "dumpsys", "package", PACKAGE])
    require(re.search(r"\bversionCode=119\b", package), "installed_version_not_119")
    paths = re.findall(r"\bcodePath=(/data/app/dev\.sewellzhong\.r1probe-[0-9]+)", package)
    require(len(set(paths)) == 1, "installed_apk_path_ambiguous")
    remote_apk = paths[0] + "/base.apk"

    boot_readback = Path(args.boot_readback).resolve(strict=True)
    require(not boot_readback.is_symlink() and boot_readback.is_file(),
            "boot_readback_invalid")
    require(boot_readback.stat().st_size == 12 * 1024 * 1024,
            "boot_readback_size_invalid")
    require(digest(boot_readback) == BOOT_SHA256, "production_boot_hash_mismatch")
    require(run(["git", "rev-parse", SOURCE_COMMIT], timeout=10) == SOURCE_COMMIT,
            "source_commit_missing")
    changed = run(["git", "diff", "--name-only", SOURCE_COMMIT, "--",
                   "android/r1-probe", "integrations/home_assistant"], timeout=10)
    require(changed == "", "frozen_product_sources_changed")

    with tempfile.TemporaryDirectory(prefix="r1-v119-freeze-") as directory:
        local_apk = Path(directory) / "base.apk"
        run(adb + ["pull", remote_apk, str(local_apk)], timeout=180)
        require(digest(local_apk) == APK_SHA256, "installed_apk_hash_mismatch")
        apksigner = Path(args.apksigner).resolve(strict=True)
        certificates = run([str(apksigner), "verify", "--print-certs", str(local_apk)])
        match = re.search(r"Signer #1 certificate SHA-256 digest: ([0-9a-f]{64})",
                          certificates)
        require(match and match.group(1) == SIGNER_SHA256,
                "installed_signer_mismatch")
        require("Signer #2" not in certificates, "multiple_signers_rejected")

    status_text = run(["python3", str(ROOT / "tools/native/manage-r1-native.py"),
                       "status", args.serial])
    status = json.loads(status_text)
    require(status.get("status") == "listening"
            and status.get("audio_opened") is True
            and status.get("audio_blocked") is False
            and status.get("factory_isolation") == "packages_hidden"
            and status.get("connections") == 1
            and status.get("failures") == 0
            and status.get("last_error") is None,
            "satellite_health_not_ready")

    result = {
        "schema": 1,
        "status": "frozen_for_v103_v119_core_regression",
        "recorded_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "device": "r1-sample01",
        "serial": args.serial,
        "fingerprint": FINGERPRINT,
        "selinux": "Enforcing",
        "source_commit": SOURCE_COMMIT,
        "apk": {"version_code": 119, "sha256": APK_SHA256,
                "signer_sha256": SIGNER_SHA256, "installed_path": remote_apk},
        "boot": {"partition": "boot", "bytes": 12 * 1024 * 1024,
                 "sha256": BOOT_SHA256},
        "services": {"update_supervisor": "running",
                     "factory_audio_agent": "running",
                     "temporary_fault_helper": "absent"},
        "satellite": {key: status.get(key) for key in
                      ("status", "audio_opened", "audio_blocked",
                       "factory_isolation", "connections", "failures")},
        "update_failure_gates": {
            "supervisor_crash_during_install": "pass",
            "rollback_install_failure": "pass",
            "failed_state_survives_restart": "pass",
        },
        "ha_core": "2026.8.2",
        "r1_input_guard": "0.14.0",
        "credentials_saved": False,
    }
    destination = Path(args.output).resolve()
    evidence_root = (ROOT / "test-results").resolve()
    require(evidence_root in destination.parents, "output_must_be_under_test_results")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    os.chmod(destination, 0o600)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("serial")
    parser.add_argument("--confirm-device", required=True)
    parser.add_argument("--boot-readback", required=True)
    parser.add_argument("--apksigner", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        result = freeze(args)
        print(json.dumps({"status": result["status"],
                          "apk_sha256": result["apk"]["sha256"],
                          "boot_sha256": result["boot"]["sha256"]}, sort_keys=True))
    except (RuntimeError, OSError, ValueError, json.JSONDecodeError,
            subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        print("R1 v119 freeze refused: " + str(error), file=__import__("sys").stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
