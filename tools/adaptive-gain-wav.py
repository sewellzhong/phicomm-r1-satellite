#!/usr/bin/env python3
import argparse
import json
import math
import struct
import wave
from pathlib import Path


SAMPLE_RATE = 16000
FRAME_SAMPLES = 320


def read_mono(path: Path) -> list[int]:
    with wave.open(str(path), "rb") as wav:
        actual = (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getcomptype())
        if actual != (1, 2, SAMPLE_RATE, "NONE"):
            raise ValueError(f"unexpected format for {path}: {actual}")
        return [sample[0] for sample in struct.iter_unpack("<h", wav.readframes(wav.getnframes()))]


def rms(samples: list[int]) -> float:
    return math.sqrt(sum(sample * sample for sample in samples) / len(samples)) if samples else 0.0


def dbfs(value: float) -> float | None:
    return 20.0 * math.log10(value / 32768.0) if value else None


def write_mono(path: Path, samples: list[float]) -> int:
    clipped = 0
    encoded = bytearray()
    for sample in samples:
        rounded = int(round(sample))
        if rounded > 32767:
            rounded = 32767
            clipped += 1
        elif rounded < -32768:
            rounded = -32768
            clipped += 1
        encoded.extend(struct.pack("<h", rounded))
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(encoded)
    return clipped


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("noise_wav", type=Path)
    parser.add_argument("input_wav", type=Path)
    parser.add_argument("output_wav", type=Path)
    parser.add_argument("--target-rms-dbfs", type=float, default=-28.0)
    parser.add_argument("--max-gain-db", type=float, default=18.0)
    parser.add_argument("--activity-ratio", type=float, default=2.0)
    parser.add_argument("--peak-limit-dbfs", type=float, default=-1.0)
    parser.add_argument("--inactive-gain-db", type=float, default=-18.0)
    args = parser.parse_args()
    if args.max_gain_db < 0.0 or args.activity_ratio <= 1.0 or args.peak_limit_dbfs > 0.0:
        raise ValueError("invalid_adaptive_gain_parameters")

    noise = read_mono(args.noise_wav)
    source = read_mono(args.input_wav)
    noise_rms = rms(noise)
    activity_threshold = noise_rms * args.activity_ratio
    target_rms = 32768.0 * 10.0 ** (args.target_rms_dbfs / 20.0)
    maximum_gain = 10.0 ** (args.max_gain_db / 20.0)
    peak_limit = 32768.0 * 10.0 ** (args.peak_limit_dbfs / 20.0)
    inactive_gain = 10.0 ** (args.inactive_gain_db / 20.0)
    current_gain = inactive_gain
    previous_gain = inactive_gain
    active_frames = 0
    gains = []
    output = []

    for offset in range(0, len(source), FRAME_SAMPLES):
        frame = source[offset:offset + FRAME_SAMPLES]
        frame_rms = rms(frame)
        frame_peak = max((abs(sample) for sample in frame), default=0)
        active = frame_rms >= activity_threshold
        if active and frame_rms > 0.0:
            desired_gain = min(maximum_gain, max(1.0, target_rms / frame_rms))
            active_frames += 1
        else:
            desired_gain = inactive_gain
        if frame_peak > 0:
            desired_gain = min(desired_gain, peak_limit / frame_peak)
        desired_gain = max(0.0, desired_gain)
        smoothing = 0.65 if desired_gain > current_gain else 0.25
        current_gain += smoothing * (desired_gain - current_gain)
        gains.append(current_gain)
        denominator = max(1, len(frame) - 1)
        for index, sample in enumerate(frame):
            interpolation = index / denominator
            gain = previous_gain + (current_gain - previous_gain) * interpolation
            output.append(sample * gain)
        previous_gain = current_gain

    clipped = write_mono(args.output_wav, output)
    print(json.dumps({
        "algorithm": "20ms_activity_gated_adaptive_gain_with_peak_limit",
        "noise_file": args.noise_wav.name,
        "input_file": args.input_wav.name,
        "output_file": args.output_wav.name,
        "sample_rate_hz": SAMPLE_RATE,
        "frame_ms": 20,
        "noise_rms_dbfs": dbfs(noise_rms),
        "activity_threshold_dbfs": dbfs(activity_threshold),
        "target_rms_dbfs": args.target_rms_dbfs,
        "max_gain_db": args.max_gain_db,
        "peak_limit_dbfs": args.peak_limit_dbfs,
        "inactive_gain_db": args.inactive_gain_db,
        "attack_smoothing": 0.65,
        "release_smoothing": 0.25,
        "active_frames": active_frames,
        "total_frames": len(gains),
        "minimum_applied_gain_db": 20.0 * math.log10(min(gains)) if gains else None,
        "maximum_applied_gain_db": 20.0 * math.log10(max(gains)) if gains else None,
        "mean_applied_gain_db": (
            sum(20.0 * math.log10(gain) for gain in gains) / len(gains) if gains else None
        ),
        "clipped_samples": clipped,
    }, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
