#!/usr/bin/env python3
"""Audit a locally pulled factory-agent validation capture; never contacts a device."""

import argparse
import hashlib
import json
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


def audit(wav_path, metadata_path, device):
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
    return {
        "status": "pass",
        "device": device,
        "wav_sha256": wav_digest,
        "metadata_sha256": sha256(metadata_path),
        "frames": frames,
        "sequence_gaps": 0,
        "agent_dropped_frames": 0,
        "doa_valid_frames": doa_valid_frames,
        "claimed_aec_reference_channels": integer(values, "aec_reference_channels_claimed"),
        "claimed_aec_active": values.get("aec_active_claimed") == "true",
        "claim_boundary": "transport_and_reported_doa_only",
        "unverified": [
            "independent_four_microphone_response",
            "runtime_output_channel_shape",
            "aec_cancellation_effect",
            "dsp_output_quality",
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", required=True)
    parser.add_argument("--wav", required=True)
    parser.add_argument("--metadata", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        result = audit(args.wav, args.metadata, args.device)
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
