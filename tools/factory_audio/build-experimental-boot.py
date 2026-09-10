#!/usr/bin/env python3
"""Build and verify a private boot-only R1 factory-audio image; never contacts a device."""

import argparse
from dataclasses import dataclass
import gzip
import hashlib
import json
import os
from pathlib import Path
import stat
import struct
import sys


ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / "docs/references/r1-3448-boot-baseline.json"
MAGICS = (b"070701", b"070702")
TRAILER = "TRAILER!!!"
PARTITION_BYTES = 12 * 1024 * 1024


class BootError(RuntimeError):
    pass


def require(value, message):
    if not value:
        raise BootError(message)


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def aligned(value, boundary):
    return (value + boundary - 1) // boundary * boundary


@dataclass
class Entry:
    name: str
    fields: list
    data: bytes
    magic: bytes = b"070701"


def parse_cpio(data):
    entries = []
    position = 0
    while True:
        require(position + 110 <= len(data), "cpio_header_truncated")
        magic = data[position:position + 6]
        require(magic in MAGICS, "cpio_magic_invalid")
        fields = [int(data[position + 6 + index * 8:position + 14 + index * 8], 16)
                  for index in range(13)]
        position += 110
        name_size, file_size = fields[11], fields[6]
        require(name_size > 0 and position + name_size <= len(data), "cpio_name_invalid")
        raw_name = data[position:position + name_size]
        require(raw_name[-1:] == b"\0", "cpio_name_not_terminated")
        name = raw_name[:-1].decode("utf-8")
        position = aligned(position + name_size, 4)
        require(position + file_size <= len(data), "cpio_data_truncated")
        payload = data[position:position + file_size]
        position = aligned(position + file_size, 4)
        if name == TRAILER:
            require(file_size == 0, "cpio_trailer_invalid")
            break
        entries.append(Entry(name, fields, payload, magic))
    require(all(byte == 0 for byte in data[position:]), "cpio_trailing_data_nonzero")
    return entries


def emit_entry(entry):
    name = entry.name.encode("utf-8") + b"\0"
    fields = list(entry.fields)
    fields[6] = len(entry.data)
    fields[11] = len(name)
    header = entry.magic + b"".join(f"{value:08x}".encode("ascii") for value in fields)
    require(len(header) == 110, "cpio_header_size_invalid")
    result = header + name
    result += b"\0" * (aligned(len(result), 4) - len(result))
    result += entry.data
    result += b"\0" * (aligned(len(result), 4) - len(result))
    return result


def build_cpio(entries):
    content = b"".join(emit_entry(entry) for entry in entries)
    maximum_inode = max((entry.fields[0] for entry in entries), default=0)
    trailer = Entry(TRAILER, [maximum_inode + 1, stat.S_IFREG, 0, 0, 1, 0, 0,
                              0, 0, 0, 0, 0, 0], b"")
    return content + emit_entry(trailer)


def regular(name, content, inode, mode=0o644):
    return Entry(name, [inode, stat.S_IFREG | mode, 0, 0, 1, 0, len(content),
                        0, 0, 0, 0, len(name.encode()) + 1, 0], content)


def replace(entries, name, content):
    matches = [entry for entry in entries if entry.name == name]
    require(len(matches) == 1, f"cpio_entry_not_unique:{name}")
    matches[0].data = content


def add(entries, name, content, mode):
    require(all(entry.name != name for entry in entries), f"cpio_entry_already_exists:{name}")
    inode = max((entry.fields[0] for entry in entries), default=0) + 1
    entries.append(regular(name, content, inode, mode))


def boot_parts(image):
    require(len(image) == PARTITION_BYTES and image[:8] == b"ANDROID!", "original_boot_invalid")
    values = struct.unpack_from("<8I", image, 8)
    kernel_size, ramdisk_size, second_size, page = values[0], values[2], values[4], values[7]
    require(page == 16384, "boot_page_size_invalid")
    kernel_start = page
    ramdisk_start = kernel_start + aligned(kernel_size, page)
    second_start = ramdisk_start + aligned(ramdisk_size, page)
    end = second_start + aligned(second_size, page)
    require(end <= len(image) and not any(image[end:]), "original_boot_padding_invalid")
    return values, image[kernel_start:kernel_start + kernel_size], \
        image[ramdisk_start:ramdisk_start + ramdisk_size], \
        image[second_start:second_start + second_size]


def build(args):
    original_path = Path(args.original_boot).resolve(strict=True)
    overlay = Path(args.overlay_dir).resolve(strict=True)
    policy_dir = Path(args.policy_dir).resolve(strict=True)
    output = Path(args.output_dir).resolve()
    try:
        output.relative_to(ROOT)
        raise BootError("private_boot_output_must_be_outside_repository")
    except ValueError:
        pass
    require(not output.exists(), "boot_output_already_exists")
    baseline = load(args.boot_baseline_report)
    reference = load(REFERENCE)
    require(baseline.get("status") == "pass", "boot_baseline_not_passed")
    require(baseline.get("device") == reference.get("device"), "boot_baseline_device_mismatch")
    require(baseline.get("reference_sha256") == digest(REFERENCE), "boot_reference_mismatch")
    expected_boot = reference["partitions"]["boot"]
    require(digest(original_path) == expected_boot["sha256"], "original_boot_hash_mismatch")
    require(original_path.stat().st_size == expected_boot["bytes"], "original_boot_size_mismatch")
    overlay_manifest = load(overlay / "manifest.json")
    policy_manifest = load(policy_dir / "manifest.json")
    require(overlay_manifest.get("device") == reference["device"], "overlay_device_mismatch")
    authorization = overlay_manifest.get("authorization", {})
    require(authorization.get("mode") in ("r0_gate", "explicit_device_limited_risk_acceptance"),
            "overlay_authorization_invalid")
    require(overlay_manifest.get("output_channels") == 2
            and overlay_manifest.get("output_channel") == 0,
            "initial_validation_channel_contract_invalid")
    require(policy_manifest.get("status") == "pass_for_boot_staging_only"
            and policy_manifest.get("device") == reference["device"], "policy_manifest_invalid")
    agent = overlay / "sbin/r1-factory-audio-agent"
    require(digest(agent) == overlay_manifest.get("agent_sha256"), "overlay_agent_hash_mismatch")
    patched_policy = policy_dir / "sepolicy"
    require(digest(patched_policy) == policy_manifest.get("patched_policy_sha256"),
            "patched_policy_hash_mismatch")

    original = original_path.read_bytes()
    values, kernel, ramdisk, second = boot_parts(original)
    entries = parse_cpio(gzip.decompress(ramdisk))
    by_name = {entry.name: entry for entry in entries}
    require(len(by_name) == len(entries), "cpio_duplicate_entry")
    require(digest_bytes(by_name["sepolicy"].data) == policy_manifest["original_policy_sha256"],
            "ramdisk_policy_hash_mismatch")
    replace(entries, "sepolicy", patched_policy.read_bytes())
    file_contexts = by_name["file_contexts"].data
    additions = (b"\n/sbin/r1-factory-audio-agent u:object_r:r1_factory_audio:s0\n"
                 b"/dev/socket/r1_factory_audio u:object_r:r1_factory_audio:s0\n")
    require(b"r1_factory_audio" not in file_contexts, "factory_audio_context_already_present")
    replace(entries, "file_contexts", file_contexts.rstrip(b"\n") + additions)
    board_init = by_name["init.rk30board.rc"].data
    require(b"init.r1_factory_audio.rc" not in board_init, "factory_audio_init_already_imported")
    replace(entries, "init.rk30board.rc", board_init.rstrip(b"\n")
            + b"\nimport /init.r1_factory_audio.rc\n")
    add(entries, "sbin/r1-factory-audio-agent", agent.read_bytes(), 0o750)
    add(entries, "init.r1_factory_audio.rc", (overlay / "init.r1_factory_audio.rc").read_bytes(), 0o644)
    new_cpio = build_cpio(entries)
    new_ramdisk = gzip.compress(new_cpio, compresslevel=9, mtime=0)
    page = values[7]
    header = bytearray(original[:page])
    struct.pack_into("<I", header, 16, len(new_ramdisk))
    boot_id = hashlib.sha1()
    for payload in (kernel, new_ramdisk, second):
        boot_id.update(payload)
        boot_id.update(struct.pack("<I", len(payload)))
    header[576:608] = boot_id.digest() + b"\0" * 12
    candidate = bytes(header) + kernel + b"\0" * (aligned(len(kernel), page) - len(kernel))
    candidate += new_ramdisk + b"\0" * (aligned(len(new_ramdisk), page) - len(new_ramdisk))
    candidate += second + b"\0" * (aligned(len(second), page) - len(second))
    require(len(candidate) <= PARTITION_BYTES, "experimental_boot_exceeds_partition")
    candidate += b"\0" * (PARTITION_BYTES - len(candidate))
    parsed_values, parsed_kernel, parsed_ramdisk, parsed_second = boot_parts(candidate)
    require(parsed_kernel == kernel and parsed_second == second, "immutable_boot_component_changed")
    for index in (1, 3, 5, 6, 7):
        require(parsed_values[index] == values[index], "boot_header_address_changed")
    parsed_names = {entry.name for entry in parse_cpio(gzip.decompress(parsed_ramdisk))}
    require({"sbin/r1-factory-audio-agent", "init.r1_factory_audio.rc"} <= parsed_names,
            "experimental_ramdisk_entries_missing")

    output.mkdir(mode=0o700)
    image = output / "boot-experimental.img"
    image.write_bytes(candidate)
    os.chmod(image, 0o600)
    manifest = {"schema_version": 1, "status": "pass_for_device_locked_boot_write",
        "device": reference["device"], "partition": {"name": "boot", "bytes": PARTITION_BYTES,
        "loader_image_start_sector": 98304, "sectors": 24576},
        "original_boot_sha256": digest(original_path), "candidate_boot_sha256": digest(image),
        "kernel_sha256": digest_bytes(kernel), "second_sha256": digest_bytes(second),
        "original_ramdisk_sha256": digest_bytes(ramdisk), "candidate_ramdisk_sha256": digest_bytes(new_ramdisk),
        "candidate_ramdisk_bytes": len(new_ramdisk), "page_size": page,
        "authorization": authorization, "overlay_manifest_sha256": digest(overlay / "manifest.json"),
        "policy_manifest_sha256": digest(policy_dir / "manifest.json"),
        "declared_changes": ["ramdisk_agent", "ramdisk_init_service", "ramdisk_file_contexts",
                             "ramdisk_enforcing_sepolicy"]}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    os.chmod(output / "manifest.json", 0o600)
    return manifest


def digest_bytes(value):
    return hashlib.sha256(value).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original-boot", required=True)
    parser.add_argument("--boot-baseline-report", required=True)
    parser.add_argument("--overlay-dir", required=True)
    parser.add_argument("--policy-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(build(args), sort_keys=True))
        return 0
    except (BootError, OSError, ValueError, KeyError, gzip.BadGzipFile,
            json.JSONDecodeError, struct.error) as error:
        print("Experimental boot build refused: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
