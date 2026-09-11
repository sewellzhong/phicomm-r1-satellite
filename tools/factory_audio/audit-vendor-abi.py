#!/usr/bin/env python3
"""Audit a local/device-extracted R1 vendor audio library without redistributing it."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


KNOWN_LIBRARIES = {
    "ce49904fd7e82446fed671f9ed8da398480ab7c3263bc6a29aafd0f13c1d504a": "libuni4michal.so",
    "24de008fc20cd60111c1ba33fd2743f193f8b5f71a93bcafac13497c8fcd72fb": "libuni4michalchance.so",
}
REQUIRED_SYMBOLS = (
    "close4MicAlgorithm",
    "get4MicBoardVersion",
    "get4MicDoaResult",
    "set4MicDebugMode",
    "set4MicWakeUpStatus",
    "uni_4mic_hal_init",
    "uni_4mic_hal_release",
    "uni_4mic_pcm_close",
    "uni_4mic_pcm_open",
    "uni_4mic_pcm_read",
    "uni_4mic_pcm_start",
    "uni_4mic_pcm_stop",
)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def audit(path):
    path = Path(path)
    digest = sha256(path)
    if digest not in KNOWN_LIBRARIES:
        raise RuntimeError("vendor_library_hash_not_3448_baseline")
    header = subprocess.run(
        ["readelf", "-hW", str(path)], check=True, capture_output=True, text=True
    ).stdout
    if "Class:                             ELF32" not in header or "Machine:                           ARM" not in header:
        raise RuntimeError("vendor_library_not_arm_elf32")
    symbols = subprocess.run(
        ["readelf", "-Ws", str(path)], check=True, capture_output=True, text=True
    ).stdout
    missing = [name for name in REQUIRED_SYMBOLS if name not in symbols]
    if missing:
        raise RuntimeError("vendor_library_symbols_missing:" + ",".join(missing))
    return {
        "abi": "armeabi-v7a",
        "library_name": KNOWN_LIBRARIES[digest],
        "library_sha256": digest,
        "required_symbols": list(REQUIRED_SYMBOLS),
        "status": "pass",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", required=True)
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    try:
        result = audit(args.library)
        payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
        if args.output:
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("x", encoding="utf-8") as handle:
                handle.write(payload)
        else:
            print(payload, end="")
        return 0
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Vendor ABI audit failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
