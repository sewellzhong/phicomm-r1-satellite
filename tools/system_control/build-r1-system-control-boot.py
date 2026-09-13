#!/usr/bin/env python3
"""Build a verified boot-only increment adding the system-control agent."""

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
SPEC = importlib.util.spec_from_file_location("r1_boot", BOOT_TOOL)
boot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(boot)
PARTITION_BYTES = 12 * 1024 * 1024
ADDITIONS = {"sbin/r1-system-control-agent": 0o750,
             "init.r1_system_control.rc": 0o644}


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
    unresolved = Path(value)
    require(not unresolved.is_symlink(), f"{label}_must_not_be_symlink")
    path = unresolved.resolve(strict=True)
    require(path.is_file(), f"{label}_not_file")
    return path


def contract(entry):
    fields = list(entry.fields)
    fields[6] = None
    return entry.magic, fields


def build(args):
    first = secure_file(args.current_boot_a, "current_boot_a")
    second = secure_file(args.current_boot_b, "current_boot_b")
    require(not os.path.samefile(first, second), "current_boot_copies_not_independent")
    expected = args.expected_current_sha256.lower()
    require(digest(first) == expected and digest(second) == expected,
            "current_boot_hash_mismatch")
    policy = secure_file(args.candidate_policy, "candidate_policy")
    policy_manifest_path = secure_file(args.policy_manifest, "policy_manifest")
    agent = secure_file(args.agent, "agent")
    init_rc = secure_file(args.init_rc, "init_rc")
    contexts = secure_file(args.file_contexts, "file_contexts")
    output = Path(args.output_dir).resolve()
    try:
        output.relative_to(ROOT)
        raise BuildError("private_boot_output_must_be_outside_repository")
    except ValueError:
        pass
    require(not output.exists(), "output_exists")
    header = subprocess.run(["readelf", "-hW", str(agent)], check=True,
                            capture_output=True, text=True).stdout
    require("ELF32" in header and "ARM" in header, "agent_not_elf32_arm")
    manifest = json.loads(policy_manifest_path.read_text())
    require(manifest.get("status") == "pass_for_system_control_boot_staging_only",
            "policy_manifest_status_invalid")
    require(manifest.get("patched_policy_sha256") == digest(policy),
            "policy_hash_mismatch")
    require(manifest.get("selinux_mode") == "enforcing"
            and manifest.get("permissive_domains") == [], "policy_not_enforcing")

    current = first.read_bytes()
    require(len(current) == PARTITION_BYTES, "current_boot_size_invalid")
    values, kernel, ramdisk, trailing = boot.boot_parts(current)
    require(current[576:596] == boot.rockchip_boot_id(
        current, kernel, ramdisk, trailing), "current_boot_id_invalid")
    entries = boot.parse_cpio(gzip.decompress(ramdisk))
    before = {item.name: (contract(item), item.data) for item in entries}
    require(len(before) == len(entries), "duplicate_ramdisk_entry")
    for name in ("sepolicy", "file_contexts", "init.rk30board.rc"):
        require(name in before, f"required_entry_missing:{name}")
    replace_existing_init = bool(getattr(args, "replace_existing_init", False))
    replace_existing_overlay = bool(getattr(args, "replace_existing_overlay", False))
    require(not (replace_existing_init and replace_existing_overlay),
            "replacement_modes_conflict")
    replace_existing = replace_existing_init or replace_existing_overlay
    expected_policy = (manifest.get("current_policy_sha256")
                       if replace_existing_overlay else
                       manifest.get("patched_policy_sha256")
                       if replace_existing_init else manifest.get("current_policy_sha256"))
    require(boot.digest_bytes(before["sepolicy"][1]) == expected_policy,
            "embedded_policy_mismatch")
    context_bytes = contexts.read_bytes()
    require(context_bytes.endswith(b"\n"), "contexts_newline_missing")
    payloads = {"sbin/r1-system-control-agent": agent.read_bytes(),
                "init.r1_system_control.rc": init_rc.read_bytes()}
    if replace_existing:
        require(before.get("sbin/r1-system-control-agent", (None, None))[1]
                == payloads["sbin/r1-system-control-agent"], "embedded_agent_mismatch")
        require("init.r1_system_control.rc" in before, "embedded_init_missing")
        require(context_bytes.rstrip(b"\n") in before["file_contexts"][1],
                "embedded_contexts_missing")
        require(b"import /init.r1_system_control.rc" in before["init.rk30board.rc"][1],
                "embedded_init_import_missing")
        if replace_existing_overlay:
            boot.replace(entries, "sepolicy", policy.read_bytes())
        boot.replace(entries, "init.r1_system_control.rc", payloads["init.r1_system_control.rc"])
    else:
        for name in ADDITIONS:
            require(name not in before, f"system_control_entry_exists:{name}")
        require(b"r1_system_control" not in before["file_contexts"][1],
                "system_control_context_exists")
        require(b"init.r1_system_control.rc" not in before["init.rk30board.rc"][1],
                "system_control_init_import_exists")
        boot.replace(entries, "sepolicy", policy.read_bytes())
        boot.replace(entries, "file_contexts",
                     before["file_contexts"][1].rstrip(b"\n") + b"\n" + context_bytes)
        boot.replace(entries, "init.rk30board.rc",
                     before["init.rk30board.rc"][1].rstrip(b"\n")
                     + b"\nimport /init.r1_system_control.rc\n")
        for name, mode in ADDITIONS.items():
            boot.add(entries, name, payloads[name], mode)
    after = {item.name: (contract(item), item.data) for item in entries}
    expected_names = set(before) if replace_existing else set(before) | set(ADDITIONS)
    require(set(after) == expected_names, "candidate_entry_set_invalid")
    changed = ({"init.r1_system_control.rc", "sepolicy"}
               if replace_existing_overlay else
               {"init.r1_system_control.rc"} if replace_existing_init else
               {"sepolicy", "file_contexts", "init.rk30board.rc"})
    for name in before:
        require(before[name][0] == after[name][0], f"metadata_changed:{name}")
        if name not in changed:
            require(before[name][1] == after[name][1], f"payload_changed:{name}")

    new_ramdisk = gzip.compress(boot.build_cpio(entries), compresslevel=9, mtime=0)
    new_ramdisk += b"\0" * (boot.aligned(len(new_ramdisk), 4) - len(new_ramdisk))
    page = values[7]
    image_header = bytearray(current[:page])
    struct.pack_into("<I", image_header, 16, len(new_ramdisk))
    image_header[576:608] = (boot.rockchip_boot_id(
        image_header, kernel, new_ramdisk, trailing) + b"\0" * 12)
    candidate = bytes(image_header) + kernel
    candidate += b"\0" * (boot.aligned(len(kernel), page) - len(kernel))
    candidate += new_ramdisk
    candidate += b"\0" * (boot.aligned(len(new_ramdisk), page) - len(new_ramdisk))
    candidate += trailing
    candidate += b"\0" * (boot.aligned(len(trailing), page) - len(trailing))
    require(len(candidate) <= PARTITION_BYTES, "candidate_exceeds_boot_partition")
    candidate += b"\0" * (PARTITION_BYTES - len(candidate))
    new_values, new_kernel, parsed_ramdisk, new_trailing = boot.boot_parts(candidate)
    require(new_kernel == kernel and new_trailing == trailing,
            "immutable_boot_component_changed")
    for index in (1, 3, 5, 6, 7):
        require(new_values[index] == values[index], "boot_header_address_changed")
    require(candidate[576:596] == boot.rockchip_boot_id(
        candidate, new_kernel, parsed_ramdisk, new_trailing), "candidate_boot_id_invalid")
    verified_entries = boot.parse_cpio(gzip.decompress(parsed_ramdisk))
    verified = {item.name: (contract(item), item.data) for item in verified_entries}
    require(verified == after, "candidate_ramdisk_verification_failed")

    output.mkdir(mode=0o700)
    image = output / "boot-r1-system-control.img"
    image.write_bytes(candidate)
    os.chmod(image, 0o600)
    result = {
        "schema_version": 1,
        "status": "pass_for_device_locked_boot_write",
        "device": manifest["device"],
        "partition": {"name": "boot", "bytes": PARTITION_BYTES,
                      "loader_image_start_sector": 98304, "sectors": 24576},
        "authorization": "2026-09-11-r1-sample01-no-disassembly-device-limited",
        "current_boot_copy_a_sha256": expected,
        "current_boot_copy_b_sha256": expected,
        "candidate_boot_sha256": digest(image),
        "current_policy_sha256": boot.digest_bytes(before["sepolicy"][1]),
        "candidate_policy_sha256": digest(policy),
        "policy_manifest_sha256": digest(policy_manifest_path),
        "agent_sha256": digest(agent), "init_rc_sha256": digest(init_rc),
        "file_contexts_sha256": digest(contexts),
        "kernel_sha256": boot.digest_bytes(kernel),
        "second_sha256": boot.digest_bytes(trailing),
        "current_ramdisk_sha256": boot.digest_bytes(ramdisk),
        "candidate_ramdisk_sha256": boot.digest_bytes(new_ramdisk),
        "candidate_ramdisk_bytes": len(new_ramdisk), "page_size": page,
        "boot_id_scheme": "rockchip_secure_ns_sha1",
        "declared_changes": (["ramdisk_enforcing_sepolicy"]
                             if replace_existing_overlay else
                             ["ramdisk_system_control_init"] if replace_existing_init else
                             ["ramdisk_system_control_agent",
                              "ramdisk_system_control_init",
                              "ramdisk_file_contexts", "ramdisk_enforcing_sepolicy"]),
    }
    (output / "manifest.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n")
    os.chmod(output / "manifest.json", 0o600)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current-boot-a", required=True)
    parser.add_argument("--current-boot-b", required=True)
    parser.add_argument("--expected-current-sha256", required=True)
    parser.add_argument("--candidate-policy", required=True)
    parser.add_argument("--policy-manifest", required=True)
    parser.add_argument("--agent", required=True)
    parser.add_argument("--init-rc", required=True)
    parser.add_argument("--file-contexts", required=True)
    parser.add_argument("--replace-existing-init", action="store_true")
    parser.add_argument("--replace-existing-overlay", action="store_true")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(build(args), sort_keys=True))
        return 0
    except (BuildError, boot.BootError, OSError, ValueError, KeyError,
            json.JSONDecodeError, gzip.BadGzipFile, struct.error,
            subprocess.CalledProcessError) as error:
        print("R1 system-control boot build refused: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
