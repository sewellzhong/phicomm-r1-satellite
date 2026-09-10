#!/usr/bin/env python3
"""Run one bounded, reversible stock-chain smoke window on r1-sample01."""

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
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
PREFLIGHT = ROOT / "tools/factory_audio/original-chain-preflight.py"
ADMIN_PATH = ROOT / "tools/native/manage-r1-native.py"
PACKAGES = ("com.phicomm.speaker.device", "com.phicomm.speaker.player")
SATELLITE = "dev.sewellzhong.r1probe"
EXPECTED_APKS = {
    PACKAGES[0]: "d98ff6aeab80c562498f42b45ddf4bb58eae318d64e47cecca7355799cee6542",
    PACKAGES[1]: "eee63585effda9697c6fb1da5ae82ddf0fc41566aa8462841e407f15aae6fdc8",
}
DEBUG_NAMES = tuple(
    f"{phase}_file_{kind}.wav"
    for phase in ("waking", "waked")
    for kind in ("4mic", "2aec", "out")
)


class SmokeError(RuntimeError):
    pass


ADMIN_SPEC = importlib.util.spec_from_file_location("r1_native_admin", ADMIN_PATH)
ADMIN = importlib.util.module_from_spec(ADMIN_SPEC)
ADMIN_SPEC.loader.exec_module(ADMIN)


def run(command, timeout=40, check=True):
    result = subprocess.run(
        command, capture_output=True, text=True, timeout=timeout
    )
    if check and result.returncode != 0:
        raise SmokeError("command_failed:" + command[0])
    return result


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def audio_released(status):
    health = status.get("health")
    return (status.get("audio") is None
            and status.get("audio_opened") is False
            and not (health and health.get("state") == "running"))


def listening_ready(status):
    return status.get("status") == "listening" and status.get("audio_opened") is True


class Device:
    def __init__(self, serial):
        self.serial = serial

    def adb(self, *args, timeout=40, check=True):
        return run(["adb", "-s", self.serial, *args], timeout=timeout, check=check)

    def shell(self, *args, timeout=40, check=True):
        result = self.adb("shell", *args, timeout=timeout, check=check)
        return (result.stdout + result.stderr).replace("\r", "").strip()

    def pm(self, *args):
        return self.shell(
            "CLASSPATH=/system/framework/pm.jar", "app_process", "/system/bin",
            "com.android.commands.pm.Pm", *args,
        )

    def pm_hidden(self, package):
        dump = self.shell("dumpsys", "package", package)
        state = re.search(r"User 0:.*?installed=(true|false).*?hidden=(true|false)", dump)
        if state is None or state.group(1) != "true":
            raise SmokeError("package_state_unavailable:" + package)
        return state.group(2) == "true"

    def package_apk(self, package):
        dump = self.shell("dumpsys", "package", package)
        match = re.search(r"^\s*codePath=(/data/app/[^\s]+)$", dump, re.MULTILINE)
        if match is None:
            raise SmokeError("data_app_code_path_unavailable:" + package)
        return match.group(1) + "/base.apk"

    def remote_file_exists(self, path):
        if path not in {"/sdcard/unidata/" + name for name in DEBUG_NAMES}:
            raise SmokeError("unsupported_remote_debug_path")
        # adb shell concatenates separate argv values on this Android 5.1 build;
        # pass the complete conditional as one remote-shell command so `sh -c`
        # cannot lose its script argument while still using the fixed allow-list.
        output = self.shell(
            "if [ -f '" + path + "' ]; then echo present; fi", check=False
        )
        return output == "present"

    def set_hidden(self, package, hidden):
        if package not in PACKAGES:
            raise SmokeError("unsupported_package")
        verb = "hide" if hidden else "unhide"
        output = self.pm(verb, "--user", "0", package)
        expected = "new hidden state: " + str(hidden).lower()
        if expected not in output or self.pm_hidden(package) != hidden:
            raise SmokeError("package_hidden_change_not_confirmed:" + package)

    def native_status(self):
        result = run([sys.executable, str(MANAGER), "status", self.serial])
        return json.loads(result.stdout)

    def native(self, action, *extra):
        result = run([sys.executable, str(MANAGER), action, self.serial, *extra], timeout=60)
        return json.loads(result.stdout) if result.stdout.strip() else {}

    def stop_native_audio(self):
        control = ADMIN.Device(self.serial)
        control.start_control()
        control.control({"action": "stop"})
        for _ in range(40):
            status = control.control({"action": "status"})
            if audio_released(status):
                control.adb("shell", "am", "stopservice", "-n", ADMIN.SERVICE)
                return status
            time.sleep(0.25)
        raise SmokeError("satellite_audio_release_not_confirmed")

    def start_native_audio(self):
        self.native("start", "--listen")
        last = {}
        for _ in range(40):
            last = self.native_status()
            if listening_ready(last):
                return last
            time.sleep(0.25)
        raise SmokeError("satellite_listening_not_confirmed")


def ping_is_local_success(output):
    return "0% packet loss" in output and "100% packet loss" not in output


def ping_is_rejected(output):
    return ("100% packet loss" in output
            and ("Destination Port Unreachable" in output
                 or "Destination unreachable: Port unreachable" in output))


def verify_wan_block(device):
    gateway = device.shell("ping", "-c", "2", "-W", "2", "192.168.94.1", check=False)
    ipv4 = {
        target: device.shell("ping", "-c", "2", "-W", "2", target, check=False)
        for target in ("1.1.1.1", "8.8.8.8")
    }
    ipv6 = {
        target: device.shell("ping6", "-c", "2", "-W", "2", target, check=False)
        for target in ("2606:4700:4700::1111", "2001:4860:4860::8888")
    }
    tcp = device.shell(
        "busybox", "nc", "-w", "3", "1.1.1.1", "443", timeout=8, check=False
    )
    http = device.shell(
        "busybox", "wget", "-T", "4", "-O", "/dev/null", "http://1.0.0.1/",
        timeout=8, check=False,
    )
    passed = (ping_is_local_success(gateway)
              and all(ping_is_rejected(value) for value in ipv4.values())
              and all(ping_is_rejected(value) for value in ipv6.values())
              and "can't connect to remote host" in tcp
              and "can't connect to remote host" in http)
    return {
        "gateway_local_success": ping_is_local_success(gateway),
        "http_rejected": "can't connect to remote host" in http,
        "ipv4_rejected": {key: ping_is_rejected(value) for key, value in ipv4.items()},
        "ipv6_rejected": {key: ping_is_rejected(value) for key, value in ipv6.items()},
        "status": "pass" if passed else "fail",
        "tcp_443_rejected": "can't connect to remote host" in tcp,
    }


def inspect_wav(path):
    result = {"bytes": path.stat().st_size, "sha256": sha256(path)}
    try:
        with wave.open(str(path), "rb") as audio:
            result.update({
                "channels": audio.getnchannels(),
                "frames": audio.getnframes(),
                "sample_rate_hz": audio.getframerate(),
                "sample_width_bytes": audio.getsampwidth(),
            })
    except (EOFError, wave.Error):
        result["wav_header_valid"] = False
    else:
        result["wav_header_valid"] = True
    return result


def factory_runtime_attestation(log_lines):
    text = "\n".join(log_lines)
    checks = {
        "aec_enabled": "aec_on=1" in text,
        "audio_source_opened": "AudioSourceImplopenIn uni4micHalJNI status = 0" in text,
        "echo_channels_two": "echo_num=2" in text,
        "four_mic_enabled": "use_4mic=1" in text,
        "mic_array_initialized": "uni_hal_4mic_array_init sucess" in text,
        "mic_channels_four": "mic_num=4" in text,
        "vendor_hal_v1_1": "UNI_4MIC_HAL_ANDROID_V1.1" in text,
    }
    return {
        "checks": checks,
        "status": "pass" if all(checks.values()) else "fail",
    }


def write_json(path, value):
    Path(path).write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def validate_output(path):
    output = Path(path).resolve()
    try:
        output.relative_to(ROOT)
    except ValueError:
        pass
    else:
        raise SmokeError("audio_output_must_be_outside_repository")
    if output.exists():
        raise SmokeError("output_directory_already_exists")
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("serial")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--seconds", type=int, choices=range(5, 21), default=20)
    parser.add_argument(
        "--trigger-mode", choices=("factory-wake-word", "center-button"), required=True
    )
    parser.add_argument("--confirm-device", required=True)
    parser.add_argument("--confirm-wan-blocked", action="store_true")
    parser.add_argument("--confirm-recording", action="store_true")
    args = parser.parse_args(argv)
    if args.confirm_device != "r1-sample01":
        parser.error("--confirm-device must be r1-sample01")
    if not args.confirm_wan_blocked or not args.confirm_recording:
        parser.error("WAN-block and recording confirmations are required")

    output = validate_output(args.output_dir)
    output.mkdir(mode=0o700, parents=True)
    logs = output / "logs"
    audio = output / "audio"
    logs.mkdir(mode=0o700)
    audio.mkdir(mode=0o700)
    device = Device(args.serial)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backups = {}
    generated = []
    satellite_stopped = False
    packages_unhidden = False
    result = {
        "device": "r1-sample01",
        "duration_seconds": args.seconds,
        "original_application_layer": "data_app_third_party_overlay_on_3448_system_base",
        "purpose": "bounded_factory_four_mic_chain_smoke",
        "trigger_mode": args.trigger_mode,
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "status": "running",
    }

    def restore():
        errors = []
        if packages_unhidden:
            device.adb("shell", "am", "force-stop", PACKAGES[0], check=False)
            device.adb("shell", "am", "force-stop", PACKAGES[1], check=False)
        for name in DEBUG_NAMES:
            device.adb("shell", "rm", "-f", "/sdcard/unidata/" + name, check=False)
        for name, backup in backups.items():
            outcome = device.adb(
                "shell", "mv", backup, "/sdcard/unidata/" + name, check=False
            )
            if outcome.returncode != 0:
                errors.append("debug_restore_failed:" + name)
        for package in PACKAGES:
            try:
                if not device.pm_hidden(package):
                    device.set_hidden(package, True)
            except Exception:
                errors.append("package_rehide_failed:" + package)
        if satellite_stopped:
            try:
                device.start_native_audio()
            except Exception:
                errors.append("satellite_restart_failed")
        return errors

    try:
        preflight = output / "preflight.json"
        run([sys.executable, str(PREFLIGHT), args.serial, "--output", str(preflight)])
        wan_before = verify_wan_block(device)
        write_json(output / "wan-before.json", wan_before)
        if wan_before["status"] != "pass":
            raise SmokeError("wan_block_not_verified")
        status = device.native_status()
        write_json(output / "satellite-before.json", status)
        if (not listening_ready(status)
                or status.get("factory_isolation") != "packages_hidden"):
            raise SmokeError("satellite_baseline_not_ready")
        for package, expected in EXPECTED_APKS.items():
            location = device.package_apk(package)
            actual = device.shell("busybox", "sha256sum", location).split()[0]
            if actual != expected:
                raise SmokeError("package_hash_mismatch:" + package)
        for name in DEBUG_NAMES:
            source = "/sdcard/unidata/" + name
            if device.remote_file_exists(source):
                backup = f"/sdcard/unidata/.r1safe-{run_id}-{name}"
                device.shell("mv", source, backup)
                backups[name] = backup

        stopped = device.stop_native_audio()
        satellite_stopped = True
        write_json(output / "satellite-stopped.json", stopped)
        if stopped.get("audio_opened") is not False:
            raise SmokeError("satellite_audio_not_released")
        packages_unhidden = True
        for package in PACKAGES:
            device.set_hidden(package, False)
        device.shell("am", "startservice", "-n", PACKAGES[1] + "/.EchoService", check=False)
        device.shell("am", "startservice", "-n", PACKAGES[0] + "/.ui.service.WindowsService", check=False)
        device.shell("am", "start", "-W", "-n", PACKAGES[0] + "/.ui.MainActivity", check=False)
        if args.trigger_mode == "factory-wake-word":
            instruction = "Say '小讯小讯', then say '请打开客厅的灯' in a normal voice."
        else:
            instruction = ("Press the R1 center button once, then say "
                           "'请打开客厅的灯' in a normal voice.")
        print(
            f"Original-chain window active for {args.seconds}s. {instruction}", flush=True
        )
        time.sleep(args.seconds)
        process_snapshot = device.shell("ps", check=False)
        (logs / "processes.txt").write_text(
            "\n".join(line for line in process_snapshot.splitlines()
                      if "com.phicomm.speaker" in line) + "\n", encoding="utf-8"
        )
        # Stop before collecting debug files so the vendor chain can flush data and
        # finalize WAV headers. The finally block still force-stops defensively.
        device.adb("shell", "am", "force-stop", PACKAGES[0], check=False)
        device.adb("shell", "am", "force-stop", PACKAGES[1], check=False)
        time.sleep(1)
        factory_pids = {
            fields[1] for line in process_snapshot.splitlines()
            if any(package in line for package in PACKAGES)
            and len(fields := line.split()) > 1
            and fields[1].isdigit()
        }
        raw_log = device.shell("logcat", "-d", "-v", "time", check=False)
        filtered = [line for line in raw_log.splitlines()
                    if re.search(r"(?i)(uni.?4mic|micarray|aec|doa|unisound)", line)
                    and any(re.search(r"\(\s*" + re.escape(pid) + r"\)", line)
                            for pid in factory_pids)]
        (logs / "factory-audio-filtered.log").write_text(
            "\n".join(filtered[-3000:]) + "\n", encoding="utf-8"
        )
        result["factory_runtime"] = factory_runtime_attestation(filtered)
        artifacts = {}
        for name in DEBUG_NAMES:
            remote = "/sdcard/unidata/" + name
            if not device.remote_file_exists(remote):
                continue
            local = audio / name
            device.adb("pull", remote, str(local), timeout=180)
            artifacts[name] = inspect_wav(local)
            generated.append(name)
        result["artifacts"] = artifacts
        result["factory_processes_observed"] = any(
            package in process_snapshot for package in PACKAGES
        )
        valid_artifacts = [name for name, item in artifacts.items()
                           if item.get("wav_header_valid") and item.get("frames", 0) > 0]
        result["valid_audio_artifacts"] = valid_artifacts
        result["status"] = ("captured" if valid_artifacts
                            else "no_valid_factory_audio_artifacts")
    except Exception as error:
        result["failure"] = type(error).__name__ + ":" + str(error)
        result["status"] = "failed"
    finally:
        restore_errors = restore() if satellite_stopped or packages_unhidden or backups else []
        result["restore_errors"] = restore_errors
        result["generated_device_files_removed"] = not restore_errors
        try:
            result["wan_after"] = verify_wan_block(device)
            result["satellite_after"] = device.native_status()
            result["packages_hidden_after"] = {
                package: device.pm_hidden(package) for package in PACKAGES
            }
        except Exception as error:
            result["postcheck_failure"] = type(error).__name__
        result["completed_utc"] = datetime.now(timezone.utc).isoformat()
        safe = (not restore_errors
                and result.get("wan_after", {}).get("status") == "pass"
                and result.get("satellite_after", {}).get("status") == "listening"
                and result.get("satellite_after", {}).get("audio_opened") is True
                and all(result.get("packages_hidden_after", {}).values()))
        result["restored_safe_baseline"] = safe
        write_json(output / "result.json", result)
        os.chmod(output / "result.json", 0o600)
    print(json.dumps({
        "artifacts": sorted(result.get("artifacts", {})),
        "output": str(output),
        "restored_safe_baseline": result.get("restored_safe_baseline", False),
        "status": result["status"],
    }, ensure_ascii=False))
    return 0 if result.get("restored_safe_baseline") and result["status"] == "captured" else 1


if __name__ == "__main__":
    raise SystemExit(main())
