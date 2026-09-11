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
    "boot_policy_update", ROOT / "tools/factory_audio/update-experimental-boot-policy.py"
)
update = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(update)
boot = update.boot


class BootPolicyUpdateTest(unittest.TestCase):
    def entry(self, name, data, inode, mode=0o644):
        return boot.Entry(name, [inode, stat.S_IFREG | mode, 0, 0, 1, 0, len(data),
            0, 0, 0, 0, len(name.encode()) + 1, 0], data)

    def fixture(self, root):
        device = {"id": "r1-sample01", "hardware": "rk30board",
                  "fingerprint": "test/3448"}
        authorization = {"mode": "explicit_device_limited_risk_acceptance",
                         "gate_status": "pending", "risk_acceptance_sha256": "a" * 64}
        old_policy = b"enforcing-policy"
        entries = [
            self.entry(update.POLICY_ENTRY, old_policy, 1),
            self.entry("file_contexts", b"contexts", 2),
            self.entry("init.r1_factory_audio.rc",
                       b"service r1 agent --allow-vendor-debug-files\n", 3),
            self.entry("sbin/r1-factory-audio-agent", b"agent", 4, 0o750),
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
                   "allow_vendor_debug_files": True,
                   "agent_sha256": boot.digest_bytes(b"agent")}
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
        (root / "reference.json").write_text(json.dumps({"device": device}))
        candidate = root / "candidate-policy"
        candidate.write_bytes(old_policy + b"-vfat-diagnostic")
        base_rules = [
            {"index": index, "source": "base", "target": "base", "class": "file",
             "permissions": "read"}
            for index in range(1, update.BASE_RULE_COUNT + 1)
        ]
        diagnostic_rules = [
            {"index": index, "source": source, "target": target, "class": cls,
             "permissions": permissions}
            for index, (source, target, cls, permissions)
            in enumerate(update.EXPECTED_DIAGNOSTIC_RULES, update.BASE_RULE_COUNT + 1)
        ]
        policy_manifest = {
            "schema_version": 1,
            "status": "pass_for_boot_staging_only",
            "device": device,
            "original_policy_sha256": boot.digest_bytes(old_policy),
            "patched_policy_sha256": update.digest(candidate),
            "selinux_mode": "enforcing",
            "permissive_domains": [],
            "patcher": {"sha256": update.PATCHER_SHA256,
                        "source_commit": update.PATCHER_SOURCE_COMMIT},
            "rules": base_rules + diagnostic_rules,
            "diagnostic_profile": {
                "name": update.PROFILE_NAME,
                "temporary": True,
                "selinux_target_type": "vfat",
                "filename_transition_confinement": False,
                "risk_scope": "r1_factory_audio_write_applies_to_visible_vfat_type_objects",
                "restore_production_boot_after_probe": True,
                "risk_acknowledgement": update.RISK_ACK,
            },
        }
        (root / "policy-manifest.json").write_text(json.dumps(policy_manifest))
        args = type("Args", (), {
            "current_boot_a": root / "current-a.img",
            "current_boot_b": root / "current-b.img",
            "current_boot_manifest": root / "manifest.json",
            "current_overlay_manifest": root / "overlay.json",
            "candidate_policy": candidate,
            "policy_manifest": root / "policy-manifest.json",
            "candidate_agent": None,
            "expected_agent_sha256": None,
            "candidate_overlay_manifest": None,
            "output_dir": root / "output",
        })
        return args, entries, policy_manifest

    def run_build(self, root, args):
        previous_reference = update.REFERENCE
        update.REFERENCE = root / "reference.json"
        try:
            return update.build(args)
        finally:
            update.REFERENCE = previous_reference

    def test_update_changes_only_enforcing_policy(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory)
            args, original_entries, _ = self.fixture(root)
            result = self.run_build(root, args)
            self.assertEqual(
                ["ramdisk_enforcing_sepolicy_temporary_vfat_diagnostic"],
                result["declared_changes"])
            self.assertTrue(result["restore_production_boot_after_probe"])
            candidate = (root / "output/boot-policy-update.img").read_bytes()
            _, _, ramdisk, _ = boot.boot_parts(candidate)
            parsed = {entry.name: entry.data
                      for entry in boot.parse_cpio(gzip.decompress(ramdisk))}
            self.assertEqual(Path(args.candidate_policy).read_bytes(),
                             parsed[update.POLICY_ENTRY])
            for entry in original_entries:
                if entry.name != update.POLICY_ENTRY:
                    self.assertEqual(entry.data, parsed[entry.name])

    def test_update_refuses_missing_type_wide_risk_acknowledgement(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory)
            args, _, manifest = self.fixture(root)
            manifest["diagnostic_profile"]["risk_acknowledgement"] = None
            Path(args.policy_manifest).write_text(json.dumps(manifest))
            with self.assertRaisesRegex(update.UpdateError,
                                        "diagnostic_policy_risk_not_acknowledged"):
                self.run_build(root, args)

    def test_update_refuses_non_debug_current_boot(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory)
            args, _, _ = self.fixture(root)
            overlay = json.loads(Path(args.current_overlay_manifest).read_text())
            overlay["allow_vendor_debug_files"] = False
            Path(args.current_overlay_manifest).write_text(json.dumps(overlay))
            current_manifest = json.loads(Path(args.current_boot_manifest).read_text())
            current_manifest["overlay_manifest_sha256"] = update.digest(
                args.current_overlay_manifest)
            Path(args.current_boot_manifest).write_text(json.dumps(current_manifest))
            with self.assertRaisesRegex(update.UpdateError,
                                        "vendor_debug_files_not_enabled_in_current_boot"):
                self.run_build(root, args)

    def test_update_refuses_policy_manifest_for_different_embedded_policy(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory)
            args, _, manifest = self.fixture(root)
            manifest["original_policy_sha256"] = "0" * 64
            Path(args.policy_manifest).write_text(json.dumps(manifest))
            with self.assertRaisesRegex(update.UpdateError,
                                        "embedded_policy_hash_not_policy_manifest"):
                self.run_build(root, args)

    def test_update_changes_only_agent_and_temporary_policy(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory)
            args, original_entries, _ = self.fixture(root)
            agent = root / "candidate-agent"
            agent.write_bytes(b"new-arm-agent")
            overlay = json.loads(Path(args.current_overlay_manifest).read_text())
            overlay["agent_sha256"] = update.digest(agent)
            candidate_overlay = root / "candidate-overlay.json"
            candidate_overlay.write_text(json.dumps(overlay))
            args.candidate_agent = agent
            args.expected_agent_sha256 = update.digest(agent)
            args.candidate_overlay_manifest = candidate_overlay
            with mock.patch.object(update, "assert_agent_elf32_arm"):
                result = self.run_build(root, args)
            self.assertEqual([
                "ramdisk_agent",
                "ramdisk_enforcing_sepolicy_temporary_vfat_diagnostic",
            ], result["declared_changes"])
            candidate = (root / "output/boot-policy-update.img").read_bytes()
            _, _, ramdisk, _ = boot.boot_parts(candidate)
            parsed = {entry.name: entry.data
                      for entry in boot.parse_cpio(gzip.decompress(ramdisk))}
            self.assertEqual(agent.read_bytes(), parsed[update.AGENT_ENTRY])
            self.assertEqual(Path(args.candidate_policy).read_bytes(),
                             parsed[update.POLICY_ENTRY])
            for entry in original_entries:
                if entry.name not in (update.AGENT_ENTRY, update.POLICY_ENTRY):
                    self.assertEqual(entry.data, parsed[entry.name])


if __name__ == "__main__":
    unittest.main()
