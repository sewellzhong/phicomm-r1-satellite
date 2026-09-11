#!/usr/bin/env python3
"""Capture and export bounded MicArray tap WAV sidecars from r1-sample01."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[2]
MANAGER = ROOT / "tools/native/manage-r1-native.py"
AUDITOR = ROOT / "tools/factory_audio/audit-validation-capture.py"
PACKAGE = "dev.sewellzhong.r1probe"
COMPONENT = PACKAGE + "/.ProbeCommandReceiver"
DIAGNOSTIC_ROOT = "/mnt/internal_sd/Android/data/dev.sewellzhong.r1probe/files/diagnostics"
EXPECTED_VERSION_CODE = 86
OUTPUT_KEYS = (
    "wav_path", "diagnostic_wav_path", "metadata_path",
    "micarray_raw_wav_path", "micarray_echo_wav_path",
    "micarray_asr_wav_path", "micarray_vad_wav_path",
)


class ExportError(RuntimeError):
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
        raise ExportError("audio_output_must_be_outside_repository")
    if output.exists():
        raise ExportError("output_directory_already_exists")
    return output


def parse_package_identity(dump):
    version = re.search(r"\bversionCode=(\d+)\b", dump)
    code_path = re.search(r"^\s*codePath=(/data/app/[^\s]+)$", dump, re.MULTILINE)
    if version is None or code_path is None:
        raise ExportError("installed_package_identity_unavailable")
    return int(version.group(1)), code_path.group(1) + "/base.apk"


def parse_output_paths(marker):
    paths = {}
    for key in OUTPUT_KEYS:
        match = re.search(r"(?:^|\s)" + key + r"=([^\s]+)", marker)
        if match is None or match.group(1) == "unavailable":
            raise ExportError("capture_output_path_missing:" + key)
        remote = match.group(1)
        if not remote.startswith(DIAGNOSTIC_ROOT + "/"):
            raise ExportError("capture_output_path_outside_diagnostics:" + key)
        name = remote[len(DIAGNOSTIC_ROOT) + 1:]
        if "/" in name or not re.fullmatch(r"[A-Za-z0-9._-]+", name):
            raise ExportError("capture_output_name_invalid:" + key)
        paths[key] = remote
    if len(set(paths.values())) != len(paths):
        raise ExportError("capture_output_paths_not_unique")
    return paths


def run_manager(action, serial, *extra):
    result = subprocess.run(
        [sys.executable, str(MANAGER), action, serial, *extra],
        capture_output=True, text=True, timeout=60, check=False,
    )
    if result.returncode != 0:
        raise ExportError("native_" + action + "_failed")
    return json.loads(result.stdout) if result.stdout.strip() else {}


class Device:
    def __init__(self, serial):
        self.serial = serial

    def adb(self, *args, timeout=40, check=True):
        result = subprocess.run(
            ["adb", "-s", self.serial, *args], capture_output=True, text=True,
            timeout=timeout, check=False,
        )
        if check and result.returncode != 0:
            raise ExportError("adb_command_failed:" + args[0])
        return (result.stdout + result.stderr).replace("\r", "").strip()

    def shell(self, command, timeout=40, check=True):
        return self.adb("shell", command, timeout=timeout, check=check)

    def verify(self, expected_apk_sha256):
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
            raise ExportError("unexpected_device_or_firmware")
        if self.shell("getenforce") != "Enforcing":
            raise ExportError("selinux_not_enforcing")
        version, apk_path = parse_package_identity(self.shell("dumpsys package " + PACKAGE))
        if version != EXPECTED_VERSION_CODE:
            raise ExportError("installed_apk_is_not_v86")
        remote_digest = self.remote_sha256(apk_path)
        if remote_digest != expected_apk_sha256:
            raise ExportError("installed_v86_apk_hash_mismatch")
        return {"properties": actual, "version_code": version,
                "apk_path": apk_path, "apk_sha256": remote_digest,
                "selinux": "Enforcing"}

    def remote_sha256(self, remote):
        output = self.shell("busybox sha256sum '" + remote + "'")
        digest = output.split()[0] if output else ""
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ExportError("remote_sha256_unavailable")
        return digest

    def exists(self, remote):
        return self.shell(
            "if [ -e '" + remote + "' ]; then echo present; fi", check=False
        ) == "present"

    def pull(self, remote, local):
        self.adb("pull", remote, str(local), timeout=180)

    def remove(self, remote):
        self.shell("rm -f '" + remote + "'")
        if self.exists(remote):
            raise ExportError("remote_capture_cleanup_failed")


def wait_for_capture(device, nonce, timeout_seconds=40):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        logs = device.adb("logcat", "-d", "-s", "R1Audio:V", "*:S", check=False)
        for line in logs.splitlines():
            if "nonce=" + nonce not in line:
                continue
            if ("R1_FACTORY_AUDIO_VALIDATION_COMPLETE" in line
                    or "R1_FACTORY_AUDIO_VALIDATION_FAILED" in line):
                return line
        time.sleep(0.25)
    raise ExportError("micarray_capture_timeout")


def audit_capture(output, local_paths):
    report = output / "audit.json"
    command = [
        sys.executable, str(AUDITOR), "--device", "r1-sample01",
        "--wav", str(local_paths["wav_path"]),
        "--diagnostic-wav", str(local_paths["diagnostic_wav_path"]),
        "--metadata", str(local_paths["metadata_path"]),
        "--micarray-raw-wav", str(local_paths["micarray_raw_wav_path"]),
        "--micarray-echo-wav", str(local_paths["micarray_echo_wav_path"]),
        "--micarray-asr-wav", str(local_paths["micarray_asr_wav_path"]),
        "--micarray-vad-wav", str(local_paths["micarray_vad_wav_path"]),
        "--output", str(report),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
    if result.returncode != 0:
        raise ExportError("offline_capture_audit_failed:" + result.stderr.strip())
    return json.loads(report.read_text(encoding="utf-8"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("serial")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--expected-apk-sha256", required=True)
    parser.add_argument("--confirm-device", required=True)
    parser.add_argument("--confirm-recording", action="store_true")
    parser.add_argument("--duration-seconds", type=int, default=5)
    args = parser.parse_args(argv)
    if args.confirm_device != "r1-sample01":
        parser.error("--confirm-device must be r1-sample01")
    if not args.confirm_recording:
        parser.error("--confirm-recording is required")
    if not re.fullmatch(r"[0-9a-f]{64}", args.expected_apk_sha256):
        parser.error("--expected-apk-sha256 must be lowercase SHA-256")
    if not 1 <= args.duration_seconds <= 30:
        parser.error("--duration-seconds must be in 1..30")

    output = validate_output(args.output_dir)
    output.mkdir(mode=0o700, parents=True)
    device = Device(args.serial)
    result = {
        "device": "r1-sample01",
        "purpose": "bounded_private_micarray_sidecar_export",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "failed",
    }
    native_was_listening = False
    remote_paths = {}
    try:
        result["identity"] = device.verify(args.expected_apk_sha256)
        status = run_manager("status", args.serial)
        if not (status.get("status") == "listening"
                and status.get("audio_opened") is True):
            raise ExportError("native_listening_baseline_required")
        native_was_listening = True
        run_manager("stop", args.serial)
        device.shell("am force-stop " + PACKAGE)
        device.adb("logcat", "-c")
        nonce = "micarray-sidecar-export-" + str(time.time_ns())
        broadcast = device.shell(
            "am broadcast -n " + COMPONENT
            + " --es probe_action factory_audio_validate"
            + " --ei duration_seconds " + str(args.duration_seconds)
            + " --es sample_id controlled-micarray-export"
            + " --ez micarray_diagnostic_tap true"
            + " --es probe_nonce " + nonce
        )
        if "Broadcast completed: result=0" not in broadcast:
            raise ExportError("micarray_capture_broadcast_failed")
        terminal = wait_for_capture(device, nonce, args.duration_seconds + 20)
        result["terminal_marker"] = terminal
        if "R1_FACTORY_AUDIO_VALIDATION_COMPLETE" not in terminal:
            raise ExportError("micarray_capture_failed")
        remote_paths = parse_output_paths(terminal)
        local_paths = {}
        exported = {}
        for key, remote in remote_paths.items():
            if not device.exists(remote):
                raise ExportError("remote_capture_missing:" + key)
            local = output / Path(remote).name
            device.pull(remote, local)
            remote_digest = device.remote_sha256(remote)
            local_digest = sha256(local)
            if local_digest != remote_digest:
                raise ExportError("capture_pull_hash_mismatch:" + key)
            local_paths[key] = local
            exported[key] = {"name": local.name, "bytes": local.stat().st_size,
                             "sha256": local_digest}
        result["audit"] = audit_capture(output, local_paths)
        for remote in remote_paths.values():
            device.remove(remote)
        result["exported"] = exported
        result["remote_cleanup"] = "pass"
        result["status"] = "pass"
    except (ExportError, OSError, subprocess.SubprocessError, ValueError) as error:
        result["failure"] = str(error)
    finally:
        try:
            device.shell("am force-stop " + PACKAGE, check=False)
        except (OSError, subprocess.SubprocessError):
            pass
        cleanup_failures = []
        for remote in remote_paths.values():
            try:
                if device.exists(remote):
                    device.remove(remote)
            except (ExportError, OSError, subprocess.SubprocessError) as error:
                cleanup_failures.append(str(error))
        if cleanup_failures:
            result["status"] = "failed"
            result["remote_cleanup_failures"] = cleanup_failures
        if native_was_listening:
            try:
                restored = run_manager("start", args.serial, "--listen")
                result["restored"] = restored
                if not (restored.get("status") == "listening"
                        and restored.get("audio_opened") is True):
                    result["status"] = "failed"
                    result["restore_failure"] = "native_listening_not_restored"
            except (ExportError, OSError, subprocess.SubprocessError, ValueError) as error:
                result["status"] = "failed"
                result["restore_failure"] = str(error)
        (output / "result.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
