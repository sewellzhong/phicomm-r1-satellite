#!/usr/bin/env python3
"""Drive bounded v110/v111 DND and media checks with HA and R1 state readback."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
import os
from pathlib import Path
import re
import time


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "announcement_validation", HERE / "validate-announcement-timers.py"
)
common = importlib.util.module_from_spec(spec)
spec.loader.exec_module(common)
admin = common.admin


def audio(state):
    value = state.get("audio")
    if state.get("status") != "listening" or not isinstance(value, dict):
        raise RuntimeError("device_not_idle")
    return value


def dnd(state):
    value = state.get("do_not_disturb")
    if not isinstance(value, dict) or value.get("schema") != 1:
        raise RuntimeError("dnd_state_unavailable")
    return value


def wait_device(device, predicate, failure, timeout=15):
    return common.wait_for(
        lambda: device.control({"action": "status"}), predicate, failure, timeout
    )


def service(ha, domain, name, data, expected_failure=False):
    try:
        return ha.post("/api/services/%s/%s" % (domain, name), data)
    except RuntimeError as error:
        if expected_failure and str(error) == "ha_request_failed":
            return None
        raise


def media_command(ha, entity_id, command, **values):
    return service(ha, "media_player", command, {"entity_id": entity_id, **values})


def dnd_values(value, manual=None):
    return {
        "manual": value["manual"] if manual is None else manual,
        "schedule_enabled": value["schedule_enabled"],
        "start_hour": value["start_hour"], "start_minute": value["start_minute"],
        "end_hour": value["end_hour"], "end_minute": value["end_minute"],
        "alarms_allowed": value["alarms_allowed"],
        "expected_version": value["version"],
    }


def validate_media_lifecycle(device, ha, entity_id, media_url, failure_url,
                             volume=.37, timeout=30):
    before_state = device.start_control()
    before = audio(before_state)
    if before.get("media_state") != "idle" or before.get("announcement_active"):
        raise RuntimeError("media_state_not_idle")
    timers = before.get("timers") or {}
    if timers.get("ringing_count", 0):
        raise RuntimeError("audio_owner_not_idle")
    original_volume = before_state.get("volume_percent")
    if type(original_volume) is not int or not 0 <= original_volume <= 100:
        raise RuntimeError("volume_state_unavailable")
    base_requests = before.get("media_requests", 0)
    base_rejected = before.get("media_rejected", 0)
    base_failures = before.get("media_failures", 0)
    changed_volume = False
    try:
        media_command(ha, entity_id, "play_media", media_content_id=media_url,
                      media_content_type="music")
        playing = wait_device(device, lambda state: audio(state).get("media_state") == "playing",
                              "media_play_not_confirmed", timeout)
        media_command(ha, entity_id, "media_pause")
        wait_device(device, lambda state: audio(state).get("media_state") == "paused",
                    "media_pause_not_confirmed")
        media_command(ha, entity_id, "media_play")
        wait_device(device, lambda state: audio(state).get("media_state") == "playing",
                    "media_resume_not_confirmed")
        media_command(ha, entity_id, "volume_set", volume_level=volume)
        expected_percent = round(volume * 100)
        wait_device(device, lambda state: state.get("volume_percent") == expected_percent,
                    "media_volume_not_confirmed")
        changed_volume = True
        media_command(ha, entity_id, "media_stop")
        stopped = wait_device(device, lambda state: audio(state).get("media_state") == "idle",
                              "media_stop_not_confirmed")
        after = audio(stopped)
        if after.get("media_rejected", 0) != base_rejected:
            raise RuntimeError("media_command_rejected")
        if after.get("media_failures", 0) != base_failures:
            raise RuntimeError("media_lifecycle_failed")
        if after.get("media_requests", 0) - base_requests < 5:
            raise RuntimeError("media_command_sequence_unproven")

        media_command(ha, entity_id, "play_media", media_content_id=failure_url,
                      media_content_type="music")
        failed = wait_device(
            device,
            lambda state: (audio(state).get("media_state") in ("failed", "idle")
                           and audio(state).get("media_failures", 0) > base_failures),
            "media_failure_not_confirmed", timeout,
        )
        failed_audio = audio(failed)
        if not re.fullmatch(r"media_[a-z0-9_]{1,64}",
                            str(failed_audio.get("media_last_failure", ""))):
            raise RuntimeError("media_failure_code_invalid")
        return {
            "scenario": "media_lifecycle", "protocol": "ha_media_player_service",
            "states": ["idle", "playing", "paused", "playing", "idle", "failed"],
            "requests_delta": failed_audio.get("media_requests", 0) - base_requests,
            "rejected_delta": failed_audio.get("media_rejected", 0) - base_rejected,
            "failures_delta": failed_audio.get("media_failures", 0) - base_failures,
            "volume_confirmed_percent": expected_percent,
            "real_backend_started": audio(playing).get("media_state") == "playing",
            "urls_saved": False, "credentials_saved": False,
        }
    finally:
        try:
            media_command(ha, entity_id, "media_stop")
            if changed_volume or original_volume != round(volume * 100):
                media_command(ha, entity_id, "volume_set",
                              volume_level=original_volume / 100)
        except Exception:
            pass


def validate_media_announcement(device, ha, media_entity_id, satellite_entity_id,
                                media_url, announcement_url, timeout=310):
    before_state = device.start_control()
    before = audio(before_state)
    if before.get("media_state") != "idle" or before.get("announcement_active"):
        raise RuntimeError("media_state_not_idle")
    media_command(ha, media_entity_id, "play_media", media_content_id=media_url,
                  media_content_type="music")
    try:
        wait_device(device, lambda state: audio(state).get("media_state") == "playing",
                    "media_play_not_confirmed", 30)
        with ThreadPoolExecutor(max_workers=1) as executor:
            request = executor.submit(ha.announce, satellite_entity_id, announcement_url)
            interrupted = wait_device(
                device,
                lambda state: (audio(state).get("announcement_active") is True
                               and audio(state).get("media_state") == "paused"),
                "media_announcement_interruption_not_confirmed", min(timeout, 30),
            )
            request.result(timeout=timeout)
        resumed = wait_device(
            device,
            lambda state: (audio(state).get("announcement_active") is False
                           and audio(state).get("media_state") == "playing"),
            "media_announcement_resume_not_confirmed", 15,
        )
        if (audio(resumed).get("announcement_completed", 0)
                <= before.get("announcement_completed", 0)):
            raise RuntimeError("announcement_completion_unproven")
        return {
            "scenario": "media_announcement", "protocol": "ha_media_and_announce_services",
            "media_paused_during_announcement": audio(interrupted)["media_state"] == "paused",
            "media_resumed_after_announcement": True,
            "announcement_completed_delta": (audio(resumed).get("announcement_completed", 0)
                                               - before.get("announcement_completed", 0)),
            "urls_saved": False, "credentials_saved": False,
        }
    finally:
        try: media_command(ha, media_entity_id, "media_stop")
        except Exception: pass


def validate_dnd_announcement(device, ha, dnd_entity_id, satellite_entity_id,
                              announcement_url, timeout=30):
    before_state = device.start_control()
    before_audio = audio(before_state)
    before = dnd(before_state)
    if before.get("active") or before.get("manual") or before.get("restore_failed"):
        raise RuntimeError("dnd_preexisting_or_invalid")
    if before_audio.get("announcement_active"):
        raise RuntimeError("announcement_already_active")
    changed = False
    try:
        service(ha, "r1_input_guard", "dnd_set",
                {"entity_id": dnd_entity_id, **dnd_values(before, manual=True)})
        # HA's blocking entity service has already confirmed the write. From this
        # point every failure path must restore, even if the first ADB readback times out.
        changed = True
        active_state = wait_device(
            device,
            lambda state: dnd(state).get("manual") is True and dnd(state).get("active") is True,
            "dnd_enable_not_confirmed",
        )
        active = dnd(active_state)
        service(ha, "assist_satellite", "announce", {
            "entity_id": satellite_entity_id, "media_id": announcement_url,
            "preannounce": False,
        }, expected_failure=True)
        suppressed_state = wait_device(
            device,
            lambda state: (dnd(state).get("suppressed_announcements", 0)
                           > before.get("suppressed_announcements", 0)),
            "dnd_announcement_suppression_not_confirmed", timeout,
        )
        suppressed_audio = audio(suppressed_state)
        if suppressed_audio.get("announcement_segments_started", 0) \
                != before_audio.get("announcement_segments_started", 0):
            raise RuntimeError("dnd_opened_announcement_media")
        if suppressed_audio.get("announcement_requests", 0) \
                <= before_audio.get("announcement_requests", 0):
            raise RuntimeError("dnd_announcement_request_unproven")
        service(ha, "r1_input_guard", "dnd_set", {
            "entity_id": dnd_entity_id, **dnd_values(active, manual=False),
        })
        restored = wait_device(
            device,
            lambda state: (dnd(state).get("manual") is False
                           and dnd(state).get("active") == before["active"]),
            "dnd_restore_not_confirmed",
        )
        changed = False
        return {
            "scenario": "dnd_announcement", "protocol": "ha_dnd_and_announce_services",
            "manual_enable_confirmed": True, "announcement_suppressed": True,
            "segments_started_delta": 0,
            "suppressed_announcements_delta": (
                dnd(suppressed_state).get("suppressed_announcements", 0)
                - before.get("suppressed_announcements", 0)),
            "original_policy_restored": dnd(restored).get("manual") == before["manual"],
            "dim_light_request_only": dnd(suppressed_state).get("dim_light_requested") is True,
            "urls_saved": False, "credentials_saved": False,
        }
    finally:
        if changed:
            try:
                latest = dnd(device.control({"action": "status"}))
                service(ha, "r1_input_guard", "dnd_set", {
                    "entity_id": dnd_entity_id,
                    **dnd_values({**before, "version": latest["version"]}),
                })
            except Exception:
                pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("serial")
    parser.add_argument("--confirm-device", required=True, choices=["r1-sample01"])
    parser.add_argument("--ha-url", required=True)
    parser.add_argument("--token-env", default="R1_HA_TOKEN")
    parser.add_argument("--output", type=Path)
    sub = parser.add_subparsers(dest="scenario", required=True)
    lifecycle = sub.add_parser("media-lifecycle")
    lifecycle.add_argument("--media-entity-id", required=True)
    lifecycle.add_argument("--media-url", required=True)
    lifecycle.add_argument("--failure-url", required=True)
    lifecycle.add_argument("--volume", type=float, default=.37)
    lifecycle.add_argument("--timeout", type=int, default=30)
    interruption = sub.add_parser("media-announcement")
    interruption.add_argument("--media-entity-id", required=True)
    interruption.add_argument("--satellite-entity-id", required=True)
    interruption.add_argument("--media-url", required=True)
    interruption.add_argument("--announcement-url", required=True)
    interruption.add_argument("--timeout", type=int, default=310)
    suppression = sub.add_parser("dnd-announcement")
    suppression.add_argument("--dnd-entity-id", required=True)
    suppression.add_argument("--satellite-entity-id", required=True)
    suppression.add_argument("--announcement-url", required=True)
    suppression.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()

    for name in ("media_entity_id", "satellite_entity_id", "dnd_entity_id"):
        value = getattr(args, name, None)
        domain = {"media_entity_id": "media_player", "satellite_entity_id": "assist_satellite",
                  "dnd_entity_id": "sensor"}[name]
        if value is not None and not re.fullmatch(domain + r"\.[a-z0-9_]+", value):
            parser.error("--%s is invalid" % name.replace("_", "-"))
    if hasattr(args, "volume") and not 0 <= args.volume <= 1:
        parser.error("--volume must be between 0 and 1")

    token = os.environ.get(args.token_env, "")
    try:
        ha = common.HomeAssistant(args.ha_url, token)
        device = admin.Device(args.serial)
        device.verify()
        if args.scenario == "media-lifecycle":
            result = validate_media_lifecycle(device, ha, args.media_entity_id,
                                              args.media_url, args.failure_url,
                                              args.volume, args.timeout)
        elif args.scenario == "media-announcement":
            result = validate_media_announcement(device, ha, args.media_entity_id,
                                                 args.satellite_entity_id, args.media_url,
                                                 args.announcement_url, args.timeout)
        else:
            result = validate_dnd_announcement(device, ha, args.dnd_entity_id,
                                               args.satellite_entity_id,
                                               args.announcement_url, args.timeout)
        common.write_report(result, args.output)
    finally:
        token = ""


if __name__ == "__main__":
    try: main()
    except Exception as error:
        print("Native DND/media validation failed: " + str(error),
              file=__import__("sys").stderr)
        raise SystemExit(1)
