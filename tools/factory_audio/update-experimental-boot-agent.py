#!/usr/bin/env python3
"""Build a device-locked R1 boot update that changes only an existing agent."""

import argparse
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / "docs/references/r1-3448-boot-baseline.json"
BASE_BUILDER = Path(__file__).with_name("build-experimental-boot.py")
AGENT_ENTRY = "sbin/r1-factory-audio-agent"

_SPEC = importlib.util.spec_from_file_location("r1_experimental_boot", BASE_BUILDER)
boot = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(boot)


class UpdateError(RuntimeError):
    pass


def require(value, message):
    if not value:
        raise UpdateError(message)


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def secure_file(path, label):
    unresolved = Path(path)
    require(not unresolved.is_symlink(), f"{label}_must_not_be_symlink")
    resolved = unresolved.resolve(strict=True)
    require(resolved.is_file(), f"{label}_not_regular_file")
    return resolved


def entry_contract(entry):
    fields = list(entry.fields)
    fields[6] = None  # payload length may change with the agent binary
    return entry.magic, entry.name, fields


def assert_agent_elf32_arm(path):
    header = subprocess.run(
        ["readelf", "-hW", str(path)], check=True, capture_output=True, text=True
    ).stdout
    require("Class:                             ELF32" in header, "agent_not_elf32")
    require("Machine:                           ARM" in header, "agent_not_arm")


def build(args):
    current_a = secure_file(args.current_boot_a, "current_boot_a")
    current_b = secure_file(args.current_boot_b, "current_boot_b")
    require(not os.path.samefile(current_a, current_b), "current_boot_copies_not_independent")
    current_manifest_path = secure_file(args.current_boot_manifest, "current_boot_manifest")
    current_overlay_path = secure_file(args.current_overlay_manifest, "current_overlay_manifest")
    agent = secure_file(args.agent, "agent")
    output = Path(args.output_dir).resolve()
    try:
        output.relative_to(ROOT)
        raise UpdateError("private_boot_output_must_be_outside_repository")
    except ValueError:
        pass
    require(not output.exists(), "boot_output_already_exists")

    reference = load(REFERENCE)
    manifest = load(current_manifest_path)
    overlay = load(current_overlay_path)
    expected_hash = args.expected_agent_sha256.lower()
    require(manifest.get("status") == "pass_for_device_locked_boot_write",
            "current_boot_manifest_status_invalid")
    require(manifest.get("device") == reference.get("device"),
            "current_boot_manifest_device_mismatch")
    require(manifest.get("partition") == {
        "name": "boot", "bytes": boot.PARTITION_BYTES,
        "loader_image_start_sector": 98304, "sectors": 24576,
    }, "current_boot_partition_contract_invalid")
    require(manifest.get("boot_id_scheme") == "rockchip_secure_ns_sha1",
            "current_boot_id_scheme_invalid")
    require(digest(current_a) == digest(current_b), "current_boot_copies_differ")
    current_hash = digest(current_a)
    require(current_hash == manifest.get("candidate_boot_sha256"),
            "current_boot_hash_not_manifest_candidate")
    require(current_a.stat().st_size == boot.PARTITION_BYTES,
            "current_boot_size_invalid")
    require(digest(current_overlay_path) == manifest.get("overlay_manifest_sha256"),
            "current_overlay_manifest_hash_mismatch")
    require(overlay.get("device") == reference.get("device"),
            "current_overlay_device_mismatch")
    require(overlay.get("authorization") == manifest.get("authorization"),
            "current_overlay_authorization_mismatch")
    require(len(expected_hash) == 64 and all(c in "0123456789abcdef" for c in expected_hash),
            "expected_agent_sha256_invalid")
    require(digest(agent) == expected_hash, "new_agent_hash_mismatch")
    assert_agent_elf32_arm(agent)

    current = current_a.read_bytes()
    values, kernel, ramdisk, second = boot.boot_parts(current)
    require(len(ramdisk) % 4 == 0, "current_ramdisk_not_rockchip_sha_aligned")
    require(current[576:596] == boot.rockchip_boot_id(current, kernel, ramdisk, second),
            "current_rockchip_boot_id_mismatch")
    entries = boot.parse_cpio(gzip.decompress(ramdisk))
    matches = [entry for entry in entries if entry.name == AGENT_ENTRY]
    require(len(matches) == 1, "current_agent_entry_not_unique")
    old_agent_hash = boot.digest_bytes(matches[0].data)
    require(old_agent_hash == overlay.get("agent_sha256"),
            "embedded_agent_hash_not_overlay")
    require(old_agent_hash != expected_hash, "agent_update_is_noop")

    before = {entry.name: (entry_contract(entry), entry.data) for entry in entries}
    require(len(before) == len(entries), "cpio_duplicate_entry")
    boot.replace(entries, AGENT_ENTRY, agent.read_bytes())
    after = {entry.name: (entry_contract(entry), entry.data) for entry in entries}
    require(set(before) == set(after), "ramdisk_entry_set_changed")
    for name in before:
        require(before[name][0] == after[name][0], f"ramdisk_metadata_changed:{name}")
        if name != AGENT_ENTRY:
            require(before[name][1] == after[name][1], f"ramdisk_payload_changed:{name}")

    new_cpio = boot.build_cpio(entries)
    new_ramdisk = gzip.compress(new_cpio, compresslevel=9, mtime=0)
    new_ramdisk += b"\0" * (boot.aligned(len(new_ramdisk), 4) - len(new_ramdisk))
    require(len(new_ramdisk) % 4 == 0, "candidate_ramdisk_not_rockchip_sha_aligned")
    page = values[7]
    header = bytearray(current[:page])
    struct.pack_into("<I", header, 16, len(new_ramdisk))
    header[576:608] = boot.rockchip_boot_id(header, kernel, new_ramdisk, second) + b"\0" * 12
    candidate = bytes(header) + kernel + b"\0" * (boot.aligned(len(kernel), page) - len(kernel))
    candidate += new_ramdisk + b"\0" * (boot.aligned(len(new_ramdisk), page) - len(new_ramdisk))
    candidate += second + b"\0" * (boot.aligned(len(second), page) - len(second))
    require(len(candidate) <= boot.PARTITION_BYTES, "updated_boot_exceeds_partition")
    candidate += b"\0" * (boot.PARTITION_BYTES - len(candidate))

    updated_values, updated_kernel, updated_ramdisk, updated_second = boot.boot_parts(candidate)
    require(updated_kernel == kernel and updated_second == second,
            "immutable_boot_component_changed")
    for index in (1, 3, 5, 6, 7):
        require(updated_values[index] == values[index], "boot_header_address_changed")
    require(candidate[576:596]
            == boot.rockchip_boot_id(candidate, updated_kernel, updated_ramdisk, updated_second),
            "candidate_rockchip_boot_id_mismatch")
    updated_entries = boot.parse_cpio(gzip.decompress(updated_ramdisk))
    updated = {entry.name: (entry_contract(entry), entry.data) for entry in updated_entries}
    require(set(updated) == set(before), "verified_ramdisk_entry_set_changed")
    for name in before:
        require(updated[name][0] == before[name][0], f"verified_ramdisk_metadata_changed:{name}")
        expected_data = agent.read_bytes() if name == AGENT_ENTRY else before[name][1]
        require(updated[name][1] == expected_data, f"verified_ramdisk_payload_changed:{name}")

    output.mkdir(mode=0o700)
    image = output / "boot-agent-update.img"
    image.write_bytes(candidate)
    os.chmod(image, 0o600)
    result = {
        "schema_version": 1,
        "status": "pass_for_device_locked_boot_write",
        "device": reference["device"],
        "partition": manifest["partition"],
        "current_boot_copy_a_sha256": current_hash,
        "current_boot_copy_b_sha256": current_hash,
        "candidate_boot_sha256": digest(image),
        "old_agent_sha256": old_agent_hash,
        "new_agent_sha256": expected_hash,
        "kernel_sha256": boot.digest_bytes(kernel),
        "second_sha256": boot.digest_bytes(second),
        "current_ramdisk_sha256": boot.digest_bytes(ramdisk),
        "candidate_ramdisk_sha256": boot.digest_bytes(new_ramdisk),
        "candidate_ramdisk_bytes": len(new_ramdisk),
        "page_size": page,
        "boot_id_scheme": "rockchip_secure_ns_sha1",
        "ramdisk_alignment_bytes": 4,
        "authorization": manifest["authorization"],
        "current_boot_manifest_sha256": digest(current_manifest_path),
        "current_overlay_manifest_sha256": digest(current_overlay_path),
        "declared_changes": ["ramdisk_agent"],
    }
    result_path = output / "manifest.json"
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(result_path, 0o600)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current-boot-a", required=True)
    parser.add_argument("--current-boot-b", required=True)
    parser.add_argument("--current-boot-manifest", required=True)
    parser.add_argument("--current-overlay-manifest", required=True)
    parser.add_argument("--agent", required=True)
    parser.add_argument("--expected-agent-sha256", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(build(args), sort_keys=True))
        return 0
    except (UpdateError, boot.BootError, OSError, ValueError, KeyError,
            json.JSONDecodeError, struct.error, subprocess.CalledProcessError) as error:
        print("Boot agent update refused: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
