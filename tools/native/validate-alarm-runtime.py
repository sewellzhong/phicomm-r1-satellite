#!/usr/bin/env python3
"""Validate natural alarm firing, DND policy, and whole-device reboot persistence."""
import argparse
from datetime import datetime, timedelta
import importlib.util
import json
from pathlib import Path
import time
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


admin = load("native_admin", "manage-r1-native.py")
sync = load("alarm_sync_validation", "validate-alarm-sync.py")


def require(condition, failure):
    if not condition:
        raise RuntimeError(failure)


def dnd(state):
    value = state.get("do_not_disturb", state)
    require(isinstance(value, dict) and value.get("schema") == 1,
            "dnd_state_unavailable")
    return value


def set_dnd(device, value, expected_version):
    return dnd(device.control({
        "action": "dnd-set", "manual": value["manual"],
        "schedule_enabled": value["schedule_enabled"],
        "start_hour": value["start_hour"], "start_minute": value["start_minute"],
        "end_hour": value["end_hour"], "end_minute": value["end_minute"],
        "alarms_allowed": value["alarms_allowed"],
        "expected_version": expected_version,
    }))


def next_due(zone_name, minutes):
    try:
        now = datetime.now(ZoneInfo(zone_name))
    except ZoneInfoNotFoundError as error:
        raise RuntimeError("alarm_time_zone_unavailable") from error
    return now.replace(second=0, microsecond=0) + timedelta(minutes=minutes)


def put_alarm(device, alarm_id, name, due, expected_version):
    return device.control({"action": "alarm-put", "id": alarm_id, "name": name,
                           "date": due.date().isoformat(), "hour": due.hour,
                           "minute": due.minute, "weekdays": 0, "enabled": True,
                           "snooze_minutes": 10, "expected_version": expected_version})


def discover_system_service(ha):
    services = ha.get("/api/services")
    require(isinstance(services, list), "ha_services_invalid")
    matches = []
    for domain in services:
        if isinstance(domain, dict) and domain.get("domain") == "esphome" \
                and isinstance(domain.get("services"), dict):
            matches.extend(name for name in domain["services"]
                           if name.endswith("_system_management"))
    require(len(matches) == 1, "system_service_not_unique")
    return matches[0]


def unwrap_system_response(value):
    if isinstance(value, dict) and "service_response" in value:
        value = value["service_response"]
    if isinstance(value, dict) and value.get("schema") == 1:
        return value
    if isinstance(value, dict) and len(value) == 1:
        nested = next(iter(value.values()))
        if isinstance(nested, dict) and nested.get("schema") == 1:
            return nested
    raise RuntimeError("system_service_response_invalid")


def reboot(ha, service):
    request_id = uuid4().hex
    request = json.dumps({"request_id": request_id, "operation": "reboot_device"},
                         separators=(",", ":"))
    response = unwrap_system_response(ha.post(
        "/api/services/esphome/" + service + "?return_response", {"request": request}))
    require(response.get("request_id") == request_id
            and response.get("operation") == "reboot_device"
            and response.get("last_operation_id") == request_id
            and response.get("last_operation") == "reboot_device"
            and response.get("last_operation_state") == "requested",
            "reboot_request_not_confirmed")
    return request_id


def boot_identity(device):
    value = device.adb("shell", "cat", "/proc/sys/kernel/random/boot_id")
    require(len(value) == 36 and value.count("-") == 4, "boot_identity_invalid")
    return value


def wait_after_reboot(device, previous, timeout=150):
    deadline = time.monotonic() + timeout
    saw_unavailable = False
    while time.monotonic() < deadline:
        try:
            current = boot_identity(device)
            if current != previous:
                state = device.start_control()
                if (state.get("status") == "listening" and state.get("audio_opened") is True
                        and state.get("audio_blocked") is False
                        and state.get("factory_isolation") == "packages_hidden"
                        and state.get("last_error") is None
                        and dnd(state).get("clock_trusted") is True):
                    return current, saw_unavailable
        except Exception:
            saw_unavailable = True
        time.sleep(1)
    raise RuntimeError("device_reboot_restore_timeout")


def wait_alarm(device, predicate, failure, deadline):
    remaining = max(1, int(deadline.timestamp() - time.time()) + 90)
    return sync.wait_for(lambda: sync.device_alarms(device), predicate, failure,
                         timeout=remaining, pause=time.sleep)


def validate(device, ha, test_ids):
    initial = device.start_control()
    require(initial.get("status") == "listening" and initial.get("audio_opened") is True
            and initial.get("audio_blocked") is False
            and initial.get("factory_isolation") == "packages_hidden"
            and initial.get("last_error") is None, "device_not_ready")
    original_dnd = dnd(initial)
    require(original_dnd.get("clock_trusted") is True, "alarm_clock_not_trusted")
    before = sync.device_alarms(device)
    require(before.get("alarm_count") == 0 and before.get("ringing_count") == 0,
            "alarm_runtime_requires_empty_baseline")
    changed_dnd = False
    try:
        blocked_policy = {**original_dnd, "manual": True, "schedule_enabled": False,
                          "alarms_allowed": False}
        blocked_dnd = set_dnd(device, blocked_policy, original_dnd["version"])
        changed_dnd = True
        blocked_due = next_due(blocked_dnd["time_zone"], 2)
        put_alarm(device, test_ids[0], "DND屏蔽验证", blocked_due, before["version"])
        blocked = wait_alarm(
            device,
            lambda value: value.get("suppressed", 0) == before.get("suppressed", 0) + 1
            and value.get("ringing_count") == 0 and value.get("ringer_active") is False,
            "dnd_alarm_suppression_not_confirmed", blocked_due)
        blocked_dnd_after = dnd(device.control({"action": "status"}))
        require(blocked_dnd_after.get("suppressed_alarms")
                == original_dnd.get("suppressed_alarms", 0) + 1,
                "dnd_suppressed_alarm_counter_missing")
        device.control({"action": "alarm-delete", "id": test_ids[0],
                        "expected_version": blocked["version"]})

        allowed_policy = {**original_dnd, "manual": True, "schedule_enabled": False,
                          "alarms_allowed": True}
        allowed_dnd = set_dnd(device, allowed_policy, blocked_dnd_after["version"])
        alarm_before_reboot = sync.device_alarms(device)
        reboot_due = next_due(allowed_dnd["time_zone"], 3)
        put_alarm(device, test_ids[1], "重启恢复验证", reboot_due,
                  alarm_before_reboot["version"])
        persisted = sync.device_alarms(device)
        target = next((item for item in persisted["alarms"]
                       if item.get("id") == test_ids[1]), None)
        require(target is not None and target.get("enabled") is True
                and target.get("next_wall_ms") is not None, "reboot_alarm_not_persisted")

        old_boot = boot_identity(device)
        system_service = discover_system_service(ha)
        operation_id = reboot(ha, system_service)
        new_boot, saw_unavailable = wait_after_reboot(device, old_boot)
        restored_alarm = sync.device_alarms(device)
        restored_target = next((item for item in restored_alarm["alarms"]
                                if item.get("id") == test_ids[1]), None)
        require(restored_target is not None, "alarm_missing_after_reboot")
        restored_dnd = dnd(device.control({"action": "status"}))
        require(restored_dnd.get("manual") is True
                and restored_dnd.get("alarms_allowed") is True
                and restored_dnd.get("active") is True,
                "dnd_policy_missing_after_reboot")

        ringing = wait_alarm(
            device,
            lambda value: value.get("ringing_count") == 1
            and value.get("ringer_active") is True
            and value.get("fires", 0) == persisted.get("fires", 0) + 1,
            "rebooted_alarm_did_not_ring", reboot_due)
        stopped = device.control({"action": "alarm-stop", "id": test_ids[1]})
        require(stopped.get("ringing_count") == 0 and stopped.get("ringer_active") is False
                and stopped.get("stops", 0) == ringing.get("stops", 0) + 1,
                "rebooted_alarm_stop_not_confirmed")
        device.control({"action": "alarm-delete", "id": test_ids[1],
                        "expected_version": stopped["version"]})
        final_alarms = sync.device_alarms(device)
        require(final_alarms.get("alarm_count") == 0 and final_alarms.get("ringing_count") == 0,
                "alarm_runtime_cleanup_failed")

        latest_dnd = dnd(device.control({"action": "status"}))
        restored = set_dnd(device, original_dnd, latest_dnd["version"])
        changed_dnd = False
        keys = ("manual", "schedule_enabled", "start_hour", "start_minute",
                "end_hour", "end_minute", "alarms_allowed")
        require(all(restored.get(key) == original_dnd.get(key) for key in keys),
                "dnd_policy_restore_failed")
        return {"status": "pass", "scenario": "alarm_natural_dnd_reboot",
                "dnd_blocked_alarm_suppressed": True,
                "alarm_suppressed_delta": 1, "ringer_started_while_blocked": False,
                "dnd_suppressed_delta": 1, "reboot_operation_id_correlated": True,
                "boot_identity_changed": new_boot != old_boot,
                "adb_unavailable_observed": saw_unavailable,
                "alarm_present_after_reboot": restored_target is not None,
                "dnd_present_after_reboot": True, "natural_alarm_fired": True,
                "alarm_stopped": True, "baseline_restored": True,
                "credentials_saved": False}
    finally:
        try:
            device.start_control()
            current = sync.device_alarms(device)
            if current.get("ringing_count", 0):
                device.control({"action": "alarm-stop"})
            for alarm_id in test_ids:
                current = sync.device_alarms(device)
                if any(item.get("id") == alarm_id for item in current.get("alarms", [])):
                    device.control({"action": "alarm-delete", "id": alarm_id,
                                    "expected_version": current["version"]})
        except Exception:
            pass
        if changed_dnd:
            try:
                latest = dnd(device.control({"action": "status"}))
                set_dnd(device, original_dnd, latest["version"])
            except Exception:
                pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("serial")
    parser.add_argument("--confirm-device", required=True, choices=("r1-sample01",))
    parser.add_argument("--ha-url", required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    token = sync.read_token(args.token_file)
    try:
        ha = sync.HomeAssistant(args.ha_url, token)
        device = admin.Device(args.serial)
        device.verify()
        prefix = "r1-validation-runtime-" + uuid4().hex[:12] + "-"
        report = validate(device, ha, [prefix + "blocked", prefix + "reboot"])
        sync.write_report(report, args.output)
        print(json.dumps(report, ensure_ascii=False))
    finally:
        token = ""


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"status": "failed", "failure": str(error)}, ensure_ascii=False),
              file=__import__("sys").stderr)
        raise SystemExit(1)
