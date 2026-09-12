import base64
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "fixed_pcm_validation", ROOT / "run-fixed-pcm-validation.py"
)
fixed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixed)


def state(status="listening", **updates):
    audio = {
        "commands": 0, "stt_results": 0, "tts_streams": 0, "completed": 0,
        "fixed_pcm_runs": 0, "fixed_pcm_cancels": 0,
        "playback_first_write_ms": 0, "playback_drained_ms": 0,
        "playback_released_ms": 0, "playback_buffer_high_water_bytes": 0,
        "playback_underruns": 0,
    }
    audio.update(updates)
    return {"status": status, "last_error": None, "audio": audio}


class Device:
    def __init__(self, states):
        self.states = iter(states)
        self.commands = []
    def start_control(self):
        return state()
    def control(self, command):
        self.commands.append(command)
        if command["action"] == "status":
            return next(self.states)
        return state()


class FixedPcmValidationTests(unittest.TestCase):
    def test_frames_are_bounded_and_completion_is_reported(self):
        device = Device([state(
            fixed_pcm_runs=1, commands=1, stt_results=1, tts_streams=1, completed=1,
            playback_first_write_ms=100, playback_drained_ms=60100,
            playback_released_ms=60110, playback_buffer_high_water_bytes=4096,
        )])
        before, after, cancelled = fixed.run(device, bytes(1280), pause=lambda _seconds: None)
        frames = [item for item in device.commands if item["action"] == "fixed-pcm-frame"]
        self.assertEqual(2, len(frames))
        self.assertTrue(all(len(base64.b64decode(item["data"])) == 640 for item in frames))
        report = fixed.safe_report(before, after, cancelled, Path("fixture.wav"))
        self.assertEqual(60000, report["playback"]["duration_ms"])
        self.assertEqual(1, report["delta"]["completed"])
        self.assertFalse(report["text_saved"])

    def test_cancel_is_sent_once_after_playback_starts(self):
        device = Device([
            state("playing", fixed_pcm_runs=1, commands=1, stt_results=1, tts_streams=1,
                  playback_first_write_ms=100),
            state(fixed_pcm_runs=1, fixed_pcm_cancels=1, commands=1, stt_results=1,
                  tts_streams=1, playback_first_write_ms=100, playback_released_ms=200),
        ])
        _before, after, cancelled = fixed.run(
            device, bytes(640), cancel_on_playback=True, pause=lambda _seconds: None
        )
        self.assertTrue(cancelled)
        self.assertEqual(1, [item["action"] for item in device.commands].count("fixed-pcm-cancel"))
        self.assertEqual(1, after["audio"]["fixed_pcm_cancels"])


if __name__ == "__main__":
    unittest.main()
