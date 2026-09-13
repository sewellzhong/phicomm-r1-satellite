#!/usr/bin/env python3
"""Patch a private R1 policy copy for the update supervisor; never load it."""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
DEVICE = "r1-sample01"
FINGERPRINT = "Android/rk322x_echo/rk322x_echo:5.1.1/LMY49F/3448:user/release-keys"
PATCHER_SHA256 = "f004860e65f95d8444104de74464bae67fd3052ad624d9f598fa3b42479e3054"
SOURCE_COMMIT = "e38bff264913e5bc2c8f18f67ec9f1017ace3982"
BASE_POLICY_SHA256 = "96fa3164741296482362fe9e0d126c9f55b8316421ec0cf9e79939b6cf5f269a"
FACTORY_PATCHER = ROOT / "tools/factory_audio/patch-device-sepolicy.py"
FACTORY_SPEC = importlib.util.spec_from_file_location("r1_factory_policy", FACTORY_PATCHER)
factory_policy = importlib.util.module_from_spec(FACTORY_SPEC)
FACTORY_SPEC.loader.exec_module(factory_policy)

# Initial enforcing profile. It is intentionally sufficient only for daemon
# startup and read-only package identity. Package replacement permissions are
# added solely from dedicated-domain AVC evidence after this profile boots.
RULES = (
    ("r1_update_supervisor", "system_file", "file", "read"),
    ("init", "r1_update_supervisor", "process", "transition,rlimitinh,siginh,noatsecure"),
    ("r1_update_supervisor", "r1_update_supervisor", "file", "entrypoint,open,read,execute,getattr"),
    ("init", "r1_update_supervisor", "unix_stream_socket", "create,bind,listen,setopt,getattr"),
    ("init", "r1_update_supervisor", "sock_file", "create,open,write,getattr,setattr,unlink"),
    ("init", "r1_update_supervisor", "dir", "create,open,read,search,getattr,setattr,relabelto"),
    ("init", "shell_data_file", "dir", "search,write,add_name"),
    ("r1_update_supervisor", "init", "fd", "use"),
    ("r1_update_supervisor", "kernel", "fd", "use"),
    ("r1_update_supervisor", "init", "process", "sigchld"),
    ("r1_update_supervisor", "r1_update_supervisor", "process", "fork,signal,sigchld,sigkill,setpgid,getcap,setcap"),
    ("r1_update_supervisor", "r1_update_supervisor", "capability", "setuid,setgid"),
    ("r1_update_supervisor", "r1_update_supervisor", "fifo_file", "read,write,getattr"),
    ("r1_update_supervisor", "rootfs", "dir", "open,read,search,getattr"),
    ("r1_update_supervisor", "rootfs", "file", "entrypoint,open,read,execute,getattr"),
    ("r1_update_supervisor", "rootfs", "lnk_file", "read,getattr"),
    ("r1_update_supervisor", "labeledfs", "filesystem", "associate"),
    ("r1_update_supervisor", "tmpfs", "filesystem", "associate"),
    ("r1_update_supervisor", "device", "dir", "search,getattr"),
    ("r1_update_supervisor", "socket_device", "dir", "search"),
    ("r1_update_supervisor", "system_file", "dir", "open,read,search,getattr"),
    ("r1_update_supervisor", "system_file", "file", "open,read,execute,execute_no_trans,getattr"),
    ("r1_update_supervisor", "system_file", "lnk_file", "read,getattr"),
    ("r1_update_supervisor", "zygote_exec", "file", "open,read,execute,execute_no_trans,getattr"),
    ("r1_update_supervisor", "dex2oat_exec", "file", "open,read,execute,execute_no_trans,getattr"),
    ("r1_update_supervisor", "r1_update_supervisor", "file", "open,read,getattr"),
    ("r1_update_supervisor", "proc", "dir", "open,read,search,getattr"),
    ("r1_update_supervisor", "proc", "file", "open,read,getattr"),
    ("r1_update_supervisor", "proc", "lnk_file", "read"),
    ("r1_update_supervisor", "sysfs", "dir", "open,read,search,getattr"),
    ("r1_update_supervisor", "sysfs", "file", "open,read,getattr"),
    ("r1_update_supervisor", "debugfs", "dir", "search"),
    ("r1_update_supervisor", "sysfs_devices_system_cpu", "dir", "open,read,search,getattr"),
    ("r1_update_supervisor", "selinuxfs", "filesystem", "getattr"),
    ("r1_update_supervisor", "properties_device", "file", "open,read,getattr"),
    ("r1_update_supervisor", "null_device", "chr_file", "open,read,write,getattr,ioctl"),
    ("r1_update_supervisor", "binder_device", "chr_file", "open,read,write,getattr,ioctl"),
    ("r1_update_supervisor", "ion_device", "chr_file", "open,read,write,getattr"),
    ("r1_update_supervisor", "ashmem_device", "chr_file", "open,read,write,getattr,ioctl"),
    ("r1_update_supervisor", "system_server_service", "service_manager", "find"),
    ("r1_update_supervisor", "servicemanager", "binder", "call"),
    ("servicemanager", "r1_update_supervisor", "dir", "search"),
    ("servicemanager", "r1_update_supervisor", "file", "open,read"),
    ("servicemanager", "r1_update_supervisor", "process", "getattr"),
    ("servicemanager", "r1_update_supervisor", "binder", "transfer"),
    ("r1_update_supervisor", "system_server", "binder", "call,transfer"),
    ("system_server", "r1_update_supervisor", "binder", "call,transfer"),
    ("r1_update_supervisor", "system_server", "fd", "use"),
    ("system_server", "r1_update_supervisor", "fd", "use"),
    ("system_server", "r1_update_supervisor", "dir", "search"),
    ("system_server", "r1_update_supervisor", "file", "open,read,getattr"),
    ("r1_update_supervisor", "system_data_file", "dir", "open,read,search,getattr"),
    ("r1_update_supervisor", "apk_data_file", "dir", "open,read,search,getattr"),
    ("r1_update_supervisor", "apk_data_file", "file", "open,read,write,getattr"),
    ("r1_update_supervisor", "dalvikcache_data_file", "dir", "open,read,write,search,add_name,remove_name,getattr"),
    ("r1_update_supervisor", "dalvikcache_data_file", "file", "create,open,read,write,execute,getattr,setattr,lock,unlink"),
    ("r1_update_supervisor", "resourcecache_data_file", "dir", "search"),
    ("r1_update_supervisor", "shell_data_file", "dir", "create,open,read,write,search,add_name,remove_name,getattr,setattr"),
    ("r1_update_supervisor", "shell_data_file", "file", "create,open,read,write,getattr,setattr,unlink"),
    ("r1_update_supervisor", "tmpfs", "file", "read"),
    ("r1_update_supervisor", "r1_update_supervisor", "dir", "create,open,read,write,search,add_name,remove_name,getattr,setattr"),
    ("r1_update_supervisor", "r1_update_supervisor", "file", "create,open,read,write,getattr,setattr,rename,link,unlink"),
    ("r1_update_supervisor", "r1_update_supervisor", "sock_file", "open,read,write,getattr"),
    ("r1_update_supervisor", "r1_update_supervisor", "unix_stream_socket", "create,connect,listen,accept,read,write,getattr,getopt,setopt,shutdown"),
    ("untrusted_app", "r1_update_supervisor", "sock_file", "open,read,write,getattr"),
    ("untrusted_app", "r1_update_supervisor", "unix_stream_socket", "connectto"),
    ("r1_update_supervisor", "untrusted_app", "unix_stream_socket", "accept,read,write,getattr,getopt,setopt"),
    ("r1_update_supervisor", "untrusted_app", "fd", "use"),
    ("r1_update_supervisor", "app_data_file", "file", "read,getattr"),
    ("r1_update_supervisor", "r1_update_supervisor", "unix_dgram_socket", "create,connect,write"),
    ("r1_update_supervisor", "logdw_socket", "sock_file", "open,write,getattr"),
    ("r1_update_supervisor", "logd", "unix_dgram_socket", "sendto"),
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


def run_rule(command, label):
    def tail(value):
        return value.replace("\n", " | ")[-1200:]

    try:
        result = run(command)
    except subprocess.CalledProcessError as error:
        detail = " ".join((error.stdout or "", error.stderr or "")).strip()
        raise PolicyError(f"{label}:exit_{error.returncode}:{tail(detail)}") from error
    detail = " ".join((result.stdout, result.stderr)).strip()
    require("Success" in result.stdout, f"{label}:missing_success:{tail(detail)}")
    return result


def outside_repository(path):
    resolved = Path(path).resolve()
    try:
        resolved.relative_to(ROOT)
        raise PolicyError("private_policy_output_must_be_outside_repository")
    except ValueError:
        return resolved


def patch(args):
    require(re.fullmatch(r"[A-Za-z0-9._:-]+", args.serial), "adb_serial_invalid")
    original = Path(args.original_policy).resolve(strict=True)
    current = Path(args.current_policy).resolve(strict=True)
    patcher = Path(args.patcher).resolve(strict=True)
    require(original.is_file() and not original.is_symlink(), "original_policy_invalid")
    require(current.is_file() and not current.is_symlink(), "current_policy_invalid")
    require(patcher.is_file() and not patcher.is_symlink(), "policy_patcher_invalid")
    require(digest(original) == args.original_sha256, "original_policy_hash_mismatch")
    require(args.original_sha256 == BASE_POLICY_SHA256, "original_policy_not_3448_base")
    require(digest(current) == args.current_policy_sha256,
            "current_policy_hash_mismatch")
    require(digest(patcher) == PATCHER_SHA256, "policy_patcher_hash_mismatch")
    output = outside_repository(args.output_dir)
    require(not output.exists(), "policy_output_already_exists")
    fingerprint = run([args.adb, "-s", args.serial, "shell", "getprop",
                       "ro.build.fingerprint"]).stdout.strip()
    hardware = run([args.adb, "-s", args.serial, "shell", "getprop",
                    "ro.hardware"]).stdout.strip()
    enforcing = run([args.adb, "-s", args.serial, "shell", "getenforce"]).stdout.strip()
    require(fingerprint == FINGERPRINT and hardware == "rk30board",
            "device_identity_mismatch")
    require(enforcing == "Enforcing", "selinux_not_enforcing")
    remote = "/data/local/tmp/r1-update-sepolicy-build"
    output.mkdir(mode=0o700)
    records = []
    try:
        run([args.adb, "-s", args.serial, "shell", "rm", "-rf", remote])
        run([args.adb, "-s", args.serial, "shell", "mkdir", remote])
        run([args.adb, "-s", args.serial, "push", str(patcher), remote + "/inject"])
        run([args.adb, "-s", args.serial, "push", str(original), remote + "/policy-0"])
        run([args.adb, "-s", args.serial, "push", str(original), remote + "/factory-0"])
        run([args.adb, "-s", args.serial, "shell", "chmod", "700", remote + "/inject"])
        for index, (source, target, cls, permissions) in enumerate(
                factory_policy.RULES, 1):
            run_rule([
                args.adb, "-s", args.serial, "shell", remote + "/inject",
                "-s", source, "-t", target, "-c", cls, "-p", permissions,
                "-P", f"{remote}/factory-{index - 1}",
                "-o", f"{remote}/factory-{index}",
            ], f"factory_policy_rule_failed_{index}")
        observed = run([
            args.adb, "-s", args.serial, "shell", "busybox", "sha256sum",
            f"{remote}/factory-{len(factory_policy.RULES)}",
        ]).stdout.strip().split()
        require(len(observed) == 2
                and observed[0] == args.current_policy_sha256
                and observed[1] == f"{remote}/factory-{len(factory_policy.RULES)}",
                "factory_policy_reconstruction_mismatch")
        # Both private domains must be inserted before the first serialization;
        # Android's old policy library cannot safely append a second type after
        # reading a policy that already contains one injected type.
        combined_rules = factory_policy.RULES + RULES
        for index, (source, target, cls, permissions) in enumerate(combined_rules, 1):
            command = [
                args.adb, "-s", args.serial, "shell", remote + "/inject",
                "-s", source, "-t", target, "-c", cls, "-p", permissions,
            ]
            if index == 1:
                command.extend(["-N", "r1_update_supervisor"])
            command.extend(["-P", f"{remote}/policy-{index - 1}",
                            "-o", f"{remote}/policy-{index}"])
            run_rule(command, f"policy_rule_failed_{index}")
            records.append({"index": index, "source": source, "target": target,
                            "class": cls, "permissions": permissions})
        run([args.adb, "-s", args.serial, "pull", f"{remote}/policy-{len(combined_rules)}",
             str(output / "sepolicy")])
        require((output / "sepolicy").stat().st_size >= original.stat().st_size,
                "patched_policy_size_invalid")
        manifest = {
            "schema_version": 1,
            "status": "pass_for_update_supervisor_boot_staging_only",
            "device": {"id": DEVICE, "hardware": hardware,
                       "fingerprint": fingerprint},
            "original_policy_sha256": digest(original),
            "current_factory_policy_sha256": digest(current),
            "patched_policy_sha256": digest(output / "sepolicy"),
            "patcher": {"sha256": digest(patcher), "source_commit": SOURCE_COMMIT},
            "selinux_mode": "enforcing",
            "permissive_domains": [],
            "profile": "update_supervisor_startup_and_read_only_identity",
            "rules": records,
        }
        (output / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        os.chmod(output / "sepolicy", 0o600)
        os.chmod(output / "manifest.json", 0o600)
        return manifest
    finally:
        subprocess.run([args.adb, "-s", args.serial, "shell", "rm", "-rf", remote],
                       capture_output=True, timeout=10, shell=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--serial", required=True)
    parser.add_argument("--original-policy", required=True)
    parser.add_argument("--original-sha256", required=True)
    parser.add_argument("--current-policy", required=True)
    parser.add_argument("--current-policy-sha256", required=True)
    parser.add_argument("--patcher", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(patch(args), sort_keys=True))
        return 0
    except (PolicyError, OSError, subprocess.SubprocessError,
            json.JSONDecodeError) as error:
        print("R1 update policy patch refused: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
