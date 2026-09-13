#!/usr/bin/env python3
"""Build a temporary, device-locked v119 fault-injection boot; never writes a device."""

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
BOOT_TOOL = ROOT / "tools/factory_audio/build-experimental-boot.py"
DEVICE = "r1-sample01"
FINGERPRINT = "Android/rk322x_echo/rk322x_echo:5.1.1/LMY49F/3448:user/release-keys"
PARTITION_BYTES = 12 * 1024 * 1024
SUPERVISOR_ENTRY = "sbin/r1-update-supervisor"
HELPER_ENTRY = "sbin/r1-update-helper.jar"
FAULT_ENTRY = "sbin/r1-update-fault-helper"
INIT_ENTRY = "init.r1_update_supervisor.rc"
CONTEXTS_ENTRY = "file_contexts"

_SPEC = importlib.util.spec_from_file_location("r1_boot", BOOT_TOOL)
boot = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(boot)


class BuildError(RuntimeError):
    pass


def require(value, message):
    if not value:
        raise BuildError(message)


def digest_bytes(value):
    return hashlib.sha256(value).hexdigest()


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def secure_file(value, label):
    path = Path(value)
    require(not path.is_symlink(), f"{label}_must_not_be_symlink")
    resolved = path.resolve(strict=True)
    require(resolved.is_file(), f"{label}_not_regular_file")
    return resolved


def expected_hash(value, label):
    require(isinstance(value, str) and len(value) == 64
            and all(char in "0123456789abcdef" for char in value),
            f"{label}_invalid")
    return value


def valid_operation(value):
    return (isinstance(value, str) and len(value) == 32
            and all(char in "0123456789abcdef" for char in value))


def assert_elf32_arm(path):
    output = subprocess.run(["readelf", "-hW", str(path)], check=True,
                            capture_output=True, text=True).stdout
    require("ELF32" in output and "ARM" in output, "fault_helper_not_elf32_arm")


def entry_contract(entry):
    fields = list(entry.fields)
    fields[6] = None
    return entry.magic, fields


def build(args):
    current_a = secure_file(args.current_boot_a, "current_boot_a")
    current_b = secure_file(args.current_boot_b, "current_boot_b")
    require(not os.path.samefile(current_a, current_b),
            "current_boot_copies_not_independent")
    fault_helper = secure_file(args.fault_helper, "fault_helper")
    output = Path(args.output_dir).resolve()
    try:
        output.relative_to(ROOT)
        raise BuildError("private_boot_output_must_be_outside_repository")
    except ValueError:
        pass
    require(not output.exists(), "boot_output_already_exists")
    require(valid_operation(args.crash_operation), "crash_operation_invalid")
    require(valid_operation(args.rollback_operation), "rollback_operation_invalid")
    require(args.crash_operation != args.rollback_operation,
            "fault_operations_must_differ")

    current_hash = digest(current_a)
    require(current_hash == digest(current_b), "current_boot_copies_differ")
    require(current_hash == expected_hash(args.expected_current_sha256,
                                          "expected_current_sha256"),
            "current_boot_hash_mismatch")
    require(current_a.stat().st_size == PARTITION_BYTES,
            "current_boot_size_invalid")
    require(digest(fault_helper) == expected_hash(args.expected_fault_helper_sha256,
                                                  "expected_fault_helper_sha256"),
            "fault_helper_hash_mismatch")
    assert_elf32_arm(fault_helper)

    current = current_a.read_bytes()
    values, kernel, ramdisk, second = boot.boot_parts(current)
    require(len(ramdisk) % 4 == 0, "current_ramdisk_not_rockchip_sha_aligned")
    require(current[576:596] == boot.rockchip_boot_id(current, kernel, ramdisk, second),
            "current_rockchip_boot_id_mismatch")
    entries = boot.parse_cpio(gzip.decompress(ramdisk))
    before = {entry.name: (entry_contract(entry), entry.data) for entry in entries}
    require(len(before) == len(entries), "cpio_duplicate_entry")
    for name in (SUPERVISOR_ENTRY, HELPER_ENTRY, INIT_ENTRY, CONTEXTS_ENTRY):
        require(name in before, f"required_entry_missing:{name}")
    require(FAULT_ENTRY not in before, "fault_helper_already_present")
    require(digest_bytes(before[SUPERVISOR_ENTRY][1])
            == expected_hash(args.expected_supervisor_sha256,
                             "expected_supervisor_sha256"),
            "embedded_supervisor_hash_mismatch")
    require(digest_bytes(before[HELPER_ENTRY][1])
            == expected_hash(args.expected_helper_sha256, "expected_helper_sha256"),
            "embedded_helper_hash_mismatch")

    original_init = before[INIT_ENTRY][1]
    require(b"service r1_update /sbin/r1-update-supervisor" in original_init,
            "production_supervisor_service_missing")
    require(b"r1_update_fault" not in original_init,
            "fault_service_already_present")
    fault_service = (
        b"\nservice r1_update_fault /sbin/r1-update-fault-helper "
        + args.crash_operation.encode("ascii") + b" "
        + args.rollback_operation.encode("ascii")
        + b"\n    class main\n    user root\n    group root\n"
          b"    seclabel u:r:r1_update_supervisor:s0\n    disabled\n    oneshot\n"
          b"\non property:sys.boot_completed=1\n    start r1_update_fault\n")
    candidate_init = original_init.rstrip(b"\n") + b"\n" + fault_service
    original_contexts = before[CONTEXTS_ENTRY][1]
    require(b"/sbin/r1-update-fault-helper" not in original_contexts,
            "fault_context_already_present")
    candidate_contexts = (original_contexts.rstrip(b"\n")
                          + b"\n/sbin/r1-update-fault-helper"
                            b"                 u:object_r:r1_update_supervisor:s0\n")

    boot.replace(entries, INIT_ENTRY, candidate_init)
    boot.replace(entries, CONTEXTS_ENTRY, candidate_contexts)
    boot.add(entries, FAULT_ENTRY, fault_helper.read_bytes(), 0o750)
    after = {entry.name: (entry_contract(entry), entry.data) for entry in entries}
    require(set(after) == set(before) | {FAULT_ENTRY},
            "candidate_ramdisk_entry_set_invalid")
    for name in before:
        require(before[name][0] == after[name][0],
                f"ramdisk_metadata_changed:{name}")
        if name not in (INIT_ENTRY, CONTEXTS_ENTRY):
            require(before[name][1] == after[name][1],
                    f"ramdisk_payload_changed:{name}")

    new_ramdisk = gzip.compress(boot.build_cpio(entries), compresslevel=9, mtime=0)
    new_ramdisk += b"\0" * (boot.aligned(len(new_ramdisk), 4) - len(new_ramdisk))
    page = values[7]
    header = bytearray(current[:page])
    struct.pack_into("<I", header, 16, len(new_ramdisk))
    header[576:608] = boot.rockchip_boot_id(header, kernel, new_ramdisk, second) + b"\0" * 12
    candidate = bytes(header) + kernel
    candidate += b"\0" * (boot.aligned(len(kernel), page) - len(kernel))
    candidate += new_ramdisk
    candidate += b"\0" * (boot.aligned(len(new_ramdisk), page) - len(new_ramdisk))
    candidate += second
    candidate += b"\0" * (boot.aligned(len(second), page) - len(second))
    require(len(candidate) <= PARTITION_BYTES, "candidate_boot_exceeds_partition")
    candidate += b"\0" * (PARTITION_BYTES - len(candidate))

    new_values, new_kernel, parsed_ramdisk, new_second = boot.boot_parts(candidate)
    require(new_kernel == kernel and new_second == second,
            "immutable_boot_component_changed")
    for index in (1, 3, 5, 6, 7):
        require(new_values[index] == values[index], "boot_header_address_changed")
    require(candidate[576:596]
            == boot.rockchip_boot_id(candidate, new_kernel, parsed_ramdisk, new_second),
            "candidate_rockchip_boot_id_mismatch")
    verified = {entry.name: entry.data for entry in
                boot.parse_cpio(gzip.decompress(parsed_ramdisk))}
    require(verified[FAULT_ENTRY] == fault_helper.read_bytes(),
            "verified_fault_helper_mismatch")
    require(verified[SUPERVISOR_ENTRY] == before[SUPERVISOR_ENTRY][1],
            "verified_supervisor_changed")

    output.mkdir(mode=0o700)
    image = output / "boot-r1-update-fault-validation.img"
    image.write_bytes(candidate)
    os.chmod(image, 0o600)
    result = {
        "schema_version": 1,
        "status": "pass_for_temporary_fault_validation_boot_write",
        "device": {"id": DEVICE, "fingerprint": FINGERPRINT},
        "partition": {"name": "boot", "bytes": PARTITION_BYTES,
                      "loader_image_start_sector": 98304, "sectors": 24576},
        "current_boot_sha256": current_hash,
        "candidate_boot_sha256": digest(image),
        "production_supervisor_sha256": digest_bytes(before[SUPERVISOR_ENTRY][1]),
        "production_helper_sha256": digest_bytes(before[HELPER_ENTRY][1]),
        "fault_helper_sha256": digest(fault_helper),
        "crash_operation": args.crash_operation,
        "rollback_operation": args.rollback_operation,
        "kernel_sha256": digest_bytes(kernel),
        "second_sha256": digest_bytes(second),
        "current_ramdisk_sha256": digest_bytes(ramdisk),
        "candidate_ramdisk_sha256": digest_bytes(new_ramdisk),
        "boot_id_scheme": "rockchip_secure_ns_sha1",
        "authorization": "2026-09-11-r1-sample01-no-disassembly-device-limited",
        "declared_changes": ["ramdisk_fault_helper", "ramdisk_fault_init",
                             "ramdisk_fault_file_context"],
        "production_policy_changed": False,
        "production_supervisor_changed": False,
    }
    manifest = output / "manifest.json"
    manifest.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
    os.chmod(manifest, 0o600)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current-boot-a", required=True)
    parser.add_argument("--current-boot-b", required=True)
    parser.add_argument("--expected-current-sha256", required=True)
    parser.add_argument("--expected-supervisor-sha256", required=True)
    parser.add_argument("--expected-helper-sha256", required=True)
    parser.add_argument("--fault-helper", required=True)
    parser.add_argument("--expected-fault-helper-sha256", required=True)
    parser.add_argument("--crash-operation", required=True)
    parser.add_argument("--rollback-operation", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(build(args), sort_keys=True))
        return 0
    except (BuildError, boot.BootError, OSError, ValueError, KeyError,
            gzip.BadGzipFile, struct.error, subprocess.CalledProcessError) as error:
        print("R1 update fault boot build refused: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
