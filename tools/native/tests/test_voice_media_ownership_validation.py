import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "voice_media", ROOT / "validate-voice-media-ownership.py"
)
ownership = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ownership)


class HA:
    def __init__(self): self.calls = []
    def post(self, path, data): self.calls.append((path, data))


class Device:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.commands = []
    def control(self, command):
        self.commands.append(command)
        return next(self.responses)


def state(status="listening", media="idle", runs=0, cancels=0):
    return {"status": status, "audio": {"media_state": media,
            "fixed_pcm_runs": runs, "fixed_pcm_cancels": cancels}}


class VoiceMediaOwnershipValidationTests(unittest.TestCase):
    def test_media_commands_target_only_selected_entity(self):
        ha = HA()
        ownership.media_command(ha, "media_player.r1", "play_media",
                                media_content_id="http://ha/local/test.wav",
                                media_content_type="music")
        self.assertEqual("/api/services/media_player/play_media", ha.calls[0][0])
        self.assertEqual("media_player.r1", ha.calls[0][1]["entity_id"])

    def test_start_voice_requires_counter_and_paused_media(self):
        device = Device([state("injecting_fixed_pcm", "paused", 4, 2)])
        result = ownership.start_voice(device, 3)
        self.assertEqual("paused", result["audio"]["media_state"])
        self.assertEqual({"action": "fixed-pcm-start"}, device.commands[0])

    def test_start_voice_rejects_unpaused_media(self):
        device = Device([state("injecting_fixed_pcm", "playing", 4, 2)])
        with self.assertRaisesRegex(RuntimeError, "voice_media_interruption_not_confirmed"):
            ownership.start_voice(device, 3)

    def test_cancel_waits_for_listening_and_exact_counter(self):
        device = Device([
            state("cancelling_fixed_pcm", "paused", 4, 3),
            state("cancelling_fixed_pcm", "paused", 4, 3),
            state("listening", "playing", 4, 3),
        ])
        result = ownership.cancel_voice(device, 2)
        self.assertEqual("playing", result["audio"]["media_state"])
        self.assertEqual("fixed-pcm-cancel", device.commands[0]["action"])


if __name__ == "__main__":
    unittest.main()
