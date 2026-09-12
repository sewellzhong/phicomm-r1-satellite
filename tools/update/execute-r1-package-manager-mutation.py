#!/usr/bin/env python3
"""Run one sealed R1 upgrade/downgrade evidence plan with bounded recovery."""

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time


def load_sibling(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


planner = load_sibling("r1_mutation_planner", "prepare-r1-package-manager-mutation.py")
collector = load_sibling("r1_package_evidence", "collect-r1-package-manager-evidence.py")

REMOTE_ROOT = "/data/local/tmp"
SERVICE_COMPONENT = f"{planner.PACKAGE_NAME}/.NativeSatelliteService"
SAFE_PLAN_ID_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_COMMAND_TEXT = 16384
POLL_SECONDS = 30


class ExecutionError(RuntimeError):
    pass


def canonical_plan_id(plan):
    base = dict(plan)
    for key in ("plan_id", "execution_confirmation", "created_at"):
        base.pop(key, None)
    payload = json.dumps(base, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def validate_plan(path, confirmation):
    path = Path(path).resolve(strict=True)
    plan = json.loads(path.read_text())
    plan_id = plan.get("plan_id", "")
    if not SAFE_PLAN_ID_RE.fullmatch(plan_id) or canonical_plan_id(plan) != plan_id:
        raise ExecutionError("plan_integrity_invalid")
    if plan.get("schema_version") != 1 or plan.get("operation") != (
        "package_manager_upgrade_and_explicit_downgrade_evidence"
    ):
        raise ExecutionError("plan_schema_invalid")
    if plan.get("device_id") != planner.DEVICE_ID or plan.get("firmware") != planner.FIRMWARE:
        raise ExecutionError("plan_target_invalid")
    if plan.get("package_name") != planner.PACKAGE_NAME:
        raise ExecutionError("plan_package_invalid")
    expected_confirmation = (
        f"{planner.DEVICE_ID}:{planner.FIRMWARE}:"
        f"v{plan.get('rollback', {}).get('version_code')}->"
        f"v{plan.get('candidate', {}).get('version_code')}->"
        f"v{plan.get('rollback', {}).get('version_code')}:{plan_id[:16]}"
    )
    if plan.get("execution_confirmation") != expected_confirmation:
        raise ExecutionError("plan_confirmation_binding_invalid")
    if confirmation != expected_confirmation:
        raise ExecutionError("execution_confirmation_required")
    evidence = Path(plan.get("device_evidence", {}).get("path", "")).resolve(strict=True)
    if planner.sha256_file(evidence) != plan["device_evidence"].get("sha256"):
        raise ExecutionError("device_evidence_changed")
    return path, plan


def validate_apk_input(plan_item, label, aapt, apksigner, runner):
    path, _ = planner.require_regular_private_input(plan_item.get("path", ""), label)
    if planner.sha256_file(path) != plan_item.get("sha256"):
        raise ExecutionError(f"{label}_hash_changed")
    actual = planner.inspect_apk(path, aapt, apksigner, runner)
    for key in ("package_name", "version_code", "size_bytes", "sha256", "signer_sha256"):
        if actual.get(key) != plan_item.get(key):
            raise ExecutionError(f"{label}_{key}_changed")
    return path, actual


def bounded(value):
    return (value or "").replace("\r", "")[:MAX_COMMAND_TEXT]


class AdbSession:
    def __init__(self, adb, serial, runner=subprocess.run):
        self.adb = str(adb)
        self.serial = serial
        self.runner = runner
        self.records = []

    def run(self, arguments, timeout=30, check=True, full_stdout=False):
        try:
            completed = self.runner(
                [self.adb, "-s", self.serial, *map(str, arguments)],
                capture_output=True, text=True, timeout=timeout, check=False, shell=False,
            )
            record = {
                "arguments": list(map(str, arguments)),
                "exit_code": completed.returncode,
                "stdout": bounded(completed.stdout),
                "stderr": bounded(completed.stderr),
            }
        except subprocess.TimeoutExpired:
            record = {
                "arguments": list(map(str, arguments)), "exit_code": 124,
                "stdout": "", "stderr": f"timed out after {timeout} seconds",
                "timed_out": True,
            }
        self.records.append(record)
        if check and record["exit_code"] != 0:
            raise ExecutionError(f"adb_command_failed:{arguments}:{record['exit_code']}")
        returned = dict(record)
        if full_stdout and not returned.get("timed_out"):
            returned["stdout"] = (completed.stdout or "").replace("\r", "")
        return returned


def read_live_package(session):
    dump = session.run(["shell", "dumpsys", "package", planner.PACKAGE_NAME])
    package = collector.parse_package_dump(dump["stdout"])
    digest_record = session.run(
        ["shell", "busybox", "sha256sum", package["apk_path"]], check=False,
    )
    package["apk_sha256"] = collector.parse_sha256(
        digest_record["stdout"], package["apk_path"]
    )
    return package


def require_live_baseline(session, plan):
    if session.run(["get-state"])["stdout"].strip() != "device":
        raise ExecutionError("adb_not_ready")
    expected = collector.EXPECTED_IDENTITY
    actual = {
        key: session.run(["shell", "getprop", key])["stdout"].strip()
        for key in expected
    }
    if actual != expected:
        raise ExecutionError("live_identity_mismatch")
    if "uid=2000(shell)" not in session.run(["shell", "id"])["stdout"]:
        raise ExecutionError("unexpected_adb_identity")
    if session.run(["shell", "getenforce"])["stdout"].strip() != "Enforcing":
        raise ExecutionError("selinux_not_enforcing")
    package = read_live_package(session)
    rollback = plan["rollback"]
    if package["version_code"] != rollback["version_code"]:
        raise ExecutionError("live_version_not_rollback")
    if package["apk_sha256"] != rollback["sha256"]:
        raise ExecutionError("live_hash_not_rollback")
    return {"identity": actual, "package": package}


def parse_success(record, label):
    lines = [line.strip() for line in record["stdout"].splitlines() if line.strip()]
    if record["exit_code"] != 0 or lines != ["Success"]:
        raise ExecutionError(f"{label}_package_manager_failed")


def wait_for_package(session, expected, sleeper=time.sleep):
    last_error = "not_observed"
    for attempt in range(POLL_SECONDS + 1):
        try:
            package = read_live_package(session)
            if (
                package["version_code"] == expected["version_code"]
                and package["apk_sha256"] == expected["sha256"]
            ):
                return package
            last_error = (
                f"identity:v{package['version_code']}:{package['apk_sha256']}"
            )
        except Exception as error:  # Package replacement can briefly remove records.
            last_error = str(error)
        if attempt < POLL_SECONDS:
            sleeper(1)
    raise ExecutionError(f"package_identity_timeout:{last_error}")


def package_manager_install(session, remote_path, downgrade=False):
    arguments = [
        "shell", "CLASSPATH=/system/framework/pm.jar", "app_process", "/system/bin",
        "com.android.commands.pm.Pm", "install", "-r",
    ]
    if downgrade:
        arguments.append("-d")
    arguments.append(remote_path)
    return session.run(arguments, timeout=120, check=False)


def avc_snapshot(session):
    record = session.run(
        ["shell", "dmesg"], timeout=20, check=False, full_stdout=True
    )
    lines = [line for line in record["stdout"].splitlines() if "avc:" in line.lower()]
    return {
        "exit_code": record["exit_code"], "lines": lines[-collector.MAX_AVC_LINES:],
        "truncated": len(lines) > collector.MAX_AVC_LINES,
    }


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


def execute(plan_path, confirmation, output, serial, execute_enabled, adb, aapt,
            apksigner, runner=subprocess.run, sleeper=time.sleep):
    if not execute_enabled:
        raise ExecutionError("explicit_execute_flag_required")
    plan_path, plan = validate_plan(plan_path, confirmation)
    expected_output = plan_path.parent / (
        f"mutation-execution-{plan['plan_id'][:16]}.json"
    )
    output = Path(output).resolve(strict=False)
    if output != expected_output:
        raise ExecutionError("output_path_not_plan_bound")
    if output.exists():
        raise FileExistsError(output)
    if serial != plan.get("adb_serial") or not serial or any(c.isspace() for c in serial):
        raise ExecutionError("adb_serial_not_plan_target")
    adb = planner.resolve_tool(adb, "adb")
    aapt = planner.resolve_tool(aapt, "aapt")
    apksigner = planner.resolve_tool(apksigner, "apksigner")
    candidate_path, _ = validate_apk_input(
        plan["candidate"], "candidate", aapt, apksigner, runner
    )
    rollback_path, _ = validate_apk_input(
        plan["rollback"], "rollback", aapt, apksigner, runner
    )
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)

    suffix = plan["plan_id"][:32]
    remote_candidate = f"{REMOTE_ROOT}/r1-update-{suffix}-candidate.apk"
    remote_rollback = f"{REMOTE_ROOT}/r1-update-{suffix}-rollback.apk"
    session = AdbSession(adb, serial, runner)
    report = {
        "schema_version": 1,
        "operation": "package_manager_upgrade_and_explicit_downgrade_evidence",
        "plan_id": plan["plan_id"],
        "device_id": planner.DEVICE_ID,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "running",
        "package_mutation_started": False,
        "emergency_rollback_attempted": False,
    }
    rollback_restored = False
    staged_started = False
    pending_error = None
    try:
        report["before"] = require_live_baseline(session, plan)
        report["avc_before"] = avc_snapshot(session)
        for local, remote, expected in (
            (candidate_path, remote_candidate, plan["candidate"]),
            (rollback_path, remote_rollback, plan["rollback"]),
        ):
            staged_started = True
            session.run(["push", local, remote], timeout=120)
            remote_digest = session.run(
                ["shell", "busybox", "sha256sum", remote], check=False
            )
            if collector.parse_sha256(remote_digest["stdout"], remote) != expected["sha256"]:
                raise ExecutionError("staged_apk_hash_mismatch")

        report["package_mutation_started"] = True
        upgrade = package_manager_install(session, remote_candidate)
        report["upgrade_return"] = upgrade
        parse_success(upgrade, "upgrade")
        report["upgraded"] = wait_for_package(session, plan["candidate"], sleeper)

        downgrade = package_manager_install(session, remote_rollback, downgrade=True)
        report["downgrade_return"] = downgrade
        parse_success(downgrade, "downgrade")
        report["restored"] = wait_for_package(session, plan["rollback"], sleeper)
        rollback_restored = True
        report["status"] = "pass_backend_evidence_only"
    except Exception as error:
        pending_error = error
        report["status"] = "failed"
        report["error"] = str(error)
        if report["package_mutation_started"]:
            try:
                current = read_live_package(session)
                if (
                    current["version_code"] == plan["rollback"]["version_code"]
                    and current["apk_sha256"] == plan["rollback"]["sha256"]
                ):
                    report["restored"] = current
                    rollback_restored = True
                else:
                    report["emergency_rollback_attempted"] = True
                    emergency = package_manager_install(
                        session, remote_rollback, downgrade=True
                    )
                    report["emergency_rollback_return"] = emergency
                    parse_success(emergency, "emergency_rollback")
                    report["restored"] = wait_for_package(
                        session, plan["rollback"], sleeper
                    )
                    rollback_restored = True
            except Exception as rollback_error:
                report["emergency_rollback_error"] = str(rollback_error)
    finally:
        report["avc_after"] = avc_snapshot(session)
        if staged_started:
            cleanup = session.run(
                ["shell", "rm", "-f", remote_candidate, remote_rollback], check=False
            )
            report["cleanup_return"] = cleanup
        if rollback_restored:
            report["service_restore_return"] = session.run(
                ["shell", "am", "startservice", "-n", SERVICE_COMPONENT],
                timeout=30, check=False,
            )
        report["commands"] = session.records
        report["rollback_restored"] = rollback_restored
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_json_exclusive(output, report)
    if pending_error is not None:
        raise pending_error
    return report


def parser():
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("serial")
    value.add_argument("--plan", required=True, type=Path)
    value.add_argument("--confirmation", required=True)
    value.add_argument("--output", required=True, type=Path)
    value.add_argument("--execute", action="store_true")
    value.add_argument("--adb", default="adb", type=Path)
    value.add_argument("--aapt", default="aapt", type=Path)
    value.add_argument("--apksigner", default="apksigner", type=Path)
    return value


def main():
    args = parser().parse_args()
    try:
        result = execute(
            args.plan, args.confirmation, args.output, args.serial, args.execute,
            args.adb, args.aapt, args.apksigner,
        )
    except (ExecutionError, planner.PlanError, collector.EvidenceError,
            FileExistsError, FileNotFoundError, json.JSONDecodeError) as error:
        print(f"stopped: {error}", file=sys.stderr)
        return 2
    print(json.dumps({
        "status": result["status"], "plan_id": result["plan_id"],
        "rollback_restored": result["rollback_restored"], "output": str(args.output),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
