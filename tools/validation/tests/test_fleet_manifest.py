import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("fleet_manifest", ROOT / "validate-fleet-manifest.py")
validation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validation)


HASH = "a" * 64


def device(index, **overrides):
    value = {
        "device_id": f"r1-sample{index:02d}",
        "serial": f"serial-{index}",
        "firmware_fingerprint": f"3448-{index}",
        "apk_sha256": HASH,
        "noise_identity_digest": "b" * 64,
        "ha_device_id": f"ha-device-{index}",
        "baseline_status": "pending",
        "evidence": [f"test-results/2026-09-14-r1-sample{index:02d}/baseline.json"],
    }
    value.update(overrides)
    return value


def manifest(devices=None):
    return {"schema": 1, "fleet_id": "r1-production-01",
            "devices": devices or [device(i) for i in range(1, 4)]}


class FleetManifestTests(unittest.TestCase):
    def test_accepts_three_independent_devices(self):
        result = validation.validate_manifest(manifest())
        self.assertEqual(3, result["device_count"])

    def test_rejects_single_device_rollout(self):
        with self.assertRaisesRegex(ValueError, "device_count_must_be_3_to_8"):
            validation.validate_manifest(manifest([device(1)]))

    def test_rejects_duplicate_identity(self):
        devices = [device(1), device(2, serial="serial-1"), device(3)]
        with self.assertRaisesRegex(ValueError, "serial_not_unique"):
            validation.validate_manifest(manifest(devices))

    def test_rejects_credentials_even_when_nested(self):
        devices = [device(1), device(2), device(3)]
        devices[0]["registration"] = {"noise_psk": "must-not-be-here"}
        with self.assertRaisesRegex(ValueError, "secret_field_forbidden"):
            validation.validate_manifest(manifest(devices))

    def test_rejects_non_test_evidence_and_uppercase_hash(self):
        devices = [device(1), device(2), device(3)]
        devices[0]["apk_sha256"] = HASH.upper()
        with self.assertRaisesRegex(ValueError, "lowercase_sha256"):
            validation.validate_manifest(manifest(devices))
        devices[0]["apk_sha256"] = HASH
        devices[0]["evidence"] = ["docs/secret.json"]
        with self.assertRaisesRegex(ValueError, "evidence_must_be_under_test_results"):
            validation.validate_manifest(manifest(devices))


if __name__ == "__main__":
    unittest.main()
