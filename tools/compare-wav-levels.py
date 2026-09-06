#!/usr/bin/env python3
import argparse
import json
import math
import struct
import wave
from pathlib import Path


EXPECTED_FORMAT = (1, 2, 16000, "NONE")


def samples(path: Path) -> list[int]:
    with wave.open(str(path), "rb") as wav:
        actual_format = (
            wav.getnchannels(),
            wav.getsampwidth(),
            wav.getframerate(),
            wav.getcomptype(),
        )
        if actual_format != EXPECTED_FORMAT:
            raise ValueError(f"unexpected format for {path}: {actual_format}")
        data = wav.readframes(wav.getnframes())

    return [sample[0] for sample in struct.iter_unpack("<h", data)]


def rms(values: list[int]) -> float:
    if not values:
        return 0.0
    return math.sqrt(sum(sample * sample for sample in values) / len(values))


def percentile_95(values: list[float]) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    return ordered[int(0.95 * (len(ordered) - 1))]


def window_rms(values: list[int], window_samples: int) -> list[float]:
    return [rms(values[offset:offset + window_samples])
            for offset in range(0, len(values), window_samples)]


def dbfs(value: float) -> float | None:
    return 20.0 * math.log10(value / 32768.0) if value else None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("silence", type=Path)
    parser.add_argument("speech", type=Path)
    args = parser.parse_args()

    silence_samples = samples(args.silence)
    speech_samples = samples(args.speech)
    silence_rms = rms(silence_samples)
    speech_rms = rms(speech_samples)
    snr_db = None
    if silence_rms and speech_rms:
        snr_db = 20.0 * math.log10(speech_rms / silence_rms)

    window_ms = 100
    window_samples = 16000 * window_ms // 1000
    silence_p95 = percentile_95(window_rms(silence_samples, window_samples))
    speech_p95 = percentile_95(window_rms(speech_samples, window_samples))
    active_delta_db = None
    if silence_p95 and speech_p95:
        active_delta_db = 20.0 * math.log10(speech_p95 / silence_p95)

    print(json.dumps({
        "silence_file": args.silence.name,
        "speech_file": args.speech.name,
        "silence_rms": silence_rms,
        "silence_rms_dbfs": dbfs(silence_rms),
        "speech_rms": speech_rms,
        "speech_rms_dbfs": dbfs(speech_rms),
        "speech_to_silence_db": snr_db,
        "meets_10db_level_separation": snr_db is not None and snr_db >= 10.0,
        "window_ms": window_ms,
        "silence_window_rms_p95_dbfs": dbfs(silence_p95),
        "speech_window_rms_p95_dbfs": dbfs(speech_p95),
        "active_window_p95_delta_db": active_delta_db,
    }, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
