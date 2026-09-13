import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("alarm_sync", ROOT / "validate-alarm-sync.py")
validation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validation)


class FakeHA:
    def __init__(self, states=None, services=None, pages=None):
        self.states = states or []
        self.services = services or []
        self.pages = list(pages or [])
        self.posts = []

    def get(self, path):
        if path == "/api/states": return self.states
        if path == "/api/services": return self.services
        raise AssertionError(path)

    def post(self, path, data, expected_failure=False):
        self.posts.append((path, data, expected_failure))
        if self.pages: return self.pages.pop(0)
        return None


def alarm(alarm_id):
    return {"id": alarm_id, "name": alarm_id, "date": "2099-12-31",
            "hour": 8, "minute": 0, "weekdays": 0, "enabled": False,
            "snooze_minutes": 10, "ringtone": "classic", "volume_percent": 100}


def page(request_id, offset, items, count, complete, version=7):
    return {"schema": 2, "request_id": request_id, "operation": "status",
            "version": version, "alarms": items, "page_offset": offset,
            "page_complete": complete, "alarm_count": count}


class AlarmSyncValidationTests(unittest.TestCase):
    def test_token_file_is_consumed_only_with_strict_private_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "token"
            path.write_text("secret-token\n")
            path.chmod(0o600)
            self.assertEqual("secret-token", validation.consume_token(path))
            self.assertFalse(path.exists())
            loose = Path(directory) / "loose"
            loose.write_text("secret-token\n")
            loose.chmod(0o644)
            with self.assertRaisesRegex(RuntimeError, "token_file_mode_invalid"):
                validation.consume_token(loose)
            self.assertTrue(loose.exists())

    def test_token_symlink_is_rejected_without_deleting_target(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target"
            target.write_text("secret-token\n"); target.chmod(0o600)
            link = Path(directory) / "link"; link.symlink_to(target)
            with self.assertRaisesRegex(RuntimeError, "token_file_not_regular"):
                validation.consume_token(link)
            self.assertTrue(target.exists())

    def test_discovers_only_unique_alarm_entity_and_service(self):
        state = {"entity_id": "sensor.r1_alarms", "attributes": {
            "alarm_count": 0, "alarms": [], "pending_changes": [], "sync_status": "synced"}}
        ha = FakeHA([state], [{"domain": "esphome", "services": {
            "r1_sample01_alarm_sync": {}}}])
        self.assertEqual(("sensor.r1_alarms", "r1_sample01_alarm_sync"),
                         validation.discover(ha))
        ha.states.append({**state, "entity_id": "sensor.another_alarms"})
        with self.assertRaisesRegex(RuntimeError, "alarm_entity_not_unique"):
            validation.discover(ha)

    def test_reads_version_locked_pages_and_requires_offset_four(self):
        items = [alarm(str(index)) for index in range(5)]
        ha = FakeHA()

        def post(path, data, expected_failure=False):
            request = json.loads(data["request"])
            offset = request["page_offset"]
            if offset == 0:
                return {"service_response": page(request["request_id"], 0, items[:4], 5, False)}
            self.assertEqual(7, request["expected_version"])
            return {"service_response": page(request["request_id"], 4, items[4:], 5, True)}

        ha.post = post
        version, actual, offsets = validation.read_all_pages(ha, "r1_sample01_alarm_sync")
        self.assertEqual(7, version)
        self.assertEqual(items, actual)
        self.assertEqual([0, 4], offsets)

    def test_changed_page_version_is_rejected(self):
        ha = FakeHA()

        def post(_path, data, expected_failure=False):
            request = json.loads(data["request"])
            return {"service_response": page(request["request_id"], 4, [], 4, True, 8)}

        ha.post = post
        with self.assertRaisesRegex(RuntimeError, "alarm_page_version_changed"):
            validation.alarm_page(ha, "r1_sample01_alarm_sync", 7, 4)

    def test_expected_entity_failure_is_explicit(self):
        ha = FakeHA()
        validation.entity_service(ha, "alarm_enable", "sensor.r1_alarms",
                                  {"id": "test", "enabled": True}, expected_failure=True)
        self.assertEqual("/api/services/r1_input_guard/alarm_enable", ha.posts[0][0])
        self.assertTrue(ha.posts[0][2])

    def test_report_must_be_new_under_ignored_evidence_root(self):
        with tempfile.TemporaryDirectory(dir=validation.ROOT / "test-results") as directory:
            output = Path(directory) / "result.json"
            validation.write_report({"status": "pass", "credentials_saved": False}, output)
            self.assertFalse(json.loads(output.read_text())["credentials_saved"])
            with self.assertRaises(FileExistsError):
                validation.write_report({"status": "pass"}, output)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "evidence_must_be_under_test_results"):
                validation.write_report({"status": "pass"}, Path(directory) / "result.json")


if __name__ == "__main__":
    unittest.main()
