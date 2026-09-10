#!/usr/bin/env python3
"""Host-only R0 image manifest, copy verification, and recovery gate reporting.

This tool intentionally has no device transport and no erase/write/flash command.
Image paths stay outside the repository and are resolved through operator-provided
storage roots; generated metadata contains only relative paths and hashes.
"""

import argparse
import hashlib
import json
import os
import shutil
import stat
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
import sys


SCHEMA_VERSION = 1
DEFAULT_STORAGE_POLICY = "dual_encrypted"
SINGLE_HOST_POLICY = "single_host_plaintext_exception"
SINGLE_HOST_RISKS = ("plaintext_sensitive_data", "single_point_loss")
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
R1_EMMC_BYTES = 7818182656
R1_FIRST4M_BYTES = 4194304


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


def checked_source(path, root, expected_size, expected_hash):
    relative = validate_relative_path(path, "source.path")
    candidate = (root / relative).resolve(strict=True)
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ValidationError("source_path_escapes_root") from error
    source_stat = os.lstat(candidate)
    if not stat.S_ISREG(source_stat.st_mode) or stat.S_ISLNK(source_stat.st_mode):
        raise ValidationError("source_not_regular_file")
    if source_stat.st_size != expected_size:
        raise ValidationError("source_size_mismatch")
    digest = stable_sha256_file(candidate)
    if digest != expected_hash:
        raise ValidationError("source_hash_mismatch")
    return candidate


def assemble_full_emmc(prefix_evidence, body_evidence, output_dir,
                       device_id, physical_bytes=R1_EMMC_BYTES,
                       first4m_bytes=R1_FIRST4M_BYTES):
    if device_id != "r1-sample01":
        raise ValidationError("assembly_device_mismatch")
    prefix_path = Path(prefix_evidence).resolve(strict=True)
    body_path = Path(body_evidence).resolve(strict=True)
    prefix = load_json(prefix_path)
    body = load_json(body_path)
    if (prefix.get("device_id") != device_id or prefix.get("status") != "pass"
            or prefix.get("operation") != "loader-first4m"):
        raise ValidationError("prefix_evidence_not_passed")
    if (body.get("device_id") != device_id or body.get("status") != "pass"
            or body.get("operation") != "loader-image-copy"):
        raise ValidationError("body_evidence_not_passed")
    if prefix.get("first4m", {}).get("bytes") != first4m_bytes:
        raise ValidationError("prefix_size_evidence_mismatch")
    body_bytes = body.get("address_space", {}).get("image_bytes")
    if body_bytes != physical_bytes - first4m_bytes:
        raise ValidationError("body_size_evidence_mismatch")
    chunks = body.get("chunks")
    if not isinstance(chunks, list) or not chunks:
        raise ValidationError("body_chunks_missing")
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    if shutil.disk_usage(output_dir).free < physical_bytes * 2 + 1024 * 1024 * 1024:
        raise ValidationError("assembly_insufficient_free_space")
    result = {
        "schema_version": 1,
        "device_id": device_id,
        "operation": "assemble-full-emmc",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "sources": {
            "prefix_evidence": {"path": str(prefix_path), "sha256": sha256_file(prefix_path)},
            "body_evidence": {"path": str(body_path), "sha256": sha256_file(body_path)},
        },
        "physical_bytes": physical_bytes,
        "copies": [],
        "status": "running",
    }
    prefix_root = prefix_path.parent
    body_root = body_path.parent
    try:
        cursor = 0
        for expected_index, chunk in enumerate(chunks):
            if chunk.get("index") != expected_index or chunk.get("start_sector") != cursor // 512:
                raise ValidationError(f"body_chunk_sequence_invalid:{expected_index}")
            length = chunk.get("bytes")
            if not isinstance(length, int) or length <= 0 or length % 512:
                raise ValidationError(f"body_chunk_length_invalid:{expected_index}")
            cursor += length
        if cursor != body_bytes:
            raise ValidationError("body_chunk_coverage_mismatch")
        prefix_specs = prefix.get("first4m", {}).get("copies")
        if not isinstance(prefix_specs, list):
            raise ValidationError("prefix_copy_set_invalid")
        prefix_by_storage = {
            item.get("storage_id"): item for item in prefix_specs if isinstance(item, dict)
        }
        if set(prefix_by_storage) != {"local-copy-a", "local-copy-b"}:
            raise ValidationError("prefix_copy_set_invalid")

        for label in ("a", "b"):
            storage_id = f"local-copy-{label}"
            prefix_spec = prefix_by_storage[storage_id]
            prefix_source = checked_source(
                prefix_spec["file"], prefix_root, first4m_bytes, prefix_spec["sha256"]
            )
            destination_dir = output_dir / f"copy-{label}"
            destination_dir.mkdir(mode=0o700)
            destination = destination_dir / "full-emmc.img"
            digest = hashlib.sha256()
            written = 0
            with destination.open("xb") as target:
                os.chmod(destination, 0o600)
                sources = [(prefix_source, first4m_bytes, prefix_spec["sha256"])]
                for expected_index, chunk in enumerate(chunks):
                    copies = {item["storage_id"]: item for item in chunk["copies"]}
                    if set(copies) != {"local-copy-a", "local-copy-b"}:
                        raise ValidationError(f"body_chunk_copy_set_invalid:{expected_index}")
                    spec = copies[storage_id]
                    sources.append((
                        checked_source(spec["file"], body_root, chunk["bytes"], spec["sha256"]),
                        chunk["bytes"], spec["sha256"],
                    ))
                for source, expected_size, _ in sources:
                    copied = 0
                    with source.open("rb") as stream:
                        while block := stream.read(1024 * 1024):
                            target.write(block)
                            digest.update(block)
                            copied += len(block)
                    if copied != expected_size:
                        raise ValidationError("source_changed_during_assembly")
                    written += copied
            if written != physical_bytes or destination.stat().st_size != physical_bytes:
                raise ValidationError(f"assembled_size_mismatch:{label}")
            result["copies"].append({
                "storage_id": storage_id,
                "file": str(destination.relative_to(output_dir)),
                "size": written,
                "sha256": digest.hexdigest(),
            })
        if result["copies"][0]["sha256"] != result["copies"][1]["sha256"]:
            raise ValidationError("assembled_copy_hash_mismatch")
        result["status"] = "pass"
    except Exception as error:
        result["status"] = "stopped"
        result["error"] = str(error)
        raise
    finally:
        result["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_json(output_dir / "assembly.json", result)
    return result


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


def validate_storage_policy(policy, device_id=None):
    if policy is None:
        return {"mode": DEFAULT_STORAGE_POLICY}
    if not isinstance(policy, dict):
        raise ValidationError("storage_policy_must_be_object")
    mode = policy.get("mode")
    if mode == DEFAULT_STORAGE_POLICY:
        if set(policy) != {"mode"}:
            raise ValidationError("default_storage_policy_has_unexpected_fields")
        return {"mode": DEFAULT_STORAGE_POLICY}
    if mode != SINGLE_HOST_POLICY:
        raise ValidationError("unsupported_storage_policy")
    expected_fields = {"mode", "device_id", "decision_date", "accepted_risks"}
    if set(policy) != expected_fields:
        raise ValidationError("single_host_policy_fields_invalid")
    exception_device = require_text(policy.get("device_id"), "storage_policy.device_id")
    if exception_device != "r1-sample01" or (device_id is not None and exception_device != device_id):
        raise ValidationError("single_host_policy_device_mismatch")
    decision_date = require_text(policy.get("decision_date"), "storage_policy.decision_date")
    try:
        datetime.strptime(decision_date, "%Y-%m-%d")
    except ValueError as error:
        raise ValidationError("storage_policy_decision_date_invalid") from error
    risks = policy.get("accepted_risks")
    if not isinstance(risks, list) or sorted(risks) != sorted(SINGLE_HOST_RISKS):
        raise ValidationError("single_host_policy_risks_not_acknowledged")
    return {
        "accepted_risks": list(SINGLE_HOST_RISKS),
        "decision_date": decision_date,
        "device_id": exception_device,
        "mode": SINGLE_HOST_POLICY,
    }


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


def validate_copies(copy_specs, classification, storages, expected_size, storage_policy):
    single_host = storage_policy["mode"] == SINGLE_HOST_POLICY
    minimum_copies = 1 if single_host else 2
    if not isinstance(copy_specs, list) or len(copy_specs) < minimum_copies:
        raise ValidationError("at_least_one_copy_required" if single_host else "at_least_two_copies_required")
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
        if classification == "sensitive" and not encrypted and not single_host:
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
    if len(storage_ids) < minimum_copies:
        raise ValidationError("copies_require_distinct_storage_ids")
    if len(hashes) != 1:
        raise ValidationError("copy_hash_mismatch")
    return metadata, next(iter(hashes))


def artifact_from_spec(area_name, kind, spec, offset, length, storages, default_source, storage_policy):
    name = require_text(spec.get("name", area_name if kind == "full" else None), "artifact.name")
    classification = spec.get("classification")
    if classification not in ("non_sensitive", "sensitive"):
        raise ValidationError(f"invalid_classification:{area_name}:{name}")
    copies, digest = validate_copies(
        spec.get("copies"), classification, storages, length, storage_policy
    )
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


def create_manifest(layout, identity, source, storages, storage_policy=None):
    if layout.get("schema_version") != SCHEMA_VERSION:
        raise ValidationError("unsupported_layout_schema_version")
    device_id = require_text(identity.get("id"), "device.id")
    storage_policy = validate_storage_policy(storage_policy, device_id)
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
        artifacts.append(artifact_from_spec(
            area_name, "full", full, 0, area_size, storages, source, storage_policy
        ))
        for region in regions:
            artifacts.append(artifact_from_spec(
                area_name, "region", region, region["offset"], region["length"], storages,
                source, storage_policy
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
            "device-files", "file", file_spec, 0, length, storages, source, storage_policy
        ))
    manifest = {
        "artifacts": artifacts,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "device": {
            "fingerprint": require_text(identity.get("fingerprint"), "device.fingerprint"),
            "hardware": require_text(identity.get("hardware"), "device.hardware"),
            "id": device_id,
        },
        "layout": {"areas": area_records},
        "schema_version": SCHEMA_VERSION,
        "storage_policy": storage_policy,
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
    storage_policy = validate_storage_policy(manifest.get("storage_policy"), device.get("id"))
    minimum_copies = 1 if storage_policy["mode"] == SINGLE_HOST_POLICY else 2
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
        if not isinstance(copies, list) or len(copies) < minimum_copies:
            raise ValidationError(
                "manifest_requires_one_copy" if minimum_copies == 1 else "manifest_requires_two_copies"
            )
        storage_ids = set()
        for copy in copies:
            storage_ids.add(require_text(copy.get("storage_id"), "copy.storage_id"))
            validate_relative_path(copy.get("path"), "copy.path")
            if (artifact["classification"] == "sensitive"
                    and copy.get("encrypted_storage") is not True
                    and storage_policy["mode"] != SINGLE_HOST_POLICY):
                raise ValidationError("manifest_sensitive_copy_not_encrypted")
        if len(storage_ids) < minimum_copies:
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
    storage_policy = validate_storage_policy(manifest.get("storage_policy"), manifest["device"]["id"])
    minimum_storages = 1 if storage_policy["mode"] == SINGLE_HOST_POLICY else 2
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
                encryption_ok = (artifact["classification"] != "sensitive"
                                 or copy.get("encrypted_storage") is True
                                 or storage_policy["mode"] == SINGLE_HOST_POLICY)
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
        if len(storage_ids) < minimum_storages:
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
    storage_policy = validate_storage_policy(manifest.get("storage_policy"), manifest["device"]["id"])
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
    if failures:
        status = "fail"
    elif pending:
        status = "pending"
    elif storage_policy["mode"] == SINGLE_HOST_POLICY:
        status = "pass_with_exception"
    else:
        status = "pass"
    return {
        "device": manifest["device"],
        "failures": sorted(set(failures)),
        "manifest_sha256": expected_manifest_hash,
        "pending": sorted(set(pending)),
        "schema_version": SCHEMA_VERSION,
        "storage_policy": storage_policy,
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
    create.add_argument("--policy-exception", help="Explicit device-scoped storage policy exception JSON")
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
    assemble = commands.add_parser("assemble-full-emmc", help="Assemble two full images from verified prefix and body")
    assemble.add_argument("--prefix-evidence", required=True)
    assemble.add_argument("--body-evidence", required=True)
    assemble.add_argument("--device-id", required=True)
    assemble.add_argument("--output", required=True)
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "assemble-full-emmc":
            result = assemble_full_emmc(
                args.prefix_evidence, args.body_evidence, args.output, args.device_id
            )
            print(f"R0 full eMMC assembly: {result['status']}")
            return 0
        if args.command == "create-manifest":
            layout = load_json(args.layout)
            manifest = create_manifest(
                layout,
                {"id": args.device_id, "hardware": args.hardware, "fingerprint": args.fingerprint},
                {"tool": args.tool, "version": args.tool_version},
                parse_storages(args.storage),
                load_json(args.policy_exception) if args.policy_exception else None,
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
        return 0 if result["status"] in ("pass", "pass_with_exception") else 1
    except (AttributeError, KeyError, OSError, TypeError, ValueError, json.JSONDecodeError, ValidationError) as error:
        print(f"R0 recovery tool refused operation: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
