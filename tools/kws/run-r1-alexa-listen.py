#!/usr/bin/env python3
"""Bounded R1 live KWS probe. No recording, factory package changes or audio upload."""
import argparse
import hashlib
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = "dev.sewellzhong.r1probe"
SERVICE = PACKAGE + "/.AlexaListeningService"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("serial")
    parser.add_argument("--confirm-device", required=True, choices=["r1-sample01"])
    parser.add_argument("--seconds", type=int, default=20)
    args = parser.parse_args()
    if not 5 <= args.seconds <= 3600:
        parser.error("--seconds must be 5..3600")

    def adb(*command):
        return subprocess.run(["adb", "-s", args.serial, *command], check=True,
                              capture_output=True, text=True, timeout=30).stdout

    for prop, expected in [("ro.product.device", "rk322x_echo"),
                           ("ro.build.version.sdk", "22"),
                           ("ro.build.version.incremental", "3448")]:
        if adb("shell", "getprop", prop).strip() != expected:
            raise RuntimeError("unexpected device/firmware: " + prop)
    package = adb("shell", "dumpsys", "package", PACKAGE)
    if "versionCode=34 " not in package:
        raise RuntimeError("install Alexa listener version 34 first")
    if "isForeground=true" in adb("shell", "dumpsys", "activity", "services", SERVICE):
        raise RuntimeError("Alexa session already running")
    stamp = time.strftime("%Y-%m-%dT%H%M%S")
    evidence = ROOT / "test-results" / (stamp + "-r1-sample01") / "stage1/alexa-kws/listen"
    evidence.mkdir(parents=True, exist_ok=False)
    nonce = "alexa-" + str(time.time_ns())
    (evidence / "session.txt").write_text(
        f"nonce={nonce}\nsource=R1_VOICE_COMMUNICATION\npurpose=live_kws_probe\n"
        f"duration_seconds={args.seconds}\naudio_retained=false\n"
        "software_denoiser=false\nfactory_packages_changed_by_this_runner=false\n")
    (evidence / "package.txt").write_text(package)
    success = False
    try:
        (evidence / "start.txt").write_text(adb(
            "shell", "am", "startservice", "-n", SERVICE,
            "--es", "probe_nonce", nonce, "--ei", "duration_seconds", str(args.seconds)))
        deadline = time.monotonic() + args.seconds + 25
        announced = False
        session_lines = []
        seen_lines = set()
        while time.monotonic() < deadline:
            logs = adb("logcat", "-d", "-s", "R1Audio:V", "*:S")
            (evidence / "logcat.txt").write_text(logs)
            lines = [line for line in logs.splitlines() if "nonce=" + nonce in line]
            # Android's small Logcat buffer can evict early events during a session.
            for line in lines:
                if line not in seen_lines:
                    seen_lines.add(line)
                    session_lines.append(line)
            (evidence / "session-events.txt").write_text("\n".join(session_lines) + "\n")
            if any("R1_ALEXA_READY" in line for line in lines) and not announced:
                print("READY: local Alexa listening; no audio retained.", flush=True)
                (evidence / "meminfo-active.txt").write_text(
                    adb("shell", "dumpsys", "meminfo", PACKAGE))
                announced = True
            terminal = [line for line in lines if any(marker in line for marker in
                        ("R1_ALEXA_COMPLETE", "R1_ALEXA_FAILED", "R1_ALEXA_STOPPED"))]
            if terminal:
                (evidence / "result-marker.txt").write_text("\n".join(terminal) + "\n")
                success = "R1_ALEXA_COMPLETE" in terminal[-1]
                print(terminal[-1], flush=True)
                break
            time.sleep(2)
    finally:
        try:
            (evidence / "stop.txt").write_text(
                adb("shell", "am", "stopservice", "-n", SERVICE))
        except (subprocess.SubprocessError, OSError) as error:
            success = False
            (evidence / "stop-error.txt").write_text(type(error).__name__ + "\n")
        if not success:
            # Firmware 3448 can leave a native AudioRecord track stuck after timeout.
            try:
                (evidence / "failure-force-stop.txt").write_text(
                    adb("shell", "am", "force-stop", PACKAGE))
            except (subprocess.SubprocessError, OSError) as error:
                (evidence / "cleanup-error.txt").write_text(type(error).__name__ + "\n")
        (evidence / "RESULT.txt").write_text(
            f"runtime_status={'pass' if success else 'fail'}\n"
            "acoustic_acceptance=not_established\naudio_retained=false\n")
        hashes = []
        for path in sorted(evidence.iterdir()):
            if path.is_file() and path.name != "SHA256SUMS":
                hashes.append(hashlib.sha256(path.read_bytes()).hexdigest() + "  " + path.name)
        (evidence / "SHA256SUMS").write_text("\n".join(hashes) + "\n")
        print("Evidence:", evidence, flush=True)
    if not success:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
