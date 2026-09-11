from pathlib import Path
import gzip
import importlib.util
import json
import stat
import struct
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "boot_agent_update", ROOT / "tools/factory_audio/update-experimental-boot-agent.py"
)
update = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(update)
boot = update.boot


class BootAgentUpdateTest(unittest.TestCase):
    def entry(self, name, data, inode, mode=0o644):
        return boot.Entry(name, [inode, stat.S_IFREG | mode, 0, 0, 1, 0, len(data),
            0, 0, 0, 0, len(name.encode()) + 1, 0], data)

    def fixture(self, root):
        device = {"id": "r1-sample01", "hardware": "rk30board",
                  "fingerprint": "test/3448"}
        authorization = {"mode": "explicit_device_limited_risk_acceptance",
                         "gate_status": "pending", "risk_acceptance_sha256": "a" * 64}
        old_agent = b"old-arm-agent"
        current_init = b"service r1 agent --vendor-output-channel 0\n"
        entries = [
            self.entry("sepolicy", b"enforcing-policy", 1),
            self.entry("file_contexts", b"contexts", 2),
            self.entry("init.rk30board.rc", b"import /init.r1_factory_audio.rc\n", 3),
            self.entry("init.r1_factory_audio.rc", current_init, 4),
            self.entry(update.AGENT_ENTRY, old_agent, 5, 0o750),
        ]
        ramdisk = gzip.compress(boot.build_cpio(entries), compresslevel=9, mtime=0)
        ramdisk += b"\0" * (boot.aligned(len(ramdisk), 4) - len(ramdisk))
        kernel, second, page = b"kernel", b"second", 16384
        header = bytearray(page)
        header[:8] = b"ANDROID!"
        values = (len(kernel), 0x60408000, len(ramdisk), 0x62000000,
                  len(second), 0x60f00000, 0x60088000, page)
        struct.pack_into("<8I", header, 8, *values)
        header[576:596] = boot.rockchip_boot_id(header, kernel, ramdisk, second)
        image = bytes(header) + kernel + b"\0" * (boot.aligned(len(kernel), page) - len(kernel))
        image += ramdisk + b"\0" * (boot.aligned(len(ramdisk), page) - len(ramdisk))
        image += second + b"\0" * (boot.aligned(len(second), page) - len(second))
        image += b"\0" * (boot.PARTITION_BYTES - len(image))
        for name in ("current-a.img", "current-b.img"):
            (root / name).write_bytes(image)

        overlay = {"device": device, "authorization": authorization,
                   "agent_sha256": boot.digest_bytes(old_agent),
                   "init_rc_sha256": boot.digest_bytes(current_init),
                   "allow_vendor_debug_files": False,
                   "output_channels": 2, "output_channel": 0}
        (root / "overlay.json").write_text(json.dumps(overlay))
        manifest = {
            "status": "pass_for_device_locked_boot_write", "device": device,
            "partition": {"name": "boot", "bytes": boot.PARTITION_BYTES,
                          "loader_image_start_sector": 98304, "sectors": 24576},
            "boot_id_scheme": "rockchip_secure_ns_sha1",
            "candidate_boot_sha256": update.digest(root / "current-a.img"),
            "overlay_manifest_sha256": update.digest(root / "overlay.json"),
            "authorization": authorization,
        }
        (root / "manifest.json").write_text(json.dumps(manifest))
        reference = {"device": device}
        (root / "reference.json").write_text(json.dumps(reference))
        new_agent = root / "new-agent"
        new_agent.write_bytes(b"new-arm-agent-with-diagnostics")
        args = type("Args", (), {
            "current_boot_a": root / "current-a.img",
            "current_boot_b": root / "current-b.img",
            "current_boot_manifest": root / "manifest.json",
            "current_overlay_manifest": root / "overlay.json",
            "agent": new_agent,
            "expected_agent_sha256": update.digest(new_agent),
            "candidate_overlay_manifest": None,
            "candidate_init_rc": None,
            "output_dir": root / "outside-repository-output",
        })
        return args, entries, new_agent

    def test_update_changes_only_existing_agent(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory)
            args, original_entries, new_agent = self.fixture(root)
            previous_reference = update.REFERENCE
            update.REFERENCE = root / "reference.json"
            try:
                with mock.patch.object(update, "assert_agent_elf32_arm"):
                    result = update.build(args)
            finally:
                update.REFERENCE = previous_reference
            self.assertEqual("pass_for_device_locked_boot_write", result["status"])
            self.assertEqual(["ramdisk_agent"], result["declared_changes"])
            self.assertEqual(update.digest(new_agent), result["new_agent_sha256"])
            candidate = (Path(args.output_dir) / "boot-agent-update.img").read_bytes()
            _, kernel, ramdisk, second = boot.boot_parts(candidate)
            parsed = {entry.name: entry.data
                      for entry in boot.parse_cpio(gzip.decompress(ramdisk))}
            expected = {entry.name: entry.data for entry in original_entries}
            expected[update.AGENT_ENTRY] = new_agent.read_bytes()
            self.assertEqual(expected, parsed)
            self.assertEqual(b"kernel", kernel)
            self.assertEqual(b"second", second)

    def test_update_refuses_mismatched_current_copies(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory)
            args, _, _ = self.fixture(root)
            (root / "current-b.img").write_bytes(b"tampered")
            previous_reference = update.REFERENCE
            update.REFERENCE = root / "reference.json"
            try:
                with mock.patch.object(update, "assert_agent_elf32_arm"):
                    with self.assertRaisesRegex(update.UpdateError, "current_boot_copies_differ"):
                        update.build(args)
            finally:
                update.REFERENCE = previous_reference

    def test_update_refuses_same_file_as_two_current_copies(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory)
            args, _, _ = self.fixture(root)
            args.current_boot_b = args.current_boot_a
            with self.assertRaisesRegex(update.UpdateError,
                                        "current_boot_copies_not_independent"):
                update.build(args)

    def test_update_refuses_symlinked_current_copy(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory)
            args, _, _ = self.fixture(root)
            link = root / "current-link.img"
            link.symlink_to(root / "current-a.img")
            args.current_boot_a = link
            with self.assertRaisesRegex(update.UpdateError, "current_boot_a_must_not_be_symlink"):
                update.build(args)

    def test_update_refuses_wrong_expected_agent_hash(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory)
            args, _, _ = self.fixture(root)
            args.expected_agent_sha256 = "0" * 64
            previous_reference = update.REFERENCE
            update.REFERENCE = root / "reference.json"
            try:
                with mock.patch.object(update, "assert_agent_elf32_arm"):
                    with self.assertRaisesRegex(update.UpdateError, "new_agent_hash_mismatch"):
                        update.build(args)
            finally:
                update.REFERENCE = previous_reference

    def test_update_changes_agent_and_exact_vendor_debug_init_flag(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory)
            args, original_entries, new_agent = self.fixture(root)
            current_overlay = json.loads((root / "overlay.json").read_text())
            candidate_init = (original_entries[3].data.replace(
                b"--vendor-output-channel 0",
                b"--vendor-output-channel 0 --allow-vendor-debug-files"))
            candidate_overlay = dict(current_overlay)
            candidate_overlay.update({
                "agent_sha256": update.digest(new_agent),
                "init_rc_sha256": boot.digest_bytes(candidate_init),
                "allow_vendor_debug_files": True,
            })
            (root / "candidate-init.rc").write_bytes(candidate_init)
            (root / "candidate-overlay.json").write_text(json.dumps(candidate_overlay))
            args.candidate_init_rc = root / "candidate-init.rc"
            args.candidate_overlay_manifest = root / "candidate-overlay.json"
            previous_reference = update.REFERENCE
            update.REFERENCE = root / "reference.json"
            try:
                with mock.patch.object(update, "assert_agent_elf32_arm"):
                    result = update.build(args)
            finally:
                update.REFERENCE = previous_reference
            self.assertEqual(
                ["ramdisk_agent", "ramdisk_init_vendor_debug_flag"],
                result["declared_changes"])
            self.assertTrue(result["allow_vendor_debug_files"])
            candidate = (Path(args.output_dir) / "boot-agent-update.img").read_bytes()
            _, _, ramdisk, _ = boot.boot_parts(candidate)
            parsed = {entry.name: entry.data
                      for entry in boot.parse_cpio(gzip.decompress(ramdisk))}
            self.assertEqual(candidate_init, parsed[update.INIT_ENTRY])

    def test_update_refuses_unrelated_candidate_init_change(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory)
            args, original_entries, new_agent = self.fixture(root)
            candidate_init = original_entries[3].data + b"setprop unrelated 1\n"
            candidate_overlay = json.loads((root / "overlay.json").read_text())
            candidate_overlay.update({
                "agent_sha256": update.digest(new_agent),
                "init_rc_sha256": boot.digest_bytes(candidate_init),
                "allow_vendor_debug_files": True,
            })
            (root / "candidate-init.rc").write_bytes(candidate_init)
            (root / "candidate-overlay.json").write_text(json.dumps(candidate_overlay))
            args.candidate_init_rc = root / "candidate-init.rc"
            args.candidate_overlay_manifest = root / "candidate-overlay.json"
            previous_reference = update.REFERENCE
            update.REFERENCE = root / "reference.json"
            try:
                with mock.patch.object(update, "assert_agent_elf32_arm"):
                    with self.assertRaisesRegex(
                            update.UpdateError,
                            "candidate_init_change_not_exact_vendor_debug_flag"):
                        update.build(args)
            finally:
                update.REFERENCE = previous_reference

    def test_update_refuses_candidate_manifest_without_init(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory)
            args, _, _ = self.fixture(root)
            args.candidate_overlay_manifest = root / "overlay.json"
            with self.assertRaisesRegex(update.UpdateError, "candidate_init_rc_required"):
                update.build(args)

    def test_update_refuses_unrelated_candidate_overlay_change(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory)
            args, original_entries, new_agent = self.fixture(root)
            candidate_init = original_entries[3].data.replace(
                b"--vendor-output-channel 0",
                b"--vendor-output-channel 0 --allow-vendor-debug-files")
            candidate_overlay = json.loads((root / "overlay.json").read_text())
            candidate_overlay.update({
                "agent_sha256": update.digest(new_agent),
                "init_rc_sha256": boot.digest_bytes(candidate_init),
                "allow_vendor_debug_files": True,
                "output_channel": 1,
            })
            (root / "candidate-init.rc").write_bytes(candidate_init)
            (root / "candidate-overlay.json").write_text(json.dumps(candidate_overlay))
            args.candidate_init_rc = root / "candidate-init.rc"
            args.candidate_overlay_manifest = root / "candidate-overlay.json"
            previous_reference = update.REFERENCE
            update.REFERENCE = root / "reference.json"
            try:
                with mock.patch.object(update, "assert_agent_elf32_arm"):
                    with self.assertRaisesRegex(
                            update.UpdateError,
                            "candidate_overlay_contract_changed:output_channel"):
                        update.build(args)
            finally:
                update.REFERENCE = previous_reference


if __name__ == "__main__":
    unittest.main()
