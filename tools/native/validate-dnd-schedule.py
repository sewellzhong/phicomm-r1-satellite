#!/usr/bin/env python3
"""Validate a cross-midnight DND schedule, real LED dimming, and service persistence."""
import argparse
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("native_admin", HERE / "manage-r1-native.py")
admin = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(admin)


def require(condition, failure):
    if not condition:
        raise RuntimeError(failure)


def policy(state):
    value = state.get("do_not_disturb", state)
    require(isinstance(value, dict) and value.get("schema") == 1,
            "dnd_state_unavailable")
    return value


def set_policy(device, value, expected_version):
    return policy(device.control({
        "action": "dnd-set", "manual": value["manual"],
        "schedule_enabled": value["schedule_enabled"],
        "start_hour": value["start_hour"], "start_minute": value["start_minute"],
        "end_hour": value["end_hour"], "end_minute": value["end_minute"],
        "alarms_allowed": value["alarms_allowed"],
        "expected_version": expected_version,
    }))


def wait_for(read, predicate, failure, timeout=20):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = read()
        if predicate(last):
            return last
        time.sleep(.2)
    raise RuntimeError(failure)


def active_cross_midnight(zone_name):
    try:
        now = datetime.now(ZoneInfo(zone_name))
    except ZoneInfoNotFoundError as error:
        raise RuntimeError("dnd_time_zone_unavailable") from error
    minute = now.hour * 60 + now.minute
    if minute >= 12 * 60:
        start, end = minute - 1, 5
    else:
        start, end = 23 * 60 + 55, minute + 5
    require(start > end and (minute >= start or minute < end),
            "cross_midnight_window_invalid")
    return start, end


def validate(device):
    before_status = device.start_control()
    require(before_status.get("status") == "listening", "device_not_listening")
    require(before_status.get("privacy", {}).get("muted") is False,
            "privacy_mute_must_be_off")
    before = policy(before_status)
    require(before.get("clock_trusted") is True, "dnd_clock_not_trusted")
    start, end = active_cross_midnight(before["time_zone"])
    candidate = {
        "manual": False, "schedule_enabled": True,
        "start_hour": start // 60, "start_minute": start % 60,
        "end_hour": end // 60, "end_minute": end % 60,
        "alarms_allowed": before["alarms_allowed"],
    }
    changed = False
    service_restarted = False
    try:
        scheduled = set_policy(device, candidate, before["version"])
        changed = True
        require(scheduled.get("active") is True and scheduled.get("source") == "schedule"
                and scheduled.get("dim_light_requested") is True,
                "scheduled_dnd_not_active")
        led = wait_for(lambda: device.control({"action": "capability-status"}),
                       lambda value: value.get("status_led", {}).get("confirmed") is True
                       and value["status_led"].get("confirmed_state") == "listening"
                       and value["status_led"].get("led0") == 0
                       and value["status_led"].get("led1") == 1,
                       "scheduled_dnd_led_not_confirmed")

        device.adb("shell", "am", "stopservice", "-n", admin.SERVICE)
        service_restarted = True
        restarted_status = wait_for(device.start_control,
                                    lambda value: value.get("status") == "listening",
                                    "service_restart_not_recovered", 40)
        restarted = policy(restarted_status)
        require(restarted.get("version") == scheduled["version"]
                and restarted.get("active") is True and restarted.get("source") == "schedule",
                "scheduled_dnd_not_persistent")
        restarted_led = wait_for(lambda: device.control({"action": "capability-status"}),
                                 lambda value: value.get("status_led", {}).get("confirmed") is True
                                 and value["status_led"].get("led0") == 0
                                 and value["status_led"].get("led1") == 1,
                                 "restarted_dnd_led_not_confirmed")
        return {
            "status": "pass", "scenario": "dnd_cross_midnight_led_service_restart",
            "schedule": {"start_hour": candidate["start_hour"],
                         "start_minute": candidate["start_minute"],
                         "end_hour": candidate["end_hour"],
                         "end_minute": candidate["end_minute"]},
            "source_before_restart": scheduled["source"],
            "source_after_restart": restarted["source"],
            "version_persisted": restarted["version"] == scheduled["version"],
            "led_before_restart": {"led0": led["status_led"]["led0"],
                                   "led1": led["status_led"]["led1"]},
            "led_after_restart": {"led0": restarted_led["status_led"]["led0"],
                                  "led1": restarted_led["status_led"]["led1"]},
            "credentials_saved": False,
        }
    finally:
        if changed:
            if service_restarted:
                device.start_control()
            latest = policy(device.control({"action": "dnd-status"}))
            restored = set_policy(device, before, latest["version"])
            require(all(restored.get(key) == before.get(key) for key in (
                "manual", "schedule_enabled", "start_hour", "start_minute",
                "end_hour", "end_minute", "alarms_allowed")),
                "original_dnd_policy_not_restored")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("serial")
    parser.add_argument("--confirm-device", required=True, choices=("r1-sample01",))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    device = admin.Device(args.serial)
    device.verify()
    result = validate(device)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"status": "failed", "failure": str(error)}, ensure_ascii=False))
        raise SystemExit(1)
