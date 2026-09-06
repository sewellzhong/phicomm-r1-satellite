#!/usr/bin/env python3
import argparse
import math
import struct
import wave
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--frequency", type=float, default=1000.0)
    parser.add_argument("--duration", type=float, default=2.0)
    args = parser.parse_args()

    sample_rate = 16000
    frame_count = int(sample_rate * args.duration)
    amplitude = int(32767 * 0.2)
    fade_frames = int(sample_rate * 0.02)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(args.output), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        for frame in range(frame_count):
            envelope = min(1.0, frame / fade_frames, (frame_count - frame - 1) / fade_frames)
            sample = int(amplitude * max(0.0, envelope)
                         * math.sin(2.0 * math.pi * args.frequency * frame / sample_rate))
            wav.writeframesraw(struct.pack("<h", sample))


if __name__ == "__main__":
    main()
