#!/usr/bin/env python3
"""Probe the stock 3448 vendor debug-file lifecycle without installing or flashing."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import wave


ROOT = Path(__file__).resolve().parents[2]
MANAGER = ROOT / "tools/native/manage-r1-native.py"
PACKAGE = "dev.sewellzhong.r1probe"
COMPONENT = PACKAGE + "/.MainActivity"
EXPECTED_VERSION_CODE = 82
EXPECTED_APK_SHA256 = "b115b5077da502a7fbe9efd8a21e2cee6c2e5ae084e8c176d8ace79d52db1c73"
DEBUG_ROOTS = ("/sdcard/unidata", "/data/unidata")
DEBUG_NAMES = tuple(
    f"{phase}_file_{kind}.wav"
    for phase in ("waking", "waked")
    for kind in ("4mic", "2aec", "out")
)
EXPECTED_CHANNELS = {"4mic": 4, "2aec": 2, "out": 2}


class ProbeError(RuntimeError):
    pass


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def validate_output(path):
    output = Path(path).resolve()
    try:
        output.relative_to(ROOT)
    except ValueError:
        pass
    else:
        raise ProbeError("debug_audio_output_must_be_outside_repository")
    if output.exists():
        raise ProbeError("output_directory_already_exists")
    return output


def parse_package_identity(dump):
    version = re.search(r"\bversionCode=(\d+)\b", dump)
    code_path = re.search(r"^\s*codePath=(/data/app/[^\s]+)$", dump, re.MULTILINE)
    if version is None or code_path is None:
        raise ProbeError("installed_package_identity_unavailable")
    return int(version.group(1)), code_path.group(1) + "/base.apk"


def inspect_wav(path, kind):
    result = {"bytes": Path(path).stat().st_size, "sha256": sha256(path)}
    try:
        with wave.open(str(path), "rb") as audio:
            result.update({
                "channels": audio.getnchannels(),
                "frames": audio.getnframes(),
                "sample_rate_hz": audio.getframerate(),
                "sample_width_bytes": audio.getsampwidth(),
            })
    except (EOFError, wave.Error):
        result["status"] = "invalid_wav"
        return result
    expected_channels = EXPECTED_CHANNELS[kind]
    valid = (
        result["channels"] == expected_channels
        and result["frames"] > 0
        and result["sample_rate_hz"] == 16000
        and result["sample_width_bytes"] == 2
    )
    result["status"] = "pass" if valid else "format_or_payload_mismatch"
    return result


def evaluate_artifacts(artifacts):
    phases = {}
    for phase in ("waking", "waked"):
        phase_items = {
            kind: artifacts.get(f"{phase}_file_{kind}.wav")
            for kind in EXPECTED_CHANNELS
        }
        phases[phase] = {
            "complete": all(
                item is not None and item.get("status") == "pass"
                for item in phase_items.values()
            ),
            "files": phase_items,
        }
    complete_phases = [name for name, value in phases.items() if value["complete"]]
    return {
        "complete_phases": complete_phases,
        "phases": phases,
        "status": "pass" if complete_phases else "no_complete_nonempty_debug_triplet",
    }


class Device:
    def __init__(self, serial):
        self.serial = serial

    def adb(self, *args, timeout=40, check=True):
        result = subprocess.run(
            ["adb", "-s", self.serial, *args], capture_output=True, text=True,
            timeout=timeout, check=False,
        )
        if check and result.returncode != 0:
            raise ProbeError("adb_command_failed:" + args[0])
        return (result.stdout + result.stderr).replace("\r", "").strip()

    def shell(self, command, timeout=40, check=True):
        return self.adb("shell", command, timeout=timeout, check=check)

    def verify(self):
        expected = {
            "ro.product.device": "rk322x_echo",
            "ro.build.version.sdk": "22",
            "ro.build.version.incremental": "3448",
            "ro.build.fingerprint": (
                "Android/rk322x_echo/rk322x_echo:5.1.1/LMY49F/3448:user/release-keys"
            ),
        }
        actual = {key: self.shell("getprop " + key) for key in expected}
        if actual != expected:
            raise ProbeError("unexpected_device_or_firmware")
        return actual

    def package_identity(self):
        dump = self.shell("dumpsys package " + PACKAGE)
        version, apk_path = parse_package_identity(dump)
        if version != EXPECTED_VERSION_CODE:
            raise ProbeError("installed_apk_is_not_v82")
        output = self.shell("busybox sha256sum " + apk_path)
        digest = output.split()[0] if output else ""
        if digest != EXPECTED_APK_SHA256:
            raise ProbeError("installed_v82_apk_hash_mismatch")
        return {"apk_path": apk_path, "sha256": digest, "version_code": version}

    def snapshot(self):
        result = {}
        for root in DEBUG_ROOTS:
            directory = self.shell("ls -ldn " + root, check=False)
            files = {}
            for name in DEBUG_NAMES:
                path = root + "/" + name
                size = self.shell(
                    "if [ -f '" + path + "' ]; then wc -c < '" + path + "'; fi",
                    check=False,
                )
                if size.isdigit():
                    files[name] = int(size)
            result[root] = {"directory_listing": directory, "files": files}
        return result

    def pull(self, remote, local):
        self.adb("pull", remote, str(local), timeout=180)

    def remote_sha256(self, remote):
        output = self.shell("busybox sha256sum '" + remote + "'")
        value = output.split()[0] if output else ""
        if not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ProbeError("remote_debug_sha256_unavailable")
        return value

    def remove(self, remote):
        self.shell("rm -f '" + remote + "'")
        if self.shell("if [ -e '" + remote + "' ]; then echo present; fi", check=False):
            raise ProbeError("remote_debug_cleanup_failed")


def run_manager(action, serial, *extra):
    result = subprocess.run(
        [sys.executable, str(MANAGER), action, serial, *extra],
        capture_output=True, text=True, timeout=60, check=False,
    )
    if result.returncode != 0:
        raise ProbeError("native_" + action + "_failed")
    return json.loads(result.stdout) if result.stdout.strip() else {}


def wait_for_capture(device, nonce, timeline, timeout_seconds=12):
    deadline = time.monotonic() + timeout_seconds
    terminal = ""
    while time.monotonic() < deadline:
        timeline.append({
            "elapsed_ms": int((timeout_seconds - (deadline - time.monotonic())) * 1000),
            "snapshot": device.snapshot(),
        })
        logs = device.adb("logcat", "-d", "-s", "R1Audio:V", "*:S", check=False)
        lines = [line for line in logs.splitlines() if "nonce=" + nonce in line]
        for line in lines:
            if "R1_FOUR_MIC_RECORD_COMPLETE" in line or "R1_FOUR_MIC_RECORD_FAILED" in line:
                terminal = line
        if terminal:
            return terminal
        time.sleep(0.25)
    raise ProbeError("vendor_debug_probe_timeout")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("serial")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--confirm-device", required=True)
    parser.add_argument("--confirm-recording", action="store_true")
    args = parser.parse_args(argv)
    if args.confirm_device != "r1-sample01":
        parser.error("--confirm-device must be r1-sample01")
    if not args.confirm_recording:
        parser.error("--confirm-recording is required")

    output = validate_output(args.output_dir)
    output.mkdir(mode=0o700, parents=True)
    (output / "audio").mkdir(mode=0o700)
    device = Device(args.serial)
    result = {
        "device": "r1-sample01",
        "purpose": "vendor_4mic_2aec_out_permission_lifecycle_and_close_flush_probe",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "failed",
    }
    native_was_listening = False
    capture_started = False
    try:
        result["identity"] = device.verify()
        result["apk"] = device.package_identity()
        before = device.snapshot()
        result["before"] = before
        existing = [
            root + "/" + name
            for root, root_state in before.items()
            for name in root_state["files"]
        ]
        if existing:
            raise ProbeError("refusing_to_overwrite_existing_vendor_debug_files")

        status = run_manager("status", args.serial)
        if status.get("status") != "listening" or status.get("audio_opened") is not True:
            raise ProbeError("native_listening_baseline_required")
        native_was_listening = True
        run_manager("stop", args.serial)
        device.adb("logcat", "-c")
        nonce = "vendor-debug-probe-" + str(time.time_ns())
        device.shell(
            "am start -W -n " + COMPONENT
            + " --es probe_action four_mic_record"
            + " --ei duration_seconds 5"
            + " --es sample_id vendor-debug-lifecycle"
            + " --es probe_nonce " + nonce
        )
        capture_started = True
        timeline = []
        terminal = wait_for_capture(device, nonce, timeline)
        result["terminal_marker"] = terminal
        if ("R1_FOUR_MIC_RECORD_COMPLETE" not in terminal
                and "four_mic_read_timeout" not in terminal):
            raise ProbeError("vendor_debug_capture_did_not_reach_close_path")
        result["timeline"] = timeline
        time.sleep(0.5)
        after_close_1 = device.snapshot()
        time.sleep(1.0)
        after_close_2 = device.snapshot()
        result["after_close"] = [after_close_1, after_close_2]
        if after_close_1 != after_close_2:
            raise ProbeError("vendor_debug_files_not_stable_after_close")

        artifacts = {}
        artifact_roots = {}
        duplicates = []
        for root, root_state in after_close_2.items():
            for name, size in root_state["files"].items():
                remote = root + "/" + name
                local_name = root.strip("/").replace("/", "_") + "__" + name
                local = output / "audio" / local_name
                device.pull(remote, local)
                remote_digest = device.remote_sha256(remote)
                if sha256(local) != remote_digest or local.stat().st_size != size:
                    raise ProbeError("vendor_debug_pull_mismatch")
                kind = name.removesuffix(".wav").rsplit("_", 1)[-1]
                inspected = inspect_wav(local, kind)
                inspected["remote_path"] = remote
                inspected["local_name"] = local_name
                device.remove(remote)
                if name in artifacts:
                    duplicates.append(name)
                else:
                    artifacts[name] = inspected
                    artifact_roots[name] = root
        cleanup = device.snapshot()
        result["after_cleanup"] = cleanup
        if any(value["files"] for value in cleanup.values()):
            raise ProbeError("vendor_debug_cleanup_incomplete")
        if duplicates:
            raise ProbeError("vendor_debug_file_present_in_multiple_roots")
        result["artifacts"] = evaluate_artifacts(artifacts)
        if result["artifacts"]["status"] != "pass":
            raise ProbeError(result["artifacts"]["status"])
        result["lifecycle"] = {
            "absent_before": True,
            "close_marker_observed": True,
            "stable_after_close": True,
            "pull_hash_verified": True,
            "exact_files_removed_after_export": True,
            "artifact_roots": artifact_roots,
            "status": "pass",
        }
        result["status"] = "pass"
    except (OSError, ProbeError, subprocess.SubprocessError, ValueError) as error:
        result["failure"] = str(error)
    finally:
        if capture_started:
            device.shell("am force-stop " + PACKAGE, check=False)
        if native_was_listening:
            try:
                restored = run_manager("start", args.serial, "--listen")
                result["native_restore"] = restored
                if (restored.get("status") != "listening"
                        or restored.get("audio_opened") is not True):
                    raise ProbeError("native_listening_restore_not_confirmed")
            except (ProbeError, ValueError) as error:
                result["native_restore"] = {"status": "failed", "failure": str(error)}
                result["status"] = "failed"
        result_path = output / "result.json"
        result_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.chmod(result_path, 0o600)
        print(json.dumps({"output": str(output), "status": result["status"]}, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
