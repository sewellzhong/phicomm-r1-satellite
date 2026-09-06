#!/usr/bin/env python3
import argparse
import json
import math
import struct
import wave
from pathlib import Path


def read(path: Path) -> list[int]:
    with wave.open(str(path), "rb") as wav:
        actual = (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getcomptype())
        if actual != (1, 2, 16000, "NONE"):
            raise ValueError(f"unexpected format for {path}: {actual}")
        return [sample[0] for sample in struct.iter_unpack("<h", wav.readframes(wav.getnframes()))]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("reference", type=Path)
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args()
    reference = read(args.reference)
    candidate = read(args.candidate)
    if len(reference) != len(candidate):
        raise ValueError("sample_count_mismatch")
    differences = [b - a for a, b in zip(reference, candidate)]
    reference_mean = sum(reference) / len(reference)
    candidate_mean = sum(candidate) / len(candidate)
    covariance = sum((a - reference_mean) * (b - candidate_mean)
                     for a, b in zip(reference, candidate))
    reference_energy = sum((a - reference_mean) ** 2 for a in reference)
    candidate_energy = sum((b - candidate_mean) ** 2 for b in candidate)
    correlation = covariance / math.sqrt(reference_energy * candidate_energy)
    print(json.dumps({
        "reference": args.reference.name,
        "candidate": args.candidate.name,
        "samples": len(reference),
        "pearson_correlation": correlation,
        "rmse_samples": math.sqrt(sum(value * value for value in differences) / len(differences)),
        "maximum_absolute_difference": max(map(abs, differences), default=0),
        "identical_samples": sum(value == 0 for value in differences),
    }, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
