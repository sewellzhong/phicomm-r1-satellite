#!/usr/bin/env python3
"""Extract and verify R1 factory-audio inputs from an already verified image copy."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile


DEVICE_ID = "r1-sample01"
FINGERPRINT = "Android/rk322x_echo/rk322x_echo:5.1.1/LMY49F/3448:user/release-keys"
SCHEMA_VERSION = 1
SECTOR_BYTES = 512
MATERIAL_PATHS = (
    "app/Unisound/Unisound.apk",
    "lib/libUni4micHalJNI.so",
    "lib/libUniLinearMicArray.so",
    "lib/libUniMicArray.so",
    "lib/libaec.so",
    "lib/libuni4michal.so",
    "lib/libuni4michalchance.so",
    "usr/uni_4mic_config/MicArrayConfig.ini",
    "usr/uni_4mic_config/MicArray_config.txt",
    "usr/uni_4mic_config/pcm_hw_config.txt",
    "usr/uni_4mic_config/wopt.bin",
    "vendor/firmware/ak7755_cram_data2.bin",
    "vendor/firmware/ak7755_ofreg_data2.bin",
    "vendor/firmware/ak7755_pram_data2.bin",
)


class AuditError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise AuditError(message)


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def safe_source(base, value, label):
    require(isinstance(value, str) and value, f"{label}_path_invalid")
    raw = Path(value)
    require(not raw.is_absolute() and ".." not in raw.parts, f"{label}_path_not_local")
    candidate = base / raw
    current = base
    for part in raw.parts:
        current = current / part
        require(not current.is_symlink(), f"{label}_symlink_rejected")
    path = candidate.resolve(strict=True)
    require(path.is_relative_to(base.resolve()), f"{label}_path_escape")
    require(path.is_file() and not path.is_symlink(), f"{label}_not_regular_file")
    return path


def regular_input(value, label):
    candidate = Path(value)
    require(not candidate.is_symlink(), f"{label}_symlink_rejected")
    path = candidate.resolve(strict=True)
    require(path.is_file(), f"{label}_not_regular_file")
    return path


def write_exclusive(path, data):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(data)


def validate_inputs(copy_manifest_path, verification_path, inventory_path):
    copy_manifest_path = regular_input(copy_manifest_path, "copy_manifest")
    verification_path = regular_input(verification_path, "copy_verification")
    inventory_path = regular_input(inventory_path, "inventory")
    copy_manifest = load_json(copy_manifest_path)
    verification = load_json(verification_path)
    inventory = load_json(inventory_path)

    for label, value in (("copy_manifest", copy_manifest),
                         ("verification", verification), ("inventory", inventory)):
        require(value.get("schema_version") == SCHEMA_VERSION, f"{label}_schema_invalid")
        require(value.get("device_id") == DEVICE_ID, f"{label}_device_mismatch")
    require(copy_manifest.get("operation") == "loader-image-copy"
            and copy_manifest.get("status") == "pass", "copy_manifest_not_passed")
    require(verification.get("operation") == "verify-loader-image-copy"
            and verification.get("status") == "pass", "copy_verification_not_passed")
    require(inventory.get("operation") == "read_only_android_storage_inventory"
            and inventory.get("status") == "pass_with_access_limits", "inventory_not_passed")
    require(inventory.get("identity", {}).get("ro.build.fingerprint") == FINGERPRINT,
            "inventory_fingerprint_mismatch")
    require(verification.get("source", {}).get("sha256") == sha256_file(copy_manifest_path),
            "copy_verification_source_mismatch")
    require(copy_manifest.get("android_inventory", {}).get("sha256") == sha256_file(inventory_path),
            "copy_manifest_inventory_mismatch")

    emmc = inventory.get("emmc", {})
    address = copy_manifest.get("address_space", {})
    prefix_bytes = address.get("physical_prefix_not_included_bytes")
    require(emmc.get("logical_block_bytes") == SECTOR_BYTES, "inventory_sector_size_invalid")
    require(isinstance(prefix_bytes, int) and prefix_bytes > 0
            and prefix_bytes % SECTOR_BYTES == 0, "physical_prefix_invalid")
    require(address.get("physical_offset_sectors_inferred") == prefix_bytes // SECTOR_BYTES,
            "physical_offset_mismatch")
    require(address.get("image_bytes") == emmc.get("bytes") - prefix_bytes,
            "image_geometry_mismatch")
    require(verification.get("expected_bytes_per_copy") == address.get("image_bytes")
            and verification.get("bytes_checked_per_copy") == address.get("image_bytes"),
            "copy_verification_geometry_mismatch")

    systems = [item for item in inventory.get("partitions", []) if item.get("name") == "system"]
    require(len(systems) == 1, "system_partition_not_unique")
    system = systems[0]
    require(system.get("read_only") is True, "system_partition_not_read_only")
    require(system.get("bytes") == system.get("sectors") * SECTOR_BYTES,
            "system_partition_size_mismatch")
    require(system.get("end_sector_exclusive") == system.get("start_sector") + system.get("sectors"),
            "system_partition_end_mismatch")
    image_start = system.get("start_sector") - address["physical_offset_sectors_inferred"]
    require(isinstance(image_start, int) and image_start >= 0, "system_before_image_start")
    image_end = image_start + system["sectors"]
    require(image_end <= address.get("image_sectors"), "system_partition_out_of_image")

    chunks = copy_manifest.get("chunks", [])
    require(isinstance(chunks, list) and chunks, "copy_chunks_missing")
    expected_start = 0
    storage_ids = None
    for expected_index, chunk in enumerate(chunks):
        require(chunk.get("index") == expected_index, "copy_chunk_index_invalid")
        require(chunk.get("start_sector") == expected_start, "copy_chunk_gap_or_overlap")
        require(chunk.get("bytes") == chunk.get("sectors") * SECTOR_BYTES,
                "copy_chunk_size_invalid")
        expected_start += chunk["sectors"]
        copies = chunk.get("copies", [])
        current_ids = {item.get("storage_id") for item in copies}
        require(len(copies) == 2 and len(current_ids) == 2 and None not in current_ids,
                "copy_chunk_requires_two_storage_ids")
        if storage_ids is None:
            storage_ids = current_ids
        require(current_ids == storage_ids, "copy_storage_ids_changed")
    require(expected_start == address.get("image_sectors"), "copy_chunks_do_not_cover_image")
    require(verification.get("chunks_checked") == len(chunks), "verification_chunk_count_mismatch")
    require(set(verification.get("overall_sha256", {})) == storage_ids,
            "verification_storage_ids_mismatch")
    return {
        "copy_manifest_path": copy_manifest_path,
        "verification_path": verification_path,
        "inventory_path": inventory_path,
        "copy_manifest": copy_manifest,
        "storage_ids": sorted(storage_ids),
        "system": system,
        "image_start_sector": image_start,
    }


def extract_storage(inputs, storage_id, output_path):
    start_byte = inputs["image_start_sector"] * SECTOR_BYTES
    end_byte = start_byte + inputs["system"]["bytes"]
    written = 0
    output_digest = hashlib.sha256()
    descriptor = os.open(output_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as output:
            for chunk in inputs["copy_manifest"]["chunks"]:
                chunk_start = chunk["start_sector"] * SECTOR_BYTES
                chunk_end = chunk_start + chunk["bytes"]
                overlap_start = max(start_byte, chunk_start)
                overlap_end = min(end_byte, chunk_end)
                if overlap_start >= overlap_end:
                    continue
                record = next(item for item in chunk["copies"]
                              if item["storage_id"] == storage_id)
                path = safe_source(inputs["copy_manifest_path"].parent, record.get("file"),
                                   f"chunk_{chunk['index']}_{storage_id}")
                require(path.stat().st_size == record.get("size") == chunk["bytes"],
                        "copy_chunk_file_size_mismatch")
                require(sha256_file(path) == record.get("sha256"), "copy_chunk_hash_mismatch")
                remaining = overlap_end - overlap_start
                with path.open("rb") as source:
                    source.seek(overlap_start - chunk_start)
                    while remaining:
                        data = source.read(min(1024 * 1024, remaining))
                        require(data, "copy_chunk_short_read")
                        output.write(data)
                        output_digest.update(data)
                        written += len(data)
                        remaining -= len(data)
    except Exception:
        raise
    require(written == inputs["system"]["bytes"], "system_extract_size_mismatch")
    return output_digest.hexdigest()


def extract_system(copy_manifest_path, verification_path, inventory_path, output_dir):
    inputs = validate_inputs(copy_manifest_path, verification_path, inventory_path)
    output_dir = Path(output_dir)
    require(not output_dir.exists(), "output_directory_exists")
    output_dir.mkdir(mode=0o700, parents=False)
    outputs = []
    for index, storage_id in enumerate(inputs["storage_ids"]):
        filename = f"system-copy-{chr(ord('a') + index)}.img"
        digest = extract_storage(inputs, storage_id, output_dir / filename)
        outputs.append({"file": filename, "storage_id": storage_id,
                        "bytes": inputs["system"]["bytes"], "sha256": digest})
    require(outputs[0]["sha256"] == outputs[1]["sha256"], "system_copies_mismatch")
    result = {
        "schema_version": SCHEMA_VERSION,
        "status": "pass_for_offline_factory_audio_only",
        "device_id": DEVICE_ID,
        "source": {
            "copy_manifest_sha256": sha256_file(inputs["copy_manifest_path"]),
            "copy_verification_sha256": sha256_file(inputs["verification_path"]),
            "inventory_sha256": sha256_file(inputs["inventory_path"]),
        },
        "partition": {
            "name": "system",
            "physical_start_sector": inputs["system"]["start_sector"],
            "image_start_sector": inputs["image_start_sector"],
            "sectors": inputs["system"]["sectors"],
            "bytes": inputs["system"]["bytes"],
            "sha256": outputs[0]["sha256"],
        },
        "copies": outputs,
    }
    write_exclusive(output_dir / "system-extraction.json",
                    (json.dumps(result, indent=2, sort_keys=True) + "\n").encode())
    return result


def validate_extraction_manifest(extraction_manifest_path):
    extraction_manifest_path = regular_input(extraction_manifest_path, "extraction_manifest")
    manifest = load_json(extraction_manifest_path)
    require(manifest.get("schema_version") == SCHEMA_VERSION, "extraction_schema_invalid")
    require(manifest.get("device_id") == DEVICE_ID, "extraction_device_mismatch")
    require(manifest.get("status") == "pass_for_offline_factory_audio_only",
            "extraction_not_passed")
    partition = manifest.get("partition", {})
    require(partition.get("name") == "system" and partition.get("bytes", 0) > 0,
            "extraction_partition_invalid")
    copies = manifest.get("copies", [])
    require(len(copies) == 2 and copies[0].get("sha256") == copies[1].get("sha256")
            == partition.get("sha256"), "extracted_system_copies_mismatch")
    paths = []
    for index, item in enumerate(copies):
        path = safe_source(extraction_manifest_path.parent, item.get("file"),
                           f"system_copy_{index}")
        require(path.stat().st_size == item.get("bytes") == partition["bytes"],
                "extracted_system_size_mismatch")
        require(sha256_file(path) == item.get("sha256"), "extracted_system_hash_mismatch")
        paths.append(path)
    return extraction_manifest_path, manifest, paths


def resolve_tool(value, label):
    path = Path(value).resolve(strict=True)
    require(path.is_file() and os.access(path, os.X_OK), f"{label}_not_executable")
    return path


def run_to_new_file(arguments, output_path):
    descriptor = os.open(output_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        subprocess.run([str(item) for item in arguments], stdout=output,
                       stderr=subprocess.PIPE, check=True)


def audit_materials(extraction_manifest_path, reference_path, output_dir,
                    seven_zip, dexdump, readelf, llvm_objdump):
    extraction_manifest_path, extraction, system_paths = validate_extraction_manifest(
        extraction_manifest_path
    )
    reference_path = regular_input(reference_path, "factory_audio_reference")
    reference = load_json(reference_path)
    require(reference.get("schema_version") == SCHEMA_VERSION,
            "factory_audio_reference_schema_invalid")
    require(reference.get("device", {}).get("id") == DEVICE_ID
            and reference.get("device", {}).get("build_fingerprint") == FINGERPRINT,
            "factory_audio_reference_device_mismatch")
    require(reference.get("status") == "static_abi_confirmed_runtime_shape_pending",
            "factory_audio_reference_status_invalid")
    require(reference.get("abi") == "armeabi-v7a", "factory_audio_reference_abi_invalid")
    tools = {
        "seven_zip": resolve_tool(seven_zip, "seven_zip"),
        "dexdump": resolve_tool(dexdump, "dexdump"),
        "readelf": resolve_tool(readelf, "readelf"),
        "llvm_objdump": resolve_tool(llvm_objdump, "llvm_objdump"),
    }
    output_dir = Path(output_dir)
    require(not output_dir.exists(), "material_output_directory_exists")
    output_dir.mkdir(mode=0o700, parents=False)
    materials = output_dir / "materials"
    analysis = output_dir / "analysis"
    materials.mkdir(mode=0o700)
    analysis.mkdir(mode=0o700)

    inventory = []
    for member in MATERIAL_PATHS:
        filename = member.replace("/", "__")
        destination = materials / filename
        run_to_new_file((tools["seven_zip"], "x", "-so", system_paths[0], member), destination)
        require(destination.stat().st_size > 0, "material_extract_empty:" + member)
        inventory.append({"system_path": member, "private_file": f"materials/{filename}",
                          "bytes": destination.stat().st_size,
                          "sha256": sha256_file(destination)})

    by_name = {Path(item["system_path"]).name: item for item in inventory}
    for name, expected_hash in reference.get("libraries", {}).items():
        require(name in by_name, "reference_library_not_extracted:" + name)
        require(by_name[name]["sha256"] == expected_hash, "reference_library_hash_mismatch:" + name)

    apk_record = by_name["Unisound.apk"]
    apk_path = output_dir / apk_record["private_file"]
    dex_path = materials / "Unisound__classes.dex"
    with zipfile.ZipFile(apk_path) as archive:
        require("classes.dex" in archive.namelist(), "unisound_classes_dex_missing")
        write_exclusive(dex_path, archive.read("classes.dex"))
    run_to_new_file((tools["dexdump"], "-d", dex_path),
                    analysis / "Unisound-classes.dexdump.txt")

    for name in reference["libraries"]:
        library = output_dir / by_name[name]["private_file"]
        run_to_new_file((tools["readelf"], "-Ws", library),
                        analysis / f"{name}.symbols.txt")
        run_to_new_file((tools["llvm_objdump"], "-d", "--triple=thumbv7a-linux-android", library),
                        analysis / f"{name}.disassembly.txt")

    analysis_files = []
    for path in sorted(analysis.iterdir()):
        analysis_files.append({"file": f"analysis/{path.name}", "bytes": path.stat().st_size,
                               "sha256": sha256_file(path)})
    result = {
        "schema_version": SCHEMA_VERSION,
        "status": "pass_materials_verified_analysis_generated",
        "claim_boundary": "offline_static_evidence_only_runtime_shape_pending",
        "device_id": DEVICE_ID,
        "source": {
            "auditor_sha256": sha256_file(Path(__file__).resolve()),
            "system_sha256": extraction["partition"]["sha256"],
            "system_extraction_manifest_sha256": sha256_file(extraction_manifest_path),
            "factory_audio_reference_sha256": sha256_file(reference_path),
        },
        "tools": {name: {"executable": path.name, "sha256": sha256_file(path)}
                  for name, path in tools.items()},
        "materials": inventory,
        "analysis": analysis_files,
    }
    write_exclusive(output_dir / "factory-audio-materials.json",
                    (json.dumps(result, indent=2, sort_keys=True) + "\n").encode())
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    extract = subparsers.add_parser("extract-system")
    extract.add_argument("--copy-manifest", required=True)
    extract.add_argument("--copy-verification", required=True)
    extract.add_argument("--inventory", required=True)
    extract.add_argument("--output-dir", required=True)
    materials = subparsers.add_parser("audit-materials")
    materials.add_argument("--extraction-manifest", required=True)
    materials.add_argument("--reference", required=True)
    materials.add_argument("--output-dir", required=True)
    materials.add_argument("--seven-zip", required=True)
    materials.add_argument("--dexdump", required=True)
    materials.add_argument("--readelf", required=True)
    materials.add_argument("--llvm-objdump", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "extract-system":
            extract_system(args.copy_manifest, args.copy_verification, args.inventory,
                           args.output_dir)
            print("R1 offline system extraction: pass")
        else:
            audit_materials(args.extraction_manifest, args.reference, args.output_dir,
                            args.seven_zip, args.dexdump, args.readelf, args.llvm_objdump)
            print("R1 offline factory-audio material audit: pass")
        return 0
    except (AuditError, FileExistsError, json.JSONDecodeError, OSError,
            subprocess.CalledProcessError, zipfile.BadZipFile) as error:
        print("R1 offline factory-audio audit refused: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
