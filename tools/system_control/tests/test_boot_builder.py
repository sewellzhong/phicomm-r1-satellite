import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import stat
import struct
import tempfile
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "tools/system_control/build-r1-system-control-boot.py"
SPEC = importlib.util.spec_from_file_location("system_control_boot", SCRIPT)
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


class BootBuilderTest(unittest.TestCase):
    def entry(self, name, data, inode, mode=0o644):
        return builder.boot.Entry(
            name, [inode, stat.S_IFREG | mode, 0, 0, 1, 0, len(data),
                   0, 0, 0, 0, len(name.encode()) + 1, 0], data)

    def image(self, policy):
        entries = [
            self.entry("sepolicy", policy, 1),
            self.entry("file_contexts", b"existing-context\n", 2),
            self.entry("init.rk30board.rc", b"existing-init\n", 3),
            self.entry("sbin/existing-agent", b"existing-agent", 4, 0o750),
        ]
        ramdisk = gzip.compress(builder.boot.build_cpio(entries), compresslevel=9, mtime=0)
        ramdisk += b"\0" * (builder.boot.aligned(len(ramdisk), 4) - len(ramdisk))
        kernel, second, page = b"kernel", b"second", 16384
        values = (len(kernel), 0x60408000, len(ramdisk), 0x62000000,
                  len(second), 0x60f00000, 0x60000100, page)
        header = bytearray(page)
        header[:8] = b"ANDROID!"
        struct.pack_into("<8I", header, 8, *values)
        header[576:596] = builder.boot.rockchip_boot_id(header, kernel, ramdisk, second)
        result = bytes(header) + kernel
        result += b"\0" * (builder.boot.aligned(len(kernel), page) - len(kernel))
        result += ramdisk
        result += b"\0" * (builder.boot.aligned(len(ramdisk), page) - len(ramdisk))
        result += second
        result += b"\0" * (builder.boot.aligned(len(second), page) - len(second))
        return result + b"\0" * (builder.PARTITION_BYTES - len(result))

    def inputs(self, root):
        root = Path(root)
        old_policy, new_policy = b"old-policy", b"new-policy"
        first, second = root / "boot-a.img", root / "boot-b.img"
        image = self.image(old_policy)
        first.write_bytes(image); second.write_bytes(image)
        policy = root / "policy"; policy.write_bytes(new_policy)
        manifest = root / "manifest.json"
        manifest.write_text(json.dumps({
            "status": "pass_for_system_control_boot_staging_only",
            "device": {"id": "r1-sample01"}, "selinux_mode": "enforcing",
            "permissive_domains": [],
            "current_policy_sha256": hashlib.sha256(old_policy).hexdigest(),
            "patched_policy_sha256": hashlib.sha256(new_policy).hexdigest(),
        }))
        agent = root / "agent"; agent.write_bytes(b"agent")
        init = root / "init.rc"; init.write_bytes(b"service system-control agent\n")
        contexts = root / "contexts"; contexts.write_bytes(b"system-control-context\n")
        return types.SimpleNamespace(
            current_boot_a=str(first), current_boot_b=str(second),
            expected_current_sha256=hashlib.sha256(image).hexdigest(),
            candidate_policy=str(policy), policy_manifest=str(manifest),
            agent=str(agent), init_rc=str(init), file_contexts=str(contexts),
            output_dir=str(root / "output"))

    def test_adds_only_declared_ramdisk_surface(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = self.inputs(temporary)
            completed = types.SimpleNamespace(stdout="ELF32 ARM")
            with mock.patch.object(builder.subprocess, "run", return_value=completed):
                result = builder.build(args)
            self.assertEqual("pass_for_device_locked_boot_write", result["status"])
            image = Path(args.output_dir, "boot-r1-system-control.img").read_bytes()
            _, _, ramdisk, _ = builder.boot.boot_parts(image)
            entries = {item.name: item.data for item in
                       builder.boot.parse_cpio(gzip.decompress(ramdisk))}
            self.assertEqual(b"existing-agent", entries["sbin/existing-agent"])
            self.assertEqual(b"new-policy", entries["sepolicy"])
            self.assertEqual(b"agent", entries["sbin/r1-system-control-agent"])
            self.assertIn(b"init.r1_system_control.rc", entries["init.rk30board.rc"])

    def test_refuses_same_boot_copy(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = self.inputs(temporary)
            args.current_boot_b = args.current_boot_a
            with self.assertRaisesRegex(builder.BuildError,
                                        "current_boot_copies_not_independent"):
                builder.build(args)


if __name__ == "__main__":
    unittest.main()
