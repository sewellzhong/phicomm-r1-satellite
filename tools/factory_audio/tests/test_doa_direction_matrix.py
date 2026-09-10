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
    def fixture(self, root, observed=(35, 125, 215, 305), concentrated=True):
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
                "claim_boundary": "transport_reported_doa_and_runtime_output_shape",
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
        manifest.write_text(json.dumps({
            "device": "r1-sample01", "captures": captures,
        }), encoding="utf-8")
        return manifest

    def test_accepts_cardinal_pattern_with_unknown_device_rotation(self):
        with tempfile.TemporaryDirectory() as directory:
            result = audit_module.audit(self.fixture(Path(directory)))
        self.assertEqual("pass", result["status"])
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
