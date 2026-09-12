#!/usr/bin/env python3
"""Collect guarded, read-only package-manager evidence from r1-sample01."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


DEVICE_ID = "r1-sample01"
PACKAGE_NAME = "dev.sewellzhong.r1probe"
EXPECTED_IDENTITY = {
    "ro.product.device": "rk322x_echo",
    "ro.hardware": "rk30board",
    "ro.build.version.incremental": "3448",
    "ro.build.version.release": "5.1.1",
    "ro.build.version.sdk": "22",
}
IDENTITY_PROPERTIES = (*EXPECTED_IDENTITY, "ro.product.model", "ro.build.fingerprint")
APK_PATH_RE = re.compile(r"^/[A-Za-z0-9_./=+-]+\.apk$")
INTEGER_RE = re.compile(r"^[0-9]+$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_AVC_LINES = 400


class EvidenceError(RuntimeError):
    pass


def write_json_exclusive(path, value):
    payload = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        Path(path).unlink(missing_ok=True)
        raise


def run_adb(adb, serial, arguments, runner=subprocess.run, timeout=15, check=True):
    completed = runner(
        [str(adb), "-s", serial, *arguments], capture_output=True, text=True,
        timeout=timeout, check=False, shell=False,
    )
    record = {
        "arguments": list(arguments),
        "exit_code": completed.returncode,
        "stdout": completed.stdout.replace("\r", ""),
        "stderr": completed.stderr.replace("\r", ""),
    }
    if check and completed.returncode != 0:
        raise EvidenceError(f"adb_command_failed:{arguments}:{completed.returncode}")
    return record


def parse_pm_path(value):
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if len(lines) != 1 or not lines[0].startswith("package:"):
        raise EvidenceError("package_path_response_invalid")
    path = lines[0][len("package:"):]
    if not APK_PATH_RE.fullmatch(path) or ".." in Path(path).parts:
        raise EvidenceError("package_path_invalid")
    return path


def parse_package_dump(value, apk_path):
    package_marker = f"Package [{PACKAGE_NAME}]"
    if package_marker not in value:
        raise EvidenceError("package_dump_identity_missing")

    def one(pattern, label):
        matches = re.findall(pattern, value, flags=re.MULTILINE)
        unique = sorted(set(matches))
        if len(unique) != 1:
            raise EvidenceError(f"package_dump_{label}_invalid")
        return unique[0]

    version = one(r"^\s*versionCode=([0-9]+)(?:\s|$)", "version")
    user_id = one(r"^\s*userId=([0-9]+)\s*$", "uid")
    code_path = one(r"^\s*codePath=(/[A-Za-z0-9_./=+-]+)\s*$", "code_path")
    if not INTEGER_RE.fullmatch(version) or not INTEGER_RE.fullmatch(user_id):
        raise EvidenceError("package_dump_integer_invalid")
    if not APK_PATH_RE.fullmatch(apk_path) or not (
        apk_path == code_path or apk_path.startswith(code_path.rstrip("/") + "/")
    ):
        raise EvidenceError("package_path_dump_mismatch")
    return {
        "package_name": PACKAGE_NAME,
        "version_code": int(version),
        "uid": int(user_id),
        "code_path": code_path,
        "apk_path": apk_path,
        "dump_sha256": hashlib.sha256(value.encode()).hexdigest(),
    }


def parse_sha256(value, apk_path):
    fields = value.strip().split()
    if len(fields) != 2 or fields[1] != apk_path or not SHA256_RE.fullmatch(fields[0]):
        raise EvidenceError("installed_apk_sha256_invalid")
    return fields[0]


def filtered_avc(record):
    if record["exit_code"] != 0:
        return {
            "available": False,
            "exit_code": record["exit_code"],
            "stderr": record["stderr"][:1000],
            "lines": [],
            "truncated": False,
        }
    matches = [line for line in record["stdout"].splitlines() if "avc:" in line.lower()]
    return {
        "available": True,
        "exit_code": 0,
        "lines": matches[-MAX_AVC_LINES:],
        "truncated": len(matches) > MAX_AVC_LINES,
    }


def collect_evidence(adb, serial, output, confirm_device, runner=subprocess.run):
    if confirm_device != DEVICE_ID:
        raise EvidenceError("device_confirmation_required")
    if not serial or any(byte.isspace() for byte in serial):
        raise EvidenceError("adb_serial_invalid")
    adb_path = shutil.which(str(adb)) if Path(adb).name == str(adb) else str(adb)
    if not adb_path:
        raise FileNotFoundError(adb)
    adb = Path(adb_path).resolve(strict=True)
    output = Path(output)
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(output)

    result = {
        "schema_version": 1,
        "device_id": DEVICE_ID,
        "adb_serial": serial,
        "package_name": PACKAGE_NAME,
        "operation": "read_only_package_manager_evidence",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "running",
    }
    try:
        state = run_adb(adb, serial, ["get-state"], runner=runner)["stdout"].strip()
        if state != "device":
            raise EvidenceError(f"adb_not_ready:{state}")

        identity = {
            name: run_adb(adb, serial, ["shell", "getprop", name], runner=runner)["stdout"].strip()
            for name in IDENTITY_PROPERTIES
        }
        mismatches = {
            name: {"expected": expected, "actual": identity.get(name)}
            for name, expected in EXPECTED_IDENTITY.items()
            if identity.get(name) != expected
        }
        if mismatches:
            raise EvidenceError(f"identity_mismatch:{json.dumps(mismatches, sort_keys=True)}")
        result["identity"] = identity

        adb_id = run_adb(adb, serial, ["shell", "id"], runner=runner)["stdout"].strip()
        enforcing = run_adb(adb, serial, ["shell", "getenforce"], runner=runner)["stdout"].strip()
        result["adb_context"] = {"id": adb_id, "selinux": enforcing}
        if "uid=2000(shell)" not in adb_id:
            raise EvidenceError("unexpected_adb_identity")
        if enforcing != "Enforcing":
            raise EvidenceError("selinux_not_enforcing")

        pm_record = run_adb(
            adb, serial, ["shell", "pm", "path", PACKAGE_NAME], runner=runner
        )
        apk_path = parse_pm_path(pm_record["stdout"])
        dump_record = run_adb(
            adb, serial, ["shell", "dumpsys", "package", PACKAGE_NAME], runner=runner
        )
        result["installed_package"] = parse_package_dump(dump_record["stdout"], apk_path)

        digest_record = run_adb(
            adb, serial, ["shell", "sha256sum", apk_path], runner=runner, check=False
        )
        if digest_record["exit_code"] == 0:
            result["installed_package"]["apk_sha256"] = parse_sha256(
                digest_record["stdout"], apk_path
            )
            result["installed_package"]["apk_sha256_source"] = "device_sha256sum"
        else:
            result["installed_package"]["apk_sha256"] = None
            result["installed_package"]["apk_sha256_source"] = "unavailable"
            result["access_limits"] = [{
                "item": "installed_apk_sha256",
                "exit_code": digest_record["exit_code"],
                "stderr": digest_record["stderr"][:1000],
            }]

        help_record = run_adb(
            adb, serial, ["shell", "pm", "help"], runner=runner, check=False
        )
        result["package_manager_entrypoint"] = {
            "pm_path_exit_code": pm_record["exit_code"],
            "pm_help_exit_code": help_record["exit_code"],
            "pm_help_sha256": hashlib.sha256(help_record["stdout"].encode()).hexdigest(),
            "pm_help_has_install": bool(re.search(r"(?:^|\s)install(?:\s|$)", help_record["stdout"])),
            "pm_help_has_downgrade_flag": "-d" in help_record["stdout"],
        }

        dmesg = run_adb(adb, serial, ["shell", "dmesg"], runner=runner, check=False)
        logcat = run_adb(
            adb, serial, ["shell", "logcat", "-d", "-v", "brief"],
            runner=runner, timeout=30, check=False,
        )
        result["avc"] = {"dmesg": filtered_avc(dmesg), "logcat": filtered_avc(logcat)}
        result["status"] = "pass_with_access_limits" if result.get("access_limits") else "pass"
    except Exception as error:
        result["status"] = "stopped"
        result["error"] = str(error)
        raise
    finally:
        result["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_json_exclusive(output, result)
    return result


def parser():
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("serial")
    value.add_argument("--confirm-device", required=True)
    value.add_argument("--output", required=True, type=Path)
    value.add_argument("--adb", default="adb", type=Path)
    return value


def main():
    args = parser().parse_args()
    try:
        result = collect_evidence(args.adb, args.serial, args.output, args.confirm_device)
    except (EvidenceError, FileExistsError, FileNotFoundError, subprocess.TimeoutExpired) as error:
        print(f"stopped: {error}", file=sys.stderr)
        return 2
    print(json.dumps({
        "status": result["status"],
        "package": result["package_name"],
        "version_code": result["installed_package"]["version_code"],
        "output": str(args.output),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
