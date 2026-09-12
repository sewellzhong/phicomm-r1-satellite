import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "feature_validation", ROOT / "validate-announcement-timers.py"
)
validation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validation)


def audio_state(**updates):
    audio = {
        "announcement_active": False, "announcement_requests": 0,
        "announcement_completed": 0, "announcement_failures": 0,
        "announcement_segments_started": 0, "announcement_segments_completed": 0,
        "playback_first_write_ms": 0, "playback_drained_ms": 0,
        "playback_released_ms": 0,
        "timers": {"ringing_count": 0},
    }
    audio.update(updates)
    return {"status": "listening", "audio": audio}


class Device:
    def __init__(self, status_states=None, timer_states=None):
        self.status_states = iter(status_states or [])
        self.timer_states = iter(timer_states or [])
        self.commands = []
    def start_control(self):
        return audio_state()
    def control(self, command):
        self.commands.append(command)
        if command["action"] == "status":
            return next(self.status_states)
        if command["action"] in ("timer-status", "timer-stop"):
            return next(self.timer_states)
        raise AssertionError(command)


class HA:
    def __init__(self):
        self.calls = []
    def announce(self, *args):
        self.calls.append(("announce", args))
    def conversation(self, *args):
        self.calls.append(("conversation", args))
        return {"response": {"response_type": "action_done"}}


class AnnouncementTimerValidationTests(unittest.TestCase):
    def test_two_segment_announcement_requires_complete_playback(self):
        device = Device(status_states=[audio_state(
            announcement_requests=1, announcement_completed=1,
            announcement_segments_started=2, announcement_segments_completed=2,
            playback_first_write_ms=10, playback_drained_ms=20, playback_released_ms=21,
        )])
        report = validation.validate_announcement(
            device, HA(), "assist_satellite.r1", "https://ha/body.wav", "https://ha/cue.wav",
            timeout=1,
        )
        self.assertEqual(2, report["segments_completed_delta"])
        self.assertFalse(report["credentials_saved"])

    def test_announcement_fails_when_segment_sequence_is_missing(self):
        device = Device(status_states=[audio_state(
            announcement_requests=1, announcement_completed=1,
            announcement_segments_started=1, announcement_segments_completed=1,
            playback_first_write_ms=10, playback_drained_ms=20, playback_released_ms=21,
        )])
        with self.assertRaisesRegex(RuntimeError, "announcement_segment_sequence_unproven"):
            validation.validate_announcement(
                device, HA(), "assist_satellite.r1", "https://ha/body.wav", "https://ha/cue.wav",
                timeout=1,
            )

    def test_timer_expiry_and_shell_stop_are_read_back(self):
        before = {"active_count": 0, "ringing_count": 0, "started": 0, "finished": 0,
                  "local_finished": 0, "local_stops": 0, "alarm_active": False}
        active = {**before, "active_count": 1, "started": 1}
        ringing = {**before, "started": 1, "ringing_count": 1,
                   "local_finished": 1, "alarm_active": True}
        stopped = {**before, "started": 1, "local_finished": 1,
                   "local_stops": 1, "alarm_active": False}
        device = Device(timer_states=[before, active, ringing, stopped])
        report = validation.validate_timer_expiry(
            device, HA(), "device123", "设置三秒计时器", "取消所有计时器", timeout=1,
            pause=lambda _seconds: None,
        )
        self.assertTrue(report["alarm_stopped"])
        self.assertEqual(1, report["local_finished_delta"])
        self.assertEqual("timer-stop", device.commands[-1]["action"])

    def test_existing_timer_is_never_modified(self):
        existing = {"active_count": 1, "ringing_count": 0}
        ha = HA()
        with self.assertRaisesRegex(RuntimeError, "existing_timer_state_refused"):
            validation.validate_timer_expiry(
                Device(timer_states=[existing]), ha, "device123", "开始", "取消",
            )
        self.assertEqual([], ha.calls)


if __name__ == "__main__":
    unittest.main()
