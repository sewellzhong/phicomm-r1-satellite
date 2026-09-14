import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "announcement_timer_ownership",
    ROOT / "validate-announcement-timer-ownership.py",
)
ownership = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ownership)


class HA:
    def __init__(self): self.conversations = []; self.announcements = []
    def conversation(self, text, device_id):
        self.conversations.append((text, device_id)); return {}
    def announce(self, entity_id, media_url):
        self.announcements.append((entity_id, media_url)); return None


class Device:
    def __init__(self, values): self.values = list(values)
    def control(self, command): return self.values.pop(0)


class AnnouncementTimerOwnershipValidationTests(unittest.TestCase):
    def test_audio_requires_dictionary(self):
        with self.assertRaisesRegex(RuntimeError, "device_audio_state_unavailable"):
            ownership.audio({"audio": None})

    def test_start_timer_requires_new_active_timer(self):
        ha = HA()
        device = Device([{"started": 2, "active_count": 1}])
        observed = ownership.start_timer(ha, device, "device123", "一分钟计时器",
                                         {"started": 1}, pause=lambda _: None)
        self.assertEqual(2, observed["started"])
        self.assertEqual([("一分钟计时器", "device123")], ha.conversations)

    def test_start_announcement_requires_active_and_paused_media(self):
        ha = HA()
        state = {"audio": {"announcement_active": True,
                           "announcement_requests": 2, "media_state": "paused"}}
        observed = ownership.start_announcement(
            ha, Device([state]), "assist_satellite.r1", "http://ha/a.wav",
            {"announcement_requests": 1}, pause=lambda _: None)
        self.assertTrue(ownership.audio(observed)["announcement_active"])
        self.assertEqual("assist_satellite.r1", ha.announcements[0][0])

    def test_timer_preemption_requires_announcement_failure_and_paused_media(self):
        state = {"audio": {"timers": {"ringing_count": 1, "alarm_active": True},
                           "announcement_active": False, "announcement_failures": 4,
                           "media_state": "paused"}}
        observed = ownership.wait_timer_preemption(
            Device([state]), {"ringing_count": 0}, {"announcement_failures": 3},
            timeout=1, pause=lambda _: None)
        self.assertFalse(ownership.audio(observed)["announcement_active"])


if __name__ == "__main__":
    unittest.main()
