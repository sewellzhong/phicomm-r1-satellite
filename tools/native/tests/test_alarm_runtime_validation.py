import importlib.util
from datetime import datetime
import json
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("alarm_runtime", ROOT / "validate-alarm-runtime.py")
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)


class HA:
    def __init__(self, services=None):
        self.services = services or []
        self.response = None
    def get(self, path):
        if path == "/api/services": return self.services
        raise AssertionError(path)
    def post(self, path, data):
        request = json.loads(data["request"])
        return {"service_response": {
            "schema": 1, "request_id": request["request_id"],
            "operation": request["operation"],
            "last_operation_id": request["request_id"],
            "last_operation": request["operation"],
            "last_operation_state": "requested"}}


class AlarmRuntimeValidationTests(unittest.TestCase):
    def test_due_time_uses_device_zone_and_whole_minutes(self):
        with patch.object(runtime, "datetime") as clock:
            clock.now.return_value = datetime(2026, 9, 14, 23, 59, 48)
            due = runtime.next_due("Asia/Shanghai", 2)
        self.assertEqual(datetime(2026, 9, 15, 0, 1), due)

    def test_system_service_must_be_unique(self):
        ha = HA([{"domain": "esphome", "services": {
            "r1_sample01_system_management": {}}}])
        self.assertEqual("r1_sample01_system_management",
                         runtime.discover_system_service(ha))
        ha.services[0]["services"]["other_system_management"] = {}
        with self.assertRaisesRegex(RuntimeError, "system_service_not_unique"):
            runtime.discover_system_service(ha)

    def test_reboot_response_is_request_correlated(self):
        operation = runtime.reboot(HA(), "r1_sample01_system_management")
        self.assertRegex(operation, r"^[a-f0-9]{32}$")

    def test_reboot_rejects_uncorrelated_response(self):
        ha = HA()
        original = ha.post
        def wrong(path, data):
            value = original(path, data)
            value["service_response"]["request_id"] = "0" * 32
            return value
        ha.post = wrong
        with self.assertRaisesRegex(RuntimeError, "reboot_request_not_confirmed"):
            runtime.reboot(ha, "r1_sample01_system_management")


if __name__ == "__main__":
    unittest.main()
