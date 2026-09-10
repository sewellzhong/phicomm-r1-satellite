#!/usr/bin/env python3
"""Verify the private r1-sample01 boot baseline against its public hash record."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import sys


DEVICE_ID = "r1-sample01"
SCHEMA_VERSION = 1
BOOT_MAGIC = b"ANDROID!"


class BaselineError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise BaselineError(message)


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                return digest.hexdigest()
            digest.update(chunk)


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def safe_local_file(base, value, label, allow_parent=False):
    require(isinstance(value, str) and value, f"{label}_path_invalid")
    raw = Path(value)
    require(not raw.is_absolute(), f"{label}_path_must_be_relative")
    if not allow_parent:
        require(".." not in raw.parts and len(raw.parts) == 1, f"{label}_path_not_local")
    path = (base / raw).resolve(strict=True)
    require(path.is_file() and not path.is_symlink(), f"{label}_not_regular_file")
    return path


def parse_boot_header(path):
    with Path(path).open("rb") as handle:
        header = handle.read(16384)
    require(len(header) >= 608 and header[:8] == BOOT_MAGIC, "android_boot_header_invalid")
    values = struct.unpack_from("<8I", header, 8)
    return {
        "magic": header[:8].decode("ascii"),
        "kernel_size": values[0], "kernel_addr": values[1],
        "ramdisk_size": values[2], "ramdisk_addr": values[3],
        "second_size": values[4], "second_addr": values[5],
        "tags_addr": values[6], "page_size": values[7],
        "name": header[48:64].split(b"\0", 1)[0].decode("ascii", "strict"),
        "cmdline": header[64:576].split(b"\0", 1)[0].decode("ascii", "strict"),
    }


def verify(reference_path, manifest_path):
    reference_path = Path(reference_path).resolve(strict=True)
    manifest_path = Path(manifest_path).resolve(strict=True)
    reference = load_json(reference_path)
    manifest = load_json(manifest_path)
    require(reference.get("schema_version") == SCHEMA_VERSION, "reference_schema_invalid")
    require(reference.get("status") == "approved_original_input_only", "reference_not_approved")
    device = reference.get("device", {})
    require(device.get("id") == DEVICE_ID, "reference_device_mismatch")
    require(manifest.get("schema_version") == SCHEMA_VERSION, "manifest_schema_invalid")
    require(manifest.get("device_id") == DEVICE_ID, "manifest_device_mismatch")
    require(manifest.get("status") == "pass_for_offline_baseline_only", "manifest_status_invalid")
    manifest_hash = sha256_file(manifest_path)
    require(manifest_hash == reference.get("baseline_manifest_sha256"), "manifest_hash_mismatch")
    base = manifest_path.parent

    source = manifest.get("source", {})
    for key in ("inventory", "copy_manifest", "copy_verification"):
        expected = reference.get("source_evidence", {}).get(key + "_sha256")
        require(source.get(key + "_sha256") == expected, f"{key}_declared_hash_mismatch")
        source_path = safe_local_file(base, source.get(key), key, allow_parent=True)
        require(sha256_file(source_path) == expected, f"{key}_file_hash_mismatch")
    verification = load_json(safe_local_file(base, source["copy_verification"],
                                              "copy_verification", allow_parent=True))
    require(verification.get("status") == "pass", "source_copy_verification_not_passed")

    manifest_parts = {item.get("name"): item for item in manifest.get("partitions", [])}
    require(set(manifest_parts) == set(reference.get("partitions", {})), "partition_set_mismatch")
    verified = {}
    for name, expected in reference["partitions"].items():
        item = manifest_parts[name]
        require(item.get("bytes") == expected["bytes"], f"{name}_size_declaration_mismatch")
        require(item.get("sha256") == expected["sha256"], f"{name}_hash_declaration_mismatch")
        require(item.get("copies_match") is True, f"{name}_copies_not_declared_matching")
        paths = [safe_local_file(base, item.get(key), f"{name}_{key}")
                 for key in ("copy_a", "copy_b")]
        for path in paths:
            require(path.stat().st_size == expected["bytes"], f"{name}_file_size_mismatch")
            require(sha256_file(path) == expected["sha256"], f"{name}_file_hash_mismatch")
        verified[name] = {"bytes": expected["bytes"], "sha256": expected["sha256"]}

    expected_boot = reference["android_boot"]
    for name in ("boot", "recovery"):
        header = parse_boot_header(safe_local_file(base, manifest_parts[name]["copy_a"], name))
        expected_ramdisk = expected_boot[f"{name}_ramdisk_size"]
        for field in ("magic", "page_size", "kernel_size", "kernel_addr", "ramdisk_addr",
                      "second_size", "second_addr", "tags_addr"):
            require(header[field] == expected_boot[field], f"{name}_{field}_mismatch")
        require(header["ramdisk_size"] == expected_ramdisk, f"{name}_ramdisk_size_mismatch")
        require(not header["name"] and not header["cmdline"], f"{name}_unexpected_header_text")

    components = manifest.get("android_boot_images", {})
    component_specs = {
        "boot-kernel.bin": (expected_boot["kernel_size"], expected_boot["kernel_sha256"]),
        "boot-second.bin": (expected_boot["second_size"], expected_boot["second_sha256"]),
        "rk-kernel.dtb": (expected_boot["dtb_size"], expected_boot["dtb_sha256"]),
    }
    for filename, (size, digest) in component_specs.items():
        path = safe_local_file(base, filename, filename)
        require(path.stat().st_size == size, f"{filename}_size_mismatch")
        require(sha256_file(path) == digest, f"{filename}_hash_mismatch")
    require(components.get("dtb_offset") == expected_boot["dtb_offset_in_second"],
            "dtb_offset_mismatch")
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "pass",
        "device": device,
        "reference_sha256": sha256_file(reference_path),
        "baseline_manifest_sha256": manifest_hash,
        "partitions": verified,
    }


def write_exclusive(path, value):
    data = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(data)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("verify", choices=("verify",))
    parser.add_argument("--reference", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        result = verify(args.reference, args.manifest)
        write_exclusive(args.output, result)
        print("R1 boot baseline: pass")
        return 0
    except (BaselineError, FileExistsError, json.JSONDecodeError, OSError,
            UnicodeDecodeError, struct.error) as error:
        print("R1 boot baseline refused: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
