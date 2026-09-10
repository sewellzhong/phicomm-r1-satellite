#!/usr/bin/env python3
"""Read-only preflight for the controlled r1-sample01 original audio-chain test."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys


EXPECTED = {
    "/system/lib/libUni4micHalJNI.so": "629593e759fbeade5960361b631d69296ebe47df1e889ce64a8cb7128aa25886",
    "/system/lib/libUniMicArray.so": "bc49e20aa671053932b1cfc21cb1d6492ac428a4c24d5d6cebcddc7f573769b9",
    "/system/lib/libuni4michal.so": "ce49904fd7e82446fed671f9ed8da398480ab7c3263bc6a29aafd0f13c1d504a",
    "/system/lib/libuni4michalchance.so": "24de008fc20cd60111c1ba33fd2743f193f8b5f71a93bcafac13497c8fcd72fb",
}
PACKAGES = ("com.phicomm.speaker.device", "com.phicomm.speaker.player")
SATELLITE = "dev.sewellzhong.r1probe"


def adb(serial, *arguments):
    return subprocess.run(
        ["adb", "-s", serial, *arguments], check=True, capture_output=True, text=True
    ).stdout.replace("\x00", "").strip()


def package_state(serial, package):
    dump = adb(serial, "shell", "dumpsys", "package", package)
    user = re.search(r"User 0:.*?installed=(true|false).*?hidden=(true|false).*?enabled=(\d+)", dump)
    uid = re.search(r"userId=(\d+)", dump)
    if user is None or uid is None:
        raise RuntimeError("package_state_unavailable:" + package)
    return {
        "enabled": int(user.group(3)),
        "hidden": user.group(2) == "true",
        "installed": user.group(1) == "true",
        "uid": int(uid.group(1)),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("serial")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        properties = {
            name: adb(args.serial, "shell", "getprop", name)
            for name in (
                "ro.product.device", "ro.hardware", "ro.build.version.incremental",
                "ro.build.version.sdk", "ro.build.fingerprint", "ro.build.version.security_patch",
            )
        }
        identity_ok = (
            properties["ro.product.device"] == "rk322x_echo"
            and properties["ro.hardware"] == "rk30board"
            and properties["ro.build.version.incremental"] == "3448"
            and properties["ro.build.version.sdk"] == "22"
        )
        hashes = {}
        for path, expected in EXPECTED.items():
            actual = adb(args.serial, "shell", "busybox", "sha256sum", path).split()[0]
            hashes[path.rsplit("/", 1)[-1]] = {
                "actual": actual, "expected": expected, "match": actual == expected
            }
        config = adb(args.serial, "shell", "cat", "/system/usr/uni_4mic_config/pcm_hw_config.txt")
        mic_array = adb(args.serial, "shell", "cat", "/system/usr/uni_4mic_config/MicArrayConfig.ini")
        unisound_config = adb(args.serial, "shell", "cat", "/system/unisound/config/config.mg")
        config_checks = {
            "aec_enabled": "aec_enable=true" in unisound_config,
            "aec_debug_configured": "aec_debug=true" in unisound_config,
            "debug_output_path_present": "debug_file_path /sdcard/unidata/" in config,
            "four_mic_circle_present": "MicNum = 4" in mic_array and "ArrayType = circle" in mic_array,
            "pcm_card_1_device_0_present": "pcm_card 1" in config and "pcm_device 0" in config,
            "two_aec_references_present": "SpeakerNum = 2" in mic_array,
        }
        packages = {package: package_state(args.serial, package) for package in PACKAGES}
        satellite = package_state(args.serial, SATELLITE)
        processes = adb(args.serial, "shell", "ps")
        original_processes_running = any(package in processes for package in PACKAGES)
        ready = (
            identity_ok
            and adb(args.serial, "shell", "getenforce") == "Enforcing"
            and all(item["match"] for item in hashes.values())
            and all(config_checks.values())
            and all(item["hidden"] for item in packages.values())
            and not original_processes_running
            and satellite["uid"] == 10010
        )
        result = {
            "config_checks": config_checks,
            "device": "r1-sample01",
            "identity": properties,
            "identity_match": identity_ok,
            "original_packages": packages,
            "original_processes_running": original_processes_running,
            "satellite": satellite,
            "selinux": adb(args.serial, "shell", "getenforce"),
            "status": "pass" if ready else "fail",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "vendor_hashes": hashes,
        }
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        print(json.dumps({"status": result["status"], "output": str(output)}))
        return 0 if ready else 1
    except (IndexError, OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print("Original-chain preflight failed: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
