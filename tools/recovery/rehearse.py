#!/usr/bin/env python3
"""Run an entirely synthetic R0 create/verify/pending/pass desktop rehearsal."""

import importlib.util
import json
from pathlib import Path
import tempfile


TOOL = Path(__file__).with_name("r1-recovery.py")
SPEC = importlib.util.spec_from_file_location("r1_recovery", TOOL)
recovery = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(recovery)


def encoded(value):
    return (json.dumps(value, sort_keys=True) + "\n").encode()


def passed(path):
    return {"status": "pass", "evidence": path, "evidence_sha256": "1" * 64}


def main():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        storages = {"media-a": root / "media-a", "media-b": root / "media-b"}
        for storage in storages.values():
            storage.mkdir()
            (storage / "full.img").write_bytes(b"abcdefgh")
            (storage / "boot.img").write_bytes(b"abcd")
            (storage / "private.img").write_bytes(b"efgh")
            (storage / "factory.bin").write_bytes(b"r1f")
        copies = lambda path, encrypted=False: [
            {"storage_id": name, "path": path, "encrypted_storage": encrypted}
            for name in storages
        ]
        layout = {
            "schema_version": 1,
            "areas": [{
                "name": "synthetic-emmc", "size": 8,
                "full_image": {"name": "full", "classification": "sensitive",
                               "copies": copies("full.img", True)},
                "regions": [
                    {"name": "boot", "offset": 0, "length": 4,
                     "classification": "non_sensitive", "copies": copies("boot.img")},
                    {"name": "private", "offset": 4, "length": 4,
                     "classification": "sensitive", "copies": copies("private.img", True)},
                ],
            }],
            "files": [{
                "name": "factory-audio", "length": 3,
                "classification": "non_sensitive",
                "source": {"tool": "synthetic-reader", "version": "1"},
                "copies": copies("factory.bin"),
            }],
        }
        identity = {"id": "r1-sample01", "hardware": "synthetic", "fingerprint": "synthetic/3448"}
        source = {"tool": "synthetic-reader", "version": "1"}
        manifest = recovery.create_manifest(layout, identity, source, storages)
        manifest_bytes = encoded(manifest)
        verification = recovery.verify_copies(manifest, storages, manifest_bytes)
        if verification["status"] != "pass":
            raise SystemExit("synthetic copy verification did not pass")
        pending = recovery.gate_report(manifest, manifest_bytes, verification, {"device": identity})
        if pending["status"] != "pending":
            raise SystemExit("incomplete recovery state did not remain pending")
        state = {
            "device": identity,
            "low_level_entry": passed("synthetic/low-level.json"),
            "controlled_full_restore": passed("synthetic/restore.json"),
            "post_restore_checks": {
                name: passed("synthetic/post-restore/" + name + ".json")
                for name in recovery.RECOVERY_CHECKS
            },
        }
        complete = recovery.gate_report(manifest, manifest_bytes, verification, state)
        if complete["status"] != "pass":
            raise SystemExit("complete synthetic recovery state did not pass")
    print("Synthetic R0 rehearsal passed: copies=pass, incomplete=pending, complete=pass")


if __name__ == "__main__":
    main()
