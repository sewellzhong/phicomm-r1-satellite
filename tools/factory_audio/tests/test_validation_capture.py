from pathlib import Path
import hashlib
import importlib.util
import struct
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

    def test_audits_distinct_stereo_diagnostic_shape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wav_path, metadata = self.fixture(root)
            diagnostic = root / "capture-diagnostic-stereo.wav"
            mono = b"".join(struct.pack("<h", sample)
                            for sample in range(1, 3 * 320 + 1))
            with wave.open(str(wav_path), "wb") as recording:
                recording.setparams((1, 2, 16000, 3 * 320, "NONE", "not compressed"))
                recording.writeframes(mono)
            stereo = b"".join(struct.pack("<hh", sample, -sample)
                              for sample in range(1, 3 * 320 + 1))
            with wave.open(str(diagnostic), "wb") as recording:
                recording.setparams((2, 2, 16000, 3 * 320, "NONE", "not compressed"))
                recording.writeframes(stereo)
            lines = metadata.read_text(encoding="utf-8").splitlines()
            lines = ["wav_sha256=" + hashlib.sha256(wav_path.read_bytes()).hexdigest()
                     if line.startswith("wav_sha256=") else line for line in lines]
            lines.extend([
                "diagnostic_output_channels=2",
                f"diagnostic_pcm_bytes={len(stereo)}",
                "diagnostic_selected_output_channel=0",
                f"diagnostic_wav_name={diagnostic.name}",
                "diagnostic_wav_sha256=" + hashlib.sha256(diagnostic.read_bytes()).hexdigest(),
            ])
            metadata.write_text("\n".join(lines) + "\n", encoding="utf-8")
            result = audit_module.audit(
                wav_path, metadata, "r1-sample01", diagnostic)
        shape = result["diagnostic_output"]
        self.assertEqual(2, shape["channels"])
        self.assertEqual(0, shape["selected_output_channel"])
        self.assertEqual([True, False], shape["mono_matches_diagnostic_channels"])
        self.assertTrue(shape["distinct_nonzero_two_channel_signal"])
        self.assertFalse(shape["channel_pair_identical"])
        self.assertNotIn("runtime_output_channel_shape", result["unverified"])

    def test_requires_diagnostic_sidecar_when_metadata_claims_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wav_path, metadata = self.fixture(root)
            with metadata.open("a", encoding="utf-8") as handle:
                handle.write("diagnostic_output_channels=2\n")
                handle.write("diagnostic_pcm_bytes=3840\n")
                handle.write("diagnostic_selected_output_channel=0\n")
            with self.assertRaisesRegex(RuntimeError, "diagnostic_wav_missing"):
                audit_module.audit(wav_path, metadata, "r1-sample01")

    def test_audits_controlled_playback_reference_without_promoting_aec(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wav_path, metadata = self.fixture(root)
            reference = root / "reference.wav"
            with wave.open(str(reference), "wb") as recording:
                recording.setparams((1, 2, 16000, 16000, "NONE", "not compressed"))
                recording.writeframes(bytes(32000))
            capture_started = 10_000_000_000
            playback_started = 11_000_000_000
            playback_completed = 12_100_000_000
            with metadata.open("a", encoding="utf-8") as handle:
                handle.write("playback_reference_present=true\n")
                handle.write(f"capture_started_monotonic_ns={capture_started}\n")
                handle.write(f"playback_reference_wav_name={reference.name}\n")
                handle.write("playback_reference_wav_sha256="
                             + hashlib.sha256(reference.read_bytes()).hexdigest() + "\n")
                handle.write("playback_reference_pcm_bytes=32000\n")
                handle.write("playback_reference_lead_in_ms=1000\n")
                handle.write(f"playback_started_monotonic_ns={playback_started}\n")
                handle.write(f"playback_completed_monotonic_ns={playback_completed}\n")
                handle.write("playback_elapsed_ms=1050\n")
                handle.write("music_volume_index=9\n")
                handle.write("music_volume_max_index=15\n")
                handle.write("music_volume_percent=60\n")
            lines = metadata.read_text(encoding="utf-8").splitlines()
            lines = ["elapsed_ms=3000" if line.startswith("elapsed_ms=")
                     else "target_duration_seconds=3"
                     if line.startswith("target_duration_seconds=") else line for line in lines]
            metadata.write_text("\n".join(lines) + "\n", encoding="utf-8")
            result = audit_module.audit(
                wav_path, metadata, "r1-sample01",
                playback_reference_wav_path=reference)
        self.assertEqual(
            "transport_reported_doa_and_controlled_playback_capture",
            result["claim_boundary"])
        self.assertEqual(60, result["controlled_playback_reference"]["music_volume_percent"])
        self.assertIn("aec_cancellation_effect", result["unverified"])

    def test_requires_playback_sidecar_when_metadata_claims_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wav_path, metadata = self.fixture(root)
            with metadata.open("a", encoding="utf-8") as handle:
                handle.write("playback_reference_present=true\n")
            with self.assertRaisesRegex(RuntimeError, "playback_reference_wav_missing"):
                audit_module.audit(wav_path, metadata, "r1-sample01")


if __name__ == "__main__":
    unittest.main()
