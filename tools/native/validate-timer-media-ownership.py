#!/usr/bin/env python3
"""Validate standard timer/media conditional resume and user-stop suppression."""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import time

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


admin = load("native_admin", "manage-r1-native.py")
common = load("announcement_timer_validation", "validate-announcement-timers.py")
sync = load("alarm_sync_validation", "validate-alarm-sync.py")


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


def wait_state(device, predicate, failure, timeout=30, pause=time.sleep):
    return common.wait_for(lambda: device.control({"action": "status"}), predicate,
                           failure, timeout=timeout, pause=pause)


def wait_timer_ringing(device, before, timeout=90, pause=time.sleep):
    return common.wait_for(
        lambda: device.control({"action": "timer-status"}),
        lambda value: (value.get("ringing_count", 0) > before.get("ringing_count", 0)
                       and value.get("alarm_active") is True),
        "timer_alarm_not_observed", timeout=timeout, pause=pause)


def start_timer(ha, device_id, text):
    result = ha.conversation(text, device_id)
    require(isinstance(result, dict), "timer_start_response_invalid")


def stop_timer(device, before):
    stopped = device.control({"action": "timer-stop"})
    require(stopped.get("ringing_count") == 0
            and stopped.get("alarm_active") is False
            and stopped.get("local_stops", 0) > before.get("local_stops", 0),
            "timer_stop_not_confirmed")
    return stopped


def validate(device, ha, media_entity_id, media_url, device_id,
             start_text, cancel_text, pause=time.sleep):
    initial = device.start_control()
    before = audio(initial)
    timer_before = device.control({"action": "timer-status"})
    require(initial.get("status") == "listening" and initial.get("audio_opened") is True
            and initial.get("audio_blocked") is False
            and initial.get("factory_isolation") == "packages_hidden"
            and initial.get("last_error") is None, "device_not_ready")
    require(before.get("media_state") == "idle"
            and not before.get("announcement_active")
            and before.get("timers", {}).get("ringing_count") == 0,
            "audio_owner_not_idle")
    require(timer_before.get("active_count", 0) == 0
            and timer_before.get("ringing_count", 0) == 0,
            "timer_baseline_not_idle")
    failures_before = before.get("media_failures", 0)
    rejected_before = before.get("media_rejected", 0)
    try:
        media_command(ha, media_entity_id, "play_media", media_content_id=media_url,
                      media_content_type="music")
        playing = wait_state(device, lambda state: audio(state).get("media_state") == "playing",
                             "media_play_not_confirmed")

        start_timer(ha, device_id, start_text)
        ringing = wait_timer_ringing(device, timer_before)
        paused = wait_state(device, lambda state: audio(state).get("media_state") == "paused",
                            "timer_media_interruption_not_confirmed")
        stopped = stop_timer(device, timer_before)
        resumed = wait_state(device, lambda state: audio(state).get("media_state") == "playing",
                             "media_not_resumed_after_timer", 20, pause)
        start_timer(ha, device_id, start_text)
        ringing_two = wait_timer_ringing(device, stopped)
        wait_state(device, lambda state: audio(state).get("media_state") == "paused",
                   "second_timer_media_interruption_not_confirmed")
        media_command(ha, media_entity_id, "media_stop")
        idle = wait_state(device, lambda state: audio(state).get("media_state") == "idle",
                          "user_media_stop_not_confirmed", 15, pause)
        stopped_two = stop_timer(device, stopped)
        latest = idle
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            latest = device.control({"action": "status"})
            require(audio(latest).get("media_state") == "idle",
                    "user_stopped_media_resumed")
            pause(.2)
        final = audio(latest)
        require(final.get("media_failures", 0) == failures_before
                and final.get("media_rejected", 0) == rejected_before,
                "media_error_counter_changed")
        return {
            "status": "pass", "scenario": "timer_media_ownership",
            "initial_media_playing": audio(playing).get("media_state") == "playing",
            "first_timer_paused_media": audio(paused).get("media_state") == "paused",
            "first_timer_ringing": ringing.get("alarm_active") is True,
            "media_resumed_after_timer_stop": audio(resumed).get("media_state") == "playing",
            "second_timer_ringing": ringing_two.get("alarm_active") is True,
            "user_stop_during_timer_confirmed": True,
            "media_remained_idle_after_timer_stop": final.get("media_state") == "idle",
            "timer_stops": stopped_two.get("local_stops", 0) - timer_before.get("local_stops", 0),
            "media_failures_delta": 0, "media_rejected_delta": 0,
            "media_url_saved": False, "credentials_saved": False,
        }
    finally:
        try:
            media_command(ha, media_entity_id, "media_stop")
        except Exception:
            pass
        try:
            device.control({"action": "timer-stop"})
            ha.conversation(cancel_text, device_id)
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("serial")
    parser.add_argument("--confirm-device", required=True, choices=("r1-sample01",))
    parser.add_argument("--ha-url", required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--ha-device-id", required=True)
    parser.add_argument("--media-entity-id", required=True)
    parser.add_argument("--media-url", required=True)
    parser.add_argument("--start-text", required=True)
    parser.add_argument("--cancel-text", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"media_player\.[a-z0-9_]+", args.media_entity_id):
        parser.error("--media-entity-id is invalid")
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", args.ha_device_id):
        parser.error("--ha-device-id is invalid")
    if not args.start_text or not args.cancel_text:
        parser.error("timer texts are required")
    parsed = __import__("urllib.parse").parse.urlsplit(args.media_url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname \
            or parsed.username or parsed.password or parsed.query or parsed.fragment:
        parser.error("--media-url is invalid")
    token = sync.read_token(args.token_file)
    try:
        ha = common.HomeAssistant(args.ha_url, token)
        device = admin.Device(args.serial)
        device.verify()
        report = validate(device, ha, args.media_entity_id, args.media_url,
                          args.ha_device_id, args.start_text, args.cancel_text)
        common.write_report(report, args.output)
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
