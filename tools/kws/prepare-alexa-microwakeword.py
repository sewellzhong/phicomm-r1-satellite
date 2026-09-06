#!/usr/bin/env python3
"""Download pinned upstream Alexa assets; never reuse Camila weights."""
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

COMMIT = "05b65922cc433c9df13e98e32a7fe520758c837e"
SHA256 = "9011a8155b04de858c48038529235cbc0e42e9fca05a55bf588cb80a653a723b"
BASE = f"https://raw.githubusercontent.com/esphome/micro-wake-word-models/{COMMIT}/"
ROOT = Path(__file__).resolve().parents[2] / "local-deps/alexa-microwakeword-r1"


def main():
    payloads = {}
    for remote, local in [
        ("models/v2/alexa.tflite", "assets/alexa_microwakeword.tflite"),
        ("models/v2/alexa.json", "alexa.json"),
        ("LICENSE", "LICENSE"),
    ]:
        with urlopen(BASE + remote, timeout=60) as response:
            payloads[local] = response.read()
    if hashlib.sha256(payloads["assets/alexa_microwakeword.tflite"]).hexdigest() != SHA256:
        raise ValueError("Alexa model checksum mismatch")
    metadata = json.loads(payloads["alexa.json"])
    if metadata["wake_word"] != "Alexa" or metadata["version"] != 2:
        raise ValueError("Unexpected Alexa manifest")
    for name, data in payloads.items():
        destination = ROOT / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_bytes(data)
        temporary.replace(destination)
    print(f"commit={COMMIT}\nmodel_sha256={SHA256}\n{ROOT}")


if __name__ == "__main__":
    main()
