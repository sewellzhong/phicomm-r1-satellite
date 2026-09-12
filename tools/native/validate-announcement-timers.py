#!/usr/bin/env python3
"""Drive bounded v103/v104 checks through real HA services and device state readback."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("native_admin", HERE / "manage-r1-native.py")
admin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(admin)


class HomeAssistant:
    """Minimal token-authenticated HA client. Token and response bodies are never reported."""
    def __init__(self, base_url, token, timeout=310):
        parsed = urllib.parse.urlsplit(base_url)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise RuntimeError("invalid_ha_url")
        if not token:
            raise RuntimeError("ha_token_required")
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def post(self, path, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path,
            data=body,
            headers={"Authorization": "Bearer " + self.token,
                     "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout,
                                        context=ssl.create_default_context()) as response:
                if response.status < 200 or response.status >= 300:
                    raise RuntimeError("ha_request_failed")
                payload = response.read(1024 * 1024)
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise RuntimeError("ha_request_failed") from error
        try:
            return json.loads(payload) if payload else None
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RuntimeError("ha_response_invalid") from error

    def announce(self, entity_id, media_id, preannounce_media_id=None):
        data = {"entity_id": entity_id, "media_id": media_id,
                "preannounce": preannounce_media_id is not None}
        if preannounce_media_id is not None:
            data["preannounce_media_id"] = preannounce_media_id
        return self.post("/api/services/assist_satellite/announce", data)

    def conversation(self, text, device_id):
        result = self.post("/api/conversation/process", {
            "text": text, "language": "zh-CN", "device_id": device_id,
        })
        if not isinstance(result, dict):
            raise RuntimeError("ha_conversation_response_invalid")
        response = result.get("response")
        if isinstance(response, dict) and response.get("response_type") == "error":
            raise RuntimeError("ha_conversation_failed")
        return result


def wait_for(read, predicate, failure, timeout, clock=time.monotonic, pause=time.sleep):
    deadline = clock() + timeout
    latest = None
    while clock() < deadline:
        latest = read()
        if predicate(latest):
            return latest
        pause(.1)
    raise RuntimeError(failure)


def require_idle_audio(state):
    audio = state.get("audio")
    if state.get("status") != "listening" or not isinstance(audio, dict):
        raise RuntimeError("device_not_idle")
    if audio.get("announcement_active"):
        raise RuntimeError("announcement_already_active")
    timers = audio.get("timers")
    if not isinstance(timers, dict) or timers.get("ringing_count") != 0:
        raise RuntimeError("timer_state_not_idle")
    return audio


def validate_announcement(device, ha, entity_id, media_id, preannounce_media_id=None,
                          timeout=310):
    before_state = device.start_control()
    before = require_idle_audio(before_state)
    expected_segments = 2 if preannounce_media_id is not None else 1
    ha.announce(entity_id, media_id, preannounce_media_id)

    def completed(state):
        audio = state.get("audio") or {}
        return (audio.get("announcement_requests", 0) == before.get("announcement_requests", 0) + 1
                and audio.get("announcement_completed", 0) == before.get("announcement_completed", 0) + 1
                and not audio.get("announcement_active", True))

    after_state = wait_for(lambda: device.control({"action": "status"}), completed,
                           "announcement_validation_timeout", timeout)
    after = after_state["audio"]
    if after.get("announcement_failures", 0) != before.get("announcement_failures", 0):
        raise RuntimeError("announcement_failed")
    if (after.get("announcement_segments_started", 0)
            - before.get("announcement_segments_started", 0) != expected_segments
            or after.get("announcement_segments_completed", 0)
            - before.get("announcement_segments_completed", 0) != expected_segments):
        raise RuntimeError("announcement_segment_sequence_unproven")
    first = after.get("playback_first_write_ms", 0)
    drained = after.get("playback_drained_ms", 0)
    released = after.get("playback_released_ms", 0)
    if first <= before.get("playback_first_write_ms", 0) or not first <= drained <= released:
        raise RuntimeError("announcement_playback_lifecycle_unproven")
    return {
        "scenario": "announcement", "protocol": "ha_assist_satellite_service",
        "requests_delta": 1, "completed_delta": 1, "failures_delta": 0,
        "segments_started_delta": expected_segments,
        "segments_completed_delta": expected_segments,
        "playback": {"first_write_ms": first, "drained_ms": drained,
                     "released_ms": released},
        "media_saved": False, "credentials_saved": False,
    }


def validate_timer_expiry(device, ha, device_id, start_text, cancel_text,
                          timeout=90, clock=time.monotonic, pause=time.sleep):
    device.start_control()
    before = device.control({"action": "timer-status"})
    if before.get("active_count") != 0 or before.get("ringing_count") != 0:
        raise RuntimeError("existing_timer_state_refused")
    try:
        ha.conversation(start_text, device_id)
        observed = wait_for(
            lambda: device.control({"action": "timer-status"}),
            lambda value: (value.get("started", 0) > before.get("started", 0)
                           and (value.get("active_count", 0) > 0
                                or value.get("ringing_count", 0) > 0)),
            "timer_start_event_not_observed", min(timeout, 30), clock, pause)
        ringing = wait_for(
            lambda: device.control({"action": "timer-status"}),
            lambda value: value.get("ringing_count", 0) > 0 and value.get("alarm_active") is True,
            "timer_alarm_not_observed", timeout, clock, pause)
        stopped = device.control({"action": "timer-stop"})
        if (stopped.get("ringing_count") != 0 or stopped.get("alarm_active") is not False
                or stopped.get("local_stops", 0) <= before.get("local_stops", 0)):
            raise RuntimeError("timer_stop_not_confirmed")
        if ringing.get("local_finished", 0) <= before.get("local_finished", 0) \
                and ringing.get("finished", 0) <= before.get("finished", 0):
            raise RuntimeError("timer_expiry_source_unproven")
        return {
            "scenario": "timer_expiry", "protocol": "ha_conversation_timer_event",
            "started_delta": observed.get("started", 0) - before.get("started", 0),
            "finished_delta": ringing.get("finished", 0) - before.get("finished", 0),
            "local_finished_delta": ringing.get("local_finished", 0) - before.get("local_finished", 0),
            "local_stops_delta": stopped.get("local_stops", 0) - before.get("local_stops", 0),
            "alarm_started": True, "alarm_stopped": True,
            "text_saved": False, "credentials_saved": False,
        }
    except BaseException:
        try:
            device.control({"action": "timer-stop"})
            ha.conversation(cancel_text, device_id)
        except Exception:
            pass
        raise


def write_report(report, output):
    report = {"schema": 1, "device": "r1-sample01",
              "recorded_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **report}
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if output is None:
        print(encoded, end="")
        return
    destination = output.resolve()
    evidence_root = (ROOT / "test-results").resolve()
    if evidence_root not in destination.parents:
        raise RuntimeError("evidence_must_be_under_test_results")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8") as stream:
        stream.write(encoded)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("serial")
    parser.add_argument("--confirm-device", required=True, choices=["r1-sample01"])
    parser.add_argument("--ha-url", required=True)
    parser.add_argument("--token-env", default="R1_HA_TOKEN")
    parser.add_argument("--output", type=Path)
    subparsers = parser.add_subparsers(dest="scenario", required=True)
    announcement = subparsers.add_parser("announcement")
    announcement.add_argument("--entity-id", required=True)
    announcement.add_argument("--media-id", required=True)
    announcement.add_argument("--preannounce-media-id")
    announcement.add_argument("--timeout", type=int, default=310)
    timer = subparsers.add_parser("timer-expiry")
    timer.add_argument("--ha-device-id", required=True)
    timer.add_argument("--start-text", required=True)
    timer.add_argument("--cancel-text", required=True)
    timer.add_argument("--timeout", type=int, default=90)
    args = parser.parse_args()

    if not re.fullmatch(r"assist_satellite\.[a-z0-9_]+", getattr(args, "entity_id", "assist_satellite.placeholder")):
        parser.error("--entity-id must name an assist_satellite entity")
    if hasattr(args, "ha_device_id") and not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", args.ha_device_id):
        parser.error("--ha-device-id is invalid")
    token = os.environ.get(args.token_env, "")
    try:
        ha = HomeAssistant(args.ha_url, token)
        device = admin.Device(args.serial)
        device.verify()
        if args.scenario == "announcement":
            report = validate_announcement(device, ha, args.entity_id, args.media_id,
                                           args.preannounce_media_id, args.timeout)
        else:
            report = validate_timer_expiry(device, ha, args.ha_device_id, args.start_text,
                                           args.cancel_text, args.timeout)
        write_report(report, args.output)
    finally:
        token = ""


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("Native feature validation failed: " + str(error), file=__import__("sys").stderr)
        raise SystemExit(1)
