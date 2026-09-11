from pathlib import Path
import importlib.util
import struct
import tempfile
import unittest
import wave


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "privileged_vendor_debug_probe",
    ROOT / "tools/factory_audio/probe-privileged-vendor-debug-files.py"
)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


class PrivilegedVendorDebugProbeTest(unittest.TestCase):
    def test_output_must_be_new_and_outside_repository(self):
        with self.assertRaisesRegex(probe.ProbeError, "outside_repository"):
            probe.validate_output(ROOT / "local-output")
        with tempfile.TemporaryDirectory() as directory:
            existing = Path(directory)
            with self.assertRaisesRegex(probe.ProbeError, "already_exists"):
                probe.validate_output(existing)
            self.assertEqual(existing / "new", probe.validate_output(existing / "new"))

    def test_package_identity_requires_data_app_and_version(self):
        version, path = probe.parse_package_identity(
            "  codePath=/data/app/dev.sewellzhong.r1probe-2\n"
            "  versionCode=84 targetSdk=22\n"
        )
        self.assertEqual(84, version)
        self.assertEqual("/data/app/dev.sewellzhong.r1probe-2/base.apk", path)
        with self.assertRaisesRegex(probe.ProbeError, "identity_unavailable"):
            probe.parse_package_identity("versionCode=84")

    def test_debug_names_and_roots_are_fixed(self):
        self.assertEqual(("/sdcard/unidata", "/data/unidata"), probe.DEBUG_ROOTS)
        self.assertEqual(6, len(probe.DEBUG_NAMES))
        self.assertIn("waking_file_4mic.wav", probe.DEBUG_NAMES)
        self.assertIn("waked_file_2aec.wav", probe.DEBUG_NAMES)

    def test_broadcast_and_native_restore_require_complete_state(self):
        self.assertTrue(probe.broadcast_succeeded("Broadcast completed: result=0"))
        self.assertFalse(probe.broadcast_succeeded("Broadcast completed: result=-1"))
        ready = {
            "status": "listening", "audio_opened": True,
            "listen": True, "enabled": True,
        }
        self.assertTrue(probe.native_listening(ready))
        for key in ready:
            incomplete = dict(ready)
            incomplete[key] = False if key != "status" else "waiting_ha"
            self.assertFalse(probe.native_listening(incomplete))

    def test_validation_outputs_are_restricted_to_app_diagnostics(self):
        base = probe.APP_DIAGNOSTIC_ROOT + "/1516615841373-capture"
        marker = ("complete wav_path=" + base + ".wav"
                  + " diagnostic_wav_path=" + base + "-stereo.wav"
                  + " metadata_path=" + base + ".meta.txt frames=250")
        paths = probe.validation_output_paths(marker)
        self.assertEqual(base + ".wav", paths["wav_path"])
        with self.assertRaisesRegex(probe.ProbeError, "outside_diagnostics"):
            probe.validation_output_paths(marker.replace(
                base + ".meta.txt", "/sdcard/other.meta.txt"))

    def test_complete_phase_requires_nonempty_valid_triplet(self):
        artifacts = {
            "waking_file_4mic.wav": {"status": "pass"},
            "waking_file_2aec.wav": {"status": "pass"},
            "waking_file_out.wav": {"status": "pass"},
            "waked_file_4mic.wav": {"status": "invalid_wav"},
        }
        result = probe.evaluate_artifacts(artifacts)
        self.assertEqual("pass", result["status"])
        self.assertEqual(["waking"], result["complete_phases"])
        artifacts.pop("waking_file_out.wav")
        self.assertEqual(
            "no_complete_nonempty_debug_triplet",
            probe.evaluate_artifacts(artifacts)["status"],
        )

    def test_wav_contract_distinguishes_raw_and_processed_shapes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for kind, channels in probe.EXPECTED_CHANNELS.items():
                path = root / (kind + ".wav")
                with wave.open(str(path), "wb") as audio:
                    audio.setnchannels(channels)
                    audio.setsampwidth(2)
                    audio.setframerate(16000)
                    audio.writeframes(struct.pack("<" + "h" * channels, *range(channels)))
                self.assertEqual("pass", probe.inspect_wav(path, kind)["status"])

            empty = root / "empty.wav"
            with wave.open(str(empty), "wb") as audio:
                audio.setnchannels(4)
                audio.setsampwidth(2)
                audio.setframerate(16000)
            self.assertEqual("format_or_payload_mismatch",
                             probe.inspect_wav(empty, "4mic")["status"])


if __name__ == "__main__":
    unittest.main()
