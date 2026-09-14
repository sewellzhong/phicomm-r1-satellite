#!/usr/bin/env python3
"""Validate nested media -> announcement -> timer ownership on r1-sample01."""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import threading
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
timer_media = load("timer_media_validation", "validate-timer-media-ownership.py")


def require(condition, failure):
    if not condition:
        raise RuntimeError(failure)


def audio(state):
    value = state.get("audio")
    require(isinstance(value, dict), "device_audio_state_unavailable")
    return value


def wait_state(device, predicate, failure, timeout=30, pause=time.sleep):
    return common.wait_for(lambda: device.control({"action": "status"}), predicate,
                           failure, timeout=timeout, pause=pause)


def start_timer(ha, device, device_id, text, before, pause=time.sleep):
    ha.conversation(text, device_id)
    return common.wait_for(
        lambda: device.control({"action": "timer-status"}),
        lambda value: (value.get("started", 0) > before.get("started", 0)
                       and value.get("active_count", 0) > 0),
        "timer_start_event_not_observed", timeout=30, pause=pause)


def start_announcement(ha, device, entity_id, media_url, before, pause=time.sleep):
    outcome = {"error": None}
    def request():
        try:
            ha.announce(entity_id, media_url)
        except BaseException as error:
            outcome["error"] = error
    worker = threading.Thread(target=request, name="ha-announcement-request", daemon=True)
    worker.start()
    observed = wait_state(
        device,
        lambda state: (audio(state).get("announcement_active") is True
                       and audio(state).get("announcement_requests", 0)
                       > before.get("announcement_requests", 0)
                       and audio(state).get("media_state") == "paused"),
        "announcement_nested_owner_not_observed", 30, pause)
    return observed, worker, outcome


def finish_announcement_request(worker, outcome):
    worker.join(10)
    require(not worker.is_alive(), "ha_announcement_request_not_released")
    require(outcome.get("error") is None, "ha_announcement_request_failed")


def wait_timer_preemption(device, timer_before, announcement_before,
                          timeout=90, pause=time.sleep):
    return wait_state(
        device,
        lambda state: (
            audio(state).get("timers", {}).get("ringing_count", 0)
            > timer_before.get("ringing_count", 0)
            and audio(state).get("timers", {}).get("alarm_active") is True
            and audio(state).get("announcement_active") is False
            and audio(state).get("announcement_failures", 0)
            > announcement_before.get("announcement_failures", 0)
            and audio(state).get("media_state") == "paused"),
        "timer_did_not_preempt_announcement", timeout, pause)


def stop_timer(device, before):
    return timer_media.stop_timer(device, before)


def run_round(device, ha, media_entity_id, media_url, satellite_entity_id,
              device_id, start_text, user_stops_media, pause=time.sleep):
    initial = device.control({"action": "status"})
    initial_audio = audio(initial)
    timer_before = device.control({"action": "timer-status"})
    require(initial_audio.get("media_state") in ("idle", "playing"),
            "media_round_baseline_invalid")
    if initial_audio.get("media_state") == "idle":
        timer_media.media_command(ha, media_entity_id, "play_media",
                                  media_content_id=media_url,
                                  media_content_type="music")
        wait_state(device, lambda state: audio(state).get("media_state") == "playing",
                   "media_play_not_confirmed")
    start_timer(ha, device, device_id, start_text, timer_before, pause)
    before_announcement = audio(device.control({"action": "status"}))
    nested, announcement_worker, announcement_outcome = start_announcement(
        ha, device, satellite_entity_id, media_url, before_announcement, pause)
    preempted = wait_timer_preemption(device, timer_before, before_announcement,
                                      90, pause)
    finish_announcement_request(announcement_worker, announcement_outcome)
    if user_stops_media:
        timer_media.media_command(ha, media_entity_id, "media_stop")
        wait_state(device, lambda state: audio(state).get("media_state") == "idle",
                   "user_media_stop_not_confirmed", 15, pause)
    stopped = stop_timer(device, timer_before)
    target = "idle" if user_stops_media else "playing"
    released = wait_state(device, lambda state: audio(state).get("media_state") == target,
                          "nested_owner_release_not_confirmed", 20, pause)
    return {
        "announcement_paused_media": audio(nested).get("media_state") == "paused",
        "timer_preempted_announcement": audio(preempted).get("announcement_active") is False,
        "timer_rang": audio(preempted).get("timers", {}).get("alarm_active") is True,
        "announcement_failures_delta": (
            audio(preempted).get("announcement_failures", 0)
            - before_announcement.get("announcement_failures", 0)),
        "timer_stops_delta": (stopped.get("local_stops", 0)
                              - timer_before.get("local_stops", 0)),
        "final_media_state": audio(released).get("media_state"),
    }


def validate(device, ha, media_entity_id, media_url, satellite_entity_id,
             device_id, start_text, cancel_text, pause=time.sleep):
    initial = device.start_control()
    before = audio(initial)
    timer_before = device.control({"action": "timer-status"})
    require(initial.get("status") == "listening" and initial.get("audio_opened") is True
            and initial.get("audio_blocked") is False
            and initial.get("factory_isolation") == "packages_hidden"
            and initial.get("last_error") is None, "device_not_ready")
    require(before.get("media_state") == "idle"
            and before.get("announcement_active") is False
            and timer_before.get("active_count", 0) == 0
            and timer_before.get("ringing_count", 0) == 0,
            "audio_owner_not_idle")
    failures_before = before.get("media_failures", 0)
    rejected_before = before.get("media_rejected", 0)
    announcement_failures_before = before.get("announcement_failures", 0)
    try:
        resumed = run_round(device, ha, media_entity_id, media_url,
                            satellite_entity_id, device_id, start_text, False, pause)
        suppressed = run_round(device, ha, media_entity_id, media_url,
                               satellite_entity_id, device_id, start_text, True, pause)
        latest = device.control({"action": "status"})
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            latest = device.control({"action": "status"})
            require(audio(latest).get("media_state") == "idle",
                    "user_stopped_media_resumed")
            pause(.2)
        final = audio(latest)
        require(final.get("announcement_active") is False
                and final.get("timers", {}).get("ringing_count", 0) == 0,
                "nested_audio_owner_not_released")
        require(final.get("media_failures", 0) == failures_before
                and final.get("media_rejected", 0) == rejected_before,
                "media_error_counter_changed")
        require(final.get("announcement_failures", 0)
                == announcement_failures_before + 2,
                "announcement_preemption_count_invalid")
        return {
            "status": "pass", "scenario": "announcement_timer_media_ownership",
            "resume_round": resumed, "user_stop_round": suppressed,
            "announcement_preemptions": 2, "timer_stops": 2,
            "media_failures_delta": 0, "media_rejected_delta": 0,
            "media_remained_idle_after_release": True,
            "media_url_saved": False, "text_saved": False,
            "credentials_saved": False,
        }
    finally:
        try:
            timer_media.media_command(ha, media_entity_id, "media_stop")
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
    parser.add_argument("--satellite-entity-id", required=True)
    parser.add_argument("--media-url", required=True)
    parser.add_argument("--start-text", required=True)
    parser.add_argument("--cancel-text", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"media_player\.[a-z0-9_]+", args.media_entity_id):
        parser.error("--media-entity-id is invalid")
    if not re.fullmatch(r"assist_satellite\.[a-z0-9_]+", args.satellite_entity_id):
        parser.error("--satellite-entity-id is invalid")
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", args.ha_device_id):
        parser.error("--ha-device-id is invalid")
    parsed = __import__("urllib.parse").parse.urlsplit(args.media_url)
    if (parsed.scheme not in ("http", "https") or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        parser.error("--media-url is invalid")
    token = sync.read_token(args.token_file)
    try:
        ha = common.HomeAssistant(args.ha_url, token)
        device = admin.Device(args.serial)
        device.verify()
        report = validate(device, ha, args.media_entity_id, args.media_url,
                          args.satellite_entity_id, args.ha_device_id,
                          args.start_text, args.cancel_text)
        common.write_report(report, args.output)
        print(json.dumps(report, ensure_ascii=False))
    finally:
        token = ""


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"status": "failed", "failure": str(error)},
                         ensure_ascii=False), file=__import__("sys").stderr)
        raise SystemExit(1)
