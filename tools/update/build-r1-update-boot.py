#!/usr/bin/env python3
"""Build and verify a private R1 update-supervisor boot image; never writes a device."""

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
BOOT_TOOL = ROOT / "tools/factory_audio/build-experimental-boot.py"
DEVICE = "r1-sample01"
FINGERPRINT = "Android/rk322x_echo/rk322x_echo:5.1.1/LMY49F/3448:user/release-keys"
PARTITION = {"name": "boot", "bytes": 12 * 1024 * 1024,
             "loader_image_start_sector": 98304, "sectors": 24576}
ADDITIONS = {
    "sbin/r1-update-supervisor": 0o750,
    "sbin/r1-update-helper.jar": 0o644,
    "init.r1_update_supervisor.rc": 0o644,
}

_SPEC = importlib.util.spec_from_file_location("r1_boot", BOOT_TOOL)
boot = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(boot)


class BuildError(RuntimeError):
    pass


def require(value, message):
    if not value:
        raise BuildError(message)


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


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def entry_contract(entry):
    fields = list(entry.fields)
    fields[6] = None
    return entry.magic, fields


def assert_elf32_arm(path):
    output = subprocess.run(["readelf", "-hW", str(path)], check=True,
                            capture_output=True, text=True).stdout
    require("ELF32" in output and "ARM" in output, "supervisor_not_elf32_arm")


def expected_hash(value, label):
    require(isinstance(value, str) and len(value) == 64
            and all(char in "0123456789abcdef" for char in value),
            f"{label}_invalid")
    return value


def build(args):
    current_a = secure_file(args.current_boot_a, "current_boot_a")
    current_b = secure_file(args.current_boot_b, "current_boot_b")
    require(not os.path.samefile(current_a, current_b), "current_boot_copies_not_independent")
    policy = secure_file(args.candidate_policy, "candidate_policy")
    policy_manifest_path = secure_file(args.policy_manifest, "policy_manifest")
    supervisor = secure_file(args.supervisor, "supervisor")
    helper = secure_file(args.helper, "helper")
    init_rc = secure_file(args.init_rc, "init_rc")
    contexts = secure_file(args.file_contexts, "file_contexts")
    output = Path(args.output_dir).resolve()
    try:
        output.relative_to(ROOT)
        raise BuildError("private_boot_output_must_be_outside_repository")
    except ValueError:
        pass
    require(not output.exists(), "boot_output_already_exists")

    current_hash = digest(current_a)
    require(current_hash == digest(current_b), "current_boot_copies_differ")
    require(current_hash == expected_hash(args.expected_current_sha256,
                                          "expected_current_sha256"),
            "current_boot_hash_mismatch")
    require(current_a.stat().st_size == PARTITION["bytes"], "current_boot_size_invalid")
    require(digest(supervisor) == expected_hash(args.expected_supervisor_sha256,
                                                "expected_supervisor_sha256"),
            "supervisor_hash_mismatch")
    require(digest(helper) == expected_hash(args.expected_helper_sha256,
                                            "expected_helper_sha256"),
            "helper_hash_mismatch")
    assert_elf32_arm(supervisor)

    manifest = load(policy_manifest_path)
    require(manifest.get("schema_version") == 1, "policy_manifest_schema_invalid")
    require(manifest.get("status") == "pass_for_update_supervisor_boot_staging_only",
            "policy_manifest_status_invalid")
    require(manifest.get("device") == {
        "id": DEVICE, "hardware": "rk30board", "fingerprint": FINGERPRINT,
    }, "policy_manifest_device_mismatch")
    require(manifest.get("selinux_mode") == "enforcing"
            and manifest.get("permissive_domains") == [], "policy_not_enforcing")
    require(manifest.get("patched_policy_sha256") == digest(policy),
            "candidate_policy_hash_mismatch")

    current = current_a.read_bytes()
    values, kernel, ramdisk, second = boot.boot_parts(current)
    require(len(ramdisk) % 4 == 0, "current_ramdisk_not_rockchip_sha_aligned")
    require(current[576:596] == boot.rockchip_boot_id(current, kernel, ramdisk, second),
            "current_rockchip_boot_id_mismatch")
    entries = boot.parse_cpio(gzip.decompress(ramdisk))
    before = {entry.name: (entry_contract(entry), entry.data) for entry in entries}
    require(len(before) == len(entries), "cpio_duplicate_entry")
    for name in ("sepolicy", "file_contexts", "init.rk30board.rc"):
        require(name in before, f"required_ramdisk_entry_missing:{name}")
    require(boot.digest_bytes(before["sepolicy"][1])
            == manifest.get("current_factory_policy_sha256"),
            "embedded_factory_policy_hash_mismatch")
    for name in ADDITIONS:
        require(name not in before, f"update_entry_already_present:{name}")

    context_bytes = contexts.read_bytes()
    require(context_bytes.endswith(b"\n"), "file_contexts_template_newline_missing")
    require(b"r1_update_supervisor" not in before["file_contexts"][1],
            "update_context_already_present")
    board_init = before["init.rk30board.rc"][1]
    require(b"init.r1_update_supervisor.rc" not in board_init,
            "update_init_already_imported")
    boot.replace(entries, "sepolicy", policy.read_bytes())
    boot.replace(entries, "file_contexts",
                 before["file_contexts"][1].rstrip(b"\n") + b"\n" + context_bytes)
    boot.replace(entries, "init.rk30board.rc", board_init.rstrip(b"\n")
                 + b"\nimport /init.r1_update_supervisor.rc\n")
    payloads = {
        "sbin/r1-update-supervisor": supervisor.read_bytes(),
        "sbin/r1-update-helper.jar": helper.read_bytes(),
        "init.r1_update_supervisor.rc": init_rc.read_bytes(),
    }
    for name, mode in ADDITIONS.items():
        boot.add(entries, name, payloads[name], mode)

    after = {entry.name: (entry_contract(entry), entry.data) for entry in entries}
    expected_names = set(before) | set(ADDITIONS)
    require(set(after) == expected_names, "candidate_ramdisk_entry_set_invalid")
    changed = {"sepolicy", "file_contexts", "init.rk30board.rc"}
    for name in before:
        require(before[name][0] == after[name][0], f"ramdisk_metadata_changed:{name}")
        if name not in changed:
            require(before[name][1] == after[name][1], f"ramdisk_payload_changed:{name}")

    new_ramdisk = gzip.compress(boot.build_cpio(entries), compresslevel=9, mtime=0)
    new_ramdisk += b"\0" * (boot.aligned(len(new_ramdisk), 4) - len(new_ramdisk))
    page = values[7]
    header = bytearray(current[:page])
    struct.pack_into("<I", header, 16, len(new_ramdisk))
    header[576:608] = boot.rockchip_boot_id(header, kernel, new_ramdisk, second) + b"\0" * 12
    candidate = bytes(header) + kernel + b"\0" * (boot.aligned(len(kernel), page) - len(kernel))
    candidate += new_ramdisk + b"\0" * (boot.aligned(len(new_ramdisk), page) - len(new_ramdisk))
    candidate += second + b"\0" * (boot.aligned(len(second), page) - len(second))
    require(len(candidate) <= PARTITION["bytes"], "candidate_boot_exceeds_partition")
    candidate += b"\0" * (PARTITION["bytes"] - len(candidate))

    new_values, new_kernel, parsed_ramdisk, new_second = boot.boot_parts(candidate)
    require(new_kernel == kernel and new_second == second, "immutable_boot_component_changed")
    for index in (1, 3, 5, 6, 7):
        require(new_values[index] == values[index], "boot_header_address_changed")
    require(candidate[576:596]
            == boot.rockchip_boot_id(candidate, new_kernel, parsed_ramdisk, new_second),
            "candidate_rockchip_boot_id_mismatch")
    verified_entries = boot.parse_cpio(gzip.decompress(parsed_ramdisk))
    verified = {entry.name: (entry_contract(entry), entry.data) for entry in verified_entries}
    require(set(verified) == expected_names, "verified_ramdisk_entry_set_invalid")
    for name in expected_names:
        require(verified[name] == after[name], f"verified_ramdisk_entry_mismatch:{name}")

    output.mkdir(mode=0o700)
    image = output / "boot-r1-update-supervisor.img"
    image.write_bytes(candidate)
    os.chmod(image, 0o600)
    result = {
        "schema_version": 1,
        "status": "pass_for_device_locked_boot_write",
        "device": {"id": DEVICE, "hardware": "rk30board", "fingerprint": FINGERPRINT},
        "partition": PARTITION,
        "current_boot_copy_a_sha256": current_hash,
        "current_boot_copy_b_sha256": current_hash,
        "candidate_boot_sha256": digest(image),
        "current_policy_sha256": boot.digest_bytes(before["sepolicy"][1]),
        "candidate_policy_sha256": digest(policy),
        "policy_manifest_sha256": digest(policy_manifest_path),
        "supervisor_sha256": digest(supervisor),
        "helper_sha256": digest(helper),
        "init_rc_sha256": digest(init_rc),
        "file_contexts_template_sha256": digest(contexts),
        "kernel_sha256": boot.digest_bytes(kernel),
        "second_sha256": boot.digest_bytes(second),
        "current_ramdisk_sha256": boot.digest_bytes(ramdisk),
        "candidate_ramdisk_sha256": boot.digest_bytes(new_ramdisk),
        "candidate_ramdisk_bytes": len(new_ramdisk),
        "page_size": page,
        "boot_id_scheme": "rockchip_secure_ns_sha1",
        "ramdisk_alignment_bytes": 4,
        "authorization": "2026-09-11-r1-sample01-no-disassembly-device-limited",
        "declared_changes": ["ramdisk_update_supervisor", "ramdisk_update_helper",
                             "ramdisk_update_init", "ramdisk_file_contexts",
                             "ramdisk_enforcing_sepolicy"],
    }
    result_path = output / "manifest.json"
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    os.chmod(result_path, 0o600)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current-boot-a", required=True)
    parser.add_argument("--current-boot-b", required=True)
    parser.add_argument("--expected-current-sha256", required=True)
    parser.add_argument("--candidate-policy", required=True)
    parser.add_argument("--policy-manifest", required=True)
    parser.add_argument("--supervisor", required=True)
    parser.add_argument("--expected-supervisor-sha256", required=True)
    parser.add_argument("--helper", required=True)
    parser.add_argument("--expected-helper-sha256", required=True)
    parser.add_argument("--init-rc", required=True)
    parser.add_argument("--file-contexts", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(build(args), sort_keys=True))
        return 0
    except (BuildError, boot.BootError, OSError, ValueError, KeyError,
            json.JSONDecodeError, gzip.BadGzipFile, struct.error,
            subprocess.CalledProcessError) as error:
        print("R1 update boot build refused: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
