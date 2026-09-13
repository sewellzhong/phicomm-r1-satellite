#!/usr/bin/env python3
"""Extract a verified sepolicy from two identical R1 boot reads."""

import argparse
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
BOOT_TOOL = ROOT / "tools/factory_audio/build-experimental-boot.py"
SPEC = importlib.util.spec_from_file_location("r1_boot", BOOT_TOOL)
boot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(boot)


class ExtractError(RuntimeError):
    pass


def require(value, message):
    if not value:
        raise ExtractError(message)


def digest_bytes(value):
    return hashlib.sha256(value).hexdigest()


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def extract(args):
    first = Path(args.boot_a).resolve(strict=True)
    second = Path(args.boot_b).resolve(strict=True)
    require(first.is_file() and second.is_file(), "boot_copy_invalid")
    require(not first.is_symlink() and not second.is_symlink(), "boot_copy_symlink")
    require(not os.path.samefile(first, second), "boot_copies_not_independent")
    first_hash = digest(first)
    require(first_hash == digest(second), "boot_copies_differ")
    require(first_hash == args.expected_boot_sha256.lower(), "boot_hash_unexpected")
    image = first.read_bytes()
    values, kernel, ramdisk, trailing = boot.boot_parts(image)
    require(image[576:596] == boot.rockchip_boot_id(
        image, kernel, ramdisk, trailing), "boot_id_invalid")
    entries = boot.parse_cpio(gzip.decompress(ramdisk))
    policies = [entry.data for entry in entries if entry.name == "sepolicy"]
    require(len(policies) == 1 and len(policies[0]) >= 100000,
            "embedded_policy_invalid")
    output = Path(args.output).resolve(strict=False)
    try:
        output.relative_to(ROOT)
        raise ExtractError("private_policy_output_must_be_outside_repository")
    except ValueError:
        pass
    require(not output.exists(), "policy_output_exists")
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(policies[0])
        stream.flush()
        os.fsync(stream.fileno())
    return {
        "status": "pass_read_only_extraction",
        "boot_sha256": first_hash,
        "policy_sha256": digest_bytes(policies[0]),
        "policy_bytes": len(policies[0]),
        "page_size": values[7],
        "output": str(output),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--boot-a", required=True)
    parser.add_argument("--boot-b", required=True)
    parser.add_argument("--expected-boot-sha256", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(extract(args), sort_keys=True))
        return 0
    except (ExtractError, OSError, ValueError, KeyError, gzip.BadGzipFile) as error:
        print("R1 boot policy extraction refused: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
