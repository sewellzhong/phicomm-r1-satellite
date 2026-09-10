#!/usr/bin/env python3
"""Guarded, fixed-range RockUSB reads for r1-sample01.

The transport utility is powerful enough to erase or rewrite a device.  This
wrapper therefore exposes only reviewed fixed sequences, verifies the binary,
never invokes a shell, and checks that the expected RockUSB mode remains
present before and after every command.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime, timezone
import re
import shutil
import stat


DEVICE_ID = "r1-sample01"
MASKROM_VID = "2207"
MASKROM_PID = "320b"
COMMANDS = (
    "list",
    "read-chip-info",
)
LOADER_STORAGE_HEADER_BYTES = 34 * 512
ALIGNMENT_READS = ((8192, 4096), (16384, 4096))
IMAGE_PHYSICAL_OFFSET_SECTORS = 8192
IMAGE_CHUNK_BYTES = 64 * 1024 * 1024
FIRST4M_BYTES = 4 * 1024 * 1024
KNOWN_PARAMETER_SHA256 = "c08d07d28418244174f1e6cc58bdaae5160c2e4de34acc191a38a825fd186337"
RAM_LOADER_CANDIDATE_ID = "rk322x-v1.07.238"
RAM_LOADER_CANONICAL_SHA256 = "0f0dfe0653c810474d892fc6cc95788b4007d17dd60581359d15748e34d747e1"
APPROVED_BINARIES = {
    "f654a31633ddc83411b19405e8c4afb5fb024f1d869f6a86b4ab0a5bae71e7b4": {
        "package": "rkdeveloptool",
        "package_version": "1.32+pine64git20240226.17823e9-1",
        "package_sha256": "18958ac375221ad94ef38a12608f6ec6cd41ff4a81c90e8e899337dd1d9d899d",
        "source_commit": "eae601ed47d35fd5965188942077df377c4b02b7",
    }
}
DIRECT_READ_BINARIES = {
    "9f7c6fa417406f9fd0a1f13c95a6ce4b3497ce888832585295b68914705c25e1": {
        "package": "rkdeveloptool-direct-read-local",
        "upstream_commit": "17823e99898131a234ccdb39ad114dbaeebb7fc3",
        "patch_sha256": "cbf3bc5a12e01c27d98000a28ae8ee3ac658b24c4004b936b0270697dc6214d8",
        "change": "generic read uses RWMETHOD_LBA instead of RWMETHOD_IMAGE",
    }
}


class ProbeError(RuntimeError):
    pass


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            block = stream.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def rockusb_devices(sysfs_root=Path("/sys/bus/usb/devices")):
    devices = []
    if not sysfs_root.is_dir():
        return devices
    for entry in sorted(sysfs_root.iterdir()):
        try:
            vendor = (entry / "idVendor").read_text().strip().lower()
            product = (entry / "idProduct").read_text().strip().lower()
        except (FileNotFoundError, OSError):
            continue
        if (vendor, product) != (MASKROM_VID, MASKROM_PID):
            continue
        record = {"sysfs_name": entry.name, "vid_pid": f"{vendor}:{product}"}
        for name in ("busnum", "devnum", "speed"):
            try:
                record[name] = (entry / name).read_text().strip()
            except (FileNotFoundError, OSError):
                record[name] = None
        try:
            record["usb_version"] = (entry / "version").read_text().strip()
        except (FileNotFoundError, OSError):
            record["usb_version"] = None
        record["mode"] = {"2.00": "Maskrom", "2.01": "Loader"}.get(
            record["usb_version"], "Unknown"
        )
        devices.append(record)
    return devices


def require_single_rockusb(device_provider=rockusb_devices):
    devices = device_provider()
    if len(devices) != 1:
        raise ProbeError(f"expected_one_rockusb_device:found_{len(devices)}")
    return devices[0]


def write_json_exclusive(path, value):
    data = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
    except Exception:
        Path(path).unlink(missing_ok=True)
        raise


def secure_local_file(path, use_sudo, command_runner=subprocess.run):
    path = Path(path)
    mode = os.lstat(path).st_mode
    if not stat.S_ISREG(mode) or stat.S_ISLNK(mode):
        raise ProbeError(f"output_not_regular_file:{path}")
    if path.stat().st_uid != os.getuid():
        if not use_sudo:
            raise ProbeError(f"output_owner_mismatch:{path}")
        completed = command_runner(
            ["sudo", "--", "/usr/bin/chown", f"{os.getuid()}:{os.getgid()}", str(path)],
            capture_output=True, text=True, timeout=10, check=False, shell=False,
        )
        if completed.returncode != 0:
            raise ProbeError(f"output_chown_failed:{path}:{completed.returncode}")
    os.chmod(path, 0o600)


def run_probe(binary, output_dir, use_sudo=False, timeout=15,
              approved_binaries=APPROVED_BINARIES,
              device_provider=rockusb_devices, command_runner=subprocess.run):
    binary = Path(binary).resolve(strict=True)
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise ProbeError("tool_not_executable")
    binary_hash = sha256_file(binary)
    metadata = approved_binaries.get(binary_hash)
    if metadata is None:
        raise ProbeError(f"unapproved_tool_sha256:{binary_hash}")

    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    result = {
        "schema_version": 1,
        "device_id": DEVICE_ID,
        "expected_vid_pid": f"{MASKROM_VID}:{MASKROM_PID}",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "tool": {"path": str(binary), "sha256": binary_hash, **metadata},
        "commands": [],
        "status": "running",
    }

    try:
        result["initial_usb"] = require_single_rockusb(device_provider)
        result["observed_initial_mode"] = result["initial_usb"].get("mode")
        for command in COMMANDS:
            before = require_single_rockusb(device_provider)
            argv = [str(binary), command]
            if use_sudo:
                argv = ["sudo", "--", *argv]
            started = time.monotonic()
            try:
                completed = command_runner(
                    argv, capture_output=True, text=True, timeout=timeout,
                    check=False, shell=False,
                )
                record = {
                    "command": command,
                    "duration_seconds": round(time.monotonic() - started, 3),
                    "exit_code": completed.returncode,
                    "stdout": completed.stdout,
                    "stderr": completed.stderr,
                    "usb_before": before,
                }
            except subprocess.TimeoutExpired as error:
                record = {
                    "command": command,
                    "duration_seconds": round(time.monotonic() - started, 3),
                    "error": "timeout",
                    "stdout": error.stdout or "",
                    "stderr": error.stderr or "",
                    "usb_before": before,
                }
                result["commands"].append(record)
                try:
                    record["usb_after"] = require_single_rockusb(device_provider)
                except ProbeError as usb_error:
                    record["usb_after_error"] = str(usb_error)
                raise ProbeError(f"command_timeout:{command}") from error

            result["commands"].append(record)
            record["usb_after"] = require_single_rockusb(device_provider)
            if record["usb_after"].get("mode") != result["observed_initial_mode"]:
                raise ProbeError("rockusb_mode_changed")

        result["final_usb"] = require_single_rockusb(device_provider)
        failed = [item["command"] for item in result["commands"]
                  if item.get("exit_code") != 0]
        result["status"] = "pass" if not failed else "partial"
        result["unsupported_or_failed_commands"] = failed
    except Exception as error:
        result["status"] = "stopped"
        result["error"] = str(error)
        raise
    finally:
        result["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_json_exclusive(output_dir / "probe.json", result)
    return result


def run_bounded_command(binary, arguments, use_sudo, timeout,
                        command_runner=subprocess.run):
    argv = [str(binary), *arguments]
    outer_timeout = timeout
    if use_sudo:
        transfer_timeout = max(1, timeout - 4)
        argv = [
            "sudo", "--", "/usr/bin/timeout", "--signal=TERM",
            "--kill-after=2", str(transfer_timeout), *argv,
        ]
    started = time.monotonic()
    try:
        completed = command_runner(
            argv, capture_output=True, text=True, timeout=outer_timeout,
            check=False, shell=False,
        )
    except subprocess.TimeoutExpired as error:
        return {
            "arguments": arguments,
            "duration_seconds": round(time.monotonic() - started, 3),
            "error": "outer_timeout",
            "stdout": error.stdout or "",
            "stderr": error.stderr or "",
        }
    return {
        "arguments": arguments,
        "duration_seconds": round(time.monotonic() - started, 3),
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def require_loader(device_provider):
    device = require_single_rockusb(device_provider)
    if device.get("mode") != "Loader" or device.get("usb_version") != "2.01":
        raise ProbeError(f"expected_loader_2.01:{device.get('mode')}:{device.get('usb_version')}")
    return device


def run_loader_storage(binary, output_dir, use_sudo=False, timeout=12,
                       approved_binaries=APPROVED_BINARIES,
                       device_provider=rockusb_devices,
                       command_runner=subprocess.run):
    binary = Path(binary).resolve(strict=True)
    binary_hash = sha256_file(binary)
    metadata = approved_binaries.get(binary_hash)
    if metadata is None:
        raise ProbeError(f"unapproved_tool_sha256:{binary_hash}")
    output_dir = Path(output_dir)
    output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    result = {
        "schema_version": 1,
        "device_id": DEVICE_ID,
        "operation": "loader-storage",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "tool": {"path": str(binary), "sha256": binary_hash, **metadata},
        "commands": [],
        "status": "running",
    }

    def invoke(arguments):
        require_loader(device_provider)
        record = run_bounded_command(
            binary, arguments, use_sudo, timeout, command_runner
        )
        result["commands"].append(record)
        record["usb_after"] = require_loader(device_provider)
        if record.get("error") or record.get("exit_code") != 0:
            raise ProbeError(f"command_failed_or_timed_out:{arguments[0]}")
        return record

    try:
        result["initial_usb"] = require_loader(device_provider)
        listing = invoke(["list"])
        if "Loader" not in listing["stdout"] or "Maskrom" in listing["stdout"]:
            raise ProbeError("rkdeveloptool_did_not_confirm_loader")
        flash = invoke(["read-flash-info"])
        match = re.search(r"Flash Size:\s*(\d+) MB", flash["stdout"])
        if not match:
            raise ProbeError("flash_capacity_missing")
        result["flash_capacity_mb"] = int(match.group(1))
        if not 7000 <= result["flash_capacity_mb"] <= 9000:
            raise ProbeError(f"flash_capacity_unexpected:{result['flash_capacity_mb']}")

        headers = []
        for suffix in ("a", "b"):
            header = (output_dir / f"first-34-sectors-{suffix}.bin").resolve()
            invoke(["read", "0", str(LOADER_STORAGE_HEADER_BYTES), str(header)])
            if not header.is_file() or header.stat().st_size != LOADER_STORAGE_HEADER_BYTES:
                raise ProbeError(f"header_size_mismatch:{suffix}")
            headers.append({
                "file": header.name,
                "size": header.stat().st_size,
                "sha256": sha256_file(header),
            })
        result["headers"] = headers
        if headers[0]["sha256"] != headers[1]["sha256"]:
            raise ProbeError("header_reread_hash_mismatch")
        invoke(["list-partitions"])
        result["final_usb"] = require_loader(device_provider)
        result["status"] = "pass"
    except Exception as error:
        result["status"] = "stopped"
        result["error"] = str(error)
        raise
    finally:
        result["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_json_exclusive(output_dir / "loader-storage.json", result)
    return result


def validate_android_inventory(path):
    path = Path(path).resolve(strict=True)
    value = json.loads(path.read_text())
    if value.get("device_id") != DEVICE_ID:
        raise ProbeError("android_inventory_device_mismatch")
    if value.get("status") not in ("pass", "pass_with_access_limits"):
        raise ProbeError("android_inventory_not_passed")
    emmc = value.get("emmc", {})
    if emmc.get("sectors") != 15269888 or emmc.get("logical_block_bytes") != 512:
        raise ProbeError("android_inventory_geometry_mismatch")
    partitions = value.get("partitions", [])
    if len(partitions) != 16 or partitions[-1].get("end_sector_exclusive") != 15269888:
        raise ProbeError("android_inventory_layout_incomplete")
    return path, value


def run_loader_known_header(binary, inventory, output_dir, use_sudo=False, timeout=12,
                            approved_binaries=APPROVED_BINARIES,
                            device_provider=rockusb_devices,
                            command_runner=subprocess.run,
                            operation="loader-known-header", start_sector=0):
    """Read only the fixed first 34 sectors after validating Android geometry."""
    binary = Path(binary).resolve(strict=True)
    binary_hash = sha256_file(binary)
    metadata = approved_binaries.get(binary_hash)
    if metadata is None:
        raise ProbeError(f"unapproved_tool_sha256:{binary_hash}")
    inventory_path, inventory_value = validate_android_inventory(inventory)
    output_dir = Path(output_dir)
    output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    result = {
        "schema_version": 1,
        "device_id": DEVICE_ID,
        "operation": operation,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "tool": {"path": str(binary), "sha256": binary_hash, **metadata},
        "android_inventory": {
            "path": str(inventory_path),
            "sha256": sha256_file(inventory_path),
            "sectors": inventory_value["emmc"]["sectors"],
            "logical_block_bytes": inventory_value["emmc"]["logical_block_bytes"],
        },
        "start_sector": start_sector,
        "commands": [],
        "status": "running",
    }

    def invoke(arguments):
        require_loader(device_provider)
        record = run_bounded_command(binary, arguments, use_sudo, timeout, command_runner)
        result["commands"].append(record)
        record["usb_after"] = require_loader(device_provider)
        if record.get("error") or record.get("exit_code") != 0:
            raise ProbeError(f"command_failed_or_timed_out:{arguments[0]}")
        return record

    try:
        result["initial_usb"] = require_loader(device_provider)
        listing = invoke(["list"])
        if "Loader" not in listing["stdout"] or "Maskrom" in listing["stdout"]:
            raise ProbeError("rkdeveloptool_did_not_confirm_loader")
        headers = []
        for suffix in ("a", "b"):
            header = (output_dir / f"first-34-sectors-{suffix}.bin").resolve()
            invoke(["read", str(start_sector), str(LOADER_STORAGE_HEADER_BYTES), str(header)])
            if not header.is_file() or header.stat().st_size != LOADER_STORAGE_HEADER_BYTES:
                raise ProbeError(f"header_size_mismatch:{suffix}")
            headers.append({
                "file": header.name,
                "size": header.stat().st_size,
                "sha256": sha256_file(header),
            })
        result["headers"] = headers
        if headers[0]["sha256"] != headers[1]["sha256"]:
            raise ProbeError("header_reread_hash_mismatch")
        result["final_usb"] = require_loader(device_provider)
        result["status"] = "pass"
    except Exception as error:
        result["status"] = "stopped"
        result["error"] = str(error)
        raise
    finally:
        result["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_json_exclusive(output_dir / f"{operation}.json", result)
    return result


def run_loader_alignment(binary, inventory, output_dir, use_sudo=False, timeout=12,
                         approved_binaries=APPROVED_BINARIES,
                         device_provider=rockusb_devices,
                         command_runner=subprocess.run,
                         operation="loader-image-alignment"):
    binary = Path(binary).resolve(strict=True)
    binary_hash = sha256_file(binary)
    metadata = approved_binaries.get(binary_hash)
    if metadata is None:
        raise ProbeError(f"unapproved_tool_sha256:{binary_hash}")
    inventory_path, _ = validate_android_inventory(inventory)
    output_dir = Path(output_dir)
    output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    result = {
        "schema_version": 1,
        "device_id": DEVICE_ID,
        "operation": operation,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "tool": {"path": str(binary), "sha256": binary_hash, **metadata},
        "android_inventory": {"path": str(inventory_path), "sha256": sha256_file(inventory_path)},
        "fixed_ranges": [{"start_sector": start, "bytes": length} for start, length in ALIGNMENT_READS],
        "commands": [],
        "reads": [],
        "status": "running",
    }

    def invoke(arguments):
        require_loader(device_provider)
        record = run_bounded_command(binary, arguments, use_sudo, timeout, command_runner)
        result["commands"].append(record)
        record["usb_after"] = require_loader(device_provider)
        if record.get("error") or record.get("exit_code") != 0:
            raise ProbeError(f"command_failed_or_timed_out:{arguments[0]}")
        return record

    try:
        result["initial_usb"] = require_loader(device_provider)
        listing = invoke(["list"])
        if "Loader" not in listing["stdout"] or "Maskrom" in listing["stdout"]:
            raise ProbeError("rkdeveloptool_did_not_confirm_loader")
        for start, length in ALIGNMENT_READS:
            copies = []
            for suffix in ("a", "b"):
                target = (output_dir / f"sector-{start}-{suffix}.bin").resolve()
                invoke(["read", str(start), str(length), str(target)])
                if not target.is_file() or target.stat().st_size != length:
                    raise ProbeError(f"alignment_size_mismatch:{start}:{suffix}")
                copies.append({"file": target.name, "size": length, "sha256": sha256_file(target)})
            if copies[0]["sha256"] != copies[1]["sha256"]:
                raise ProbeError(f"alignment_reread_hash_mismatch:{start}")
            result["reads"].append({"start_sector": start, "bytes": length, "copies": copies})
        result["final_usb"] = require_loader(device_provider)
        result["status"] = "pass"
    except Exception as error:
        result["status"] = "stopped"
        result["error"] = str(error)
        raise
    finally:
        result["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_json_exclusive(output_dir / f"{operation}.json", result)
    return result


def run_loader_image_copy(binary, inventory, output_dir, use_sudo=False, timeout=60,
                          approved_binaries=APPROVED_BINARIES,
                          device_provider=rockusb_devices,
                          command_runner=subprocess.run,
                          image_offset_sectors=IMAGE_PHYSICAL_OFFSET_SECTORS,
                          chunk_bytes=IMAGE_CHUNK_BYTES):
    """Read and re-read the fixed image address space in bounded chunks."""
    binary = Path(binary).resolve(strict=True)
    binary_hash = sha256_file(binary)
    metadata = approved_binaries.get(binary_hash)
    if metadata is None:
        raise ProbeError(f"unapproved_tool_sha256:{binary_hash}")
    inventory_path, inventory_value = validate_android_inventory(inventory)
    logical = inventory_value["emmc"]["logical_block_bytes"]
    physical_sectors = inventory_value["emmc"]["sectors"]
    if image_offset_sectors < 0 or image_offset_sectors >= physical_sectors:
        raise ProbeError("invalid_image_offset")
    if chunk_bytes <= 0 or chunk_bytes % logical:
        raise ProbeError("invalid_chunk_size")
    image_sectors = physical_sectors - image_offset_sectors
    image_bytes = image_sectors * logical
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    for name in ("copy-a", "copy-b"):
        (output_dir / name).mkdir(mode=0o700)
    required_bytes = image_bytes * 2 + 1024 * 1024 * 1024
    if shutil.disk_usage(output_dir).free < required_bytes:
        raise ProbeError(f"insufficient_free_space:required_{required_bytes}")
    result = {
        "schema_version": 1,
        "device_id": DEVICE_ID,
        "operation": "loader-image-copy",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "tool": {"path": str(binary), "sha256": binary_hash, **metadata},
        "android_inventory": {"path": str(inventory_path), "sha256": sha256_file(inventory_path)},
        "address_space": {
            "loader_start_sector": 0,
            "image_sectors": image_sectors,
            "image_bytes": image_bytes,
            "physical_offset_sectors_inferred": image_offset_sectors,
            "physical_prefix_not_included_bytes": image_offset_sectors * logical,
        },
        "chunk_bytes": chunk_bytes,
        "commands": [],
        "chunks": [],
        "status": "running",
    }

    def invoke(arguments):
        require_loader(device_provider)
        record = run_bounded_command(binary, arguments, use_sudo, timeout, command_runner)
        result["commands"].append(record)
        record["usb_after"] = require_loader(device_provider)
        if record.get("error") or record.get("exit_code") != 0:
            raise ProbeError(f"command_failed_or_timed_out:{arguments[0]}")
        return record

    try:
        result["initial_usb"] = require_loader(device_provider)
        listing = invoke(["list"])
        if "Loader" not in listing["stdout"] or "Maskrom" in listing["stdout"]:
            raise ProbeError("rkdeveloptool_did_not_confirm_loader")
        completed_bytes = 0
        index = 0
        while completed_bytes < image_bytes:
            length = min(chunk_bytes, image_bytes - completed_bytes)
            start_sector = completed_bytes // logical
            copies = []
            for label in ("a", "b"):
                target = (output_dir / f"copy-{label}" / f"chunk-{index:04d}.bin").resolve()
                invoke(["read", str(start_sector), str(length), str(target)])
                if not target.is_file() or target.stat().st_size != length:
                    raise ProbeError(f"chunk_size_mismatch:{index}:{label}")
                secure_local_file(target, use_sudo)
                copies.append({
                    "storage_id": f"local-copy-{label}",
                    "file": str(target.relative_to(output_dir)),
                    "size": length,
                    "sha256": sha256_file(target),
                })
            if copies[0]["sha256"] != copies[1]["sha256"]:
                raise ProbeError(f"chunk_reread_hash_mismatch:{index}")
            result["chunks"].append({
                "index": index,
                "start_sector": start_sector,
                "sectors": length // logical,
                "bytes": length,
                "copies": copies,
            })
            completed_bytes += length
            index += 1
            print(json.dumps({
                "chunk": index,
                "completed_bytes": completed_bytes,
                "total_bytes": image_bytes,
            }, sort_keys=True), flush=True)
        result["final_usb"] = require_loader(device_provider)
        result["status"] = "pass"
    except Exception as error:
        result["status"] = "stopped"
        result["error"] = str(error)
        raise
    finally:
        result["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_json_exclusive(output_dir / "loader-image-copy.json", result)
    return result


def verify_loader_image_copy(evidence, output):
    evidence = Path(evidence).resolve(strict=True)
    root = evidence.parent
    source = json.loads(evidence.read_text())
    if source.get("device_id") != DEVICE_ID or source.get("operation") != "loader-image-copy":
        raise ProbeError("image_copy_evidence_identity_mismatch")
    if source.get("status") != "pass":
        raise ProbeError("image_copy_evidence_not_passed")
    expected_bytes = source.get("address_space", {}).get("image_bytes")
    chunks = source.get("chunks")
    if not isinstance(expected_bytes, int) or expected_bytes <= 0 or not isinstance(chunks, list):
        raise ProbeError("image_copy_evidence_invalid")
    result = {
        "schema_version": 1,
        "device_id": DEVICE_ID,
        "operation": "verify-loader-image-copy",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "source": {"path": str(evidence), "sha256": sha256_file(evidence)},
        "expected_bytes_per_copy": expected_bytes,
        "chunks_checked": 0,
        "status": "running",
    }
    digests = {"local-copy-a": hashlib.sha256(), "local-copy-b": hashlib.sha256()}
    cursor = 0
    try:
        for expected_index, chunk in enumerate(chunks):
            if chunk.get("index") != expected_index or chunk.get("start_sector") != cursor // 512:
                raise ProbeError(f"chunk_sequence_invalid:{expected_index}")
            length = chunk.get("bytes")
            if not isinstance(length, int) or length <= 0 or length % 512:
                raise ProbeError(f"chunk_length_invalid:{expected_index}")
            copies = chunk.get("copies")
            if not isinstance(copies, list) or [copy.get("storage_id") for copy in copies] != ["local-copy-a", "local-copy-b"]:
                raise ProbeError(f"chunk_copies_invalid:{expected_index}")
            observed_hashes = []
            for copy in copies:
                relative = Path(copy.get("file", ""))
                if relative.is_absolute() or ".." in relative.parts:
                    raise ProbeError(f"chunk_path_invalid:{expected_index}")
                path = (root / relative).resolve(strict=True)
                try:
                    path.relative_to(root)
                except ValueError as error:
                    raise ProbeError(f"chunk_path_escape:{expected_index}") from error
                file_stat = os.lstat(path)
                if not stat.S_ISREG(file_stat.st_mode) or stat.S_ISLNK(file_stat.st_mode):
                    raise ProbeError(f"chunk_not_regular:{expected_index}")
                if file_stat.st_uid != os.getuid() or stat.S_IMODE(file_stat.st_mode) != 0o600:
                    raise ProbeError(f"chunk_permissions_invalid:{expected_index}")
                if file_stat.st_size != length or copy.get("size") != length:
                    raise ProbeError(f"chunk_size_invalid:{expected_index}")
                per_file = hashlib.sha256()
                with path.open("rb") as stream:
                    while block := stream.read(1024 * 1024):
                        per_file.update(block)
                        digests[copy["storage_id"]].update(block)
                observed = per_file.hexdigest()
                if observed != copy.get("sha256"):
                    raise ProbeError(f"chunk_hash_invalid:{expected_index}:{copy['storage_id']}")
                observed_hashes.append(observed)
            if observed_hashes[0] != observed_hashes[1]:
                raise ProbeError(f"chunk_copy_mismatch:{expected_index}")
            cursor += length
            result["chunks_checked"] += 1
        if cursor != expected_bytes:
            raise ProbeError(f"image_size_mismatch:{cursor}:{expected_bytes}")
        overall = {name: digest.hexdigest() for name, digest in digests.items()}
        if len(set(overall.values())) != 1:
            raise ProbeError("overall_copy_hash_mismatch")
        result["bytes_checked_per_copy"] = cursor
        result["overall_sha256"] = overall
        result["status"] = "pass"
    except Exception as error:
        result["status"] = "stopped"
        result["error"] = str(error)
        raise
    finally:
        result["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_json_exclusive(output, result)
    return result


def validate_ram_loader_probe(path):
    path = Path(path).resolve(strict=True)
    value = json.loads(path.read_text())
    if value.get("device_id") != DEVICE_ID or value.get("status") != "pass":
        raise ProbeError("ram_loader_probe_not_passed")
    if value.get("candidate_id") != RAM_LOADER_CANDIDATE_ID:
        raise ProbeError("ram_loader_candidate_mismatch")
    if value.get("loader_canonical_sha256") != RAM_LOADER_CANONICAL_SHA256:
        raise ProbeError("ram_loader_hash_mismatch")
    required = value.get("required_capabilities", {})
    if required.get("missing") != []:
        raise ProbeError("ram_loader_first4m_capability_missing")
    expected = set(required.get("expected", []))
    if not {"Direct LBA:\tenabled", "First 4m Access:\tenabled", "Read LBA:\tenabled"}.issubset(expected):
        raise ProbeError("ram_loader_capability_evidence_incomplete")
    return path, value


def run_loader_first4m(binary, inventory, ram_probe, output_dir, use_sudo=False,
                       timeout=60, approved_binaries=DIRECT_READ_BINARIES,
                       device_provider=rockusb_devices,
                       command_runner=subprocess.run):
    binary = Path(binary).resolve(strict=True)
    binary_hash = sha256_file(binary)
    metadata = approved_binaries.get(binary_hash)
    if metadata is None:
        raise ProbeError(f"unapproved_direct_tool_sha256:{binary_hash}")
    inventory_path, inventory_value = validate_android_inventory(inventory)
    ram_path, ram_value = validate_ram_loader_probe(ram_probe)
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    result = {
        "schema_version": 1,
        "device_id": DEVICE_ID,
        "operation": "loader-first4m",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "tool": {"path": str(binary), "sha256": binary_hash, **metadata},
        "android_inventory": {"path": str(inventory_path), "sha256": sha256_file(inventory_path)},
        "ram_loader_probe": {"path": str(ram_path), "sha256": sha256_file(ram_path)},
        "ram_loader_sha256": ram_value["loader_sha256"],
        "ram_loader_canonical_sha256": ram_value["loader_canonical_sha256"],
        "physical_bytes": (
            inventory_value["emmc"]["sectors"]
            * inventory_value["emmc"]["logical_block_bytes"]
        ),
        "commands": [],
        "status": "running",
    }

    def invoke(arguments):
        require_loader(device_provider)
        record = run_bounded_command(binary, arguments, use_sudo, timeout, command_runner)
        result["commands"].append(record)
        record["usb_after"] = require_loader(device_provider)
        if record.get("error") or record.get("exit_code") != 0:
            raise ProbeError(f"command_failed_or_timed_out:{arguments[0]}")
        return record

    try:
        result["initial_usb"] = require_loader(device_provider)
        listing = invoke(["list"])
        if "Loader" not in listing["stdout"] or "Maskrom" in listing["stdout"]:
            raise ProbeError("rkdeveloptool_did_not_confirm_loader")
        copies = []
        for label in ("a", "b"):
            target = (output_dir / f"first-4m-{label}.bin").resolve()
            invoke(["read", "0", str(FIRST4M_BYTES), str(target)])
            if not target.is_file() or target.stat().st_size != FIRST4M_BYTES:
                raise ProbeError(f"first4m_size_mismatch:{label}")
            secure_local_file(target, use_sudo)
            copies.append({
                "storage_id": f"local-copy-{label}",
                "file": target.name,
                "size": target.stat().st_size,
                "sha256": sha256_file(target),
            })
        if copies[0]["sha256"] != copies[1]["sha256"]:
            raise ProbeError("first4m_reread_hash_mismatch")
        result["first4m"] = {"bytes": FIRST4M_BYTES, "copies": copies}

        mapping = []
        for label in ("a", "b"):
            target = (output_dir / f"physical-sector-8192-{label}.bin").resolve()
            invoke(["read", "8192", str(LOADER_STORAGE_HEADER_BYTES), str(target)])
            if not target.is_file() or target.stat().st_size != LOADER_STORAGE_HEADER_BYTES:
                raise ProbeError(f"parameter_mapping_size_mismatch:{label}")
            secure_local_file(target, use_sudo)
            digest = sha256_file(target)
            if digest != KNOWN_PARAMETER_SHA256:
                raise ProbeError(f"parameter_mapping_hash_mismatch:{label}:{digest}")
            mapping.append({"file": target.name, "size": target.stat().st_size, "sha256": digest})
        result["parameter_mapping"] = {
            "physical_start_sector": 8192,
            "expected_sha256": KNOWN_PARAMETER_SHA256,
            "copies": mapping,
        }
        result["final_usb"] = require_loader(device_provider)
        result["status"] = "pass"
    except Exception as error:
        result["status"] = "stopped"
        result["error"] = str(error)
        raise
    finally:
        result["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_json_exclusive(output_dir / "loader-first4m.json", result)
    return result


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    probe = commands.add_parser("probe", help="Run the fixed read-only inventory")
    probe.add_argument("--tool", required=True, help="Path to the reviewed rkdeveloptool binary")
    probe.add_argument("--output", required=True, help="New private evidence directory")
    probe.add_argument("--device-id", required=True)
    probe.add_argument("--use-sudo", action="store_true",
                       help="Use sudo only for each fixed RockUSB invocation")
    probe.add_argument("--timeout", type=int, default=15)
    storage = commands.add_parser(
        "loader-storage", help="Run the fixed Loader capacity and disk-header reads"
    )
    storage.add_argument("--tool", required=True)
    storage.add_argument("--output", required=True)
    storage.add_argument("--device-id", required=True)
    storage.add_argument("--use-sudo", action="store_true")
    storage.add_argument("--timeout", type=int, default=12)
    header = commands.add_parser(
        "loader-known-header", help="Read a fixed header using validated Android geometry"
    )
    header.add_argument("--tool", required=True)
    header.add_argument("--inventory", required=True)
    header.add_argument("--output", required=True)
    header.add_argument("--device-id", required=True)
    header.add_argument("--use-sudo", action="store_true")
    header.add_argument("--timeout", type=int, default=12)
    direct = commands.add_parser(
        "loader-direct-header", help="Read a fixed header with the audited direct-LBA build"
    )
    direct.add_argument("--tool", required=True)
    direct.add_argument("--inventory", required=True)
    direct.add_argument("--output", required=True)
    direct.add_argument("--device-id", required=True)
    direct.add_argument("--use-sudo", action="store_true")
    direct.add_argument("--timeout", type=int, default=12)
    tail = commands.add_parser(
        "loader-image-tail", help="Read the fixed final 34 sectors of image address space"
    )
    tail.add_argument("--tool", required=True)
    tail.add_argument("--inventory", required=True)
    tail.add_argument("--output", required=True)
    tail.add_argument("--device-id", required=True)
    tail.add_argument("--use-sudo", action="store_true")
    tail.add_argument("--timeout", type=int, default=12)
    image_copy = commands.add_parser(
        "loader-image-copy", help="Read the fixed image space twice in bounded chunks"
    )
    image_copy.add_argument("--tool", required=True)
    image_copy.add_argument("--inventory", required=True)
    image_copy.add_argument("--output", required=True)
    image_copy.add_argument("--device-id", required=True)
    image_copy.add_argument("--use-sudo", action="store_true")
    image_copy.add_argument("--timeout", type=int, default=60)
    verify = commands.add_parser(
        "verify-image-copy", help="Offline rehash a completed chunked image copy"
    )
    verify.add_argument("--evidence", required=True)
    verify.add_argument("--output", required=True)
    verify.add_argument("--device-id", required=True)
    first4m = commands.add_parser(
        "loader-first4m", help="Read physical first 4 MiB after proven RAM-loader capability"
    )
    first4m.add_argument("--tool", required=True)
    first4m.add_argument("--inventory", required=True)
    first4m.add_argument("--ram-probe", required=True)
    first4m.add_argument("--output", required=True)
    first4m.add_argument("--device-id", required=True)
    first4m.add_argument("--use-sudo", action="store_true")
    first4m.add_argument("--timeout", type=int, default=60)
    for name, help_text in (
        ("loader-image-alignment", "Read fixed image-LBA alignment candidates"),
        ("loader-direct-alignment", "Read fixed direct-LBA alignment candidates"),
    ):
        alignment = commands.add_parser(name, help=help_text)
        alignment.add_argument("--tool", required=True)
        alignment.add_argument("--inventory", required=True)
        alignment.add_argument("--output", required=True)
        alignment.add_argument("--device-id", required=True)
        alignment.add_argument("--use-sudo", action="store_true")
        alignment.add_argument("--timeout", type=int, default=12)
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    if args.device_id != DEVICE_ID:
        print("Refusing probe: device id must be r1-sample01", file=sys.stderr)
        return 2
    if hasattr(args, "timeout") and not 1 <= args.timeout <= 60:
        print("Refusing probe: timeout must be between 1 and 60 seconds", file=sys.stderr)
        return 2
    try:
        if args.command == "verify-image-copy":
            result = verify_loader_image_copy(args.evidence, args.output)
        elif args.command == "loader-first4m":
            result = run_loader_first4m(
                args.tool, args.inventory, args.ram_probe, args.output,
                args.use_sudo, args.timeout,
            )
        elif args.command == "probe":
            result = run_probe(args.tool, args.output, args.use_sudo, args.timeout)
        elif args.command == "loader-storage":
            result = run_loader_storage(
                args.tool, args.output, args.use_sudo, args.timeout
            )
        elif args.command == "loader-known-header":
            result = run_loader_known_header(
                args.tool, args.inventory, args.output, args.use_sudo, args.timeout
            )
        elif args.command == "loader-image-tail":
            _, inventory_value = validate_android_inventory(args.inventory)
            image_sectors = inventory_value["emmc"]["sectors"] - 8192
            result = run_loader_known_header(
                args.tool, args.inventory, args.output, args.use_sudo, args.timeout,
                operation="loader-image-tail", start_sector=image_sectors - 34,
            )
        elif args.command == "loader-direct-header":
            result = run_loader_known_header(
                args.tool, args.inventory, args.output, args.use_sudo, args.timeout,
                approved_binaries=DIRECT_READ_BINARIES,
                operation="loader-direct-header",
            )
        elif args.command == "loader-image-copy":
            result = run_loader_image_copy(
                args.tool, args.inventory, args.output, args.use_sudo, args.timeout
            )
        else:
            direct_mode = args.command == "loader-direct-alignment"
            result = run_loader_alignment(
                args.tool, args.inventory, args.output, args.use_sudo, args.timeout,
                approved_binaries=DIRECT_READ_BINARIES if direct_mode else APPROVED_BINARIES,
                operation=args.command,
            )
    except (OSError, ProbeError) as error:
        print(f"RockUSB read-only operation stopped: {error}", file=sys.stderr)
        return 1
    print(f"RockUSB read-only {args.command}: {result['status']}")
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
