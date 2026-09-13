#!/usr/bin/env python3
"""Validate alarm/media ownership: conditional resume and user-stop suppression."""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import time
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


admin = load("native_admin", "manage-r1-native.py")
sync = load("alarm_sync_validation", "validate-alarm-sync.py")
runtime = load("alarm_runtime_validation", "validate-alarm-runtime.py")


def require(condition, failure):
    if not condition:
        raise RuntimeError(failure)


def audio(state):
    value = state.get("audio")
    require(isinstance(value, dict), "device_audio_state_unavailable")
    return value


def media_command(ha, entity_id, command, **values):
    return ha.post("/api/services/media_player/" + command,
                   {"entity_id": entity_id, **values})


def wait_state(device, predicate, failure, timeout=30):
    return sync.wait_for(lambda: device.control({"action": "status"}), predicate,
                         failure, timeout=timeout, pause=time.sleep)


def create_due_alarm(device, alarm_id, name, minutes):
    state = sync.device_alarms(device)
    status = device.control({"action": "status"})
    policy = runtime.dnd(status)
    require(policy.get("clock_trusted") is True, "alarm_clock_not_trusted")
    due = runtime.next_due(policy["time_zone"], minutes)
    runtime.put_alarm(device, alarm_id, name, due, state["version"])
    return due, state


def wait_interruption(device, due, fires_before):
    timeout = max(1, int(due.timestamp() - time.time()) + 90)
    def interrupted(value):
        alarms = sync.device_alarms(device)
        return (alarms.get("ringing_count") == 1
                and alarms.get("fires", 0) == fires_before + 1
                and audio(value).get("media_state") == "paused")
    return wait_state(
        device, interrupted,
        "alarm_media_interruption_not_confirmed", timeout)


def delete_alarm(device, alarm_id):
    current = sync.device_alarms(device)
    if any(item.get("id") == alarm_id for item in current.get("alarms", [])):
        device.control({"action": "alarm-delete", "id": alarm_id,
                        "expected_version": current["version"]})


def validate(device, ha, media_entity_id, media_url, test_ids):
    initial = device.start_control()
    initial_audio = audio(initial)
    initial_alarms = sync.device_alarms(device)
    initial_dnd = runtime.dnd(initial)
    require(initial.get("status") == "listening" and initial.get("audio_opened") is True
            and initial.get("audio_blocked") is False
            and initial.get("factory_isolation") == "packages_hidden"
            and initial.get("last_error") is None, "device_not_ready")
    require(initial_alarms.get("alarm_count") == 0
            and initial_alarms.get("ringing_count") == 0, "alarm_baseline_not_empty")
    require(initial_audio.get("media_state") == "idle"
            and not initial_audio.get("announcement_active")
            and initial_audio.get("timers", {}).get("ringing_count") == 0,
            "audio_owner_not_idle")
    require(initial_dnd.get("active") is False, "dnd_must_be_inactive")
    media_failures = initial_audio.get("media_failures", 0)
    media_rejected = initial_audio.get("media_rejected", 0)

    try:
        media_command(ha, media_entity_id, "play_media", media_content_id=media_url,
                      media_content_type="music")
        playing = wait_state(device, lambda value: audio(value).get("media_state") == "playing",
                             "media_play_not_confirmed", 30)

        first_due, first_before = create_due_alarm(device, test_ids[0],
                                                    "媒体恢复验证", 2)
        first_paused = wait_interruption(device, first_due, first_before.get("fires", 0))
        first_alarm = sync.device_alarms(device)
        require(first_alarm.get("ringer_active") is True, "alarm_ringer_not_active")
        stopped = device.control({"action": "alarm-stop", "id": test_ids[0]})
        require(stopped.get("ringing_count") == 0 and stopped.get("ringer_active") is False,
                "first_alarm_stop_not_confirmed")
        resumed = wait_state(device, lambda value: audio(value).get("media_state") == "playing",
                             "media_not_resumed_after_alarm", 20)
        delete_alarm(device, test_ids[0])

        second_due, second_before = create_due_alarm(device, test_ids[1],
                                                      "用户停止验证", 2)
        second_paused = wait_interruption(device, second_due, second_before.get("fires", 0))
        second_alarm = sync.device_alarms(device)
        require(second_alarm.get("ringer_active") is True, "second_alarm_ringer_not_active")
        media_command(ha, media_entity_id, "media_stop")
        wait_state(device, lambda value: audio(value).get("media_state") == "idle",
                   "user_media_stop_not_confirmed", 15)
        stopped_second = device.control({"action": "alarm-stop", "id": test_ids[1]})
        require(stopped_second.get("ringing_count") == 0
                and stopped_second.get("ringer_active") is False,
                "second_alarm_stop_not_confirmed")
        stable_deadline = time.monotonic() + 5
        latest = None
        while time.monotonic() < stable_deadline:
            latest = device.control({"action": "status"})
            require(audio(latest).get("media_state") == "idle",
                    "user_stopped_media_resumed")
            time.sleep(.2)
        delete_alarm(device, test_ids[1])

        final = device.control({"action": "status"})
        final_audio = audio(final)
        final_alarms = sync.device_alarms(device)
        require(final_alarms.get("alarm_count") == 0
                and final_alarms.get("ringing_count") == 0,
                "alarm_cleanup_failed")
        require(final_audio.get("media_state") == "idle"
                and final_audio.get("media_failures", 0) == media_failures
                and final_audio.get("media_rejected", 0) == media_rejected,
                "media_final_state_invalid")
        return {"status": "pass", "scenario": "alarm_media_ownership",
                "initial_media_playing": audio(playing).get("media_state") == "playing",
                "first_alarm_paused_media": audio(first_paused).get("media_state") == "paused",
                "first_alarm_ringer_active": True,
                "media_resumed_after_alarm_stop": audio(resumed).get("media_state") == "playing",
                "second_alarm_paused_media": audio(second_paused).get("media_state") == "paused",
                "user_stop_during_alarm_confirmed": True,
                "media_remained_idle_after_alarm_stop": audio(latest).get("media_state") == "idle",
                "media_failures_delta": 0, "media_rejected_delta": 0,
                "alarm_baseline_restored": True, "media_url_saved": False,
                "credentials_saved": False}
    finally:
        try:
            media_command(ha, media_entity_id, "media_stop")
        except Exception:
            pass
        try:
            current = sync.device_alarms(device)
            if current.get("ringing_count", 0):
                device.control({"action": "alarm-stop"})
            for alarm_id in test_ids:
                delete_alarm(device, alarm_id)
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("serial")
    parser.add_argument("--confirm-device", required=True, choices=("r1-sample01",))
    parser.add_argument("--ha-url", required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--media-entity-id", required=True)
    parser.add_argument("--media-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"media_player\.[a-z0-9_]+", args.media_entity_id):
        parser.error("--media-entity-id is invalid")
    parsed = __import__("urllib.parse").parse.urlsplit(args.media_url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname \
            or parsed.username or parsed.password or parsed.query or parsed.fragment:
        parser.error("--media-url is invalid")
    token = sync.read_token(args.token_file)
    try:
        ha = sync.HomeAssistant(args.ha_url, token)
        device = admin.Device(args.serial)
        device.verify()
        prefix = "r1-validation-owner-" + uuid4().hex[:12] + "-"
        report = validate(device, ha, args.media_entity_id, args.media_url,
                          [prefix + "resume", prefix + "stop"])
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
