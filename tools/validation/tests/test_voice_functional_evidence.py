import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("voice_evidence", ROOT / "validate-voice-functional-evidence.py")
validation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validation)


def evidence(**overrides):
    value = {
        "schema": 1, "device_id": "r1-sample01", "apk_sha256": "a" * 64,
        "mode": "natural_functional",
        "cases": [
            {"case_id": "alexa_wake", "status": "passed"},
            {"case_id": "chinese_stt_intent_tts", "status": "passed"},
            {"case_id": "streaming_answer", "status": "passed"},
        ],
    }
    value.update(overrides)
    return value


class VoiceEvidenceTests(unittest.TestCase):
    def test_accepts_redacted_function_results(self):
        result = validation.validate_evidence(evidence())
        self.assertEqual(3, result["case_count"])
        self.assertEqual(3, result["passed"])

    def test_rejects_raw_transcript(self):
        value = evidence()
        value["cases"][0]["transcript"] = "Alexa"
        with self.assertRaisesRegex(ValueError, "conversation_content_forbidden"):
            validation.validate_evidence(value)

    def test_rejects_duplicate_or_unknown_cases(self):
        value = evidence()
        value["cases"].append({"case_id": "alexa_wake", "status": "passed"})
        with self.assertRaisesRegex(ValueError, "case_id_not_unique"):
            validation.validate_evidence(value)
        value = evidence(cases=[{"case_id": "unknown", "status": "passed"}])
        with self.assertRaisesRegex(ValueError, "case_id_invalid"):
            validation.validate_evidence(value)

    def test_accepts_controlled_diagnostic_without_making_it_functional(self):
        value = evidence(mode="controlled_diagnostic", cases=[
            {"case_id": "alexa_wake", "status": "skipped", "failure_code": "operator_skipped"}
        ])
        self.assertEqual("controlled_diagnostic", validation.validate_evidence(value)["mode"])


if __name__ == "__main__":
    unittest.main()
