from pathlib import Path
import hashlib
import importlib.util
import tempfile
import unittest
import wave


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "validation_capture", ROOT / "tools/factory_audio/audit-validation-capture.py"
)
audit_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit_module)


class ValidationCaptureAuditTest(unittest.TestCase):
    def fixture(self, root, gaps=0, backend="unisound_uni4mic_3448"):
        wav_path = root / "capture.wav"
        frames = 3
        with wave.open(str(wav_path), "wb") as recording:
            recording.setparams((1, 2, 16000, frames * 320, "NONE", "not compressed"))
            recording.writeframes(bytes(frames * 640))
        wav_hash = hashlib.sha256(wav_path.read_bytes()).hexdigest()
        metadata = root / "capture.meta.txt"
        metadata.write_text("\n".join([
            "purpose=R1 factory audio bounded validation capture",
            "attestation=validation_only_not_production",
            "source=factory_proxy_unattested_validation",
            "format=PCM_S16LE_16000Hz_mono_20ms",
            "target_duration_seconds=1",
            "started_at_epoch_ms=1",
            "elapsed_ms=60",
            f"backend={backend}",
            "vendor_board_version=UNI_4MIC_HAL_ANDROID_V1.1",
            "raw_mic_channels_claimed=4",
            "aec_reference_channels_claimed=0",
            "array_processing_claimed=true",
            "aec_active_claimed=false",
            f"frames={frames}",
            f"pcm_bytes={frames * 640}",
            "first_sequence=1",
            "last_sequence=3",
            f"sequence_gaps={gaps}",
            "agent_dropped_frames=0",
            "doa_valid_frames=2",
            "doa_histogram_10_degrees=1,0,0,0,0,0,0,0,0,0,0,0,0,0,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0",
            f"wav_sha256={wav_hash}",
            "",
        ]), encoding="utf-8")
        return wav_path, metadata

    def test_accepts_contiguous_capture_without_promoting_audio_claims(self):
        with tempfile.TemporaryDirectory() as directory:
            wav_path, metadata = self.fixture(Path(directory))
            result = audit_module.audit(wav_path, metadata, "r1-sample01")
        self.assertEqual("pass", result["status"])
        self.assertEqual("transport_and_reported_doa_only", result["claim_boundary"])
        self.assertIn("aec_cancellation_effect", result["unverified"])
        self.assertFalse(result["claimed_aec_active"])

    def test_rejects_sequence_gap(self):
        with tempfile.TemporaryDirectory() as directory:
            wav_path, metadata = self.fixture(Path(directory), gaps=1)
            with self.assertRaisesRegex(RuntimeError, "sequence_gaps_present"):
                audit_module.audit(wav_path, metadata, "r1-sample01")

    def test_rejects_synthetic_backend(self):
        with tempfile.TemporaryDirectory() as directory:
            wav_path, metadata = self.fixture(Path(directory), backend="synthetic-fake")
            with self.assertRaisesRegex(RuntimeError, "backend_mismatch"):
                audit_module.audit(wav_path, metadata, "r1-sample01")


if __name__ == "__main__":
    unittest.main()
