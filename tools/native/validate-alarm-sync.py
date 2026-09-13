#!/usr/bin/env python3
"""Validate real HA/R1 alarm paging, offline pending state, and conflict locking."""
import argparse
import json
import os
from pathlib import Path
import re
import ssl
import stat
import time
import urllib.error
import urllib.parse
import urllib.request
from uuid import uuid4

import importlib.util


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("native_admin", HERE / "manage-r1-native.py")
admin = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(admin)

TEST_DATE = "2099-12-31"
TEST_COUNT = 5
MAX_ALARMS = 32


def require(condition, failure):
    if not condition:
        raise RuntimeError(failure)


def consume_token(path):
    path = Path(path)
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and not path.is_symlink(), "token_file_not_regular")
    require(info.st_uid == os.getuid(), "token_file_owner_invalid")
    require(stat.S_IMODE(info.st_mode) == 0o600, "token_file_mode_invalid")
    require(1 <= info.st_size <= 4096, "token_file_size_invalid")
    token = path.read_text(encoding="utf-8")
    require(token.endswith("\n") and token.count("\n") == 1, "token_file_format_invalid")
    token = token[:-1]
    require(1 <= len(token) <= 4095 and not any(char.isspace() for char in token),
            "token_file_format_invalid")
    path.unlink()
    return token


class HomeAssistant:
    def __init__(self, base_url, token, timeout=20):
        parsed = urllib.parse.urlsplit(base_url)
        require(parsed.scheme in ("http", "https") and parsed.hostname
                and not parsed.username and not parsed.password and not parsed.query
                and not parsed.fragment, "invalid_ha_url")
        require(bool(token), "ha_token_required")
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def request(self, method, path, data=None, expected_failure=False):
        encoded = None if data is None else json.dumps(
            data, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path, data=encoded, method=method,
            headers={"Authorization": "Bearer " + self.token,
                     "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout,
                                        context=ssl.create_default_context()) as response:
                require(not expected_failure, "ha_service_unexpected_success")
                payload = response.read(1024 * 1024 + 1)
                require(len(payload) <= 1024 * 1024, "ha_response_too_large")
        except urllib.error.HTTPError as error:
            if expected_failure and error.code == 500:
                error.close()
                return None
            error.close()
            raise RuntimeError("ha_request_failed") from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise RuntimeError("ha_request_failed") from error
        if not payload:
            return None
        try:
            return json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RuntimeError("ha_response_invalid") from error

    def get(self, path):
        return self.request("GET", path)

    def post(self, path, data, expected_failure=False):
        return self.request("POST", path, data, expected_failure)


def entity_attributes(value):
    require(isinstance(value, dict) and isinstance(value.get("attributes"), dict),
            "alarm_entity_state_invalid")
    attributes = value["attributes"]
    require(isinstance(attributes.get("alarms"), list)
            and isinstance(attributes.get("alarm_count"), int)
            and attributes["alarm_count"] == len(attributes["alarms"])
            and attributes.get("sync_status") in ("connecting", "synced", "offline",
                                                   "pending", "conflict")
            and isinstance(attributes.get("pending_changes"), list),
            "alarm_entity_state_invalid")
    return attributes


def discover(ha):
    states = ha.get("/api/states")
    require(isinstance(states, list), "ha_states_invalid")
    entities = []
    for state in states:
        entity_id = state.get("entity_id") if isinstance(state, dict) else None
        attributes = state.get("attributes") if isinstance(state, dict) else None
        if (isinstance(entity_id, str) and entity_id.startswith("sensor.")
                and isinstance(attributes, dict) and "alarm_count" in attributes
                and "alarms" in attributes and "pending_changes" in attributes
                and "sync_status" in attributes):
            entities.append(entity_id)
    require(len(entities) == 1, "alarm_entity_not_unique")

    services = ha.get("/api/services")
    require(isinstance(services, list), "ha_services_invalid")
    alarm_services = []
    for domain in services:
        if not isinstance(domain, dict) or domain.get("domain") != "esphome":
            continue
        available = domain.get("services")
        if isinstance(available, dict):
            alarm_services.extend(name for name in available if name.endswith("_alarm_sync"))
    require(len(alarm_services) == 1, "alarm_service_not_unique")
    return entities[0], alarm_services[0]


def get_entity(ha, entity_id):
    require(re.fullmatch(r"sensor\.[a-z0-9_]+", entity_id) is not None,
            "alarm_entity_id_invalid")
    return entity_attributes(ha.get("/api/states/" + entity_id))


def wait_for(read, predicate, failure, timeout=30, pause=time.sleep):
    deadline = time.monotonic() + timeout
    latest = None
    while time.monotonic() < deadline:
        latest = read()
        if predicate(latest):
            return latest
        pause(.2)
    raise RuntimeError(failure)


def editable(alarm):
    keys = ("id", "name", "date", "hour", "minute", "weekdays", "enabled",
            "snooze_minutes", "ringtone", "volume_percent")
    require(isinstance(alarm, dict) and all(key in alarm for key in keys),
            "alarm_shape_invalid")
    return {key: alarm[key] for key in keys}


def canonical(alarms):
    values = [editable(alarm) for alarm in alarms]
    require(len({alarm["id"] for alarm in values}) == len(values), "alarm_ids_not_unique")
    return sorted(values, key=lambda alarm: alarm["id"])


def entity_service(ha, name, entity_id, values=None, expected_failure=False):
    data = {"entity_id": entity_id}
    if values:
        data.update(values)
    return ha.post("/api/services/r1_input_guard/" + name, data, expected_failure)


def unwrap_service_response(value):
    if isinstance(value, dict) and "service_response" in value:
        value = value["service_response"]
    if isinstance(value, dict) and value.get("schema") == 2:
        return value
    if isinstance(value, dict) and len(value) == 1:
        nested = next(iter(value.values()))
        if isinstance(nested, dict) and nested.get("schema") == 2:
            return nested
    raise RuntimeError("alarm_service_response_invalid")


def alarm_page(ha, service, version=None, offset=0):
    require(re.fullmatch(r"[a-z][a-z0-9_]{0,63}_alarm_sync", service) is not None,
            "alarm_service_name_invalid")
    request_id = uuid4().hex
    request = {"request_id": request_id, "operation": "status", "page_offset": offset}
    if version is not None:
        request["expected_version"] = version
    response = unwrap_service_response(ha.post(
        "/api/services/esphome/" + service + "?return_response",
        {"request": json.dumps(request, separators=(",", ":"))},
    ))
    require(response.get("request_id") == request_id and response.get("operation") == "status"
            and isinstance(response.get("version"), int) and response["version"] >= 0
            and isinstance(response.get("alarms"), list) and len(response["alarms"]) <= 4
            and response.get("page_offset") == offset
            and isinstance(response.get("page_complete"), bool)
            and isinstance(response.get("alarm_count"), int),
            "alarm_page_invalid")
    require(response["alarm_count"] >= offset + len(response["alarms"])
            and response["page_complete"] == (
                offset + len(response["alarms"]) == response["alarm_count"]),
            "alarm_page_invalid")
    if version is not None:
        require(response["version"] == version, "alarm_page_version_changed")
    return response


def read_all_pages(ha, service):
    first = alarm_page(ha, service, offset=0)
    version = first["version"]
    pages = [first]
    alarms = list(first["alarms"])
    while not pages[-1]["page_complete"]:
        next_page = alarm_page(ha, service, version, len(alarms))
        require(next_page["page_offset"] == len(alarms), "alarm_page_offset_changed")
        alarms.extend(next_page["alarms"])
        pages.append(next_page)
    require(len(alarms) == first["alarm_count"]
            and len({alarm.get("id") for alarm in alarms}) == len(alarms),
            "alarm_page_set_invalid")
    return version, alarms, [page["page_offset"] for page in pages]


def device_alarms(device):
    value = device.control({"action": "alarm-status"})
    require(isinstance(value, dict) and value.get("schema") == 2
            and isinstance(value.get("version"), int) and isinstance(value.get("alarms"), list),
            "device_alarm_state_invalid")
    return value


def wait_device_ready(device, timeout=45):
    return wait_for(lambda: device.control({"action": "status"}),
                    lambda value: value.get("status") == "listening"
                    and value.get("audio_opened") is True
                    and value.get("audio_blocked") is False
                    and value.get("factory_isolation") == "packages_hidden"
                    and value.get("last_error") is None,
                    "device_restore_failed", timeout)


def test_alarm(alarm_id, index):
    return {"id": alarm_id, "name": "R1分页验证%d" % (index + 1),
            "date": TEST_DATE, "hour": 8 + index, "minute": index,
            "weekdays": 0, "enabled": False, "snooze_minutes": 10,
            "ringtone": "classic", "volume_percent": 100}


def validate(device, ha, entity_id, service, test_ids):
    before_status = device.start_control()
    require(before_status.get("status") == "listening"
            and before_status.get("audio_opened") is True
            and before_status.get("audio_blocked") is False,
            "device_not_ready")
    before_device = device_alarms(device)
    require(before_device.get("ringing_count") == 0 and not before_device.get("ringer_active"),
            "alarm_ringing_precondition")
    baseline = canonical(before_device["alarms"])
    baseline_ids = {alarm["id"] for alarm in baseline}
    require(len(baseline) <= MAX_ALARMS - TEST_COUNT, "alarm_capacity_insufficient")
    require(not baseline_ids.intersection(test_ids), "test_alarm_id_collision")
    initial_entity = get_entity(ha, entity_id)
    require(initial_entity["sync_status"] == "synced"
            and not initial_entity["pending_changes"]
            and canonical(initial_entity["alarms"]) == baseline,
            "ha_alarm_baseline_not_synced")

    created = []
    device_disabled = False
    try:
        for index, alarm_id in enumerate(test_ids):
            entity_service(ha, "alarm_put", entity_id, test_alarm(alarm_id, index))
            created.append(alarm_id)
        populated = wait_for(lambda: get_entity(ha, entity_id),
                             lambda value: value["sync_status"] == "synced"
                             and {alarm["id"] for alarm in value["alarms"]}.issuperset(test_ids),
                             "test_alarms_not_synced")
        require(populated["alarm_count"] == len(baseline) + TEST_COUNT,
                "test_alarm_count_invalid")

        page_version, paged, offsets = read_all_pages(ha, service)
        require(len(offsets) >= 2 and offsets[:2] == [0, 4], "alarm_pagination_not_exercised")
        require(canonical(paged) == canonical(populated["alarms"]),
                "noise_pages_do_not_match_ha")

        device.control({"action": "stop"})
        device.adb("shell", "am", "stopservice", "-n", admin.SERVICE)
        device_disabled = True
        try:
            entity_service(ha, "alarm_refresh", entity_id, expected_failure=True)
        except RuntimeError as error:
            if str(error) != "ha_service_unexpected_success":
                raise
        offline = wait_for(lambda: get_entity(ha, entity_id),
                           lambda value: value["sync_status"] == "offline",
                           "ha_alarm_offline_not_observed")
        require(not offline["pending_changes"], "unexpected_pending_before_write")

        entity_service(ha, "alarm_enable", entity_id,
                       {"id": test_ids[0], "enabled": True}, expected_failure=True)
        pending = wait_for(lambda: get_entity(ha, entity_id),
                           lambda value: value["sync_status"] == "pending"
                           and value.get("last_error") == "not_delivered"
                           and len(value["pending_changes"]) == 1,
                           "offline_pending_not_observed")
        pending_item = pending["pending_changes"][0]
        require(pending_item.get("id") == test_ids[0]
                and pending_item.get("blocked") is False
                and pending_item.get("desired", {}).get("enabled") is True,
                "offline_pending_invalid")

        device.start_control()
        local = device_alarms(device)
        target = next((alarm for alarm in local["alarms"] if alarm.get("id") == test_ids[0]), None)
        require(target is not None, "conflict_alarm_missing")
        device.control({"action": "alarm-put", "id": test_ids[0],
                        "name": target["name"] + "-本地修改", "date": target["date"],
                        "hour": (target["hour"] + 1) % 24, "minute": target["minute"],
                        "weekdays": target["weekdays"], "enabled": False,
                        "snooze_minutes": target["snooze_minutes"],
                        "expected_version": local["version"]})
        remote = device_alarms(device)
        remote_target = next(alarm for alarm in remote["alarms"] if alarm["id"] == test_ids[0])

        device.control({"action": "start", "listen": True})
        device_disabled = False
        wait_device_ready(device)
        conflict = wait_for(lambda: get_entity(ha, entity_id),
                            lambda value: value["sync_status"] == "conflict"
                            and value.get("last_error") == "remote_changed"
                            and len(value["pending_changes"]) == 1
                            and value["pending_changes"][0].get("blocked") is True,
                            "remote_conflict_not_observed", 45)
        retained = next((alarm for alarm in conflict["alarms"]
                         if alarm.get("id") == test_ids[0]), None)
        require(retained is not None and editable(retained) == editable(remote_target),
                "remote_change_was_overwritten")

        entity_service(ha, "alarm_pending_discard", entity_id, {"id": test_ids[0]})
        entity_service(ha, "alarm_refresh", entity_id)
        recovered = wait_for(lambda: get_entity(ha, entity_id),
                             lambda value: value["sync_status"] == "synced"
                             and not value["pending_changes"],
                             "alarm_conflict_not_recovered")

        for alarm_id in test_ids:
            entity_service(ha, "alarm_delete", entity_id, {"id": alarm_id})
        created.clear()
        restored = wait_for(lambda: get_entity(ha, entity_id),
                            lambda value: value["sync_status"] == "synced"
                            and not value["pending_changes"]
                            and canonical(value["alarms"]) == baseline,
                            "alarm_baseline_not_restored")
        final_device = device_alarms(device)
        require(canonical(final_device["alarms"]) == baseline,
                "device_alarm_baseline_not_restored")
        return {"status": "pass", "scenario": "alarm_paging_pending_conflict",
                "baseline_alarm_count": len(baseline), "test_alarm_count": TEST_COUNT,
                "noise_page_offsets": offsets, "noise_version": page_version,
                "ha_full_list_count": populated["alarm_count"],
                "offline_sync_status": offline["sync_status"],
                "pending_sync_status": pending["sync_status"],
                "conflict_sync_status": conflict["sync_status"],
                "conflict_reason": conflict["last_error"],
                "remote_change_retained": True,
                "pending_discarded": not recovered["pending_changes"],
                "baseline_restored": canonical(restored["alarms"]) == baseline,
                "credentials_saved": False}
    finally:
        if device_disabled:
            try:
                device.start_control()
                device.control({"action": "start", "listen": True})
                wait_device_ready(device)
            except Exception:
                pass
        # Only this run's exact random IDs are cleanup targets.
        for alarm_id in test_ids:
            try:
                entity_service(ha, "alarm_pending_discard", entity_id, {"id": alarm_id})
            except Exception:
                pass
        for alarm_id in test_ids:
            try:
                current = device_alarms(device)
                if any(alarm.get("id") == alarm_id for alarm in current["alarms"]):
                    device.control({"action": "alarm-delete", "id": alarm_id,
                                    "expected_version": current["version"]})
            except Exception:
                pass


def write_report(report, output):
    destination = Path(output).resolve()
    evidence_root = (ROOT / "test-results").resolve()
    require(evidence_root in destination.parents, "evidence_must_be_under_test_results")
    destination.parent.mkdir(parents=True, exist_ok=True)
    value = {"schema": 1, "device": "r1-sample01",
             "recorded_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **report}
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("serial")
    parser.add_argument("--confirm-device", required=True, choices=("r1-sample01",))
    parser.add_argument("--ha-url", required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    token = consume_token(args.token_file)
    try:
        ha = HomeAssistant(args.ha_url, token)
        device = admin.Device(args.serial)
        device.verify()
        entity_id, service = discover(ha)
        prefix = "r1-validation-" + uuid4().hex[:12] + "-"
        test_ids = [prefix + str(index) for index in range(TEST_COUNT)]
        report = validate(device, ha, entity_id, service, test_ids)
        write_report(report, args.output)
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
