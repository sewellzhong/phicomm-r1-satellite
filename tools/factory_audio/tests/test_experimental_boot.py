from pathlib import Path
import gzip
import importlib.util
import json
import stat
import struct
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "experimental_boot", ROOT / "tools/factory_audio/build-experimental-boot.py"
)
boot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(boot)


class ExperimentalBootTest(unittest.TestCase):
    def entry(self, name, data, inode):
        return boot.Entry(name, [inode, stat.S_IFREG | 0o644, 0, 0, 1, 0, len(data),
            0, 0, 0, 0, len(name.encode()) + 1, 0], data)

    def test_cpio_round_trip_preserves_symlink_and_regular_data(self):
        entries = [self.entry("init.rc", b"init", 1),
            boot.Entry("charger", [2, stat.S_IFLNK | 0o777, 0, 0, 1, 0, 4,
                0, 0, 0, 0, 8, 0], b"init")]
        parsed = boot.parse_cpio(boot.build_cpio(entries))
        self.assertEqual([(item.name, item.data, item.fields[1]) for item in entries],
                         [(item.name, item.data, item.fields[1]) for item in parsed])

    def test_boot_build_changes_only_ramdisk_and_records_fixed_partition(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory)
            original_policy = b"policy-v26"
            entries = [self.entry("sepolicy", original_policy, 1),
                self.entry("file_contexts", b"/system u:object_r:system_file:s0\n", 2),
                self.entry("init.rk30board.rc", b"import /init.rockchip.rc\n", 3)]
            ramdisk = gzip.compress(boot.build_cpio(entries), mtime=0)
            ramdisk += bytes(boot.aligned(len(ramdisk), 4) - len(ramdisk))
            kernel, second, page = b"kernel", b"second", 16384
            header = bytearray(page)
            header[:8] = b"ANDROID!"
            values = (len(kernel), 0x60408000, len(ramdisk), 0x62000000,
                      len(second), 0x60f00000, 0x60088000, page)
            struct.pack_into("<8I", header, 8, *values)
            header[576:596] = boot.rockchip_boot_id(header, kernel, ramdisk, second)
            image = bytes(header) + kernel + bytes(boot.aligned(len(kernel), page) - len(kernel))
            image += ramdisk + bytes(boot.aligned(len(ramdisk), page) - len(ramdisk))
            image += second + bytes(boot.aligned(len(second), page) - len(second))
            image += bytes(boot.PARTITION_BYTES - len(image))
            (root / "boot.img").write_bytes(image)
            device = {"id": "r1-sample01", "hardware": "rk30board", "fingerprint": "test/3448"}
            reference = {"device": device, "partitions": {"boot": {
                "bytes": len(image), "sha256": boot.digest(root / "boot.img")}}}
            (root / "reference.json").write_text(json.dumps(reference))
            baseline = {"status": "pass", "device": device,
                "reference_sha256": boot.digest(root / "reference.json")}
            (root / "baseline.json").write_text(json.dumps(baseline))
            overlay = root / "overlay"
            (overlay / "sbin").mkdir(parents=True)
            agent = overlay / "sbin/r1-factory-audio-agent"
            agent.write_bytes(b"agent")
            (overlay / "init.r1_factory_audio.rc").write_text("service r1 /sbin/r1-factory-audio-agent\n")
            (overlay / "sepolicy").mkdir()
            (overlay / "sepolicy/file_contexts").write_text("/sbin/r1 u:object_r:r1:s0\n")
            (overlay / "sepolicy/r1_factory_audio.te").write_text("type r1;\n")
            overlay_manifest = {"device": device, "agent_sha256": boot.digest(agent),
                "init_rc_sha256": boot.digest(overlay / "init.r1_factory_audio.rc"),
                "file_contexts_sha256": boot.digest(overlay / "sepolicy/file_contexts"),
                "policy_source_sha256": boot.digest(overlay / "sepolicy/r1_factory_audio.te"),
                "authorization": {"mode": "explicit_device_limited_risk_acceptance"},
                "output_channels": 2, "output_channel": 0}
            (overlay / "manifest.json").write_text(json.dumps(overlay_manifest))
            policy = root / "policy"
            policy.mkdir()
            (policy / "sepolicy").write_bytes(original_policy + b"-patched")
            policy_manifest = {"status": "pass_for_boot_staging_only", "device": device,
                "original_policy_sha256": boot.digest_bytes(original_policy),
                "patched_policy_sha256": boot.digest(policy / "sepolicy")}
            (policy / "manifest.json").write_text(json.dumps(policy_manifest))
            output = root / "output"
            args = type("Args", (), {"original_boot": root / "boot.img",
                "boot_baseline_report": root / "baseline.json", "overlay_dir": overlay,
                "policy_dir": policy, "output_dir": output})()
            old_reference = boot.REFERENCE
            try:
                boot.REFERENCE = root / "reference.json"
                result = boot.build(args)
            finally:
                boot.REFERENCE = old_reference
            self.assertEqual("pass_for_device_locked_boot_write", result["status"])
            self.assertEqual("rockchip_secure_ns_sha1", result["boot_id_scheme"])
            self.assertEqual(0, result["candidate_ramdisk_bytes"] % 4)
            self.assertEqual(98304, result["partition"]["loader_image_start_sector"])
            candidate = (output / "boot-experimental.img").read_bytes()
            _, candidate_kernel, candidate_ramdisk, candidate_second = boot.boot_parts(candidate)
            self.assertEqual(kernel, candidate_kernel)
            self.assertEqual(second, candidate_second)
            self.assertEqual(candidate[576:596], boot.rockchip_boot_id(
                candidate, candidate_kernel, candidate_ramdisk, candidate_second))
            names = {item.name for item in boot.parse_cpio(gzip.decompress(candidate_ramdisk))}
            self.assertIn("sbin/r1-factory-audio-agent", names)
            self.assertIn("init.r1_factory_audio.rc", names)


if __name__ == "__main__":
    unittest.main()
