#!/usr/bin/env python3
"""Generate the self-owned factory-audio Java Lite protocol."""

from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[2]
PROTO = ROOT / "protocol/factory_audio/factory_audio.proto"
PROTOC = ROOT / "local-deps/protoc-3.25.5/protoc"
OUT = ROOT / "android/r1-probe/app/build/generated/factory_audio"
EXPECTED_PROTOC_SHA256 = "d69b0a9ac8264bb3d464ae22742430943aa0a6cdf3734180af5a607c0bf8adaa"


def sha256(path):
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if not PROTOC.is_file() or sha256(PROTOC) != EXPECTED_PROTOC_SHA256:
        raise SystemExit("Missing or invalid pinned protoc 3.25.5; run tools/dev/prepare.py")
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    subprocess.run([
        str(PROTOC), "-I" + str(PROTO.parent), "--java_out=lite:" + str(OUT), str(PROTO)
    ], check=True)
    print("Generated factory-audio Java Lite protocol v1.")


if __name__ == "__main__":
    main()
