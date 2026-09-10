#!/usr/bin/env python3
"""Render a private boot-overlay staging tree after all device gates pass; never flash it."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
DEVICE = ROOT / "android/factory-audio-agent/device"
BOOT_REFERENCE = ROOT / "docs/references/r1-3448-boot-baseline.json"
RISK_KEYS = {
    "incomplete_full_emmc_backup", "no_independent_recovery_entry",
    "permanent_device_loss", "data_loss",
}


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def outside_repository(path, message):
    path = Path(path).resolve()
    try:
        path.relative_to(ROOT)
        raise RuntimeError(message)
    except ValueError:
        return path


def authorize(gate, boot, risk_path):
    if gate.get("status") in ("pass", "pass_with_exception"):
        require(risk_path is None, "risk_acceptance_not_allowed_after_r0_pass")
        return {"mode": "r0_gate", "gate_status": gate["status"]}
    require(gate.get("status") == "pending", "r0_gate_status_invalid")
    require(risk_path is not None, "r0_gate_not_passed")
    path = outside_repository(risk_path, "risk_acceptance_must_be_outside_repository")
    risk = load(path)
    require(risk.get("schema_version") == 1, "risk_acceptance_schema_invalid")
    require(risk.get("decision") == "accept_boot_partition_brick_risk"
            and risk.get("accepted") is True, "risk_acceptance_decision_invalid")
    require(risk.get("device") == gate.get("device"), "risk_acceptance_device_mismatch")
    require(risk.get("scope") == ["boot"], "risk_acceptance_scope_invalid")
    require(risk.get("original_boot_sha256")
            == boot.get("partitions", {}).get("boot", {}).get("sha256"),
            "risk_acceptance_boot_hash_mismatch")
    risks = risk.get("risks", {})
    require(set(risks) == RISK_KEYS and all(risks.values()), "risk_acceptance_risks_incomplete")
    recorded = risk.get("recorded_at")
    require(isinstance(recorded, str) and recorded.startswith("2026-09-10"),
            "risk_acceptance_date_invalid")
    return {"mode": "explicit_device_limited_risk_acceptance", "gate_status": "pending",
            "risk_acceptance_sha256": digest(path)}


def render(args):
    gate = load(args.gate_report)
    require(gate.get("device", {}).get("id") == "r1-sample01", "gate_device_mismatch")
    if gate.get("status") == "pending":
        require(getattr(args, "risk_acceptance", None) is not None, "r0_gate_not_passed")
    boot = load(args.boot_baseline_report)
    require(boot.get("status") == "pass", "boot_baseline_not_passed")
    require(boot.get("device", {}).get("id") == "r1-sample01", "boot_baseline_device_mismatch")
    require(boot.get("device", {}).get("fingerprint")
            == gate["device"].get("fingerprint"), "boot_baseline_fingerprint_mismatch")
    authorization = authorize(gate, boot, getattr(args, "risk_acceptance", None))
    require(boot.get("reference_sha256") == digest(BOOT_REFERENCE),
            "boot_baseline_reference_mismatch")
    boot_reference = load(BOOT_REFERENCE)
    require(boot.get("baseline_manifest_sha256")
            == boot_reference.get("baseline_manifest_sha256"),
            "boot_baseline_manifest_mismatch")
    preflight = load(args.preflight)
    require(preflight.get("status") == "pass", "factory_audio_preflight_not_passed")
    require(preflight.get("device") == "r1-sample01", "preflight_device_mismatch")
    require(preflight.get("identity", {}).get("ro.build.fingerprint")
            == gate["device"].get("fingerprint"), "preflight_fingerprint_mismatch")
    client_uid = preflight.get("satellite", {}).get("uid")
    require(client_uid == 10010, "satellite_uid_not_10010")
    abi = load(args.abi_report)
    require(abi.get("status") == "pass", "vendor_abi_not_passed")
    require(abi.get("library_name") == Path(args.vendor_library).name,
            "vendor_library_report_mismatch")
    require(args.output_channels in (1, 2), "output_channels_not_proven")
    require(0 <= args.output_channel < args.output_channels, "output_channel_not_proven")
    agent = Path(args.agent).resolve()
    require(agent.is_file(), "agent_missing")
    header = subprocess.run(
        ["readelf", "-hW", str(agent)], check=True, capture_output=True, text=True
    ).stdout
    require("Class:                             ELF32" in header
            and "Machine:                           ARM" in header, "agent_not_arm_elf32")
    output = outside_repository(args.output_dir, "private_overlay_must_be_outside_repository")
    require(not output.exists(), "output_directory_already_exists")
    (output / "sbin").mkdir(parents=True)
    (output / "sepolicy").mkdir()
    shutil.copy2(agent, output / "sbin/r1-factory-audio-agent")
    init = (DEVICE / "init.r1_factory_audio.rc").read_text(encoding="utf-8")
    init = init.replace("@PROVEN_OUTPUT_CHANNELS@", str(args.output_channels))
    init = init.replace("@PROVEN_OUTPUT_CHANNEL@", str(args.output_channel))
    init = init.replace("/system/lib/libuni4michal.so", args.vendor_library)
    require("@PROVEN_" not in init, "unresolved_init_template_token")
    (output / "init.r1_factory_audio.rc").write_text(init, encoding="utf-8")
    for name in ("r1_factory_audio.te", "file_contexts"):
        shutil.copy2(DEVICE / "sepolicy" / name, output / "sepolicy" / name)
    manifest = {
        "agent_sha256": digest(output / "sbin/r1-factory-audio-agent"),
        "init_rc_sha256": digest(output / "init.r1_factory_audio.rc"),
        "file_contexts_sha256": digest(output / "sepolicy/file_contexts"),
        "policy_source_sha256": digest(output / "sepolicy/r1_factory_audio.te"),
        "boot_baseline_manifest_sha256": boot["baseline_manifest_sha256"],
        "boot_baseline_reference_sha256": boot["reference_sha256"],
        "device": gate["device"],
        "authorization": authorization,
        "output_channel": args.output_channel,
        "output_channels": args.output_channels,
        "satellite_uid": client_uid,
        "vendor_library": args.vendor_library,
        "vendor_library_sha256": abi["library_sha256"],
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gate-report", required=True)
    parser.add_argument("--risk-acceptance")
    parser.add_argument("--boot-baseline-report", required=True)
    parser.add_argument("--preflight", required=True)
    parser.add_argument("--abi-report", required=True)
    parser.add_argument("--agent", required=True)
    parser.add_argument("--vendor-library", choices=(
        "/system/lib/libuni4michal.so", "/system/lib/libuni4michalchance.so"
    ), required=True)
    parser.add_argument("--output-channels", type=int, required=True)
    parser.add_argument("--output-channel", type=int, required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    try:
        result = render(args)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
        print("Overlay rendering refused: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
