import gzip
import hashlib
import importlib.util
from pathlib import Path
import stat
import struct
import tempfile
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "tools/update/build-r1-update-fault-boot.py"
SPEC = importlib.util.spec_from_file_location("fault_boot", SCRIPT)
fault_boot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fault_boot)


class FaultBootBuilderTest(unittest.TestCase):
    def entry(self, name, data, inode, mode=0o644):
        return fault_boot.boot.Entry(
            name, [inode, stat.S_IFREG | mode, 0, 0, 1, 0, len(data),
                   0, 0, 0, 0, len(name.encode()) + 1, 0], data)

    def fixture(self, directory):
        base = Path(directory)
        supervisor = b"production-supervisor"
        helper = b"production-helper"
        init = (b"service r1_update /sbin/r1-update-supervisor\n"
                b"    disabled\n\non property:sys.boot_completed=1\n"
                b"    start r1_update\n")
        contexts = (b"/sbin/r1-update-supervisor u:object_r:r1_update_supervisor:s0\n"
                    b"/sbin/r1-update-helper.jar u:object_r:r1_update_supervisor:s0\n")
        entries = [
            self.entry("sepolicy", b"production-policy", 1),
            self.entry("file_contexts", contexts, 2),
            self.entry("init.rk30board.rc",
                       b"import /init.r1_update_supervisor.rc\n", 3),
            self.entry("init.r1_update_supervisor.rc", init, 4),
            self.entry("sbin/r1-update-supervisor", supervisor, 5, 0o750),
            self.entry("sbin/r1-update-helper.jar", helper, 6),
        ]
        ramdisk = gzip.compress(fault_boot.boot.build_cpio(entries),
                                compresslevel=9, mtime=0)
        ramdisk += b"\0" * (fault_boot.boot.aligned(len(ramdisk), 4) - len(ramdisk))
        kernel, second, page = b"kernel", b"second", 16384
        values = (len(kernel), 0x60408000, len(ramdisk), 0x62000000,
                  len(second), 0x60f00000, 0x60000100, page)
        header = bytearray(page)
        header[:8] = b"ANDROID!"
        struct.pack_into("<8I", header, 8, *values)
        header[576:596] = fault_boot.boot.rockchip_boot_id(
            header, kernel, ramdisk, second)
        image = bytes(header) + kernel
        image += b"\0" * (fault_boot.boot.aligned(len(kernel), page) - len(kernel))
        image += ramdisk
        image += b"\0" * (fault_boot.boot.aligned(len(ramdisk), page) - len(ramdisk))
        image += second
        image += b"\0" * (fault_boot.boot.aligned(len(second), page) - len(second))
        image += b"\0" * (fault_boot.PARTITION_BYTES - len(image))
        boot_a, boot_b = base / "boot-a.img", base / "boot-b.img"
        boot_a.write_bytes(image)
        boot_b.write_bytes(image)
        binary = base / "fault-helper"
        binary.write_bytes(b"ELF32 ARM fault helper")
        args = types.SimpleNamespace(
            current_boot_a=str(boot_a), current_boot_b=str(boot_b),
            expected_current_sha256=hashlib.sha256(image).hexdigest(),
            expected_supervisor_sha256=hashlib.sha256(supervisor).hexdigest(),
            expected_helper_sha256=hashlib.sha256(helper).hexdigest(),
            fault_helper=str(binary),
            expected_fault_helper_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
            crash_operation="1" * 32, rollback_operation="2" * 32,
            output_dir=str(base / "output"),
        )
        return args, entries

    def test_adds_only_fault_helper_init_and_context(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            args, original = self.fixture(directory)
            with mock.patch.object(fault_boot, "assert_elf32_arm"):
                result = fault_boot.build(args)
            self.assertFalse(result["production_supervisor_changed"])
            candidate = Path(args.output_dir, "boot-r1-update-fault-validation.img")
            _, kernel, ramdisk, second = fault_boot.boot.boot_parts(candidate.read_bytes())
            parsed = {entry.name: entry.data for entry in
                      fault_boot.boot.parse_cpio(gzip.decompress(ramdisk))}
            before = {entry.name: entry.data for entry in original}
            self.assertEqual(before["sbin/r1-update-supervisor"],
                             parsed["sbin/r1-update-supervisor"])
            self.assertEqual(before["sepolicy"], parsed["sepolicy"])
            self.assertIn(b"1" * 32 + b" " + b"2" * 32,
                          parsed["init.r1_update_supervisor.rc"])
            self.assertIn("sbin/r1-update-fault-helper", parsed)
            self.assertEqual(b"kernel", kernel)
            self.assertEqual(b"second", second)

    def test_refuses_wrong_current_hash(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            args, _ = self.fixture(directory)
            args.expected_current_sha256 = "0" * 64
            with mock.patch.object(fault_boot, "assert_elf32_arm"):
                with self.assertRaisesRegex(fault_boot.BuildError,
                                            "current_boot_hash_mismatch"):
                    fault_boot.build(args)

    def test_refuses_reused_operation_id(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            args, _ = self.fixture(directory)
            args.rollback_operation = args.crash_operation
            with self.assertRaisesRegex(fault_boot.BuildError,
                                        "fault_operations_must_differ"):
                fault_boot.build(args)


if __name__ == "__main__":
    unittest.main()
