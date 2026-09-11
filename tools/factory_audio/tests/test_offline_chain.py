import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "offline_chain", ROOT / "tools/factory_audio/audit-offline-chain.py"
)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class OfflineChainTest(unittest.TestCase):
    def fixture(self, root):
        root = Path(root)
        source = root / "source"
        source.mkdir()
        copy_bytes = {
            "copy-a": [b"A" * 512 + b"B" * 512, b"C" * 1024],
            "copy-b": [b"A" * 512 + b"B" * 512, b"C" * 1024],
        }
        chunks = []
        for index in range(2):
            copies = []
            for storage_id, values in copy_bytes.items():
                directory = source / storage_id
                directory.mkdir(exist_ok=True)
                path = directory / f"chunk-{index}.bin"
                path.write_bytes(values[index])
                copies.append({"file": f"{storage_id}/{path.name}", "storage_id": storage_id,
                               "size": 1024, "sha256": digest(path)})
            chunks.append({"index": index, "start_sector": index * 2, "sectors": 2,
                           "bytes": 1024, "copies": copies})
        inventory = {
            "schema_version": 1, "operation": "read_only_android_storage_inventory",
            "status": "pass_with_access_limits", "device_id": audit.DEVICE_ID,
            "identity": {"ro.build.fingerprint": audit.FINGERPRINT},
            "emmc": {"bytes": 2560, "logical_block_bytes": 512},
            "partitions": [{"name": "system", "read_only": True, "start_sector": 2,
                            "end_sector_exclusive": 4, "sectors": 2, "bytes": 1024}],
        }
        inventory_path = source / "inventory.json"
        inventory_path.write_text(json.dumps(inventory))
        manifest = {
            "schema_version": 1, "operation": "loader-image-copy", "status": "pass",
            "device_id": audit.DEVICE_ID,
            "address_space": {"image_bytes": 2048, "image_sectors": 4,
                              "physical_prefix_not_included_bytes": 512,
                              "physical_offset_sectors_inferred": 1},
            "android_inventory": {"sha256": digest(inventory_path)},
            "chunks": chunks,
        }
        manifest_path = source / "copy.json"
        manifest_path.write_text(json.dumps(manifest))
        verification = {
            "schema_version": 1, "operation": "verify-loader-image-copy", "status": "pass",
            "device_id": audit.DEVICE_ID, "bytes_checked_per_copy": 2048,
            "expected_bytes_per_copy": 2048, "chunks_checked": 2,
            "overall_sha256": {"copy-a": "unused", "copy-b": "unused"},
            "source": {"sha256": digest(manifest_path)},
        }
        verification_path = source / "verification.json"
        verification_path.write_text(json.dumps(verification))
        return manifest_path, verification_path, inventory_path

    def test_cross_chunk_system_extracts_two_matching_copies(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, verification, inventory = self.fixture(directory)
            output = Path(directory) / "output"
            result = audit.extract_system(manifest, verification, inventory, output)
            expected = b"B" * 512 + b"C" * 512
            self.assertEqual(expected, (output / "system-copy-a.img").read_bytes())
            self.assertEqual(expected, (output / "system-copy-b.img").read_bytes())
            self.assertEqual(hashlib.sha256(expected).hexdigest(), result["partition"]["sha256"])

    def test_tampered_overlapping_chunk_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, verification, inventory = self.fixture(directory)
            (manifest.parent / "copy-a/chunk-0.bin").write_bytes(b"X" * 1024)
            with self.assertRaisesRegex(audit.AuditError, "chunk_hash_mismatch"):
                audit.extract_system(manifest, verification, inventory, Path(directory) / "output")

    def test_existing_output_is_rejected_before_source_reads(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, verification, inventory = self.fixture(directory)
            output = Path(directory) / "output"
            output.mkdir()
            with self.assertRaisesRegex(audit.AuditError, "output_directory_exists"):
                audit.extract_system(manifest, verification, inventory, output)

    def test_path_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, verification, inventory = self.fixture(directory)
            data = json.loads(manifest.read_text())
            data["chunks"][0]["copies"][0]["file"] = "../outside.bin"
            manifest.write_text(json.dumps(data))
            verify = json.loads(verification.read_text())
            verify["source"]["sha256"] = digest(manifest)
            verification.write_text(json.dumps(verify))
            with self.assertRaisesRegex(audit.AuditError, "path_not_local"):
                audit.extract_system(manifest, verification, inventory, Path(directory) / "output")

    def test_wrong_fingerprint_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, verification, inventory = self.fixture(directory)
            data = json.loads(inventory.read_text())
            data["identity"]["ro.build.fingerprint"] = "wrong"
            inventory.write_text(json.dumps(data))
            with self.assertRaisesRegex(audit.AuditError, "fingerprint_mismatch"):
                audit.validate_inputs(manifest, verification, inventory)

    def test_inventory_must_match_copy_manifest_source(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, verification, inventory = self.fixture(directory)
            data = json.loads(inventory.read_text())
            data["access_limits"] = ["changed after image capture"]
            inventory.write_text(json.dumps(data))
            with self.assertRaisesRegex(audit.AuditError, "manifest_inventory_mismatch"):
                audit.validate_inputs(manifest, verification, inventory)

    def test_copy_mismatch_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, verification, inventory = self.fixture(directory)
            changed = manifest.parent / "copy-b/chunk-1.bin"
            changed.write_bytes(b"D" * 1024)
            data = json.loads(manifest.read_text())
            data["chunks"][1]["copies"][1]["sha256"] = digest(changed)
            manifest.write_text(json.dumps(data))
            verify = json.loads(verification.read_text())
            verify["source"]["sha256"] = digest(manifest)
            verification.write_text(json.dumps(verify))
            with self.assertRaisesRegex(audit.AuditError, "system_copies_mismatch"):
                audit.extract_system(manifest, verification, inventory, Path(directory) / "output")

    def test_symlinked_chunk_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, verification, inventory = self.fixture(directory)
            source = manifest.parent / "copy-a/chunk-0.bin"
            real = manifest.parent / "copy-a/real.bin"
            source.rename(real)
            source.symlink_to(real.name)
            data = json.loads(manifest.read_text())
            data["chunks"][0]["copies"][0]["sha256"] = digest(real)
            manifest.write_text(json.dumps(data))
            verify = json.loads(verification.read_text())
            verify["source"]["sha256"] = digest(manifest)
            verification.write_text(json.dumps(verify))
            with self.assertRaisesRegex(audit.AuditError, "symlink_rejected"):
                audit.extract_system(manifest, verification, inventory, Path(directory) / "output")

    def test_extraction_manifest_rehashes_both_private_images(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            content = b"system-image"
            copies = []
            for suffix in ("a", "b"):
                path = base / f"system-copy-{suffix}.img"
                path.write_bytes(content)
                copies.append({"file": path.name, "bytes": len(content),
                               "sha256": digest(path), "storage_id": f"copy-{suffix}"})
            manifest = base / "system-extraction.json"
            manifest.write_text(json.dumps({
                "schema_version": 1, "device_id": audit.DEVICE_ID,
                "status": "pass_for_offline_factory_audio_only",
                "partition": {"name": "system", "bytes": len(content),
                              "sha256": digest(base / "system-copy-a.img")},
                "copies": copies,
            }))
            _, _, paths = audit.validate_extraction_manifest(manifest)
            self.assertEqual(2, len(paths))
            (base / "system-copy-b.img").write_bytes(b"tampered")
            with self.assertRaisesRegex(audit.AuditError, "size_mismatch"):
                audit.validate_extraction_manifest(manifest)

    def test_material_allowlist_excludes_audio_recordings(self):
        self.assertIn("app/Unisound/Unisound.apk", audit.MATERIAL_PATHS)
        self.assertIn("vendor/firmware/ak7755_pram_data2.bin", audit.MATERIAL_PATHS)
        self.assertFalse(any(path.endswith((".wav", ".pcm")) for path in audit.MATERIAL_PATHS))

    def test_static_analysis_requires_ordered_semantic_anchors(self):
        with tempfile.TemporaryDirectory() as directory:
            analysis = Path(directory)
            evidence = analysis / "evidence.txt"
            evidence.write_text(
                "  0010: instruction first semantic call\n"
                "0014: instruction second semantic call\n",
                encoding="utf-8",
            )
            reference = {"static_analysis_contract": {"evidence.txt": [
                {"offset": "0x0010", "contains": "first semantic call"},
                {"offset": "0x0014", "contains": "second semantic call"},
            ]}}
            checked = audit.verify_static_analysis(reference, analysis)
            self.assertEqual(2, checked[0]["anchors_checked"])
            reference["static_analysis_contract"]["evidence.txt"][1]["contains"] = "wrong"
            with self.assertRaisesRegex(audit.AuditError, "fragment_mismatch"):
                audit.verify_static_analysis(reference, analysis)

    def test_static_analysis_rejects_missing_anchors(self):
        with tempfile.TemporaryDirectory() as directory:
            analysis = Path(directory)
            (analysis / "evidence.txt").write_text("0010: present\n", encoding="utf-8")
            missing = {"static_analysis_contract": {"evidence.txt": [
                {"offset": "0x0014", "contains": "missing"},
            ]}}
            with self.assertRaisesRegex(audit.AuditError, "anchor_missing"):
                audit.verify_static_analysis(missing, analysis)

    def test_public_reference_keeps_runtime_shape_pending(self):
        reference = json.loads(
            (ROOT / "docs/references/r1-3448-factory-audio-abi.json").read_text()
        )
        contract = reference["original_java_contract"]
        self.assertEqual(2, contract["open_audio_in_argument"])
        self.assertEqual(1200, contract["default_packet_samples"])
        self.assertEqual(2400, contract["default_four_mic_read_buffer_bytes"])
        self.assertEqual(1, contract["default_four_mic_debug_mode_argument"])
        self.assertTrue(contract["read_buffer_runtime_configurable"])
        self.assertEqual("pending", contract["runtime_output_channels"])
        debug_contract = reference["debug_artifact_contract"]
        self.assertEqual("/sdcard/unidata/", debug_contract["configured_directory"])
        self.assertEqual("0x1ec", debug_contract["debug_flag_struct_offset"])
        self.assertIn("not uni_4mic_pcm_read", debug_contract["payload_writer"])
        self.assertIn("zero frames", debug_contract["stock_real_wake_result"])


if __name__ == "__main__":
    unittest.main()
