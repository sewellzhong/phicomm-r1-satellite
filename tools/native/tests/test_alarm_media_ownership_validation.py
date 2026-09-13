import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "alarm_media", ROOT / "validate-alarm-media-ownership.py"
)
ownership = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ownership)


class HA:
    def __init__(self): self.calls = []
    def post(self, path, data): self.calls.append((path, data))


class Device:
    def __init__(self):
        self.alarms = {"schema": 2, "version": 7, "alarms": [],
                       "alarm_count": 0, "ringing_count": 0}
        self.commands = []
    def control(self, command):
        self.commands.append(command)
        return self.alarms


class AlarmMediaOwnershipValidationTests(unittest.TestCase):
    def test_media_commands_use_only_selected_entity(self):
        ha = HA()
        ownership.media_command(ha, "media_player.r1", "play_media",
                                media_content_id="http://ha/local/test.wav",
                                media_content_type="music")
        self.assertEqual("/api/services/media_player/play_media", ha.calls[0][0])
        self.assertEqual("media_player.r1", ha.calls[0][1]["entity_id"])

    def test_delete_targets_only_exact_present_test_id_with_version(self):
        device = Device()
        device.alarms["alarms"] = [{"id": "test"}, {"id": "other"}]
        ownership.delete_alarm(device, "test")
        self.assertEqual({"action": "alarm-delete", "id": "test", "expected_version": 7},
                         device.commands[-1])
        count = len(device.commands)
        ownership.delete_alarm(device, "missing")
        self.assertEqual(count + 1, len(device.commands))  # status read only

    def test_audio_requires_real_dictionary(self):
        with self.assertRaisesRegex(RuntimeError, "device_audio_state_unavailable"):
            ownership.audio({"audio": None})
        self.assertEqual("idle", ownership.audio({"audio": {"media_state": "idle"}})["media_state"])


if __name__ == "__main__":
    unittest.main()
