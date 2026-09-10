from pathlib import Path
import importlib.util
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "original_chain_smoke", ROOT / "tools/factory_audio/run-original-chain-smoke.py"
)
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


class OriginalChainSmokeTest(unittest.TestCase):
    def test_audio_release_requires_all_owners_stopped(self):
        self.assertTrue(smoke.audio_released(
            {"audio": None, "audio_opened": False, "health": None}
        ))
        self.assertFalse(smoke.audio_released(
            {"audio": None, "audio_opened": True, "health": None}
        ))
        self.assertFalse(smoke.audio_released(
            {"audio": None, "audio_opened": False, "health": {"state": "running"}}
        ))

    def test_listening_ready_requires_open_audio(self):
        self.assertTrue(smoke.listening_ready({"status": "listening", "audio_opened": True}))
        self.assertFalse(smoke.listening_ready({"status": "listening", "audio_opened": False}))

    def test_package_path_uses_data_app_overlay_not_system_base(self):
        device = smoke.Device("unused")
        device.shell = lambda *args, **kwargs: (
            "  codePath=/data/app/com.phicomm.speaker.device-1\n"
            "  codePath=/system/app/Unisound\n"
        )
        self.assertEqual(
            "/data/app/com.phicomm.speaker.device-1/base.apk",
            device.package_apk("com.phicomm.speaker.device"),
        )

    def test_remote_file_exists_uses_output_not_legacy_adb_exit_status(self):
        device = smoke.Device("unused")
        device.shell = lambda *args, **kwargs: "present"
        self.assertTrue(device.remote_file_exists("/sdcard/unidata/waked_file_4mic.wav"))
        device.shell = lambda *args, **kwargs: ""
        self.assertFalse(device.remote_file_exists("/sdcard/unidata/waked_file_4mic.wav"))
        with self.assertRaisesRegex(smoke.SmokeError, "unsupported_remote_debug_path"):
            device.remote_file_exists("/sdcard/other.wav")

    def test_gateway_success_does_not_accept_total_loss(self):
        self.assertTrue(smoke.ping_is_local_success("2 received, 0% packet loss"))
        self.assertFalse(smoke.ping_is_local_success("0 received, 100% packet loss"))

    def test_wan_rejection_requires_loss_and_router_reject(self):
        self.assertTrue(smoke.ping_is_rejected(
            "Destination Port Unreachable\n0 received, 100% packet loss"
        ))
        self.assertTrue(smoke.ping_is_rejected(
            "Destination unreachable: Port unreachable\n0 received, 100% packet loss"
        ))
        self.assertFalse(smoke.ping_is_rejected("0 received, 100% packet loss"))
        self.assertFalse(smoke.ping_is_rejected("2 received, 0% packet loss"))

    def test_output_must_be_new_and_outside_repository(self):
        with self.assertRaisesRegex(smoke.SmokeError, "outside_repository"):
            smoke.validate_output(ROOT / "local-output")
        with tempfile.TemporaryDirectory() as directory:
            existing = Path(directory)
            with self.assertRaisesRegex(smoke.SmokeError, "already_exists"):
                smoke.validate_output(existing)
            candidate = existing / "new"
            self.assertEqual(candidate, smoke.validate_output(candidate))

    def test_debug_names_are_fixed_and_bounded(self):
        self.assertEqual(6, len(smoke.DEBUG_NAMES))
        self.assertIn("waking_file_4mic.wav", smoke.DEBUG_NAMES)
        self.assertIn("waked_file_2aec.wav", smoke.DEBUG_NAMES)

    def test_factory_runtime_attestation_is_strict(self):
        complete = [
            "UNI_4MIC_HAL_ANDROID_V1.1", "use_4mic=1",
            "uni_hal_4mic_array_init sucess", "mic_num=4", "echo_num=2",
            "aec_on=1", "AudioSourceImplopenIn uni4micHalJNI status = 0",
        ]
        self.assertEqual("pass", smoke.factory_runtime_attestation(complete)["status"])
        self.assertEqual(
            "fail", smoke.factory_runtime_attestation(complete[:-1])["status"]
        )


if __name__ == "__main__":
    unittest.main()
