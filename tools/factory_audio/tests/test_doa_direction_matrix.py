from pathlib import Path
import importlib.util
import json
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "doa_matrix", ROOT / "tools/factory_audio/audit-doa-direction-matrix.py"
)
audit_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit_module)


class DoaDirectionMatrixAuditTest(unittest.TestCase):
    def fixture(self, root, observed=(35, 125, 215, 305), concentrated=True,
                claim_boundary="transport_reported_doa_and_runtime_output_shape",
                evaluation_mode=None):
        captures = []
        for label, expected, angle in zip(
                ("front", "right", "back", "left"),
                (0, 90, 180, 270), observed):
            histogram = [0] * 36
            if concentrated:
                histogram[int(angle // 10) % 36] = 90
            else:
                for index in range(36):
                    histogram[index] = 2 if index < 18 else 3
            mean, concentration = audit_module.histogram_stats(histogram)
            report = root / (label + ".json")
            report.write_text(json.dumps({
                "status": "pass",
                "device": "r1-sample01",
                "claim_boundary": claim_boundary,
                "frames": 100,
                "doa_valid_frames": sum(histogram),
                "doa_valid_fraction": sum(histogram) / 100,
                "doa_histogram_10_degrees": histogram,
                "doa_circular_stats": {
                    "mean_degrees": mean,
                    "resultant_length": concentration,
                },
            }), encoding="utf-8")
            captures.append({
                "label": label,
                "expected_degrees": expected,
                "audit_report": report.name,
            })
        manifest = root / "manifest.json"
        value = {"device": "r1-sample01", "captures": captures}
        if evaluation_mode is not None:
            value["evaluation_mode"] = evaluation_mode
        manifest.write_text(json.dumps(value), encoding="utf-8")
        return manifest

    def test_accepts_cardinal_pattern_with_unknown_device_rotation(self):
        with tempfile.TemporaryDirectory() as directory:
            result = audit_module.audit(self.fixture(Path(directory)))
        self.assertEqual("pass", result["status"])
        self.assertEqual("relative_cardinal_acceptance", result["evaluation_mode"])
        self.assertAlmostEqual(35.0, result["fitted_device_zero_offset_degrees"])
        self.assertEqual("four_direction_reported_doa_relative_response_only",
                         result["claim_boundary"])
        self.assertIn("aec_cancellation_effect", result["unverified"])

    def test_fails_when_one_direction_does_not_move(self):
        with tempfile.TemporaryDirectory() as directory:
            result = audit_module.audit(self.fixture(
                Path(directory), observed=(35, 125, 215, 215)))
        self.assertEqual("fail", result["status"])
        self.assertTrue(any(not row["residual_ok"] for row in result["captures"]))

    def test_fails_when_direction_is_not_concentrated(self):
        with tempfile.TemporaryDirectory() as directory:
            result = audit_module.audit(self.fixture(Path(directory), concentrated=False))
        self.assertEqual("fail", result["status"])

    def test_accepts_micarray_integrity_capture_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            result = audit_module.audit(self.fixture(
                Path(directory),
                claim_boundary="micarray_symbol_binding_continuity_and_nonempty_payloads",
            ))
        self.assertEqual("pass", result["status"])

    def test_vendor_native_mode_preserves_angles_without_directional_acceptance(self):
        with tempfile.TemporaryDirectory() as directory:
            result = audit_module.audit(self.fixture(
                Path(directory),
                observed=(305, 225, 145, 225),
                evaluation_mode="vendor_native_diagnostic",
            ))
        self.assertEqual("pass", result["status"])
        self.assertEqual("skipped_by_user", result["directional_acceptance"])
        self.assertFalse(result["directional_relationship_evaluated"])
        self.assertEqual("vendor_native_degrees_unremapped",
                         result["reported_angle_semantics"])
        self.assertNotIn("expected_degrees", result["captures"][0])
        self.assertNotIn("residual_degrees", result["captures"][0])
        self.assertIn("doa_directional_accuracy", result["unverified"])

    def test_vendor_native_mode_still_fails_missing_doa_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.fixture(root, evaluation_mode="vendor_native_diagnostic")
            report = root / "front.json"
            value = json.loads(report.read_text())
            value["frames"] = 200
            value["doa_valid_fraction"] = value["doa_valid_frames"] / 200
            report.write_text(json.dumps(value))
            result = audit_module.audit(manifest)
        self.assertEqual("fail", result["status"])
        self.assertFalse(result["captures"][0]["valid_fraction_ok"])

    def test_rejects_unknown_evaluation_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = self.fixture(Path(directory), evaluation_mode="factory_pass")
            with self.assertRaisesRegex(RuntimeError, "evaluation_mode_invalid"):
                audit_module.audit(manifest)

    def test_rejects_wrong_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.fixture(root)
            value = json.loads(manifest.read_text())
            value["captures"][0]["label"] = "north"
            manifest.write_text(json.dumps(value))
            with self.assertRaisesRegex(RuntimeError, "direction_labels"):
                audit_module.audit(manifest)


if __name__ == "__main__":
    unittest.main()
