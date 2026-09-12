import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "dnd_media_validation", ROOT / "validate-dnd-media.py"
)
validation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validation)


def dnd_state(manual=False, version=3, suppressed=0):
    return {"schema": 1, "version": version, "manual": manual,
            "schedule_enabled": False, "start_hour": 22, "start_minute": 0,
            "end_hour": 7, "end_minute": 0, "alarms_allowed": True,
            "active": manual, "restore_failed": False,
            "dim_light_requested": manual, "suppressed_announcements": suppressed}


def state(media="idle", requests=0, rejected=0, failures=0, failure="none",
          volume=50, announcement_active=False, announcement_requests=0,
          announcement_completed=0, announcement_started=0, dnd_value=None):
    return {"status": "listening", "volume_percent": volume,
            "do_not_disturb": dnd_value or dnd_state(),
            "audio": {"media_state": media, "media_requests": requests,
                      "media_rejected": rejected, "media_failures": failures,
                      "media_last_failure": failure,
                      "announcement_active": announcement_active,
                      "announcement_requests": announcement_requests,
                      "announcement_completed": announcement_completed,
                      "announcement_segments_started": announcement_started,
                      "timers": {"ringing_count": 0}}}


class Device:
    def __init__(self, states):
        self.states = iter(states); self.commands = []
    def start_control(self): return next(self.states)
    def control(self, command):
        self.commands.append(command); return next(self.states)


class HA:
    def __init__(self): self.calls = []
    def post(self, path, data): self.calls.append((path, data)); return []
    def announce(self, entity, media, preannounce=None):
        self.calls.append(("announce", {"entity": entity})); return []


class DndMediaValidationTests(unittest.TestCase):
    def test_media_lifecycle_requires_real_states_and_restores_volume(self):
        device = Device([
            state(), state("playing", requests=1), state("paused", requests=2),
            state("playing", requests=3), state("playing", requests=4, volume=37),
            state("idle", requests=5, volume=37),
            state("failed", requests=6, failures=1, failure="media_io_error", volume=37),
        ])
        ha = HA()
        report = validation.validate_media_lifecycle(
            device, ha, "media_player.r1", "http://host/long.mp3",
            "http://host/missing.mp3", timeout=1,
        )
        self.assertTrue(report["real_backend_started"])
        self.assertEqual(1, report["failures_delta"])
        self.assertFalse(report["urls_saved"])
        self.assertEqual("/api/services/media_player/volume_set", ha.calls[-1][0])
        self.assertEqual(.5, ha.calls[-1][1]["volume_level"])

    def test_media_rejection_fails_before_failure_probe(self):
        device = Device([
            state(), state("playing", requests=1), state("paused", requests=2),
            state("playing", requests=3), state("playing", requests=4, volume=37),
            state("idle", requests=5, rejected=1, volume=37),
        ])
        with self.assertRaisesRegex(RuntimeError, "media_command_rejected"):
            validation.validate_media_lifecycle(
                device, HA(), "media_player.r1", "http://host/long.mp3",
                "http://host/missing.mp3", timeout=1,
            )

    def test_announcement_pauses_and_resumes_media(self):
        device = Device([
            state(), state("playing", requests=1),
            state("paused", requests=1, announcement_active=True, announcement_requests=1),
            state("playing", requests=1, announcement_completed=1),
        ])
        report = validation.validate_media_announcement(
            device, HA(), "media_player.r1", "assist_satellite.r1",
            "http://host/long.mp3", "http://host/notice.wav", timeout=1,
        )
        self.assertTrue(report["media_paused_during_announcement"])
        self.assertTrue(report["media_resumed_after_announcement"])

    def test_dnd_suppresses_without_opening_media_and_restores_policy(self):
        before = dnd_state()
        active = dnd_state(True, 4)
        suppressed = dnd_state(True, 4, 1)
        restored = dnd_state(False, 5, 1)
        device = Device([
            state(dnd_value=before), state(dnd_value=active),
            state(announcement_requests=1, dnd_value=suppressed),
            state(announcement_requests=1, dnd_value=restored),
        ])
        report = validation.validate_dnd_announcement(
            device, HA(), "sensor.r1_dnd", "assist_satellite.r1",
            "http://host/notice.wav", timeout=1,
        )
        self.assertTrue(report["announcement_suppressed"])
        self.assertTrue(report["original_policy_restored"])
        self.assertTrue(report["dim_light_request_only"])

    def test_dnd_refuses_to_overwrite_existing_active_policy(self):
        with self.assertRaisesRegex(RuntimeError, "dnd_preexisting_or_invalid"):
            validation.validate_dnd_announcement(
                Device([state(dnd_value=dnd_state(True))]), HA(),
                "sensor.r1_dnd", "assist_satellite.r1", "http://host/notice.wav",
            )

    def test_dnd_readback_timeout_still_attempts_original_policy_restore(self):
        before = dnd_state()
        unchanged = state(dnd_value=before)
        device = Device([unchanged, unchanged])
        ha = HA()
        with patch.object(validation, "wait_device",
                          side_effect=RuntimeError("dnd_enable_not_confirmed")):
            with self.assertRaisesRegex(RuntimeError, "dnd_enable_not_confirmed"):
                validation.validate_dnd_announcement(
                    device, ha, "sensor.r1_dnd", "assist_satellite.r1",
                    "http://host/notice.wav", timeout=0,
                )
        calls = [item for item in ha.calls
                 if item[0] == "/api/services/r1_input_guard/dnd_set"]
        self.assertEqual(2, len(calls))
        self.assertTrue(calls[0][1]["manual"])
        self.assertFalse(calls[1][1]["manual"])


if __name__ == "__main__": unittest.main()
