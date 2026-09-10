#!/usr/bin/env python3
"""Audit a locally pulled factory-agent validation capture; never contacts a device."""

import argparse
from array import array
import hashlib
import json
import math
from pathlib import Path
import sys
import wave


EXPECTED_BACKEND = "unisound_uni4mic_3448"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def load_metadata(path):
    values = {}
    for number, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        require("=" in raw, f"metadata_line_{number}_invalid")
        key, value = raw.split("=", 1)
        require(key and key not in values, f"metadata_key_{key or number}_duplicate")
        values[key] = value
    return values


def integer(values, key):
    require(key in values, f"metadata_{key}_missing")
    try:
        return int(values[key])
    except ValueError as error:
        raise RuntimeError(f"metadata_{key}_invalid") from error


def circular_histogram_stats(histogram):
    total = sum(histogram)
    if total == 0:
        return {
            "mean_degrees": None,
            "resultant_length": 0.0,
            "peak_bin_degrees": None,
            "peak_bin_frames": 0,
        }
    x = 0.0
    y = 0.0
    for index, count in enumerate(histogram):
        angle = math.radians(index * 10 + 5)
        x += count * math.cos(angle)
        y += count * math.sin(angle)
    mean = math.degrees(math.atan2(y, x)) % 360.0
    peak = max(range(len(histogram)), key=histogram.__getitem__)
    return {
        "mean_degrees": mean,
        "resultant_length": math.hypot(x, y) / total,
        "peak_bin_degrees": peak * 10 + 5,
        "peak_bin_frames": histogram[peak],
    }


def analyze_diagnostic_wav(path, channels, selected_channel, pcm_bytes, mono_pcm):
    require(channels in (1, 2), "validation_diagnostic_channels_invalid")
    require(0 <= selected_channel < channels,
            "validation_diagnostic_selected_channel_invalid")
    with wave.open(str(path), "rb") as recording:
        require(recording.getnchannels() == channels,
                "validation_diagnostic_wav_channel_mismatch")
        require(recording.getsampwidth() == 2, "validation_diagnostic_wav_not_s16le")
        require(recording.getframerate() == 16000, "validation_diagnostic_wav_not_16khz")
        payload = recording.readframes(recording.getnframes())
    require(len(payload) == pcm_bytes, "validation_diagnostic_wav_length_mismatch")
    require(len(payload) % (channels * 2) == 0, "validation_diagnostic_pcm_alignment_invalid")
    samples = array("h")
    samples.frombytes(payload)
    if sys.byteorder != "little":
        samples.byteswap()
    per_channel = [samples[index::channels] for index in range(channels)]
    channel_stats = []
    for values in per_channel:
        count = len(values)
        square_sum = sum(value * value for value in values)
        channel_stats.append({
            "samples": count,
            "nonzero_samples": sum(value != 0 for value in values),
            "peak_absolute": max((abs(value) for value in values), default=0),
            "rms": math.sqrt(square_sum / count) if count else 0.0,
        })
    channel_bytes = []
    for values in per_channel:
        encoded = array("h", values)
        if sys.byteorder != "little":
            encoded.byteswap()
        channel_bytes.append(encoded.tobytes())
    mono_matches = [mono_pcm == value for value in channel_bytes]
    require(mono_matches[selected_channel], "validation_selected_channel_pcm_mismatch")
    pair_equal_samples = None
    pair_identical = None
    if channels == 2:
        pair_equal_samples = sum(a == b for a, b in zip(per_channel[0], per_channel[1]))
        pair_identical = pair_equal_samples == len(per_channel[0])
    return {
        "channels": channels,
        "selected_output_channel": selected_channel,
        "pcm_bytes": pcm_bytes,
        "channel_stats": channel_stats,
        "mono_matches_diagnostic_channels": mono_matches,
        "channel_pair_equal_samples": pair_equal_samples,
        "channel_pair_identical": pair_identical,
        "distinct_nonzero_two_channel_signal": channels == 2
            and all(item["nonzero_samples"] > 0 for item in channel_stats)
            and not pair_identical,
    }


def audit(wav_path, metadata_path, device, diagnostic_wav_path=None):
    require(device == "r1-sample01", "device_not_r1_sample01")
    wav_path = Path(wav_path)
    metadata_path = Path(metadata_path)
    require(wav_path.is_file(), "validation_wav_missing")
    require(metadata_path.is_file(), "validation_metadata_missing")
    values = load_metadata(metadata_path)
    require(values.get("attestation") == "validation_only_not_production",
            "production_boundary_missing")
    require(values.get("source") == "factory_proxy_unattested_validation",
            "validation_source_mismatch")
    require(values.get("backend") == EXPECTED_BACKEND, "validation_backend_mismatch")
    require(values.get("vendor_board_version"), "validation_board_version_missing")
    require(integer(values, "raw_mic_channels_claimed") == 4,
            "validation_four_mic_claim_missing")
    require(values.get("array_processing_claimed") == "true",
            "validation_array_claim_missing")
    frames = integer(values, "frames")
    pcm_bytes = integer(values, "pcm_bytes")
    require(frames > 0 and pcm_bytes == frames * 640, "validation_frame_count_mismatch")
    require(integer(values, "last_sequence") - integer(values, "first_sequence") + 1 == frames,
            "validation_sequence_range_mismatch")
    require(integer(values, "sequence_gaps") == 0, "validation_sequence_gaps_present")
    require(integer(values, "agent_dropped_frames") == 0, "validation_agent_drops_present")
    doa_valid_frames = integer(values, "doa_valid_frames")
    require(0 <= doa_valid_frames <= frames, "validation_doa_count_invalid")
    histogram = [int(item) for item in values.get("doa_histogram_10_degrees", "").split(",")]
    require(len(histogram) == 36 and all(item >= 0 for item in histogram),
            "validation_doa_histogram_invalid")
    require(sum(histogram) == doa_valid_frames, "validation_doa_histogram_count_mismatch")
    wav_digest = sha256(wav_path)
    require(values.get("wav_sha256") == wav_digest, "validation_wav_hash_mismatch")
    with wave.open(str(wav_path), "rb") as recording:
        require(recording.getnchannels() == 1, "validation_wav_not_mono")
        require(recording.getsampwidth() == 2, "validation_wav_not_s16le")
        require(recording.getframerate() == 16000, "validation_wav_not_16khz")
        require(recording.getnframes() * 2 == pcm_bytes, "validation_wav_length_mismatch")
        mono_pcm = recording.readframes(recording.getnframes())
    diagnostic_channels = integer(values, "diagnostic_output_channels") \
        if "diagnostic_output_channels" in values else 0
    diagnostic_pcm_bytes = integer(values, "diagnostic_pcm_bytes") \
        if "diagnostic_pcm_bytes" in values else 0
    diagnostic = None
    if diagnostic_channels == 0:
        require(diagnostic_pcm_bytes == 0, "validation_diagnostic_metadata_inconsistent")
        require(not diagnostic_wav_path, "validation_unexpected_diagnostic_wav")
    else:
        selected_channel = integer(values, "diagnostic_selected_output_channel")
        require(diagnostic_wav_path is not None, "validation_diagnostic_wav_missing")
        diagnostic_path = Path(diagnostic_wav_path)
        require(diagnostic_path.is_file(), "validation_diagnostic_wav_missing")
        require(values.get("diagnostic_wav_name") == diagnostic_path.name,
                "validation_diagnostic_wav_name_mismatch")
        diagnostic_digest = sha256(diagnostic_path)
        require(values.get("diagnostic_wav_sha256") == diagnostic_digest,
                "validation_diagnostic_wav_hash_mismatch")
        require(diagnostic_pcm_bytes == frames * 640 * diagnostic_channels,
                "validation_diagnostic_frame_count_mismatch")
        diagnostic = analyze_diagnostic_wav(
            diagnostic_path, diagnostic_channels, selected_channel,
            diagnostic_pcm_bytes, mono_pcm)
        diagnostic["wav_sha256"] = diagnostic_digest
    return {
        "status": "pass",
        "device": device,
        "wav_sha256": wav_digest,
        "metadata_sha256": sha256(metadata_path),
        "frames": frames,
        "sequence_gaps": 0,
        "agent_dropped_frames": 0,
        "doa_valid_frames": doa_valid_frames,
        "doa_valid_fraction": doa_valid_frames / frames,
        "doa_histogram_10_degrees": histogram,
        "doa_circular_stats": circular_histogram_stats(histogram),
        "claimed_aec_reference_channels": integer(values, "aec_reference_channels_claimed"),
        "claimed_aec_active": values.get("aec_active_claimed") == "true",
        "claim_boundary": ("transport_reported_doa_and_runtime_output_shape"
                           if diagnostic is not None else "transport_and_reported_doa_only"),
        "diagnostic_output": diagnostic,
        "unverified": [
            "independent_four_microphone_response",
            "aec_cancellation_effect",
            "dsp_output_quality",
        ] + ([] if diagnostic is not None else ["runtime_output_channel_shape"]),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", required=True)
    parser.add_argument("--wav", required=True)
    parser.add_argument("--metadata", required=True)
    parser.add_argument("--diagnostic-wav")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        result = audit(args.wav, args.metadata, args.device, args.diagnostic_wav)
        output = Path(args.output)
        require(not output.exists(), "output_already_exists")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, RuntimeError, ValueError, wave.Error) as error:
        print("Validation capture audit refused: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
