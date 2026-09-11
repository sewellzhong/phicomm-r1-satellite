#!/usr/bin/env python3
"""Build a device-locked boot candidate that changes only the embedded policy.

This updater accepts only the explicit temporary VFAT vendor-debug profile
emitted by patch-device-sepolicy.py.  It never writes the device.
"""

import argparse
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import sys


ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / "docs/references/r1-3448-boot-baseline.json"
BASE_BUILDER = Path(__file__).with_name("build-experimental-boot.py")
POLICY_ENTRY = "sepolicy"
PROFILE_NAME = "vendor_debug_files_vfat_type_wide"
RISK_ACK = "accept-mediaserver-vfat-type-wide-write"
PATCHER_SHA256 = "9e301f027fb30244ef143d367d49d266c944e90345099a60e3414e7ad09d5c11"
PATCHER_SOURCE_COMMIT = "e38bff264913e5bc2c8f18f67ec9f1017ace3982"
BASE_RULE_COUNT = 33
EXPECTED_DIAGNOSTIC_RULES = (
    ("mediaserver", "vfat", "dir", "search,write,add_name"),
    ("mediaserver", "vfat", "file", "create,open,write,getattr,setattr"),
)

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
    fields[6] = None
    return entry.magic, entry.name, fields


def effective_overlay_manifest_hash(manifest):
    value = manifest.get("overlay_manifest_sha256")
    if value is None:
        value = (manifest.get("candidate_overlay_manifest_sha256")
                 or manifest.get("current_overlay_manifest_sha256"))
    require(isinstance(value, str) and len(value) == 64,
            "current_boot_overlay_hash_missing")
    return value


def validate_policy_manifest(manifest, current_policy, candidate_policy, reference):
    require(manifest.get("schema_version") == 1, "policy_manifest_schema_invalid")
    require(manifest.get("status") == "pass_for_boot_staging_only",
            "policy_manifest_status_invalid")
    require(manifest.get("device") == reference.get("device"),
            "policy_manifest_device_mismatch")
    require(manifest.get("selinux_mode") == "enforcing", "policy_not_enforcing")
    require(manifest.get("permissive_domains") == [], "policy_has_permissive_domains")
    require(manifest.get("patcher") == {
        "sha256": PATCHER_SHA256, "source_commit": PATCHER_SOURCE_COMMIT,
    }, "policy_patcher_identity_invalid")
    require(manifest.get("original_policy_sha256") == boot.digest_bytes(current_policy),
            "embedded_policy_hash_not_policy_manifest")
    require(manifest.get("patched_policy_sha256") == digest(candidate_policy),
            "candidate_policy_hash_not_policy_manifest")
    profile = manifest.get("diagnostic_profile", {})
    require(profile.get("name") == PROFILE_NAME, "diagnostic_policy_profile_invalid")
    require(profile.get("temporary") is True, "diagnostic_policy_not_temporary")
    require(profile.get("selinux_target_type") == "vfat",
            "diagnostic_policy_target_type_invalid")
    require(profile.get("filename_transition_confinement") is False,
            "diagnostic_policy_scope_not_disclosed")
    require(profile.get("risk_scope")
            == "mediaserver_write_applies_to_visible_vfat_type_objects",
            "diagnostic_policy_risk_scope_invalid")
    require(profile.get("restore_production_boot_after_probe") is True,
            "diagnostic_policy_restore_requirement_missing")
    require(profile.get("risk_acknowledgement") == RISK_ACK,
            "diagnostic_policy_risk_not_acknowledged")
    rules = manifest.get("rules", [])
    require(len(rules) == BASE_RULE_COUNT + len(EXPECTED_DIAGNOSTIC_RULES),
            "diagnostic_policy_rule_count_invalid")
    diagnostic_rules = tuple(
        (item.get("source"), item.get("target"), item.get("class"),
         item.get("permissions"))
        for item in rules[BASE_RULE_COUNT:]
    )
    require(diagnostic_rules == EXPECTED_DIAGNOSTIC_RULES,
            "diagnostic_policy_rules_invalid")
    require([item.get("index") for item in rules]
            == list(range(1, len(rules) + 1)), "policy_rule_indices_invalid")


def build(args):
    current_a = secure_file(args.current_boot_a, "current_boot_a")
    current_b = secure_file(args.current_boot_b, "current_boot_b")
    require(not os.path.samefile(current_a, current_b), "current_boot_copies_not_independent")
    current_manifest_path = secure_file(args.current_boot_manifest, "current_boot_manifest")
    current_overlay_path = secure_file(args.current_overlay_manifest,
                                       "current_overlay_manifest")
    candidate_policy = secure_file(args.candidate_policy, "candidate_policy")
    policy_manifest_path = secure_file(args.policy_manifest, "policy_manifest")
    output = Path(args.output_dir).resolve()
    try:
        output.relative_to(ROOT)
        raise UpdateError("private_boot_output_must_be_outside_repository")
    except ValueError:
        pass
    require(not output.exists(), "boot_output_already_exists")

    reference = load(REFERENCE)
    current_manifest = load(current_manifest_path)
    overlay = load(current_overlay_path)
    policy_manifest = load(policy_manifest_path)
    require(current_manifest.get("status") == "pass_for_device_locked_boot_write",
            "current_boot_manifest_status_invalid")
    require(current_manifest.get("device") == reference.get("device"),
            "current_boot_manifest_device_mismatch")
    require(current_manifest.get("partition") == {
        "name": "boot", "bytes": boot.PARTITION_BYTES,
        "loader_image_start_sector": 98304, "sectors": 24576,
    }, "current_boot_partition_contract_invalid")
    require(current_manifest.get("boot_id_scheme") == "rockchip_secure_ns_sha1",
            "current_boot_id_scheme_invalid")
    require(digest(current_a) == digest(current_b), "current_boot_copies_differ")
    current_hash = digest(current_a)
    require(current_hash == current_manifest.get("candidate_boot_sha256"),
            "current_boot_hash_not_manifest_candidate")
    require(current_a.stat().st_size == boot.PARTITION_BYTES,
            "current_boot_size_invalid")
    require(digest(current_overlay_path) == effective_overlay_manifest_hash(current_manifest),
            "current_overlay_manifest_hash_mismatch")
    require(overlay.get("device") == reference.get("device"),
            "current_overlay_device_mismatch")
    require(overlay.get("authorization") == current_manifest.get("authorization"),
            "current_overlay_authorization_mismatch")
    require(overlay.get("allow_vendor_debug_files") is True,
            "vendor_debug_files_not_enabled_in_current_boot")

    current = current_a.read_bytes()
    values, kernel, ramdisk, second = boot.boot_parts(current)
    require(len(ramdisk) % 4 == 0, "current_ramdisk_not_rockchip_sha_aligned")
    require(current[576:596] == boot.rockchip_boot_id(current, kernel, ramdisk, second),
            "current_rockchip_boot_id_mismatch")
    entries = boot.parse_cpio(gzip.decompress(ramdisk))
    matches = [entry for entry in entries if entry.name == POLICY_ENTRY]
    require(len(matches) == 1, "current_policy_entry_not_unique")
    current_policy = matches[0].data
    validate_policy_manifest(
        policy_manifest, current_policy, candidate_policy, reference)
    require(boot.digest_bytes(current_policy) != digest(candidate_policy),
            "policy_update_is_noop")

    before = {entry.name: (entry_contract(entry), entry.data) for entry in entries}
    require(len(before) == len(entries), "cpio_duplicate_entry")
    boot.replace(entries, POLICY_ENTRY, candidate_policy.read_bytes())
    after = {entry.name: (entry_contract(entry), entry.data) for entry in entries}
    require(set(before) == set(after), "ramdisk_entry_set_changed")
    for name in before:
        require(before[name][0] == after[name][0], f"ramdisk_metadata_changed:{name}")
        if name != POLICY_ENTRY:
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
        expected = candidate_policy.read_bytes() if name == POLICY_ENTRY else before[name][1]
        require(updated[name][1] == expected, f"verified_ramdisk_payload_changed:{name}")

    output.mkdir(mode=0o700)
    image = output / "boot-policy-update.img"
    image.write_bytes(candidate)
    os.chmod(image, 0o600)
    result = {
        "schema_version": 1,
        "status": "pass_for_device_locked_boot_write",
        "device": reference["device"],
        "partition": current_manifest["partition"],
        "current_boot_copy_a_sha256": current_hash,
        "current_boot_copy_b_sha256": current_hash,
        "candidate_boot_sha256": digest(image),
        "current_policy_sha256": boot.digest_bytes(current_policy),
        "candidate_policy_sha256": digest(candidate_policy),
        "policy_manifest_sha256": digest(policy_manifest_path),
        "diagnostic_profile": policy_manifest["diagnostic_profile"],
        "kernel_sha256": boot.digest_bytes(kernel),
        "second_sha256": boot.digest_bytes(second),
        "current_ramdisk_sha256": boot.digest_bytes(ramdisk),
        "candidate_ramdisk_sha256": boot.digest_bytes(new_ramdisk),
        "candidate_ramdisk_bytes": len(new_ramdisk),
        "page_size": page,
        "boot_id_scheme": "rockchip_secure_ns_sha1",
        "ramdisk_alignment_bytes": 4,
        "authorization": current_manifest["authorization"],
        "current_boot_manifest_sha256": digest(current_manifest_path),
        "current_overlay_manifest_sha256": digest(current_overlay_path),
        "overlay_manifest_sha256": digest(current_overlay_path),
        "declared_changes": ["ramdisk_enforcing_sepolicy_temporary_vfat_diagnostic"],
        "restore_production_boot_after_probe": True,
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
    parser.add_argument("--current-boot-manifest", required=True)
    parser.add_argument("--current-overlay-manifest", required=True)
    parser.add_argument("--candidate-policy", required=True)
    parser.add_argument("--policy-manifest", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(build(args), sort_keys=True))
        return 0
    except (UpdateError, boot.BootError, OSError, ValueError, KeyError,
            json.JSONDecodeError, struct.error) as error:
        print("Boot policy update refused: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
