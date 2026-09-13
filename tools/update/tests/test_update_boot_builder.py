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
SCRIPT = ROOT / "tools/update/build-r1-update-boot.py"
SPEC = importlib.util.spec_from_file_location("update_boot", SCRIPT)
update_boot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(update_boot)


class UpdateBootBuilderTest(unittest.TestCase):
    def entry(self, name, data, inode, mode=0o644):
        return update_boot.boot.Entry(
            name, [inode, stat.S_IFREG | mode, 0, 0, 1, 0, len(data),
                   0, 0, 0, 0, len(name.encode()) + 1, 0], data)

    def boot_image(self, policy):
        entries = [
            self.entry("sepolicy", policy, 1),
            self.entry("file_contexts", b"/sbin/r1-factory-audio-agent u:object_r:r1_factory_audio:s0\n", 2),
            self.entry("init.rk30board.rc", b"import /init.r1_factory_audio.rc\n", 3),
            self.entry("sbin/r1-factory-audio-agent", b"factory-agent", 4, 0o750),
            self.entry("init.r1_factory_audio.rc", b"service factory /sbin/r1-factory-audio-agent\n", 5),
        ]
        ramdisk = gzip.compress(update_boot.boot.build_cpio(entries), compresslevel=9, mtime=0)
        ramdisk += b"\0" * (update_boot.boot.aligned(len(ramdisk), 4) - len(ramdisk))
        kernel, second, page = b"kernel", b"second", 16384
        values = (len(kernel), 0x60408000, len(ramdisk), 0x62000000,
                  len(second), 0x60f00000, 0x60000100, page)
        header = bytearray(page)
        header[:8] = b"ANDROID!"
        struct.pack_into("<8I", header, 8, *values)
        header[576:596] = update_boot.boot.rockchip_boot_id(header, kernel, ramdisk, second)
        image = bytes(header) + kernel
        image += b"\0" * (update_boot.boot.aligned(len(kernel), page) - len(kernel))
        image += ramdisk
        image += b"\0" * (update_boot.boot.aligned(len(ramdisk), page) - len(ramdisk))
        image += second
        image += b"\0" * (update_boot.boot.aligned(len(second), page) - len(second))
        return image + b"\0" * (update_boot.boot.PARTITION_BYTES - len(image))

    def inputs(self, directory):
        base = Path(directory)
        original_policy = b"factory-policy"
        candidate_policy = base / "candidate-policy"
        candidate_policy.write_bytes(b"factory-plus-update-policy")
        policy_manifest = base / "policy-manifest.json"
        policy_manifest.write_text(json.dumps({
            "schema_version": 1,
            "status": "pass_for_update_supervisor_boot_staging_only",
            "device": {"id": "r1-sample01", "hardware": "rk30board",
                       "fingerprint": update_boot.FINGERPRINT},
            "selinux_mode": "enforcing", "permissive_domains": [],
            "current_factory_policy_sha256": hashlib.sha256(original_policy).hexdigest(),
            "patched_policy_sha256": hashlib.sha256(candidate_policy.read_bytes()).hexdigest(),
        }))
        boot_a, boot_b = base / "boot-a.img", base / "boot-b.img"
        image = self.boot_image(original_policy)
        boot_a.write_bytes(image)
        boot_b.write_bytes(image)
        supervisor, helper = base / "supervisor", base / "helper.jar"
        supervisor.write_bytes(b"ELF32 ARM supervisor")
        helper.write_bytes(b"dex helper")
        init_rc, contexts = base / "init.rc", base / "file_contexts"
        init_rc.write_bytes(b"service r1_update_supervisor /sbin/r1-update-supervisor\n")
        contexts.write_bytes(b"/sbin/r1-update-supervisor u:object_r:r1_update_supervisor:s0\n")
        return types.SimpleNamespace(
            current_boot_a=str(boot_a), current_boot_b=str(boot_b),
            expected_current_sha256=hashlib.sha256(image).hexdigest(),
            candidate_policy=str(candidate_policy), policy_manifest=str(policy_manifest),
            supervisor=str(supervisor),
            expected_supervisor_sha256=hashlib.sha256(supervisor.read_bytes()).hexdigest(),
            helper=str(helper),
            expected_helper_sha256=hashlib.sha256(helper.read_bytes()).hexdigest(),
            init_rc=str(init_rc), file_contexts=str(contexts),
            output_dir=str(base / "output"))

    def test_build_preserves_existing_payloads_and_adds_exact_update_overlay(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = self.inputs(temporary)
            with mock.patch.object(update_boot, "assert_elf32_arm"):
                result = update_boot.build(args)
            self.assertEqual("pass_for_device_locked_boot_write", result["status"])
            candidate = Path(args.output_dir, "boot-r1-update-supervisor.img").read_bytes()
            _, _, ramdisk, _ = update_boot.boot.boot_parts(candidate)
            entries = {item.name: item for item in
                       update_boot.boot.parse_cpio(gzip.decompress(ramdisk))}
            self.assertEqual(b"factory-agent", entries["sbin/r1-factory-audio-agent"].data)
            self.assertEqual(b"factory-plus-update-policy", entries["sepolicy"].data)
            self.assertIn("sbin/r1-update-supervisor", entries)
            self.assertIn("sbin/r1-update-helper.jar", entries)
            self.assertIn(b"import /init.r1_update_supervisor.rc",
                          entries["init.rk30board.rc"].data)

    def test_refuses_same_boot_file_twice(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = self.inputs(temporary)
            args.current_boot_b = args.current_boot_a
            with mock.patch.object(update_boot, "assert_elf32_arm"):
                with self.assertRaisesRegex(update_boot.BuildError,
                                            "current_boot_copies_not_independent"):
                    update_boot.build(args)


if __name__ == "__main__":
    unittest.main()
