#!/usr/bin/env python3
import argparse
import math
import struct
import wave
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--gain-db", type=float, required=True)
    args = parser.parse_args()

    with wave.open(str(args.input), "rb") as source:
        params = source.getparams()
        if (params.nchannels, params.sampwidth, params.framerate, params.comptype) \
                != (1, 2, 16000, "NONE"):
            raise ValueError(f"unexpected input format: {params}")
        pcm = source.readframes(params.nframes)

    multiplier = math.pow(10.0, args.gain_db / 20.0)
    amplified = bytearray()
    for (sample,) in struct.iter_unpack("<h", pcm):
        scaled = int(round(sample * multiplier))
        scaled = max(-32768, min(32767, scaled))
        amplified.extend(struct.pack("<h", scaled))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(args.output), "wb") as destination:
        destination.setnchannels(1)
        destination.setsampwidth(2)
        destination.setframerate(16000)
        destination.writeframes(amplified)


if __name__ == "__main__":
    main()
