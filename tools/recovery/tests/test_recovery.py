"""Offline safety tests for the host-only R0 recovery metadata tool."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location(
    "r1_recovery", Path(__file__).parents[1] / "r1-recovery.py"
)
recovery = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(recovery)


class RecoveryToolTest(unittest.TestCase):
    EVIDENCE_HASH = "1" * 64
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.a = self.root / "a"
        self.b = self.root / "b"
        self.a.mkdir()
        self.b.mkdir()
        self.storages = {"copy-a": self.a, "copy-b": self.b}
        for root in (self.a, self.b):
            (root / "full.img").write_bytes(b"abcdefgh")
            (root / "boot.img").write_bytes(b"abcd")
            (root / "data.img").write_bytes(b"efgh")
            (root / "audio-hal.bin").write_bytes(b"hal")

    def tearDown(self):
        self.temporary.cleanup()

    def layout(self):
        copies = lambda name, encrypted=False: [
            {"storage_id": "copy-a", "path": name, "encrypted_storage": encrypted},
            {"storage_id": "copy-b", "path": name, "encrypted_storage": encrypted},
        ]
        return {
            "schema_version": 1,
            "areas": [{
                "name": "user",
                "size": 8,
                "full_image": {
                    "name": "full-emmc",
                    "classification": "sensitive",
                    "copies": copies("full.img", True),
                },
                "regions": [
                    {"name": "boot", "offset": 0, "length": 4,
                     "classification": "non_sensitive", "copies": copies("boot.img")},
                    {"name": "data", "offset": 4, "length": 4,
                     "classification": "sensitive", "copies": copies("data.img", True)},
                ],
            }],
            "files": [{
                "name": "audio-hal",
                "length": 3,
                "classification": "non_sensitive",
                "source": {"tool": "adb-readonly", "version": "1.0"},
                "copies": copies("audio-hal.bin"),
            }],
        }

    def manifest(self, layout=None):
        return recovery.create_manifest(
            layout or self.layout(),
            {"id": "r1-sample01", "hardware": "rk3229", "fingerprint": "firmware/3448"},
            {"tool": "synthetic-reader", "version": "1"},
            self.storages,
        )

    @staticmethod
    def encoded(value):
        return (json.dumps(value, sort_keys=True) + "\n").encode()

    def test_complete_layout_and_two_copies_create_manifest(self):
        manifest = self.manifest()
        self.assertEqual(4, len(manifest["artifacts"]))
        self.assertEqual("r1-sample01", manifest["device"]["id"])
        self.assertEqual("adb-readonly", manifest["artifacts"][-1]["source"]["tool"])
        self.assertNotIn(str(self.root), json.dumps(manifest))

    def test_cli_has_no_device_write_or_transport_command(self):
        commands = set(recovery.parser()._subparsers._group_actions[0].choices)
        self.assertEqual({"create-manifest", "verify-copies", "gate-report"}, commands)

    def test_json_evidence_is_not_overwritten(self):
        output = self.root / "evidence.json"
        recovery.write_json(output, {"first": True})
        with self.assertRaises(FileExistsError):
            recovery.write_json(output, {"second": True})
        self.assertEqual({"first": True}, recovery.load_json(output))

    def test_region_gap_is_rejected(self):
        layout = self.layout()
        layout["areas"][0]["regions"][1]["offset"] = 5
        with self.assertRaisesRegex(recovery.ValidationError, "region_gap"):
            self.manifest(layout)

    def test_region_overlap_is_rejected(self):
        layout = self.layout()
        layout["areas"][0]["regions"][1]["offset"] = 3
        with self.assertRaisesRegex(recovery.ValidationError, "region_overlap"):
            self.manifest(layout)

    def test_truncated_copy_is_rejected(self):
        (self.b / "boot.img").write_bytes(b"abc")
        with self.assertRaisesRegex(recovery.ValidationError, "copy_size_mismatch"):
            self.manifest()

    def test_hash_mismatch_is_rejected(self):
        (self.b / "boot.img").write_bytes(b"wxyz")
        with self.assertRaisesRegex(recovery.ValidationError, "copy_hash_mismatch"):
            self.manifest()

    def test_sensitive_copy_requires_encrypted_storage_attestation(self):
        layout = self.layout()
        layout["areas"][0]["regions"][1]["copies"][0]["encrypted_storage"] = False
        with self.assertRaisesRegex(recovery.ValidationError, "requires_encrypted_storage"):
            self.manifest(layout)

    def test_full_image_covering_sensitive_region_must_be_sensitive(self):
        layout = self.layout()
        layout["areas"][0]["full_image"]["classification"] = "non_sensitive"
        with self.assertRaisesRegex(recovery.ValidationError, "full_image_must_be_sensitive"):
            self.manifest(layout)

    def test_same_file_alias_is_rejected(self):
        layout = self.layout()
        (self.b / "boot.img").unlink()
        (self.b / "boot.img").hardlink_to(self.a / "boot.img")
        with self.assertRaisesRegex(recovery.ValidationError, "same_file"):
            self.manifest(layout)

    def test_absolute_manifest_path_is_rejected(self):
        manifest = self.manifest()
        manifest["artifacts"][0]["copies"][0]["path"] = "/private/full.img"
        with self.assertRaisesRegex(recovery.ValidationError, "safe_relative_path"):
            recovery.validate_manifest(manifest)

    def test_tampered_manifest_region_coverage_is_rejected(self):
        manifest = self.manifest()
        region = next(item for item in manifest["artifacts"] if item["name"] == "data")
        region["offset"] = 5
        with self.assertRaisesRegex(recovery.ValidationError, "manifest_region_gap"):
            recovery.validate_manifest(manifest)

    def test_verification_detects_post_manifest_change(self):
        manifest = self.manifest()
        manifest_bytes = self.encoded(manifest)
        (self.b / "boot.img").write_bytes(b"wxyz")
        result = recovery.verify_copies(manifest, self.storages, manifest_bytes)
        self.assertEqual("fail", result["status"])

    def test_gate_stays_pending_until_real_recovery_checks_pass(self):
        manifest = self.manifest()
        manifest_bytes = self.encoded(manifest)
        verification = recovery.verify_copies(manifest, self.storages, manifest_bytes)
        state = {"device": manifest["device"]}
        report = recovery.gate_report(manifest, manifest_bytes, verification, state)
        self.assertEqual("pending", report["status"])
        self.assertIn("controlled_full_restore", report["pending"])

    def test_gate_pass_requires_identity_restore_and_all_checks(self):
        manifest = self.manifest()
        manifest_bytes = self.encoded(manifest)
        verification = recovery.verify_copies(manifest, self.storages, manifest_bytes)
        state = {
            "device": manifest["device"],
            "low_level_entry": self.passed("low-level.json"),
            "controlled_full_restore": self.passed("restore.json"),
            "post_restore_checks": {
                name: self.passed(f"post-restore/{name}.json") for name in recovery.RECOVERY_CHECKS
            },
        }
        report = recovery.gate_report(manifest, manifest_bytes, verification, state)
        self.assertEqual("pass", report["status"])

    def passed(self, evidence):
        return {"status": "pass", "evidence": evidence, "evidence_sha256": self.EVIDENCE_HASH}

    def test_gate_rejects_pass_without_evidence(self):
        manifest = self.manifest()
        manifest_bytes = self.encoded(manifest)
        verification = recovery.verify_copies(manifest, self.storages, manifest_bytes)
        state = {
            "device": manifest["device"],
            "low_level_entry": {"status": "pass"},
        }
        report = recovery.gate_report(manifest, manifest_bytes, verification, state)
        self.assertEqual("fail", report["status"])
        self.assertIn("evidence_missing_or_invalid:low_level_entry", report["failures"])

    def test_device_identity_mismatch_fails_gate(self):
        manifest = self.manifest()
        manifest_bytes = self.encoded(manifest)
        verification = recovery.verify_copies(manifest, self.storages, manifest_bytes)
        state = {"device": {**manifest["device"], "id": "another-device"}}
        report = recovery.gate_report(manifest, manifest_bytes, verification, state)
        self.assertEqual("fail", report["status"])
        self.assertIn("device_id_mismatch", report["failures"])

    def test_cli_create_verify_and_pending_gate(self):
        layout_path = self.root / "layout.json"
        manifest_path = self.root / "manifest.json"
        verification_path = self.root / "verification.json"
        state_path = self.root / "state.json"
        report_path = self.root / "report.json"
        recovery.write_json(layout_path, self.layout())
        storage_args = ["--storage", f"copy-a={self.a}", "--storage", f"copy-b={self.b}"]
        self.assertEqual(0, recovery.main([
            "create-manifest", "--layout", str(layout_path),
            "--device-id", "r1-sample01", "--hardware", "rk3229",
            "--fingerprint", "firmware/3448", "--tool", "synthetic-reader",
            "--tool-version", "1", *storage_args, "--output", str(manifest_path),
        ]))
        self.assertEqual(0, recovery.main([
            "verify-copies", "--manifest", str(manifest_path), *storage_args,
            "--output", str(verification_path),
        ]))
        manifest = recovery.load_json(manifest_path)
        recovery.write_json(state_path, {"device": manifest["device"]})
        self.assertEqual(1, recovery.main([
            "gate-report", "--manifest", str(manifest_path),
            "--verification", str(verification_path), "--recovery-state", str(state_path),
            "--output", str(report_path),
        ]))
        self.assertEqual("pending", recovery.load_json(report_path)["status"])


if __name__ == "__main__":
    unittest.main()
