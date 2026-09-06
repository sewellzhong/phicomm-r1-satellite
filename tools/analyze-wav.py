#!/usr/bin/env python3
import argparse
import json
import math
import struct
import wave
from pathlib import Path


def analyze(path: Path) -> dict:
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        sample_rate = wav.getframerate()
        frames = wav.getnframes()
        compression = wav.getcomptype()
        if channels not in (1, 2) or (sample_width, sample_rate, compression) != (2, 16000, "NONE"):
            raise ValueError(
                f"unexpected format: channels={channels} width={sample_width} "
                f"rate={sample_rate} compression={compression}"
            )
        data = wav.readframes(frames)

    values = [sample[0] for sample in struct.iter_unpack("<h", data)]
    sample_count = len(values)
    total = 0
    sum_squares = 0
    peak = 0
    clipped = 0
    for sample in values:
        absolute = abs(sample)
        total += sample
        sum_squares += sample * sample
        peak = max(peak, absolute)
        if absolute >= 32760:
            clipped += 1

    rms = math.sqrt(sum_squares / sample_count) if sample_count else 0.0
    channel_metrics = []
    for channel_index in range(channels):
        channel_values = values[channel_index::channels]
        channel_sum_squares = sum(sample * sample for sample in channel_values)
        channel_rms = math.sqrt(channel_sum_squares / len(channel_values)) if channel_values else 0.0
        channel_peak = max((abs(sample) for sample in channel_values), default=0)
        channel_metrics.append({
            "channel_index": channel_index,
            "rms": channel_rms,
            "rms_dbfs": 20.0 * math.log10(channel_rms / 32768.0) if channel_rms else None,
            "peak": channel_peak,
            "peak_dbfs": 20.0 * math.log10(channel_peak / 32768.0) if channel_peak else None,
        })

    return {
        "file": path.name,
        "channels": channels,
        "sample_width_bytes": sample_width,
        "sample_rate_hz": sample_rate,
        "frames": frames,
        "duration_seconds": frames / sample_rate,
        "pcm_bytes": len(data),
        "dc_offset": total / sample_count if sample_count else 0.0,
        "rms": rms,
        "rms_dbfs": 20.0 * math.log10(rms / 32768.0) if rms else None,
        "peak": peak,
        "peak_dbfs": 20.0 * math.log10(peak / 32768.0) if peak else None,
        "clipped_samples": clipped,
        "clipped_ratio": clipped / sample_count if sample_count else 0.0,
        "channel_metrics": channel_metrics,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("wav", type=Path)
    args = parser.parse_args()
    print(json.dumps(analyze(args.wav), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
