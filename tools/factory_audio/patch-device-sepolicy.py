#!/usr/bin/env python3
"""Patch a private policy copy on the named R1; never loads policy or writes a partition."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
DEVICE = "r1-sample01"
FINGERPRINT = "Android/rk322x_echo/rk322x_echo:5.1.1/LMY49F/3448:user/release-keys"
PATCHER_SHA256 = "9e301f027fb30244ef143d367d49d266c944e90345099a60e3414e7ad09d5c11"
SOURCE_COMMIT = "e38bff264913e5bc2c8f18f67ec9f1017ace3982"
RULES = (
    ("r1_factory_audio", "system_file", "file", "read"),
    ("init", "r1_factory_audio", "process", "transition"),
    ("init", "r1_factory_audio", "unix_stream_socket", "create,bind,listen,setopt,getattr"),
    ("init", "r1_factory_audio", "sock_file", "create,open,write,getattr,setattr,unlink"),
    ("r1_factory_audio", "tmpfs", "filesystem", "associate"),
    ("r1_factory_audio", "rootfs", "file", "entrypoint,open,read,execute,getattr"),
    ("r1_factory_audio", "rootfs", "dir", "search,getattr"),
    ("r1_factory_audio", "null_device", "chr_file", "open,read,write,getattr,ioctl"),
    ("r1_factory_audio", "kernel", "fd", "use"),
    ("r1_factory_audio", "properties_device", "file", "open,read,getattr"),
    ("r1_factory_audio", "device", "dir", "search,getattr"),
    ("r1_factory_audio", "socket_device", "dir", "search"),
    ("r1_factory_audio", "tmpfs", "file", "read,write,execute"),
    ("r1_factory_audio", "rootfs", "lnk_file", "read,getattr"),
    ("init", "r1_factory_audio", "process", "rlimitinh,siginh,noatsecure"),
    ("r1_factory_audio", "init", "process", "sigchld"),
    ("r1_factory_audio", "r1_factory_audio", "unix_dgram_socket", "create,connect,write"),
    ("r1_factory_audio", "logdw_socket", "sock_file", "open,write,getattr"),
    ("r1_factory_audio", "logd", "unix_dgram_socket", "sendto"),
    ("r1_factory_audio", "r1_factory_audio", "process", "fork"),
    ("r1_factory_audio", "init", "fd", "use"),
    ("r1_factory_audio", "r1_factory_audio", "file", "entrypoint,open,read,execute,getattr"),
    ("r1_factory_audio", "system_file", "dir", "open,read,search,getattr"),
    ("r1_factory_audio", "system_file", "file", "open,read,execute,execute_no_trans,getattr"),
    ("r1_factory_audio", "audio_device", "dir", "open,read,search,getattr"),
    ("r1_factory_audio", "audio_device", "chr_file", "open,read,write,ioctl,getattr"),
    ("r1_factory_audio", "r1_factory_audio", "capability", "setuid,setgid,chown"),
    ("r1_factory_audio", "r1_factory_audio", "process", "signal,sigchld"),
    ("r1_factory_audio", "r1_factory_audio", "unix_stream_socket", "listen,accept,read,write,getattr,getopt,setopt"),
    ("r1_factory_audio", "r1_factory_audio", "sock_file", "open,read,write,getattr"),
    ("untrusted_app", "r1_factory_audio", "sock_file", "open,read,write,getattr"),
    ("untrusted_app", "r1_factory_audio", "unix_stream_socket", "connectto"),
    ("r1_factory_audio", "untrusted_app", "unix_stream_socket", "accept,read,write,getattr,getopt,setopt"),
)

# Android 5.1 mounts the emulated/internal SD card with a single ``vfat``
# security type.  VFAT cannot persist per-file SELinux xattrs, so a filename
# transition cannot confine the vendor's hard-coded /sdcard/unidata outputs.
# These rules are therefore intentionally separate from RULES and may only be
# added to a short-lived diagnostic policy with an explicit risk acknowledgement.
DIAGNOSTIC_VFAT_VENDOR_FILE_RULES = (
    ("mediaserver", "vfat", "dir", "search,write,add_name"),
    ("mediaserver", "vfat", "file", "create,open,write,getattr,setattr"),
)
DIAGNOSTIC_VFAT_RISK_ACK = "accept-mediaserver-vfat-type-wide-write"


class PolicyError(RuntimeError):
    pass


def require(value, message):
    if not value:
        raise PolicyError(message)


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def run(command, timeout=30):
    return subprocess.run(command, check=True, capture_output=True, text=True, timeout=timeout)


def outside_repository(path):
    path = Path(path).resolve()
    try:
        path.relative_to(ROOT)
        raise PolicyError("private_policy_output_must_be_outside_repository")
    except ValueError:
        return path


def selected_rules(diagnostic_vfat, risk_ack):
    if diagnostic_vfat:
        require(risk_ack == DIAGNOSTIC_VFAT_RISK_ACK,
                "diagnostic_vfat_type_wide_risk_not_acknowledged")
        return RULES + DIAGNOSTIC_VFAT_VENDOR_FILE_RULES
    require(risk_ack is None, "diagnostic_vfat_profile_required_for_risk_acknowledgement")
    return RULES


def patch(args):
    require(re.fullmatch(r"[A-Za-z0-9._:-]+", args.serial), "adb_serial_invalid")
    original = Path(args.original_policy).resolve(strict=True)
    patcher = Path(args.patcher).resolve(strict=True)
    require(original.is_file() and not original.is_symlink(), "original_policy_invalid")
    require(patcher.is_file() and not patcher.is_symlink(), "policy_patcher_invalid")
    require(digest(original) == args.original_sha256, "original_policy_hash_mismatch")
    require(digest(patcher) == PATCHER_SHA256, "policy_patcher_hash_mismatch")
    diagnostic_vfat = bool(getattr(args, "diagnostic_vfat_vendor_files", False))
    risk_ack = getattr(args, "acknowledge_vfat_type_wide_risk", None)
    rules = selected_rules(diagnostic_vfat, risk_ack)
    output = outside_repository(args.output_dir)
    require(not output.exists(), "policy_output_already_exists")
    identity = run([args.adb, "-s", args.serial, "shell", "getprop", "ro.build.fingerprint"]).stdout.strip()
    hardware = run([args.adb, "-s", args.serial, "shell", "getprop", "ro.hardware"]).stdout.strip()
    require(identity == FINGERPRINT and hardware == "rk30board", "device_identity_mismatch")
    remote = "/data/local/tmp/r1-sepolicy-build"
    logs = []
    output.mkdir(mode=0o700)
    try:
        run([args.adb, "-s", args.serial, "shell", "rm", "-rf", remote])
        run([args.adb, "-s", args.serial, "shell", "mkdir", remote])
        run([args.adb, "-s", args.serial, "push", str(patcher), remote + "/inject"])
        run([args.adb, "-s", args.serial, "push", str(original), remote + "/policy-0"])
        run([args.adb, "-s", args.serial, "shell", "chmod", "700", remote + "/inject"])
        for index, (source, target, cls, perms) in enumerate(rules, 1):
            result = run([args.adb, "-s", args.serial, "shell", remote + "/inject",
                "-s", source, "-t", target, "-c", cls, "-p", perms,
                "-P", f"{remote}/policy-{index - 1}", "-o", f"{remote}/policy-{index}"])
            require("Success" in result.stdout, f"policy_rule_failed_{index}")
            logs.append({"index": index, "source": source, "target": target,
                         "class": cls, "permissions": perms})
        run([args.adb, "-s", args.serial, "pull", f"{remote}/policy-{len(rules)}",
             str(output / "sepolicy")])
        require((output / "sepolicy").stat().st_size >= original.stat().st_size,
                "patched_policy_size_invalid")
        manifest = {"schema_version": 1, "status": "pass_for_boot_staging_only",
            "device": {"id": DEVICE, "hardware": hardware, "fingerprint": identity},
            "original_policy_sha256": digest(original),
            "patched_policy_sha256": digest(output / "sepolicy"),
            "patcher": {"sha256": digest(patcher), "source_commit": SOURCE_COMMIT},
            "selinux_mode": "enforcing", "permissive_domains": [], "rules": logs}
        if diagnostic_vfat:
            manifest["diagnostic_profile"] = {
                "name": "vendor_debug_files_vfat_type_wide",
                "temporary": True,
                "requested_path": "/sdcard/unidata",
                "requested_filenames": [
                    f"{phase}_file_{kind}.wav"
                    for phase in ("waking", "waked")
                    for kind in ("4mic", "2aec", "out")
                ],
                "selinux_target_type": "vfat",
                "filename_transition_confinement": False,
                "limitation": "vfat_has_no_per_file_selinux_xattrs",
                "risk_scope": "mediaserver_write_applies_to_visible_vfat_type_objects",
                "restore_production_boot_after_probe": True,
                "risk_acknowledgement": risk_ack,
            }
        (output / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        os.chmod(output / "sepolicy", 0o600)
        os.chmod(output / "manifest.json", 0o600)
        return manifest
    finally:
        subprocess.run([args.adb, "-s", args.serial, "shell", "rm", "-rf", remote],
                       capture_output=True, timeout=10)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--serial", required=True)
    parser.add_argument("--original-policy", required=True)
    parser.add_argument("--original-sha256", required=True)
    parser.add_argument("--patcher", required=True)
    parser.add_argument("--diagnostic-vfat-vendor-files", action="store_true")
    parser.add_argument("--acknowledge-vfat-type-wide-risk")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(patch(args), sort_keys=True))
        return 0
    except (PolicyError, OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        print("R1 policy patch refused: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
