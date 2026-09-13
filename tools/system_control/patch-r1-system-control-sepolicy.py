#!/usr/bin/env python3
"""Rebuild the 3448 policy with existing private rules plus system-control."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
BASE_POLICY_SHA256 = "96fa3164741296482362fe9e0d126c9f55b8316421ec0cf9e79939b6cf5f269a"
PATCHER_SHA256 = "c289bcf5f0011bdbfaa520d813b0103f1d878285f6750e1972a6089321ade055"
FINGERPRINT = "Android/rk322x_echo/rk322x_echo:5.1.1/LMY49F/3448:user/release-keys"
RULES = (
    ("r1_system_control", "system_file", "file", "read"),
    ("init", "r1_system_control", "process", "transition,rlimitinh,siginh,noatsecure"),
    ("r1_system_control", "r1_system_control", "file", "entrypoint,open,read,execute,getattr"),
    ("init", "r1_system_control", "unix_stream_socket", "create,bind,listen,setopt,getattr"),
    ("init", "r1_system_control", "sock_file", "create,open,write,getattr,setattr,unlink"),
    ("r1_system_control", "init", "fd", "use"),
    ("r1_system_control", "kernel", "fd", "use"),
    ("r1_system_control", "init", "process", "sigchld"),
    ("r1_system_control", "rootfs", "dir", "search,getattr"),
    ("r1_system_control", "rootfs", "file", "entrypoint,open,read,execute,getattr"),
    ("r1_system_control", "device", "dir", "search,getattr"),
    ("r1_system_control", "socket_device", "dir", "search"),
    ("r1_system_control", "sysfs", "dir", "open,read,search,getattr"),
    ("r1_system_control", "sysfs", "file", "open,read,write,getattr"),
    ("r1_system_control", "r1_system_control", "capability", "sys_boot"),
    ("r1_system_control", "r1_system_control", "unix_stream_socket", "accept,read,write,getattr,getopt,setopt,shutdown"),
    ("untrusted_app", "r1_system_control", "sock_file", "open,read,write,getattr"),
    ("untrusted_app", "r1_system_control", "unix_stream_socket", "connectto"),
    ("r1_system_control", "untrusted_app", "unix_stream_socket", "accept,read,write,getattr,getopt,setopt"),
    ("r1_system_control", "r1_system_control", "unix_dgram_socket", "create,connect,write"),
    ("r1_system_control", "logdw_socket", "sock_file", "open,write,getattr"),
    ("r1_system_control", "logd", "unix_dgram_socket", "sendto"),
)


class PolicyError(RuntimeError):
    pass


def require(value, message):
    if not value:
        raise PolicyError(message)


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def run(command, timeout=30):
    return subprocess.run(command, check=True, capture_output=True, text=True,
                          timeout=timeout, shell=False)


def patch(args):
    require(re.fullmatch(r"[A-Za-z0-9._:-]+", args.serial), "adb_serial_invalid")
    original = Path(args.original_policy).resolve(strict=True)
    current = Path(args.current_policy).resolve(strict=True)
    current_manifest_path = Path(args.current_policy_manifest).resolve(strict=True)
    patcher = Path(args.patcher).resolve(strict=True)
    require(digest(original) == BASE_POLICY_SHA256, "original_policy_not_3448_base")
    require(digest(current) == args.current_policy_sha256, "current_policy_hash_mismatch")
    require(digest(patcher) == PATCHER_SHA256, "policy_patcher_hash_mismatch")
    current_manifest = json.loads(current_manifest_path.read_text())
    require(current_manifest.get("patched_policy_sha256") == digest(current),
            "current_policy_manifest_mismatch")
    existing = current_manifest.get("rules")
    require(isinstance(existing, list) and len(existing) >= 100,
            "current_policy_rule_history_incomplete")
    existing_rules = []
    for index, record in enumerate(existing, 1):
        require(record.get("index") == index, "current_policy_rule_index_invalid")
        values = tuple(record.get(name) for name in
                       ("source", "target", "class", "permissions"))
        require(all(isinstance(value, str) and value for value in values),
                "current_policy_rule_invalid")
        existing_rules.append(values)
    output = Path(args.output_dir).resolve()
    try:
        output.relative_to(ROOT)
        raise PolicyError("private_policy_output_must_be_outside_repository")
    except ValueError:
        pass
    require(not output.exists(), "policy_output_exists")
    fingerprint = run([args.adb, "-s", args.serial, "shell", "getprop",
                       "ro.build.fingerprint"]).stdout.strip()
    enforcing = run([args.adb, "-s", args.serial, "shell", "getenforce"]).stdout.strip()
    require(fingerprint == FINGERPRINT and enforcing == "Enforcing",
            "device_identity_or_enforcing_mismatch")
    remote = "/data/local/tmp/r1-system-control-policy"
    output.mkdir(mode=0o700)
    records = []
    try:
        run([args.adb, "-s", args.serial, "shell", "rm", "-rf", remote])
        run([args.adb, "-s", args.serial, "shell", "mkdir", remote])
        run([args.adb, "-s", args.serial, "push", str(patcher), remote + "/inject"])
        run([args.adb, "-s", args.serial, "push", str(original), remote + "/policy-0"])
        run([args.adb, "-s", args.serial, "shell", "chmod", "700", remote + "/inject"])
        combined = tuple(existing_rules) + RULES
        for index, (source, target, cls, permissions) in enumerate(combined, 1):
            command = [args.adb, "-s", args.serial, "shell", remote + "/inject",
                       "-s", source, "-t", target, "-c", cls, "-p", permissions]
            if index == 1:
                command.extend(["-N", "r1_update_supervisor",
                                "-N", "r1_system_control"])
            command.extend(["-P", f"{remote}/policy-{index - 1}",
                            "-o", f"{remote}/policy-{index}"])
            result = run(command)
            require("Success" in result.stdout, f"policy_rule_failed_{index}")
            records.append({"index": index, "source": source, "target": target,
                            "class": cls, "permissions": permissions})
        run([args.adb, "-s", args.serial, "pull", f"{remote}/policy-{len(combined)}",
             str(output / "sepolicy")])
        manifest = {
            "schema_version": 1,
            "status": "pass_for_system_control_boot_staging_only",
            "device": {"id": "r1-sample01", "hardware": "rk30board",
                       "fingerprint": fingerprint},
            "original_policy_sha256": digest(original),
            "current_policy_sha256": digest(current),
            "current_policy_manifest_sha256": digest(current_manifest_path),
            "patched_policy_sha256": digest(output / "sepolicy"),
            "patcher_sha256": digest(patcher),
            "selinux_mode": "enforcing", "permissive_domains": [],
            "existing_rule_count": len(existing_rules),
            "system_control_rule_count": len(RULES), "rules": records,
        }
        (output / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        os.chmod(output / "sepolicy", 0o600)
        os.chmod(output / "manifest.json", 0o600)
        return manifest
    finally:
        subprocess.run([args.adb, "-s", args.serial, "shell", "rm", "-rf", remote],
                       capture_output=True, timeout=10, shell=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--serial", required=True)
    parser.add_argument("--original-policy", required=True)
    parser.add_argument("--current-policy", required=True)
    parser.add_argument("--current-policy-sha256", required=True)
    parser.add_argument("--current-policy-manifest", required=True)
    parser.add_argument("--patcher", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(patch(args), sort_keys=True))
        return 0
    except (PolicyError, OSError, subprocess.SubprocessError,
            json.JSONDecodeError) as error:
        print("R1 system-control policy patch refused: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
