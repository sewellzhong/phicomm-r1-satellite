"""Tests for the guarded Android storage inventory."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location(
    "r1_adb_storage_inventory",
    Path(__file__).parents[1] / "r1-adb-storage-inventory.py",
)
inventory = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inventory)


class Completed:
    def __init__(self, stdout="", returncode=0, stderr=""):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


class AdbStorageInventoryTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.adb = self.root / "adb"
        self.adb.write_text("fixture")
        self.adb.chmod(0o755)
        self.calls = []

    def tearDown(self):
        self.temporary.cleanup()

    def runner(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        args = argv[3:]
        if args == ["get-state"]:
            return Completed("device\n")
        if args[:2] == ["shell", "getprop"]:
            values = {
                **inventory.EXPECTED_IDENTITY,
                "ro.product.model": "rk322x-box",
                "ro.build.fingerprint": "fixture/fingerprint",
                "ro.boot.console": "ttyFIQ0",
                "ro.boot.hardware": "rk30board",
                "ro.boot.mode": "emmc",
                "ro.boot.selinux": "permissive",
            }
            return Completed(values[args[2]] + "\n")
        if args == ["shell", "id"]:
            return Completed("uid=2000(shell) gid=2000(shell) context=u:r:shell:s0\n")
        if args == ["shell", "getenforce"]:
            return Completed("Enforcing\n")
        if args[:2] == ["shell", "cat"]:
            path = args[2]
            fixed = {
                "/sys/block/mmcblk0/queue/logical_block_size": "512\n",
                "/sys/block/mmcblk0/queue/physical_block_size": "512\n",
                "/sys/block/mmcblk0/size": "16000000\n",
                "/sys/block/mmcblk0/removable": "0\n",
                "/sys/block/mmcblk0/device/type": "MMC\n",
                "/sys/block/mmcblk0/device/name": "fixture\n",
                "/sys/block/mmcblk0/device/manfid": "0x15\n",
                "/sys/block/mmcblk0/device/oemid": "0x100\n",
            }
            if path in fixed:
                return Completed(fixed[path])
            if path == "/proc/partitions":
                return Completed("\n".join(
                    f"179 {number} 1 mmcblk0p{number}" for number in range(1, 17)
                ))
            if path == "/proc/mounts":
                return Completed("/dev/block/system /system ext4 ro 0 0\n")
            match = inventory.PARTITION_RE.search(Path(path).parts[-2])
            if match:
                number = int(match.group(1))
                field = Path(path).name
                start = 1000 * number
                size = 1000 if number < 16 else 16000000 - start
                values = {
                    "start": f"{start}\n",
                    "size": f"{size}\n",
                    "ro": "0\n",
                    "uevent": f"PARTN={number}\nPARTNAME=part{number}\n",
                }
                return Completed(values[field])
            return Completed("cat: Permission denied\n", 1)
        if args[:2] == ["shell", "ls"]:
            return Completed("ls: Permission denied\n", 1)
        raise AssertionError(args)

    def test_collects_validated_layout_without_shell_expansion(self):
        output = self.root / "evidence" / "inventory.json"
        result = inventory.collect_inventory(
            self.adb, "SERIAL", output, "r1-sample01", runner=self.runner
        )
        self.assertEqual("pass_with_access_limits", result["status"])
        self.assertEqual(16, len(result["partitions"]))
        self.assertEqual(16000000 * 512, result["emmc"]["bytes"])
        self.assertEqual(16000000, result["partitions"][-1]["end_sector_exclusive"])
        self.assertEqual(
            [{"start_sector": 0, "end_sector_exclusive": 1000,
              "sectors": 1000, "bytes": 512000}],
            result["unmapped_ranges"],
        )
        self.assertEqual(3, len(result["access_limits"]))
        self.assertTrue(all(call[1]["shell"] is False for call in self.calls))
        self.assertEqual("pass_with_access_limits", json.loads(output.read_text())["status"])

    def test_wrong_confirmation_stops_before_adb(self):
        with self.assertRaisesRegex(inventory.InventoryError, "confirmation"):
            inventory.collect_inventory(
                self.adb, "SERIAL", self.root / "out.json", "another-device",
                runner=self.runner,
            )
        self.assertEqual([], self.calls)

    def test_identity_mismatch_stops_before_storage_reads_and_records_failure(self):
        def runner(argv, **kwargs):
            result = self.runner(argv, **kwargs)
            if argv[3:] == ["shell", "getprop", "ro.hardware"]:
                return Completed("unexpected\n")
            return result

        output = self.root / "out.json"
        with self.assertRaisesRegex(inventory.InventoryError, "identity_mismatch"):
            inventory.collect_inventory(
                self.adb, "SERIAL", output, "r1-sample01", runner=runner
            )
        self.assertEqual("stopped", json.loads(output.read_text())["status"])
        self.assertFalse(any("/sys/block" in " ".join(call[0]) for call in self.calls))

    def test_existing_evidence_is_not_overwritten(self):
        output = self.root / "out.json"
        output.write_text("keep")
        with self.assertRaises(FileExistsError):
            inventory.collect_inventory(
                self.adb, "SERIAL", output, "r1-sample01", runner=self.runner
            )
        self.assertEqual("keep", output.read_text())


if __name__ == "__main__":
    unittest.main()
