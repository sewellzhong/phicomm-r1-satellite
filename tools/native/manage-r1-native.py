#!/usr/bin/env python3
"""R1 native administration over a shell-authorized ADB local socket. Never print PSKs."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = "dev.sewellzhong.r1probe"
SERVICE = PACKAGE + "/.NativeSatelliteService"

class Device:
    def __init__(self, serial):
        self.serial = serial
    def adb(self, *args):
        if args[0] == "install":
            import uuid
            remote = "/data/local/tmp/r1-native-" + uuid.uuid4().hex + ".apk"
            try:
                self.adb("push", args[-1], remote)
                result = self.adb("shell", "pm", "install", *args[1:-1], remote)
                if "Success" not in result: raise RuntimeError("apk_install_failed")
                return result
            finally: self.adb("shell", "rm", "-f", remote)
        # Firmware 3448's pm wrapper delegates incorrectly in some shells; use the stock Java command.
        if len(args) >= 2 and args[:2] == ("shell", "pm"):
            args = ("shell", "CLASSPATH=/system/framework/pm.jar", "app_process", "/system/bin", "com.android.commands.pm.Pm", *args[2:])
        return subprocess.run(["adb", "-s", self.serial, *args], check=True,
                              capture_output=True, text=True, timeout=180 if args[0] in ("pull", "push", "install") else 40).stdout.strip()
    def verify(self):
        for prop, value in [("ro.product.device", "rk322x_echo"), ("ro.build.version.sdk", "22"),
                            ("ro.build.version.incremental", "3448")]:
            if self.adb("shell", "getprop", prop) != value:
                raise RuntimeError("unexpected_device_or_firmware")
    def control(self, command):
        shared_port = getattr(self, "export_port", None)
        port = shared_port or int(self.adb("forward", "tcp:0", "localabstract:r1-native-control"))
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=10) as connection:
                connection.sendall((json.dumps(command) + "\n").encode())
                with connection.makefile("rb") as stream:
                    data = stream.readline(8193)
                if len(data) > 8192 or not data.endswith(b"\n"):
                    raise RuntimeError("invalid_control_response")
                response = json.loads(data)
                if "error" in response:
                    raise RuntimeError("control_request_rejected")
                return response
        finally:
            if shared_port is None: self.adb("forward", "--remove", "tcp:" + str(port))
    def start_control(self):
        self.adb("shell", "am", "startservice", "-n", SERVICE)
        for _ in range(30):
            try: return self.control({"action": "status"})
            except (OSError, ValueError, RuntimeError): time.sleep(.2)
        raise RuntimeError("native_control_unavailable")


def export_diagnostic(device, destination):
    """Keep the device copy on any transfer/checksum error; never overwrite local evidence."""
    state = device.control({"action": "diagnostic-status"})
    if not state.get("ready"): raise RuntimeError("capture_not_ready")
    size, expected = state["bytes"], state["sha256"]
    if not isinstance(size, int) or not 4 <= size <= 8 * 1024 * 1024:
        raise RuntimeError("invalid_capture_size")
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    metadata = destination.with_suffix(destination.suffix + ".json")
    if metadata.exists(): raise RuntimeError("local_evidence_exists")
    digest = hashlib.sha256()
    device.export_port = int(device.adb("forward", "tcp:0", "localabstract:r1-native-control"))
    try:
        with destination.open("xb") as output:
            offset = 0
            while offset < size:
                chunk = device.control({"action": "diagnostic-export", "offset": offset, "sha256": expected})
                data = base64.b64decode(chunk["data"], validate=True)
                if chunk["offset"] != offset or not data or len(data) > min(2048, size-offset):
                    raise RuntimeError("invalid_capture_chunk")
                output.write(data); digest.update(data); offset += len(data)
        if digest.hexdigest() != expected: raise RuntimeError("capture_checksum_mismatch")
        metadata.write_text(json.dumps({**state, "format": "R1D1", "purpose": "silence_diagnosis",
            "exported_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "device_firmware": "3448", "source": "r1-sample01 microphone and local prompt",
            "complete": state["reason"] in ("requested", "timeout")}, indent=2)+"\n")
        device.control({"action": "diagnostic-clear", "sha256": expected})
        return {"exported": str(destination), "bytes": size, "sha256": expected,
                "reason": state["reason"], "device_copy_cleared": True}
    finally:
        device.adb("forward", "--remove", "tcp:"+str(device.export_port))
        del device.export_port


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["initialize", "start", "stop", "status", "rotate", "pair", "audio-check",
        "diagnostic-window", "diagnostic-start", "diagnostic-arm", "diagnostic-stop", "diagnostic-status", "diagnostic-export", "diagnostic-clear",
        "capability-status", "hardware-reset", "bluetooth-discoverable", "bluetooth-close", "ble-window", "ble-close", "hotspot-window", "hotspot-close",
        "original-provisioning-open", "original-provisioning-close", "provisioning-recover"])
    parser.add_argument("serial")
    parser.add_argument("--seconds", type=int, default=30, choices=range(1,121))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--sha256")
    parser.add_argument("--name", default="r1-sample01")
    parser.add_argument("--prompt-index", type=int, choices=range(10))
    parser.add_argument("--followup", action="store_true")
    parser.add_argument("--listen", action="store_true")
    parser.add_argument("--ha-host", default="home-assistant")
    args = parser.parse_args()
    if args.action in ("diagnostic-start", "diagnostic-arm") and args.seconds > 30:
        parser.error("diagnostic capture is limited to 30 seconds")
    if args.prompt_index is not None and (args.action != "diagnostic-window" or args.followup):
        parser.error("--prompt-index requires an initial diagnostic-window")
    device = Device(args.serial); device.verify()
    if args.action not in ("status", "diagnostic-status", "diagnostic-export", "diagnostic-clear", "diagnostic-stop"): device.start_control()
    if args.action == "diagnostic-export":
        if args.output is None: parser.error("--output is required")
        print(json.dumps(export_diagnostic(device,args.output),ensure_ascii=False)); return
    command = {"action": args.action}
    if args.action in ("diagnostic-start", "diagnostic-arm", "bluetooth-discoverable", "ble-window", "hotspot-window"):
        command["seconds"] = args.seconds
    if args.action == "diagnostic-clear":
        if not args.sha256: parser.error("--sha256 is required")
        command["sha256"] = args.sha256
    if args.action == "diagnostic-window":
        command["followup"] = args.followup
        if args.prompt_index is not None: command["prompt_index"] = args.prompt_index
    if args.action == "initialize": command["name"] = args.name
    if args.action == "start": command["listen"] = args.listen
    if args.action == "pair":
        pairing = device.control({"action": "pairing"})
        pairing["host"] = args.serial.split(":")[0]
        result = subprocess.run([sys.executable, str(ROOT / "tools/native/pair-home-assistant.py"),
                                 "--host", args.ha_host], input=json.dumps(pairing),
                                text=True, check=True)
        pairing.clear()
        return result.returncode
    response = device.control(command)
    print(json.dumps(response, ensure_ascii=False))
    if args.action == "stop": device.adb("shell", "am", "stopservice", "-n", SERVICE)

if __name__ == "__main__":
    try: sys.exit(main())
    except Exception as error:
        print("Native administration failed: " + type(error).__name__, file=sys.stderr)
        sys.exit(1)
