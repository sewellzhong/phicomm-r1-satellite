import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "r1_boot_baseline", ROOT / "tools/recovery/r1-boot-baseline.py"
)
baseline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(baseline)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True) + "\n")


class BootBaselineTest(unittest.TestCase):
    def fixture(self, root):
        root = Path(root)
        evidence = root / "evidence"
        private = root / "private"
        evidence.mkdir()
        private.mkdir()
        source_paths = {}
        for name, value in (
                ("inventory", {"status": "pass"}),
                ("copy_manifest", {"status": "pass"}),
                ("copy_verification", {"status": "pass"})):
            path = evidence / (name + ".json")
            write_json(path, value)
            source_paths[name] = path

        page = 16384
        header_values = {
            "kernel_size": 4, "kernel_addr": 0x60408000,
            "ramdisk_addr": 0x62000000, "second_size": 4,
            "second_addr": 0x60F00000, "tags_addr": 0x60088000,
            "page_size": page,
        }
        partition_specs = {}
        for name, ramdisk_size, total in (("boot", 3, page), ("recovery", 5, page * 2)):
            data = bytearray(total)
            data[:8] = b"ANDROID!"
            struct.pack_into("<8I", data, 8, header_values["kernel_size"],
                             header_values["kernel_addr"], ramdisk_size,
                             header_values["ramdisk_addr"], header_values["second_size"],
                             header_values["second_addr"], header_values["tags_addr"], page)
            for suffix in ("a", "b"):
                (private / f"{name}-{suffix}.img").write_bytes(data)
            partition_specs[name] = {"bytes": total, "sha256": digest(private / f"{name}-a.img")}
        for suffix in ("a", "b"):
            (private / f"kernel-{suffix}.img").write_bytes(b"kernel")
        partition_specs["kernel"] = {"bytes": 6, "sha256": digest(private / "kernel-a.img")}
        (private / "boot-kernel.bin").write_bytes(b"kern")
        (private / "boot-second.bin").write_bytes(b"seco")
        (private / "rk-kernel.dtb").write_bytes(b"dtb")

        manifest = {
            "schema_version": 1, "device_id": "r1-sample01",
            "status": "pass_for_offline_baseline_only",
            "source": {
                name: "../evidence/" + path.name for name, path in source_paths.items()
            } | {
                name + "_sha256": digest(path) for name, path in source_paths.items()
            },
            "partitions": [
                {"name": name, "bytes": spec["bytes"], "sha256": spec["sha256"],
                 "copy_a": f"{name}-a.img", "copy_b": f"{name}-b.img", "copies_match": True}
                for name, spec in partition_specs.items()
            ],
            "android_boot_images": {"dtb_offset": 2},
        }
        manifest_path = private / "manifest.json"
        write_json(manifest_path, manifest)
        reference = {
            "schema_version": 1, "status": "approved_original_input_only",
            "device": {"id": "r1-sample01", "hardware": "synthetic",
                       "fingerprint": "synthetic/3448"},
            "baseline_manifest_sha256": digest(manifest_path),
            "source_evidence": {
                name + "_sha256": digest(path) for name, path in source_paths.items()
            },
            "partitions": partition_specs,
            "android_boot": {
                "magic": "ANDROID!", **header_values,
                "boot_ramdisk_size": 3, "recovery_ramdisk_size": 5,
                "kernel_sha256": digest(private / "boot-kernel.bin"),
                "second_sha256": digest(private / "boot-second.bin"),
                "dtb_offset_in_second": 2, "dtb_size": 3,
                "dtb_sha256": digest(private / "rk-kernel.dtb"),
            },
        }
        reference_path = root / "reference.json"
        write_json(reference_path, reference)
        return reference_path, manifest_path, private

    def test_verified_private_baseline_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            reference, manifest, _ = self.fixture(directory)
            result = baseline.verify(reference, manifest)
            self.assertEqual("pass", result["status"])
            self.assertEqual("r1-sample01", result["device"]["id"])

    def test_partition_tamper_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            reference, manifest, private = self.fixture(directory)
            (private / "boot-b.img").write_bytes(b"tampered")
            with self.assertRaisesRegex(baseline.BaselineError, "boot_file_size_mismatch"):
                baseline.verify(reference, manifest)

    def test_manifest_tamper_is_rejected_before_files(self):
        with tempfile.TemporaryDirectory() as directory:
            reference, manifest, _ = self.fixture(directory)
            value = json.loads(manifest.read_text())
            value["device_id"] = "another-device"
            write_json(manifest, value)
            with self.assertRaisesRegex(baseline.BaselineError, "manifest_device_mismatch"):
                baseline.verify(reference, manifest)


if __name__ == "__main__":
    unittest.main()
