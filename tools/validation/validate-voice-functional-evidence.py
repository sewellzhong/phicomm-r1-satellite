#!/usr/bin/env python3
"""Validate redacted human/automated voice acceptance evidence.

This accepts event outcomes and timing/state summaries only.  It rejects raw
transcripts, recordings and credential-shaped fields so evidence can be kept
in the public repository without turning it into a conversation archive.
"""
import argparse
import json
import re
from pathlib import Path


HEX64 = re.compile(r"[0-9a-f]{64}$")
DEVICE_ID = re.compile(r"r1-[a-z0-9][a-z0-9-]{1,62}$")
SECRET = re.compile(r"(token|password|passwd|psk|secret|private[_-]?key|credential)", re.I)
FORBIDDEN_CONTENT = re.compile(r"(transcript|utterance|recording|audio[_-]?(path|file|data)|raw[_-]?(text|audio))", re.I)
MODES = {"natural_functional", "controlled_diagnostic", "automated_state"}
STATUSES = {"passed", "failed", "skipped", "blocked"}
CASE_IDS = {
    "alexa_wake", "chinese_stt_intent_tts", "streaming_answer",
    "playback_barge_in", "direct_interruption", "announcement",
    "timer", "alarm", "media", "do_not_disturb", "software_mute",
}


def fail(message):
    raise ValueError(message)


def reject_fields(value, path="evidence"):
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            if SECRET.search(key_text):
                fail(f"secret_field_forbidden:{path}.{key_text}")
            if FORBIDDEN_CONTENT.search(key_text):
                fail(f"conversation_content_forbidden:{path}.{key_text}")
            reject_fields(child, f"{path}.{key_text}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_fields(child, f"{path}[{index}]")


def validate_evidence(payload):
    if not isinstance(payload, dict) or payload.get("schema") != 1:
        fail("schema_unsupported")
    reject_fields(payload)
    device_id = payload.get("device_id")
    if not isinstance(device_id, str) or not DEVICE_ID.fullmatch(device_id):
        fail("device_id_invalid")
    apk = payload.get("apk_sha256")
    if not isinstance(apk, str) or not HEX64.fullmatch(apk):
        fail("apk_sha256_invalid")
    mode = payload.get("mode")
    if mode not in MODES:
        fail("mode_invalid")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        fail("cases_required")
    seen = set()
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            fail(f"cases[{index}]_must_be_object")
        case_id = case.get("case_id")
        if case_id not in CASE_IDS:
            fail(f"cases[{index}].case_id_invalid")
        if case_id in seen:
            fail("case_id_not_unique")
        seen.add(case_id)
        if case.get("status") not in STATUSES:
            fail(f"cases[{index}].status_invalid")
        if "failure_code" in case and (not isinstance(case["failure_code"], str)
                                        or not re.fullmatch(r"[a-z0-9_]{1,64}", case["failure_code"])):
            fail(f"cases[{index}].failure_code_invalid")
    return {"schema": 1, "device_id": device_id, "apk_sha256": apk,
            "mode": mode, "case_count": len(cases),
            "passed": sum(case["status"] == "passed" for case in cases),
            "failed": sum(case["status"] == "failed" for case in cases)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args(argv)
    try:
        result = validate_evidence(json.loads(args.evidence.read_text(encoding="utf-8")))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
