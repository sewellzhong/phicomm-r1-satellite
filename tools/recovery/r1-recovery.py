#!/usr/bin/env python3
"""Host-only R0 image manifest, copy verification, and recovery gate reporting.

This tool intentionally has no device transport and no erase/write/flash command.
Image paths stay outside the repository and are resolved through operator-provided
storage roots; generated metadata contains only relative paths and hashes.
"""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
import sys


SCHEMA_VERSION = 1
RECOVERY_CHECKS = (
    "boot",
    "adb",
    "wifi",
    "bluetooth",
    "microphone",
    "speaker",
    "buttons",
    "leds",
    "factory_audio_hashes",
)


class ValidationError(RuntimeError):
    pass


def load_json(path):
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path, value):
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with destination.open("x", encoding="utf-8") as handle:
        handle.write(payload)


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def stable_sha256_file(path):
    before = path.stat()
    digest = sha256_file(path)
    after = path.stat()
    identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if identity_before != identity_after:
        raise ValidationError("copy_changed_while_hashing")
    return digest


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def require_text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field}_required")
    return value.strip()


def require_positive_int(value, field):
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValidationError(f"{field}_must_be_positive_integer")
    return value


def validate_sha256(value, field):
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValidationError(f"{field}_invalid_sha256")
    return value


def validate_relative_path(value, field="path"):
    value = require_text(value, field)
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or value.startswith("~"):
        raise ValidationError(f"{field}_must_be_safe_relative_path")
    return value


def parse_storages(values):
    storages = {}
    for value in values:
        if "=" not in value:
            raise ValidationError("storage_must_be_ID=PATH")
        storage_id, root = value.split("=", 1)
        storage_id = require_text(storage_id, "storage_id")
        if storage_id in storages:
            raise ValidationError("duplicate_storage_id")
        root_path = Path(require_text(root, "storage_root")).expanduser().resolve()
        if not root_path.is_dir():
            raise ValidationError(f"storage_root_not_directory:{storage_id}")
        storages[storage_id] = root_path
    return storages


def resolve_copy(copy, storages):
    storage_id = require_text(copy.get("storage_id"), "copy.storage_id")
    if storage_id not in storages:
        raise ValidationError(f"storage_not_provided:{storage_id}")
    relative = validate_relative_path(copy.get("path"), "copy.path")
    root = storages[storage_id]
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise ValidationError("copy_path_escapes_storage") from error
    if not path.is_file():
        raise ValidationError(f"copy_missing:{storage_id}:{relative}")
    return storage_id, relative, path


def validate_regions(area):
    area_name = require_text(area.get("name"), "area.name")
    area_size = require_positive_int(area.get("size"), f"area.{area_name}.size")
    regions = area.get("regions")
    if not isinstance(regions, list) or not regions:
        raise ValidationError(f"area_regions_required:{area_name}")
    ordered = sorted(regions, key=lambda item: item.get("offset", -1))
    cursor = 0
    names = set()
    for region in ordered:
        name = require_text(region.get("name"), "region.name")
        if name in names:
            raise ValidationError(f"duplicate_region:{area_name}:{name}")
        names.add(name)
        offset = region.get("offset")
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            raise ValidationError(f"invalid_region_offset:{area_name}:{name}")
        length = require_positive_int(region.get("length"), f"region.{name}.length")
        if offset != cursor:
            reason = "overlap" if offset < cursor else "gap"
            raise ValidationError(f"region_{reason}:{area_name}:{name}")
        cursor = offset + length
        if cursor > area_size:
            raise ValidationError(f"region_out_of_bounds:{area_name}:{name}")
    if cursor != area_size:
        raise ValidationError(f"region_gap_at_end:{area_name}")
    return ordered


def validate_copies(copy_specs, classification, storages, expected_size):
    if not isinstance(copy_specs, list) or len(copy_specs) < 2:
        raise ValidationError("at_least_two_copies_required")
    metadata = []
    identities = set()
    storage_ids = set()
    hashes = set()
    for copy in copy_specs:
        storage_id, relative, path = resolve_copy(copy, storages)
        try:
            identity = (path.stat().st_dev, path.stat().st_ino)
        except OSError as error:
            raise ValidationError(f"copy_stat_failed:{storage_id}:{relative}") from error
        if identity in identities:
            raise ValidationError("copies_resolve_to_same_file")
        identities.add(identity)
        storage_ids.add(storage_id)
        encrypted = copy.get("encrypted_storage") is True
        if classification == "sensitive" and not encrypted:
            raise ValidationError(f"sensitive_copy_requires_encrypted_storage:{storage_id}:{relative}")
        size = path.stat().st_size
        if size != expected_size:
            raise ValidationError(f"copy_size_mismatch:{storage_id}:{relative}")
        digest = stable_sha256_file(path)
        hashes.add(digest)
        metadata.append({
            "encrypted_storage": encrypted,
            "path": relative,
            "sha256": digest,
            "size": size,
            "storage_id": storage_id,
        })
    if len(storage_ids) < 2:
        raise ValidationError("copies_require_distinct_storage_ids")
    if len(hashes) != 1:
        raise ValidationError("copy_hash_mismatch")
    return metadata, next(iter(hashes))


def artifact_from_spec(area_name, kind, spec, offset, length, storages, default_source):
    name = require_text(spec.get("name", area_name if kind == "full" else None), "artifact.name")
    classification = spec.get("classification")
    if classification not in ("non_sensitive", "sensitive"):
        raise ValidationError(f"invalid_classification:{area_name}:{name}")
    copies, digest = validate_copies(spec.get("copies"), classification, storages, length)
    source = spec.get("source", default_source)
    if not isinstance(source, dict):
        raise ValidationError("artifact_source_must_be_object")
    return {
        "area": area_name,
        "classification": classification,
        "copies": copies,
        "kind": kind,
        "length": length,
        "name": name,
        "offset": offset,
        "sha256": digest,
        "source": {
            "tool": require_text(source.get("tool"), "artifact.source.tool"),
            "version": require_text(source.get("version"), "artifact.source.version"),
        },
    }


def create_manifest(layout, identity, source, storages):
    if layout.get("schema_version") != SCHEMA_VERSION:
        raise ValidationError("unsupported_layout_schema_version")
    areas = layout.get("areas")
    if not isinstance(areas, list) or not areas:
        raise ValidationError("areas_required")
    artifacts = []
    area_records = []
    area_names = set()
    for area in areas:
        area_name = require_text(area.get("name"), "area.name")
        if area_name in area_names:
            raise ValidationError(f"duplicate_area:{area_name}")
        area_names.add(area_name)
        area_size = require_positive_int(area.get("size"), f"area.{area_name}.size")
        full = area.get("full_image")
        if not isinstance(full, dict):
            raise ValidationError(f"full_image_required:{area_name}")
        regions = validate_regions(area)
        if any(region.get("classification") == "sensitive" for region in regions):
            if full.get("classification") != "sensitive":
                raise ValidationError(f"full_image_must_be_sensitive:{area_name}")
        artifacts.append(artifact_from_spec(area_name, "full", full, 0, area_size, storages, source))
        for region in regions:
            artifacts.append(artifact_from_spec(
                area_name, "region", region, region["offset"], region["length"], storages, source
            ))
        area_records.append({
            "name": area_name,
            "regions": [
                {"length": item["length"], "name": item["name"], "offset": item["offset"]}
                for item in regions
            ],
            "size": area_size,
        })
    files = layout.get("files", [])
    if not isinstance(files, list):
        raise ValidationError("files_must_be_list")
    file_names = set()
    for file_spec in files:
        name = require_text(file_spec.get("name"), "file.name")
        if name in file_names:
            raise ValidationError(f"duplicate_file:{name}")
        file_names.add(name)
        length = require_positive_int(file_spec.get("length"), f"file.{name}.length")
        artifacts.append(artifact_from_spec(
            "device-files", "file", file_spec, 0, length, storages, source
        ))
    manifest = {
        "artifacts": artifacts,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "device": {
            "fingerprint": require_text(identity.get("fingerprint"), "device.fingerprint"),
            "hardware": require_text(identity.get("hardware"), "device.hardware"),
            "id": require_text(identity.get("id"), "device.id"),
        },
        "layout": {"areas": area_records},
        "schema_version": SCHEMA_VERSION,
        "source": {
            "tool": require_text(source.get("tool"), "source.tool"),
            "version": require_text(source.get("version"), "source.version"),
        },
    }
    return validate_manifest(manifest)


def validate_manifest(manifest):
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValidationError("unsupported_manifest_schema_version")
    device = manifest.get("device", {})
    for field in ("id", "hardware", "fingerprint"):
        require_text(device.get(field), f"device.{field}")
    source = manifest.get("source", {})
    require_text(source.get("tool"), "source.tool")
    require_text(source.get("version"), "source.version")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ValidationError("manifest_artifacts_required")
    names = set()
    for artifact in artifacts:
        key = (artifact.get("area"), artifact.get("kind"), artifact.get("name"))
        if key in names:
            raise ValidationError("duplicate_manifest_artifact")
        names.add(key)
        require_text(artifact.get("area"), "artifact.area")
        require_text(artifact.get("name"), "artifact.name")
        if artifact.get("kind") not in ("full", "region", "file"):
            raise ValidationError("invalid_artifact_kind")
        if artifact.get("classification") not in ("non_sensitive", "sensitive"):
            raise ValidationError("invalid_artifact_classification")
        if not isinstance(artifact.get("offset"), int) or isinstance(artifact.get("offset"), bool) or artifact["offset"] < 0:
            raise ValidationError("invalid_artifact_offset")
        require_positive_int(artifact.get("length"), "artifact.length")
        digest = validate_sha256(artifact.get("sha256"), "artifact")
        copies = artifact.get("copies")
        if not isinstance(copies, list) or len(copies) < 2:
            raise ValidationError("manifest_requires_two_copies")
        storage_ids = set()
        for copy in copies:
            storage_ids.add(require_text(copy.get("storage_id"), "copy.storage_id"))
            validate_relative_path(copy.get("path"), "copy.path")
            if artifact["classification"] == "sensitive" and copy.get("encrypted_storage") is not True:
                raise ValidationError("manifest_sensitive_copy_not_encrypted")
        if len(storage_ids) < 2:
            raise ValidationError("manifest_requires_distinct_storage_ids")
        artifact_source = artifact.get("source", {})
        require_text(artifact_source.get("tool"), "artifact.source.tool")
        require_text(artifact_source.get("version"), "artifact.source.version")
        for copy in copies:
            if copy.get("size") != artifact["length"] or copy.get("sha256") != digest:
                raise ValidationError("manifest_copy_metadata_mismatch")
    areas = {}
    for artifact in artifacts:
        if artifact["kind"] == "file":
            continue
        areas.setdefault(artifact["area"], []).append(artifact)
    for area_name, area_artifacts in areas.items():
        full = [item for item in area_artifacts if item["kind"] == "full"]
        if len(full) != 1 or full[0]["offset"] != 0:
            raise ValidationError(f"manifest_full_image_invalid:{area_name}")
        cursor = 0
        regions = sorted(
            (item for item in area_artifacts if item["kind"] == "region"),
            key=lambda item: item["offset"],
        )
        if not regions:
            raise ValidationError(f"manifest_regions_missing:{area_name}")
        if any(region["classification"] == "sensitive" for region in regions):
            if full[0]["classification"] != "sensitive":
                raise ValidationError(f"manifest_full_image_must_be_sensitive:{area_name}")
        for region in regions:
            if region["offset"] != cursor:
                reason = "overlap" if region["offset"] < cursor else "gap"
                raise ValidationError(f"manifest_region_{reason}:{area_name}:{region['name']}")
            cursor += region["length"]
        if cursor != full[0]["length"]:
            raise ValidationError(f"manifest_region_coverage_mismatch:{area_name}")
    return manifest


def verify_copies(manifest, storages, manifest_bytes):
    validate_manifest(manifest)
    failures = []
    checked = []
    seen_files = set()
    for artifact in manifest["artifacts"]:
        artifact_key = f"{artifact['area']}:{artifact['kind']}:{artifact['name']}"
        storage_ids = set()
        for copy in artifact.get("copies", []):
            try:
                storage_id, relative, path = resolve_copy(copy, storages)
                identity = (path.stat().st_dev, path.stat().st_ino)
                if identity in seen_files:
                    failures.append({"artifact": artifact_key, "reason": "copy_reuses_file"})
                seen_files.add(identity)
                storage_ids.add(storage_id)
                size_ok = path.stat().st_size == artifact["length"]
                hash_ok = stable_sha256_file(path) == artifact["sha256"]
                encryption_ok = artifact["classification"] != "sensitive" or copy.get("encrypted_storage") is True
                if not (size_ok and hash_ok and encryption_ok):
                    failures.append({"artifact": artifact_key, "reason": "copy_verification_failed", "storage_id": storage_id})
                checked.append({
                    "artifact": artifact_key,
                    "hash_ok": hash_ok,
                    "size_ok": size_ok,
                    "storage_id": storage_id,
                })
            except (OSError, ValidationError):
                failures.append({"artifact": artifact_key, "reason": "copy_unavailable"})
        if len(storage_ids) < 2:
            failures.append({"artifact": artifact_key, "reason": "independent_storages_missing"})
    return {
        "checked": checked,
        "failures": failures,
        "manifest_sha256": sha256_bytes(manifest_bytes),
        "schema_version": SCHEMA_VERSION,
        "status": "fail" if failures else "pass",
    }


def gate_report(manifest, manifest_bytes, verification, recovery):
    validate_manifest(manifest)
    failures = []
    pending = []
    expected_manifest_hash = sha256_bytes(manifest_bytes)
    if verification.get("manifest_sha256") != expected_manifest_hash:
        failures.append("verification_manifest_mismatch")
    if verification.get("status") != "pass":
        failures.append("copy_verification_not_passed")
    expected_copy_count = sum(len(artifact["copies"]) for artifact in manifest["artifacts"])
    expected_checked = {
        (f"{artifact['area']}:{artifact['kind']}:{artifact['name']}", copy["storage_id"])
        for artifact in manifest["artifacts"] for copy in artifact["copies"]
    }
    checked = verification.get("checked")
    if not isinstance(checked, list) or len(checked) != expected_copy_count:
        failures.append("copy_verification_incomplete")
    else:
        actual_checked = {(item.get("artifact"), item.get("storage_id")) for item in checked}
        if actual_checked != expected_checked:
            failures.append("copy_verification_incomplete")
        if any(item.get("hash_ok") is not True or item.get("size_ok") is not True for item in checked):
            failures.append("copy_verification_not_passed")
    if verification.get("failures"):
        failures.append("copy_verification_not_passed")
    recovery_device = recovery.get("device", {})
    for field in ("id", "hardware", "fingerprint"):
        if recovery_device.get(field) != manifest["device"][field]:
            failures.append(f"device_{field}_mismatch")
    def evaluate_record(label, record):
        if record is None:
            pending.append(label)
            return
        if not isinstance(record, dict):
            failures.append(f"invalid_status:{label}")
            return
        status = record.get("status", "pending")
        if status == "fail":
            failures.append(label)
        elif status == "pending":
            pending.append(label)
        elif status == "pass":
            try:
                validate_relative_path(record.get("evidence"), f"{label}.evidence")
                validate_sha256(record.get("evidence_sha256"), f"{label}.evidence")
            except ValidationError:
                failures.append(f"evidence_missing_or_invalid:{label}")
        else:
            failures.append(f"invalid_status:{label}")

    for gate in ("low_level_entry", "controlled_full_restore"):
        evaluate_record(gate, recovery.get(gate))
    checks = recovery.get("post_restore_checks", {})
    for name in RECOVERY_CHECKS:
        evaluate_record(f"post_restore:{name}", checks.get(name))
    status = "fail" if failures else "pending" if pending else "pass"
    return {
        "device": manifest["device"],
        "failures": sorted(set(failures)),
        "manifest_sha256": expected_manifest_hash,
        "pending": sorted(set(pending)),
        "schema_version": SCHEMA_VERSION,
        "status": status,
    }


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-manifest", help="Create and validate a hashed R0 manifest")
    create.add_argument("--layout", required=True)
    create.add_argument("--device-id", required=True)
    create.add_argument("--hardware", required=True)
    create.add_argument("--fingerprint", required=True)
    create.add_argument("--tool", required=True)
    create.add_argument("--tool-version", required=True)
    create.add_argument("--storage", action="append", default=[], metavar="ID=PATH")
    create.add_argument("--output", required=True)
    verify = commands.add_parser("verify-copies", help="Re-read and verify every image copy")
    verify.add_argument("--manifest", required=True)
    verify.add_argument("--storage", action="append", default=[], metavar="ID=PATH")
    verify.add_argument("--output", required=True)
    gate = commands.add_parser("gate-report", help="Generate the R0 pass/pending/fail report")
    gate.add_argument("--manifest", required=True)
    gate.add_argument("--verification", required=True)
    gate.add_argument("--recovery-state", required=True)
    gate.add_argument("--output", required=True)
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "create-manifest":
            layout = load_json(args.layout)
            manifest = create_manifest(
                layout,
                {"id": args.device_id, "hardware": args.hardware, "fingerprint": args.fingerprint},
                {"tool": args.tool, "version": args.tool_version},
                parse_storages(args.storage),
            )
            write_json(args.output, manifest)
            print("R0 manifest created and copy hashes matched")
            return 0
        manifest_bytes = Path(args.manifest).read_bytes()
        manifest = json.loads(manifest_bytes)
        if args.command == "verify-copies":
            result = verify_copies(manifest, parse_storages(args.storage), manifest_bytes)
            write_json(args.output, result)
            print(f"R0 copy verification: {result['status']}")
            return 0 if result["status"] == "pass" else 1
        result = gate_report(
            manifest,
            manifest_bytes,
            load_json(args.verification),
            load_json(args.recovery_state),
        )
        write_json(args.output, result)
        print(f"R0 recovery gate: {result['status']}")
        return 0 if result["status"] == "pass" else 1
    except (AttributeError, KeyError, OSError, TypeError, ValueError, json.JSONDecodeError, ValidationError) as error:
        print(f"R0 recovery tool refused operation: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
