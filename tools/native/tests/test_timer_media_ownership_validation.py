import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "timer_media", ROOT / "validate-timer-media-ownership.py"
)
ownership = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ownership)


class HA:
    def __init__(self): self.calls = []
    def post(self, path, data): self.calls.append((path, data)); return None


class Device:
    def __init__(self, timer_state): self.timer_state = timer_state; self.commands = []
    def control(self, command):
        self.commands.append(command)
        if command.get("action") == "timer-stop":
            self.timer_state = {**self.timer_state, "ringing_count": 0,
                                "alarm_active": False, "local_stops": 4}
        return self.timer_state


class TimerMediaOwnershipValidationTests(unittest.TestCase):
    def test_media_commands_use_only_selected_entity(self):
        ha = HA()
        ownership.media_command(ha, "media_player.r1", "play_media",
                                media_content_id="http://ha/local/test.wav",
                                media_content_type="music")
        self.assertEqual("/api/services/media_player/play_media", ha.calls[0][0])
        self.assertEqual("media_player.r1", ha.calls[0][1]["entity_id"])

    def test_stop_requires_ringing_to_end_and_local_stop_counter(self):
        device = Device({"ringing_count": 1, "alarm_active": True, "local_stops": 4})
        result = ownership.stop_timer(device, {"local_stops": 3})
        self.assertEqual(4, result["local_stops"])
        self.assertEqual("timer-stop", device.commands[-1]["action"])

    def test_wait_timer_ringing_requires_alarm_active(self):
        device = Device({"ringing_count": 1, "alarm_active": True})
        self.assertTrue(ownership.wait_timer_ringing(device, {"ringing_count": 0}, timeout=1,
                                                     pause=lambda _: None)["alarm_active"])

    def test_audio_requires_dictionary(self):
        with self.assertRaisesRegex(RuntimeError, "device_audio_state_unavailable"):
            ownership.audio({"audio": None})


if __name__ == "__main__":
    unittest.main()
