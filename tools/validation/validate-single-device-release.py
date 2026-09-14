#!/usr/bin/env python3
"""Check whether one R1 has cleared the gate for multi-device onboarding.

This is a read-only release gate.  It validates a redacted summary and never
contacts ADB, Home Assistant, a device, or the update supervisor.
"""
import argparse
import json
import re
from pathlib import Path


DEVICE_ID = re.compile(r"r1-[a-z0-9][a-z0-9-]{1,62}$")
HASH = re.compile(r"[0-9a-f]{64}$")
SECRET = re.compile(r"(token|password|passwd|psk|secret|private[_-]?key|credential)", re.I)
REQUIRED_GATES = (
    "human_functional", "automated_regression", "provisioning",
    "update_rollback", "network_recovery", "stability_72h",
)


def fail(message):
    raise ValueError(message)


def reject_secrets(value, path="release"):
    if isinstance(value, dict):
        for key, child in value.items():
            if SECRET.search(str(key)):
                fail(f"secret_field_forbidden:{path}.{key}")
            reject_secrets(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_secrets(child, f"{path}[{index}]")


def validate_release(payload):
    if not isinstance(payload, dict) or payload.get("schema") != 1:
        fail("schema_unsupported")
    reject_secrets(payload)
    device_id = payload.get("device_id")
    if not isinstance(device_id, str) or not DEVICE_ID.fullmatch(device_id):
        fail("device_id_invalid")
    apk = payload.get("apk_sha256")
    if not isinstance(apk, str) or not HASH.fullmatch(apk):
        fail("apk_sha256_invalid")
    gates = payload.get("gates")
    if not isinstance(gates, dict):
        fail("gates_required")
    for gate in REQUIRED_GATES:
        if gates.get(gate) != "passed":
            fail(f"gate_not_passed:{gate}")
    evidence = payload.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        fail("evidence_required")
    for item in evidence:
        if not isinstance(item, str) or not item.startswith("test-results/"):
            fail("evidence_must_be_under_test_results")
        path = Path(item)
        if path.is_absolute() or ".." in path.parts:
            fail("evidence_path_invalid")
    return {"schema": 1, "device_id": device_id, "apk_sha256": apk,
            "release_status": "ready_for_multi_device_onboarding",
            "gates": list(REQUIRED_GATES)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release", type=Path)
    args = parser.parse_args(argv)
    try:
        result = validate_release(json.loads(args.release.read_text(encoding="utf-8")))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
