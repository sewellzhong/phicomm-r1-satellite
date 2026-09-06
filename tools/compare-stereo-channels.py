#!/usr/bin/env python3
import argparse
import json
import math
import struct
import wave
from pathlib import Path


def read_stereo(path: Path) -> tuple[list[int], list[int]]:
    with wave.open(str(path), "rb") as wav:
        actual = (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getcomptype())
        if actual != (2, 2, 16000, "NONE"):
            raise ValueError(f"unexpected stereo format for {path}: {actual}")
        values = [sample[0] for sample in struct.iter_unpack("<h", wav.readframes(wav.getnframes()))]
    return values[0::2], values[1::2]


def rms(values: list[int]) -> float:
    return math.sqrt(sum(value * value for value in values) / len(values)) if values else 0.0


def correlation(left: list[int], right: list[int]) -> float | None:
    if not left or len(left) != len(right):
        return None
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    covariance = sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right))
    left_variance = sum((a - left_mean) ** 2 for a in left)
    right_variance = sum((b - right_mean) ** 2 for b in right)
    denominator = math.sqrt(left_variance * right_variance)
    return covariance / denominator if denominator else None


def analyze(path: Path) -> dict:
    left, right = read_stereo(path)
    left_rms = rms(left)
    right_rms = rms(right)
    return {
        "file": path.name,
        "frames": len(left),
        "left_rms": left_rms,
        "right_rms": right_rms,
        "right_to_left_rms_db": (
            20.0 * math.log10(right_rms / left_rms) if left_rms and right_rms else None
        ),
        "left_right_pearson_correlation": correlation(left, right),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("stereo_wav", type=Path)
    args = parser.parse_args()
    print(json.dumps(analyze(args.stereo_wav), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
