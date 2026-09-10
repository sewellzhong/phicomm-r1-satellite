#!/usr/bin/env python3
"""Prepare one reviewed RK3229 RAM loader and run a bounded read-only probe.

The loader changes only volatile device state.  This tool deliberately has no
reset, erase, storage-switch, LBA-write, or arbitrary-command interface.
Third-party binaries and raw device evidence must remain outside Git.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import urllib.request


DEVICE_ID = "r1-sample01"
VID_PID = "2207:320b"
RKBIN_CANDIDATE_COMMIT = "364df6ae7c88450280293616eecc554404959898"
RKBIN_TOOL_COMMIT = "3e288fe814e059dd06833495f845cab04ac20a5c"
CANDIDATE_ID = "rk322x-v1.07.238"
LOADER_FILENAME = "rk322x_loader_v1.07.238.bin"
CANDIDATE_CANONICAL_SHA256 = "0f0dfe0653c810474d892fc6cc95788b4007d17dd60581359d15748e34d747e1"
RELEASE_TIME_SLICE = slice(14, 21)
RKDEVELOPTOOL_SHA256 = "f654a31633ddc83411b19405e8c4afb5fb024f1d869f6a86b4ab0a5bae71e7b4"
ARTIFACTS = {
    "RK322XMINIALL.ini": {
        "commit": RKBIN_CANDIDATE_COMMIT,
        "repo_path": "RKBOOT/RK322XMINIALL.ini",
        "sha256": "bdf7b53d73ee4492cd9cc5f6e3c4c50377f7a3a3a6de79c16c2d5a6d916088d6",
    },
    "rk322x_ddr_300MHz_v1.07.bin": {
        "commit": RKBIN_CANDIDATE_COMMIT,
        "repo_path": "bin/rk32/rk322x_ddr_300MHz_v1.07.bin",
        "sha256": "d4b66e9615ba7a4d3e0a5ec7f81687200b9c3dbcf69c70e258b2cf2cfa31c16f",
    },
    "rk322x_usbplug_v2.38.bin": {
        "commit": RKBIN_CANDIDATE_COMMIT,
        "repo_path": "bin/rk32/rk322x_usbplug_v2.38.bin",
        "sha256": "ffa5e412c97d0a20a3f590b2470f0209ded8fd54da3c1658f918df66cb770681",
    },
    "rk322x_miniloader_v2.38.bin": {
        "commit": RKBIN_CANDIDATE_COMMIT,
        "repo_path": "bin/rk32/rk322x_miniloader_v2.38.bin",
        "sha256": "16e43c88d1747b0579a94667d7edb6c28977e96652769d0e8e18c8159b4da630",
    },
    "boot_merger": {
        "commit": RKBIN_TOOL_COMMIT,
        "repo_path": "tools/boot_merger",
        "sha256": "f8e1a2d01bc475e9571ab0aec00e4cca3d85bbd4587f3873970560443a237d0c",
    },
    "LICENSE.rockchip-rkbin": {
        "commit": RKBIN_TOOL_COMMIT,
        "repo_path": "LICENSE",
        "sha256": "1b3cfbd212ef0e645b34aa6beee07343ce954a4f512338f12317ab297a9c9829",
    },
}
UNPACKED_PAYLOADS = {
    "rk322x_ddr_300MHz_v.bin": "rk322x_ddr_300MHz_v1.07.bin",
    "rk322x_usbplug_v2.bin": "rk322x_usbplug_v2.38.bin",
    "rk322x_miniloader_v.bin": "rk322x_miniloader_v2.38.bin",
}
READ_COMMANDS = (
    "read-chip-info",
    "read-capability",
    "read-flash-info",
)
REQUIRED_CAPABILITIES = (
    "Direct LBA:\tenabled",
    "First 4m Access:\tenabled",
    "Read LBA:\tenabled",
)
FORBIDDEN_COMMANDS = {
    "write", "write-partition", "write-partition-table", "write-parameter",
    "erase-flash", "upgrade-loader", "change-storage", "test-device",
    "reset", "reboot", "reboot-maskrom", "shutdown",
}


class LoaderError(RuntimeError):
    pass


def sha256_file(file_path):
    digest = hashlib.sha256()
    with Path(file_path).open("rb") as stream:
        while True:
            block = stream.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def canonical_loader_sha256(file_path):
    content = bytearray(Path(file_path).read_bytes())
    if len(content) < 25 or content[:4] != b"BOOT":
        raise LoaderError("loader_header_invalid")
    content[RELEASE_TIME_SLICE] = b"\0" * 7
    return hashlib.sha256(content[:-4]).hexdigest()


def write_json_exclusive(file_path, value):
    data = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    descriptor = os.open(file_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
    except Exception:
        Path(file_path).unlink(missing_ok=True)
        raise


def artifact_url(spec):
    return ("https://raw.githubusercontent.com/rockchip-linux/rkbin/"
            f"{spec['commit']}/{spec['repo_path']}")


def download_artifact(destination, spec, opener=urllib.request.urlopen):
    with opener(artifact_url(spec), timeout=60) as response:
        content = response.read()
    digest = hashlib.sha256(content).hexdigest()
    if digest != spec["sha256"]:
        raise LoaderError(f"download_hash_mismatch:{destination.name}:{digest}")
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(content)


def validate_padded_payload(unpacked, original):
    unpacked = Path(unpacked).read_bytes()
    original = Path(original).read_bytes()
    if not unpacked.startswith(original):
        raise LoaderError("unpacked_payload_mismatch")
    if any(unpacked[len(original):]):
        raise LoaderError("unpacked_padding_not_zero")


def unpack_and_validate(bundle_dir, command_runner=subprocess.run):
    bundle_dir = Path(bundle_dir).resolve(strict=True)
    merger = bundle_dir / "inputs/boot_merger"
    loader = bundle_dir / LOADER_FILENAME
    if sha256_file(merger) != ARTIFACTS["boot_merger"]["sha256"]:
        raise LoaderError("boot_merger_hash_mismatch")
    with tempfile.TemporaryDirectory(prefix="r1-loader-unpack-") as temporary:
        unpacked = Path(temporary)
        completed = command_runner(
            [str(merger), "unpack", "-i", str(loader), "-o", str(unpacked)],
            capture_output=True, text=True, timeout=15, check=False, shell=False,
        )
        if completed.returncode != 0:
            raise LoaderError("loader_unpack_failed")
        if "Info:Unpack loader ok." not in completed.stdout:
            raise LoaderError("loader_unpack_success_missing")
        actual_names = {item.name for item in unpacked.iterdir() if item.is_file()}
        if actual_names != set(UNPACKED_PAYLOADS):
            raise LoaderError("loader_entry_set_mismatch")
        for unpacked_name, input_name in UNPACKED_PAYLOADS.items():
            validate_padded_payload(
                unpacked / unpacked_name, bundle_dir / "inputs" / input_name
            )


def validate_bundle(bundle_dir, command_runner=subprocess.run):
    bundle_dir = Path(bundle_dir).resolve(strict=True)
    manifest_path = bundle_dir / "loader-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("schema_version") != 1:
        raise LoaderError("unsupported_manifest")
    if (manifest.get("chip") != "RK322A"
            or manifest.get("candidate_id") != CANDIDATE_ID
            or manifest.get("loader_version") != "1.07.238"
            or manifest.get("rkbin_commit") != RKBIN_CANDIDATE_COMMIT
            or manifest.get("boot_merger_commit") != RKBIN_TOOL_COMMIT):
        raise LoaderError("loader_identity_mismatch")
    for name, spec in ARTIFACTS.items():
        candidate = bundle_dir / "inputs" / name
        if sha256_file(candidate) != spec["sha256"]:
            raise LoaderError(f"input_hash_mismatch:{name}")
    loader = bundle_dir / LOADER_FILENAME
    loader_hash = sha256_file(loader)
    canonical_hash = canonical_loader_sha256(loader)
    if manifest.get("loader_sha256") != loader_hash:
        raise LoaderError("loader_hash_mismatch")
    if (manifest.get("loader_canonical_sha256") != canonical_hash
            or canonical_hash != CANDIDATE_CANONICAL_SHA256):
        raise LoaderError("loader_canonical_hash_mismatch")
    unpack_and_validate(bundle_dir, command_runner)
    return loader, loader_hash, canonical_hash


def prepare_bundle(output_dir, opener=urllib.request.urlopen,
                   command_runner=subprocess.run):
    output_dir = Path(output_dir)
    output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    inputs = output_dir / "inputs"
    inputs.mkdir(mode=0o700)
    for name, spec in ARTIFACTS.items():
        download_artifact(inputs / name, spec, opener)
    (inputs / "boot_merger").chmod(0o700)

    loader = output_dir / LOADER_FILENAME
    pack_command = [
        str(inputs / "boot_merger"), "pack", "-c-RK322A", "-v", "2.38",
        "-1", str(inputs / "rk322x_ddr_300MHz_v1.07.bin"),
        "-2", str(inputs / "rk322x_usbplug_v2.38.bin"),
        "-3", str(inputs / "rk322x_ddr_300MHz_v1.07.bin"),
        "-3", str(inputs / "rk322x_miniloader_v2.38.bin"),
        "-d", "1", "-o", str(loader),
    ]
    completed = command_runner(
        pack_command, capture_output=True, text=True, timeout=15,
        check=False, shell=False,
    )
    if completed.returncode != 0 or "Info:Pack loader ok." not in completed.stdout:
        raise LoaderError("loader_pack_failed")
    manifest = {
        "schema_version": 1,
        "device_id": DEVICE_ID,
        "chip": "RK322A",
        "candidate_id": CANDIDATE_ID,
        "loader_version": "1.07.238",
        "rkbin_commit": RKBIN_CANDIDATE_COMMIT,
        "boot_merger_commit": RKBIN_TOOL_COMMIT,
        "loader_sha256": sha256_file(loader),
        "loader_canonical_sha256": canonical_loader_sha256(loader),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "inputs": {name: {**spec, "url": artifact_url(spec)}
                   for name, spec in ARTIFACTS.items()},
        "pack_arguments": pack_command[1:],
        "distribution": "local_only",
    }
    write_json_exclusive(output_dir / "loader-manifest.json", manifest)
    validate_bundle(output_dir, command_runner)
    return manifest


def validate_attempt_history(history_dir, loader_hash, canonical_hash):
    history_dir = Path(history_dir).resolve(strict=True)
    if not history_dir.is_dir():
        raise LoaderError("attempt_history_not_directory")
    evidence_files = sorted(history_dir.rglob("ram-loader-probe.json"))
    for evidence_path in evidence_files:
        try:
            evidence = json.loads(evidence_path.read_text())
        except (OSError, json.JSONDecodeError) as error:
            raise LoaderError(f"attempt_history_invalid:{evidence_path.name}") from error
        if not isinstance(evidence, dict):
            raise LoaderError(f"attempt_history_invalid:{evidence_path.name}")
        commands = evidence.get("commands", [])
        if not isinstance(commands, list):
            raise LoaderError(f"attempt_history_invalid:{evidence_path.name}")
        sent_boot = any(
            isinstance(record, dict)
            and isinstance(record.get("arguments"), list)
            and record["arguments"][:1] == ["boot"]
            for record in commands
        )
        same_candidate = (
            evidence.get("candidate_id") == CANDIDATE_ID
            or evidence.get("loader_canonical_sha256") == canonical_hash
            or evidence.get("loader_sha256") == loader_hash
        )
        if sent_boot and same_candidate:
            raise LoaderError(f"loader_candidate_already_attempted:{CANDIDATE_ID}")
    return evidence_files


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
        devices.append({
            "sysfs_name": entry.name,
            "vid_pid": VID_PID,
            "busnum": (entry / "busnum").read_text().strip(),
            "devnum": (entry / "devnum").read_text().strip(),
            "usb_version": (entry / "version").read_text().strip(),
            "mode": ({"2.00": "Maskrom", "2.01": "Loader"}.get(
                (entry / "version").read_text().strip(), "Unknown"
            )),
        })
    return devices


def require_one_device(device_provider=rockusb_devices):
    devices = device_provider()
    if len(devices) != 1:
        raise LoaderError(f"expected_one_rockusb_device:found_{len(devices)}")
    return devices[0]


def invoke(tool, arguments, use_sudo, timeout, command_runner=subprocess.run):
    if any(argument in FORBIDDEN_COMMANDS for argument in arguments):
        raise LoaderError("forbidden_command")
    argv = [str(tool), *arguments]
    if use_sudo:
        transfer_timeout = max(1, timeout - 4)
        argv = [
            "sudo", "--", "/usr/bin/timeout", "--signal=TERM",
            "--kill-after=2", str(transfer_timeout), *argv,
        ]
    started = time.monotonic()
    try:
        completed = command_runner(
            argv, capture_output=True, text=True, timeout=timeout,
            check=False, shell=False,
        )
    except subprocess.TimeoutExpired as error:
        raise LoaderError(f"command_timeout:{arguments[0]}") from error
    return {
        "arguments": arguments,
        "duration_seconds": round(time.monotonic() - started, 3),
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def require_mode(record, expected):
    if record["exit_code"] != 0 or expected not in record["stdout"]:
        raise LoaderError(f"expected_{expected.lower()}_mode")
    other = "Loader" if expected == "Maskrom" else "Maskrom"
    if other in record["stdout"]:
        raise LoaderError("ambiguous_rockusb_mode")


def run_load_probe(tool, bundle_dir, output_dir, attempt_history, use_sudo=False, timeout=15,
                   device_provider=rockusb_devices, command_runner=subprocess.run,
                   bundle_validator=validate_bundle):
    tool = Path(tool).resolve(strict=True)
    if sha256_file(tool) != RKDEVELOPTOOL_SHA256:
        raise LoaderError("rkdeveloptool_hash_mismatch")
    loader, loader_hash, canonical_hash = bundle_validator(bundle_dir, command_runner)
    history_files = validate_attempt_history(attempt_history, loader_hash, canonical_hash)
    output_dir = Path(output_dir)
    output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    evidence = {
        "schema_version": 1,
        "device_id": DEVICE_ID,
        "candidate_id": CANDIDATE_ID,
        "loader_sha256": loader_hash,
        "loader_canonical_sha256": canonical_hash,
        "attempt_history": {
            "directory": str(Path(attempt_history).resolve(strict=True)),
            "evidence_files_checked": len(history_files),
        },
        "started_at": datetime.now(timezone.utc).isoformat(),
        "commands": [],
        "status": "running",
    }

    def checked_invoke(arguments):
        require_one_device(device_provider)
        record = invoke(tool, arguments, use_sudo, timeout, command_runner)
        evidence["commands"].append(record)
        require_one_device(device_provider)
        if record["exit_code"] != 0:
            raise LoaderError(f"command_failed:{arguments[0]}")
        return record

    try:
        evidence["initial_usb"] = require_one_device(device_provider)
        if evidence["initial_usb"].get("mode") != "Maskrom":
            raise LoaderError(
                f"initial_usb_mode_not_maskrom:{evidence['initial_usb'].get('mode')}"
            )
        before = checked_invoke(["list"])
        require_mode(before, "Maskrom")
        # A successful RAM boot intentionally re-enumerates USB, so do not
        # require the old device node to survive this one command.
        require_one_device(device_provider)
        boot_record = invoke(
            tool, ["boot", str(loader)], use_sudo, timeout, command_runner
        )
        evidence["commands"].append(boot_record)
        if boot_record["exit_code"] != 0:
            raise LoaderError("command_failed:boot")

        deadline = time.monotonic() + 10
        while True:
            try:
                require_one_device(device_provider)
            except LoaderError:
                if time.monotonic() >= deadline:
                    raise LoaderError("loader_usb_reenumeration_timeout")
                time.sleep(0.25)
                continue
            after = checked_invoke(["list"])
            if "Loader" in after["stdout"] and "Maskrom" not in after["stdout"]:
                break
            if time.monotonic() >= deadline:
                raise LoaderError("loader_mode_timeout")
            time.sleep(0.25)
        evidence["loader_usb"] = require_one_device(device_provider)

        for command in READ_COMMANDS:
            checked_invoke([command])
        capability = next(
            record["stdout"] for record in evidence["commands"]
            if record["arguments"] == ["read-capability"]
        )
        missing_capabilities = [
            name for name in REQUIRED_CAPABILITIES if name not in capability
        ]
        evidence["required_capabilities"] = {
            "expected": list(REQUIRED_CAPABILITIES),
            "missing": missing_capabilities,
        }
        if missing_capabilities:
            raise LoaderError(f"required_capability_missing:{missing_capabilities}")
        flash_info = evidence["commands"][-1]["stdout"]
        match = re.search(r"Flash Size:\s*(\d+) MB", flash_info)
        if not match:
            raise LoaderError("flash_capacity_missing")
        capacity_mb = int(match.group(1))
        evidence["flash_capacity_mb"] = capacity_mb
        if not 7000 <= capacity_mb <= 9000:
            raise LoaderError(f"flash_capacity_unexpected:{capacity_mb}")
        checked_invoke(["list-partitions"])
        evidence["status"] = "pass"
        evidence["final_usb"] = require_one_device(device_provider)
    except Exception as error:
        evidence["status"] = "stopped"
        evidence["error"] = str(error)
        raise
    finally:
        evidence["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_json_exclusive(output_dir / "ram-loader-probe.json", evidence)
    return evidence


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="Build and validate the local-only loader")
    prepare.add_argument("--output", required=True)
    load = commands.add_parser("load-probe", help="Load once to RAM and run fixed reads")
    load.add_argument("--tool", required=True)
    load.add_argument("--bundle", required=True)
    load.add_argument("--output", required=True)
    load.add_argument("--attempt-history", required=True)
    load.add_argument("--device-id", required=True)
    load.add_argument("--use-sudo", action="store_true")
    load.add_argument("--timeout", type=int, default=15)
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "prepare":
            manifest = prepare_bundle(args.output)
            print(f"RAM loader prepared: {manifest['loader_sha256']}")
            return 0
        if args.device_id != DEVICE_ID:
            raise LoaderError("device_id_must_be_r1-sample01")
        if not 1 <= args.timeout <= 60:
            raise LoaderError("timeout_must_be_1_to_60")
        result = run_load_probe(
            args.tool, args.bundle, args.output, args.attempt_history,
            args.use_sudo, args.timeout
        )
        print(f"RAM loader probe: {result['status']}")
        return 0
    except (LoaderError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"RAM loader operation stopped: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
