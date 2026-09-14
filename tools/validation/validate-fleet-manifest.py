#!/usr/bin/env python3
"""Validate the public, secret-free manifest for a multi-R1 rollout.

The manifest is an inventory and evidence index, not a deployment command.  It
deliberately refuses credentials and requires every device to have its own
identity and baseline record.  Device mutation remains in the separately
gated update tooling.
"""
import argparse
import json
import re
from pathlib import Path


DEVICE_ID = re.compile(r"r1-[a-z0-9][a-z0-9-]{1,62}$")
HEX64 = re.compile(r"[0-9a-f]{64}$")
SECRET_KEYS = re.compile(
    r"(token|password|passwd|psk|secret|private[_-]?key|credential)", re.I
)
STATUSES = {"pending", "passed", "failed", "blocked"}
ROOT = Path(__file__).resolve().parents[2]


def fail(message):
    raise ValueError(message)


def require_string(value, field):
    if not isinstance(value, str) or not value.strip():
        fail(f"{field}_required")
    return value


def reject_secret_keys(value, path="manifest"):
    if isinstance(value, dict):
        for key, child in value.items():
            if SECRET_KEYS.search(str(key)):
                fail(f"secret_field_forbidden:{path}.{key}")
            reject_secret_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_secret_keys(child, f"{path}[{index}]")


def validate_manifest(payload):
    if not isinstance(payload, dict) or payload.get("schema") != 1:
        fail("schema_unsupported")
    reject_secret_keys(payload)
    fleet_id = require_string(payload.get("fleet_id"), "fleet_id")
    devices = payload.get("devices")
    if not isinstance(devices, list) or not 3 <= len(devices) <= 8:
        fail("device_count_must_be_3_to_8")

    seen_ids = set()
    seen_serials = set()
    seen_ha_ids = set()
    result = []
    required = (
        "device_id", "serial", "firmware_fingerprint", "apk_sha256",
        "noise_identity_digest", "ha_device_id", "baseline_status",
        "evidence",
    )
    for index, device in enumerate(devices):
        prefix = f"devices[{index}]"
        if not isinstance(device, dict):
            fail(f"{prefix}_must_be_object")
        for field in required:
            if field not in device:
                fail(f"{prefix}.{field}_required")
        device_id = require_string(device["device_id"], f"{prefix}.device_id")
        if not DEVICE_ID.fullmatch(device_id):
            fail(f"{prefix}.device_id_invalid")
        serial = require_string(device["serial"], f"{prefix}.serial")
        ha_id = require_string(device["ha_device_id"], f"{prefix}.ha_device_id")
        if device_id in seen_ids:
            fail("device_id_not_unique")
        if serial in seen_serials:
            fail("serial_not_unique")
        if ha_id in seen_ha_ids:
            fail("ha_device_id_not_unique")
        seen_ids.add(device_id); seen_serials.add(serial); seen_ha_ids.add(ha_id)
        for field in ("apk_sha256", "noise_identity_digest"):
            value = require_string(device[field], f"{prefix}.{field}")
            if not HEX64.fullmatch(value):
                fail(f"{prefix}.{field}_must_be_lowercase_sha256")
        status = device["baseline_status"]
        if status not in STATUSES:
            fail(f"{prefix}.baseline_status_invalid")
        evidence = device["evidence"]
        if not isinstance(evidence, list) or not evidence:
            fail(f"{prefix}.evidence_required")
        for evidence_path in evidence:
            path = require_string(evidence_path, f"{prefix}.evidence")
            candidate = Path(path)
            if candidate.is_absolute() or ".." in candidate.parts:
                fail(f"{prefix}.evidence_path_invalid")
            if not path.startswith("test-results/"):
                fail(f"{prefix}.evidence_must_be_under_test_results")
        result.append({"device_id": device_id, "baseline_status": status})
    return {"schema": 1, "fleet_id": fleet_id, "device_count": len(result),
            "devices": result}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args(argv)
    try:
        payload = json.loads(args.manifest.read_text(encoding="utf-8"))
        summary = validate_manifest(payload)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
