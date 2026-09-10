#!/usr/bin/env python3
"""One-shot Android -> Loader -> Maskrom transition for r1-sample01.

This narrowly scoped tool changes only volatile boot mode.  It exposes no
loader download, storage read/write, erase, or arbitrary RockUSB command.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


DEVICE_ID = "r1-sample01"
ADB_SERIAL = "CBEAU1116K01314"
VID_PID = "2207:320b"
RKDEVELOPTOOL_SHA256 = "f654a31633ddc83411b19405e8c4afb5fb024f1d869f6a86b4ab0a5bae71e7b4"
EXPECTED_IDENTITY = {
    "ro.product.device": "rk322x_echo",
    "ro.hardware": "rk30board",
    "ro.build.version.incremental": "3448",
    "ro.build.version.release": "5.1.1",
    "ro.build.version.sdk": "22",
    "ro.build.fingerprint": "Android/rk322x_echo/rk322x_echo:5.1.1/LMY49F/3448:user/release-keys",
}


class TransitionError(RuntimeError):
    pass


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def write_json_exclusive(path, value):
    payload = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
    except Exception:
        Path(path).unlink(missing_ok=True)
        raise


def rockusb_devices(sysfs_root=Path("/sys/bus/usb/devices")):
    devices = []
    for entry in sorted(sysfs_root.iterdir()) if sysfs_root.is_dir() else []:
        try:
            vendor = (entry / "idVendor").read_text().strip().lower()
            product = (entry / "idProduct").read_text().strip().lower()
        except (FileNotFoundError, OSError):
            continue
        if f"{vendor}:{product}" != VID_PID:
            continue
        version = (entry / "version").read_text().strip()
        devices.append({
            "sysfs_name": entry.name,
            "vid_pid": VID_PID,
            "usb_version": version,
            "mode": {"2.00": "Maskrom", "2.01": "Loader"}.get(version, "Unknown"),
        })
    return devices


def require_mode(expected, device_provider=rockusb_devices):
    devices = device_provider()
    if len(devices) != 1:
        raise TransitionError(f"expected_one_rockusb_device:found_{len(devices)}")
    device = devices[0]
    expected_version = "2.01" if expected == "Loader" else "2.00"
    if device.get("mode") != expected or device.get("usb_version") != expected_version:
        raise TransitionError(f"expected_{expected.lower()}:{device.get('mode')}:{device.get('usb_version')}")
    return device


def wait_for_mode(expected, timeout, device_provider=rockusb_devices,
                  monotonic=time.monotonic, sleeper=time.sleep):
    deadline = monotonic() + timeout
    last_error = None
    while monotonic() < deadline:
        try:
            return require_mode(expected, device_provider)
        except TransitionError as error:
            last_error = error
            sleeper(0.25)
    raise TransitionError(f"{expected.lower()}_enumeration_timeout:{last_error}")


def run_command(argv, timeout, runner=subprocess.run):
    started = time.monotonic()
    completed = runner(
        argv, capture_output=True, text=True, timeout=timeout,
        check=False, shell=False,
    )
    return {
        "arguments": argv[1:],
        "duration_seconds": round(time.monotonic() - started, 3),
        "exit_code": completed.returncode,
        "stdout": completed.stdout.replace("\r", ""),
        "stderr": completed.stderr.replace("\r", ""),
    }


def transition(adb, tool, serial, output_dir, confirm_device, use_sudo=False,
               command_runner=subprocess.run, device_provider=rockusb_devices,
               mode_waiter=wait_for_mode):
    if confirm_device != DEVICE_ID or serial != ADB_SERIAL:
        raise TransitionError("target_confirmation_mismatch")
    adb_path = shutil.which(str(adb)) if Path(adb).name == str(adb) else str(adb)
    if not adb_path:
        raise FileNotFoundError(adb)
    adb = Path(adb_path).resolve(strict=True)
    tool = Path(tool).resolve(strict=True)
    tool_hash = sha256_file(tool)
    if tool_hash != RKDEVELOPTOOL_SHA256:
        raise TransitionError(f"rkdeveloptool_hash_mismatch:{tool_hash}")
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    evidence = {
        "schema_version": 1,
        "device_id": DEVICE_ID,
        "adb_serial": serial,
        "operation": "android-loader-maskrom-transition",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "tool": {"path": str(tool), "sha256": tool_hash},
        "commands": [],
        "status": "running",
    }
    try:
        state = run_command([str(adb), "-s", serial, "get-state"], 10, command_runner)
        evidence["commands"].append(state)
        if state["exit_code"] != 0 or state["stdout"].strip() != "device":
            raise TransitionError("adb_not_ready")
        identity = {}
        for name, expected in EXPECTED_IDENTITY.items():
            record = run_command(
                [str(adb), "-s", serial, "shell", "getprop", name], 10, command_runner
            )
            evidence["commands"].append(record)
            actual = record["stdout"].strip()
            identity[name] = actual
            if record["exit_code"] != 0 or actual != expected:
                raise TransitionError(f"identity_mismatch:{name}:{actual}")
        evidence["android_identity"] = identity
        reboot = run_command([str(adb), "-s", serial, "reboot", "bootloader"], 10, command_runner)
        evidence["commands"].append(reboot)
        if reboot["exit_code"] != 0:
            raise TransitionError("adb_reboot_bootloader_failed")
        evidence["loader_usb"] = mode_waiter("Loader", 20, device_provider=device_provider)

        argv = [str(tool), "reboot-maskrom"]
        if use_sudo:
            argv = [
                "sudo", "--", "/usr/bin/timeout", "--signal=TERM", "--kill-after=2",
                "8", *argv,
            ]
        reset = run_command(argv, 12, command_runner)
        evidence["commands"].append(reset)
        if reset["exit_code"] != 0:
            raise TransitionError(f"reboot_maskrom_failed:{reset['exit_code']}")
        evidence["maskrom_usb"] = mode_waiter("Maskrom", 20, device_provider=device_provider)
        evidence["status"] = "pass"
    except Exception as error:
        evidence["status"] = "stopped"
        evidence["error"] = str(error)
        raise
    finally:
        evidence["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_json_exclusive(output_dir / "mode-transition.json", evidence)
    return evidence


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("to-maskrom", choices=("to-maskrom",))
    root.add_argument("--adb", default="adb")
    root.add_argument("--serial", required=True)
    root.add_argument("--tool", required=True)
    root.add_argument("--output", required=True)
    root.add_argument("--device-id", required=True)
    root.add_argument("--use-sudo", action="store_true")
    return root


def main():
    args = parser().parse_args()
    try:
        result = transition(
            args.adb, args.tool, args.serial, args.output, args.device_id, args.use_sudo
        )
    except (TransitionError, FileNotFoundError, FileExistsError, subprocess.TimeoutExpired) as error:
        print(f"RockUSB transition stopped: {error}", file=sys.stderr)
        return 1
    print(f"RockUSB transition: {result['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
