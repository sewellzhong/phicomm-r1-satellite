#!/usr/bin/env python3
"""Validate fixed-PCM voice/media ownership and conditional media resume."""
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
    return sync.wait_for(lambda: device.control({"action": "status"}), predicate,
                         failure, timeout=timeout, pause=pause)


def start_media(device, ha, entity_id, media_url):
    media_command(ha, entity_id, "play_media", media_content_id=media_url,
                  media_content_type="music")
    return wait_state(device, lambda value: audio(value).get("media_state") == "playing",
                      "media_play_not_confirmed", 30)


def start_voice(device, runs_before):
    started = device.control({"action": "fixed-pcm-start"})
    require(started.get("status") == "injecting_fixed_pcm"
            and audio(started).get("fixed_pcm_runs") == runs_before + 1
            and audio(started).get("media_state") == "paused",
            "voice_media_interruption_not_confirmed")
    return started


def cancel_voice(device, cancels_before):
    device.control({"action": "fixed-pcm-cancel"})
    return wait_state(
        device,
        lambda value: (value.get("status") == "listening"
                       and audio(value).get("fixed_pcm_cancels") == cancels_before + 1),
        "voice_cancel_release_not_confirmed", 15)


def validate(device, ha, media_entity_id, media_url, pause=time.sleep):
    initial = device.start_control()
    before = audio(initial)
    timers = before.get("timers") or {}
    require(initial.get("status") == "listening" and initial.get("audio_opened") is True
            and initial.get("audio_blocked") is False
            and initial.get("factory_isolation") == "packages_hidden"
            and initial.get("last_error") is None, "device_not_ready")
    require(before.get("media_state") == "idle"
            and not before.get("announcement_active")
            and timers.get("active_count") == 0 and timers.get("ringing_count") == 0,
            "audio_owner_not_idle")
    runs_before = before.get("fixed_pcm_runs", 0)
    cancels_before = before.get("fixed_pcm_cancels", 0)
    failures_before = before.get("media_failures", 0)
    rejected_before = before.get("media_rejected", 0)

    try:
        playing = start_media(device, ha, media_entity_id, media_url)
        first_paused = start_voice(device, runs_before)
        first_released = cancel_voice(device, cancels_before)
        resumed = wait_state(device, lambda value: audio(value).get("media_state") == "playing",
                             "media_not_resumed_after_voice_cancel", 20)

        second_paused = start_voice(device, runs_before + 1)
        media_command(ha, media_entity_id, "media_stop")
        wait_state(device, lambda value: audio(value).get("media_state") == "idle",
                   "user_media_stop_not_confirmed", 15)
        second_released = cancel_voice(device, cancels_before + 1)
        deadline = time.monotonic() + 5
        latest = second_released
        while time.monotonic() < deadline:
            latest = device.control({"action": "status"})
            require(audio(latest).get("media_state") == "idle",
                    "user_stopped_media_resumed")
            pause(.2)

        final_audio = audio(latest)
        require(final_audio.get("fixed_pcm_runs") == runs_before + 2
                and final_audio.get("fixed_pcm_cancels") == cancels_before + 2,
                "voice_counters_invalid")
        require(final_audio.get("media_failures", 0) == failures_before
                and final_audio.get("media_rejected", 0) == rejected_before,
                "media_error_counter_changed")
        return {
            "status": "pass", "scenario": "voice_media_ownership",
            "initial_media_playing": audio(playing).get("media_state") == "playing",
            "first_voice_paused_media": audio(first_paused).get("media_state") == "paused",
            "first_voice_cancel_released": first_released.get("status") == "listening",
            "media_resumed_after_voice_cancel": audio(resumed).get("media_state") == "playing",
            "second_voice_paused_media": audio(second_paused).get("media_state") == "paused",
            "user_stop_during_voice_confirmed": True,
            "media_remained_idle_after_voice_cancel": final_audio.get("media_state") == "idle",
            "fixed_pcm_runs_delta": 2, "fixed_pcm_cancels_delta": 2,
            "media_failures_delta": 0, "media_rejected_delta": 0,
            "pcm_frames_sent": 0, "media_url_saved": False,
            "credentials_saved": False,
        }
    finally:
        try:
            current = device.control({"action": "status"})
            if current.get("status") in ("injecting_fixed_pcm", "cancelling_fixed_pcm"):
                device.control({"action": "fixed-pcm-cancel"})
        except Exception:
            pass
        try:
            media_command(ha, media_entity_id, "media_stop")
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
        report = validate(device, ha, args.media_entity_id, args.media_url)
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
