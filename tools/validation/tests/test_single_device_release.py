import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("single_release", ROOT / "validate-single-device-release.py")
validation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validation)


def release(**overrides):
    value = {
        "schema": 1, "device_id": "r1-sample01", "apk_sha256": "a" * 64,
        "gates": {gate: "passed" for gate in validation.REQUIRED_GATES},
        "evidence": ["test-results/2026-09-14-r1-sample01/release.json"],
    }
    value.update(overrides)
    return value


class SingleDeviceReleaseTests(unittest.TestCase):
    def test_ready_release_unlocks_multi_device_phase(self):
        result = validation.validate_release(release())
        self.assertEqual("ready_for_multi_device_onboarding", result["release_status"])

    def test_missing_stability_blocks_onboarding(self):
        gates = {gate: "passed" for gate in validation.REQUIRED_GATES}
        gates["stability_72h"] = "pending"
        with self.assertRaisesRegex(ValueError, "gate_not_passed:stability_72h"):
            validation.validate_release(release(gates=gates))

    def test_missing_network_recovery_blocks_onboarding(self):
        gates = {gate: "passed" for gate in validation.REQUIRED_GATES}
        gates["network_recovery"] = "failed"
        with self.assertRaisesRegex(ValueError, "gate_not_passed:network_recovery"):
            validation.validate_release(release(gates=gates))

    def test_release_rejects_secret_and_external_evidence(self):
        value = release()
        value["ha_token"] = "redacted"
        with self.assertRaisesRegex(ValueError, "secret_field_forbidden"):
            validation.validate_release(value)
        value = release(evidence=["/tmp/release.json"])
        with self.assertRaisesRegex(ValueError, "evidence_must_be_under_test_results"):
            validation.validate_release(value)


if __name__ == "__main__":
    unittest.main()
