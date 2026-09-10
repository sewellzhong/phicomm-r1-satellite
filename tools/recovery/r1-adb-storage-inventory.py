#!/usr/bin/env python3
"""Collect a guarded, read-only Android view of r1-sample01 storage."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


DEVICE_ID = "r1-sample01"
EXPECTED_IDENTITY = {
    "ro.product.device": "rk322x_echo",
    "ro.hardware": "rk30board",
    "ro.build.version.incremental": "3448",
    "ro.build.version.release": "5.1.1",
    "ro.build.version.sdk": "22",
}
IDENTITY_PROPERTIES = (*EXPECTED_IDENTITY, "ro.product.model", "ro.build.fingerprint")
BOOT_PROPERTIES = ("ro.boot.console", "ro.boot.hardware", "ro.boot.mode", "ro.boot.selinux")
PARTITION_RE = re.compile(r"^mmcblk0p([1-9][0-9]*)$")
UEVENT_RE = re.compile(r"^([A-Z0-9_]+)=(.*)$")


class InventoryError(RuntimeError):
    pass


def write_json_exclusive(path, value):
    data = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
    except Exception:
        Path(path).unlink(missing_ok=True)
        raise


def run_adb(adb, serial, arguments, runner=subprocess.run, timeout=10, check=True):
    completed = runner(
        [str(adb), "-s", serial, *arguments], capture_output=True, text=True,
        timeout=timeout, check=False, shell=False,
    )
    record = {
        "arguments": arguments,
        "exit_code": completed.returncode,
        "stdout": completed.stdout.replace("\r", ""),
        "stderr": completed.stderr.replace("\r", ""),
    }
    if check and completed.returncode != 0:
        raise InventoryError(f"adb_command_failed:{arguments}:{completed.returncode}")
    return record


def read_text(adb, serial, path, runner=subprocess.run):
    return run_adb(adb, serial, ["shell", "cat", path], runner=runner)["stdout"].strip()


def read_int(adb, serial, path, runner=subprocess.run):
    value = read_text(adb, serial, path, runner=runner)
    try:
        return int(value, 10)
    except ValueError as error:
        raise InventoryError(f"invalid_integer:{path}:{value}") from error


def parse_proc_partitions(value):
    nodes = []
    for line in value.splitlines():
        fields = line.split()
        if len(fields) != 4 or not PARTITION_RE.fullmatch(fields[3]):
            continue
        nodes.append(fields[3])
    return sorted(nodes, key=lambda node: int(PARTITION_RE.fullmatch(node).group(1)))


def parse_uevent(value):
    result = {}
    for line in value.splitlines():
        match = UEVENT_RE.fullmatch(line)
        if match:
            result[match.group(1)] = match.group(2)
    return result


def collect_inventory(adb, serial, output, confirm_device, runner=subprocess.run):
    if confirm_device != DEVICE_ID:
        raise InventoryError("device_confirmation_required")
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
        "started_at": datetime.now(timezone.utc).isoformat(),
        "operation": "read_only_android_storage_inventory",
        "status": "running",
    }
    try:
        state = run_adb(adb, serial, ["get-state"], runner=runner)["stdout"].strip()
        if state != "device":
            raise InventoryError(f"adb_not_ready:{state}")

        identity = {}
        for name in IDENTITY_PROPERTIES:
            identity[name] = run_adb(
                adb, serial, ["shell", "getprop", name], runner=runner
            )["stdout"].strip()
        mismatches = {
            name: {"expected": expected, "actual": identity.get(name)}
            for name, expected in EXPECTED_IDENTITY.items()
            if identity.get(name) != expected
        }
        if mismatches:
            raise InventoryError(f"identity_mismatch:{json.dumps(mismatches, sort_keys=True)}")
        result["identity"] = identity
        result["adb_context"] = {
            "id": run_adb(adb, serial, ["shell", "id"], runner=runner)["stdout"].strip(),
            "selinux": run_adb(adb, serial, ["shell", "getenforce"], runner=runner)["stdout"].strip(),
        }
        if "uid=2000(shell)" not in result["adb_context"]["id"]:
            raise InventoryError("unexpected_adb_identity")

        logical = read_int(adb, serial, "/sys/block/mmcblk0/queue/logical_block_size", runner)
        physical = read_int(adb, serial, "/sys/block/mmcblk0/queue/physical_block_size", runner)
        sectors = read_int(adb, serial, "/sys/block/mmcblk0/size", runner)
        result["emmc"] = {
            "sectors": sectors,
            "logical_block_bytes": logical,
            "physical_block_bytes": physical,
            "bytes": sectors * logical,
            "removable": read_int(adb, serial, "/sys/block/mmcblk0/removable", runner),
            "type": read_text(adb, serial, "/sys/block/mmcblk0/device/type", runner),
            "name": read_text(adb, serial, "/sys/block/mmcblk0/device/name", runner),
            "manufacturer_id": read_text(adb, serial, "/sys/block/mmcblk0/device/manfid", runner),
            "oem_id": read_text(adb, serial, "/sys/block/mmcblk0/device/oemid", runner),
        }
        if logical != 512 or physical != 512 or not 10_000_000 <= sectors <= 20_000_000:
            raise InventoryError("unexpected_emmc_geometry")

        proc_partitions = read_text(adb, serial, "/proc/partitions", runner)
        result["proc_partitions"] = proc_partitions
        nodes = parse_proc_partitions(proc_partitions)
        if nodes != [f"mmcblk0p{number}" for number in range(1, 17)]:
            raise InventoryError(f"unexpected_partition_nodes:{nodes}")

        partitions = []
        previous_end = 0
        unmapped_ranges = []
        for node in nodes:
            root = f"/sys/class/block/{node}"
            start = read_int(adb, serial, f"{root}/start", runner)
            size = read_int(adb, serial, f"{root}/size", runner)
            read_only = read_int(adb, serial, f"{root}/ro", runner)
            uevent = parse_uevent(read_text(adb, serial, f"{root}/uevent", runner))
            number = int(PARTITION_RE.fullmatch(node).group(1))
            if int(uevent.get("PARTN", "-1")) != number or not uevent.get("PARTNAME"):
                raise InventoryError(f"invalid_partition_identity:{node}")
            end = start + size
            if start < previous_end or end > sectors:
                raise InventoryError(f"invalid_partition_range:{node}:{start}:{end}")
            if start > previous_end:
                unmapped_ranges.append({
                    "start_sector": previous_end,
                    "end_sector_exclusive": start,
                    "sectors": start - previous_end,
                    "bytes": (start - previous_end) * logical,
                })
            partitions.append({
                "node": node,
                "number": number,
                "name": uevent["PARTNAME"],
                "start_sector": start,
                "sectors": size,
                "end_sector_exclusive": end,
                "bytes": size * logical,
                "read_only": bool(read_only),
            })
            previous_end = end
        if partitions[-1]["end_sector_exclusive"] != sectors:
            unmapped_ranges.append({
                "start_sector": partitions[-1]["end_sector_exclusive"],
                "end_sector_exclusive": sectors,
                "sectors": sectors - partitions[-1]["end_sector_exclusive"],
                "bytes": (sectors - partitions[-1]["end_sector_exclusive"]) * logical,
            })
        result["partitions"] = partitions
        result["unmapped_ranges"] = unmapped_ranges
        result["unallocated_prefix_sectors"] = partitions[0]["start_sector"]
        result["unallocated_suffix_sectors"] = sectors - partitions[-1]["end_sector_exclusive"]

        result["boot_properties"] = {
            name: run_adb(adb, serial, ["shell", "getprop", name], runner=runner)["stdout"].strip()
            for name in BOOT_PROPERTIES
        }
        result["mounts"] = read_text(adb, serial, "/proc/mounts", runner)
        result["access_limits"] = []
        for label, arguments in (
            ("kernel_cmdline", ["shell", "cat", "/proc/cmdline"]),
            ("platform_by_name", ["shell", "ls", "-l", "/dev/block/platform/30020000.rksdmmc/by-name"]),
            ("fstab", ["shell", "cat", "/fstab.rk30board"]),
        ):
            record = run_adb(adb, serial, arguments, runner=runner, check=False)
            if record["exit_code"] != 0 or "Permission denied" in record["stdout"] + record["stderr"]:
                result["access_limits"].append({"item": label, **record})
            else:
                result[label] = record["stdout"]

        result["status"] = "pass_with_access_limits" if result["access_limits"] else "pass"
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
        result = collect_inventory(
            args.adb, args.serial, args.output, args.confirm_device
        )
    except (InventoryError, FileExistsError, FileNotFoundError, subprocess.TimeoutExpired) as error:
        print(f"stopped: {error}", file=sys.stderr)
        return 2
    print(json.dumps({
        "status": result["status"],
        "bytes": result["emmc"]["bytes"],
        "partitions": len(result["partitions"]),
        "output": str(args.output),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
