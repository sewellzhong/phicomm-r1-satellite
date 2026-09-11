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
PLAYBACK_ELAPSED_CLOCK_TOLERANCE_MS = 10


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


def playback_elapsed_consistent(reported_ms, observed_ms):
    return 0 < reported_ms <= observed_ms + PLAYBACK_ELAPSED_CLOCK_TOLERANCE_MS


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


def analyze_micarray_wav(path, name, channels, pcm_bytes, nonzero_bytes):
    path = Path(path)
    require(path.is_file(), f"validation_micarray_{name}_wav_missing")
    with wave.open(str(path), "rb") as recording:
        require(recording.getnchannels() == channels,
                f"validation_micarray_{name}_wav_channel_mismatch")
        require(recording.getsampwidth() == 2,
                f"validation_micarray_{name}_wav_not_s16le")
        require(recording.getframerate() == 16000,
                f"validation_micarray_{name}_wav_not_16khz")
        require(recording.getcomptype() == "NONE",
                f"validation_micarray_{name}_wav_compressed")
        frames = recording.getnframes()
        payload = recording.readframes(frames)
    require(len(payload) == pcm_bytes,
            f"validation_micarray_{name}_wav_length_mismatch")
    require(sum(value != 0 for value in payload) == nonzero_bytes,
            f"validation_micarray_{name}_wav_nonzero_mismatch")
    return {
        "name": path.name,
        "sha256": sha256(path),
        "channels": channels,
        "frames": frames,
        "pcm_bytes": pcm_bytes,
        "nonzero_bytes": nonzero_bytes,
    }


def audit(wav_path, metadata_path, device, diagnostic_wav_path=None,
          playback_reference_wav_path=None, micarray_wav_paths=None):
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
    require(integer(values, "aec_reference_channels_configured") == 2,
            "validation_aec_configuration_missing")
    require(values.get("aec_configured") == "true",
            "validation_aec_configuration_missing")
    require(integer(values, "aec_reference_channels_claimed") == 0,
            "validation_unproven_aec_channels_claimed")
    require(values.get("aec_active_claimed") == "false",
            "validation_unproven_aec_activity_claimed")
    require(values.get("array_processing_claimed") == "true",
            "validation_array_claim_missing")
    vendor_debug_requested = values.get("vendor_debug_files_requested", "false")
    vendor_debug_active = values.get("vendor_debug_files_active", "false")
    require(vendor_debug_requested in {"true", "false"}
            and vendor_debug_active in {"true", "false"},
            "validation_vendor_debug_state_invalid")
    require(vendor_debug_requested == vendor_debug_active,
            "validation_vendor_debug_not_active")
    micarray_tap_requested = values.get("micarray_diagnostic_tap_requested", "false")
    micarray_tap_active = values.get("micarray_diagnostic_tap_active", "false")
    require(micarray_tap_requested in {"true", "false"}
            and micarray_tap_active in {"true", "false"},
            "validation_micarray_tap_state_invalid")
    require(micarray_tap_requested == micarray_tap_active,
            "validation_micarray_tap_not_active")
    micarray_tap = None
    if micarray_tap_requested == "true":
        calls = integer(values, "micarray_diagnostic_tap_calls")
        first = integer(values, "micarray_diagnostic_tap_first_sequence")
        last = integer(values, "micarray_diagnostic_tap_last_sequence")
        gaps = integer(values, "micarray_diagnostic_tap_sequence_gaps")
        raw_bytes = integer(values, "micarray_diagnostic_tap_raw_bytes")
        echo_bytes = integer(values, "micarray_diagnostic_tap_echo_bytes")
        asr_bytes = integer(values, "micarray_diagnostic_tap_asr_bytes")
        vad_bytes = integer(values, "micarray_diagnostic_tap_vad_bytes")
        require(calls > 0 and first > 0 and last - first + 1 == calls,
                "validation_micarray_tap_sequence_range_mismatch")
        require(gaps == 0, "validation_micarray_tap_sequence_gaps_present")
        require(raw_bytes == calls * 256 * 4 * 2,
                "validation_micarray_tap_raw_shape_mismatch")
        require(echo_bytes == calls * 256 * 2 * 2,
                "validation_micarray_tap_echo_shape_mismatch")
        require(0 < asr_bytes == vad_bytes <= calls * 256 * 2,
                "validation_micarray_tap_output_shape_mismatch")
        payloads = {}
        for name, byte_count, channels in (
                ("raw", raw_bytes, 4), ("echo", echo_bytes, 2),
                ("asr", asr_bytes, 1), ("vad", vad_bytes, 1)):
            nonzero = integer(values, "micarray_diagnostic_tap_" + name
                              + "_nonzero_bytes")
            require(0 < nonzero <= byte_count,
                    "validation_micarray_tap_" + name + "_payload_empty")
            payloads[name] = {"bytes": byte_count, "nonzero_bytes": nonzero}
        sidecars = {}
        require(micarray_wav_paths is not None,
                "validation_micarray_sidecars_missing")
        for name, byte_count, channels in (
                ("raw", raw_bytes, 4), ("echo", echo_bytes, 2),
                ("asr", asr_bytes, 1), ("vad", vad_bytes, 1)):
            nonzero = payloads[name]["nonzero_bytes"]
            prefix = "micarray_diagnostic_tap_" + name + "_wav_"
            sidecar_path = micarray_wav_paths.get(name)
            require(sidecar_path is not None,
                    f"validation_micarray_{name}_wav_missing")
            require(Path(sidecar_path).name == values.get(prefix + "name"),
                    f"validation_micarray_{name}_wav_name_mismatch")
            require(integer(values, prefix + "channels") == channels,
                    f"validation_micarray_{name}_wav_channel_metadata_mismatch")
            require(integer(values, prefix + "pcm_bytes") == byte_count,
                    f"validation_micarray_{name}_wav_length_metadata_mismatch")
            analyzed = analyze_micarray_wav(
                sidecar_path, name, channels, byte_count, nonzero)
            require(values.get(prefix + "sha256") == analyzed["sha256"],
                    f"validation_micarray_{name}_wav_hash_mismatch")
            sidecars[name] = analyzed
        require(values.get("micarray_diagnostic_tap_final_active") == "true",
                "validation_micarray_tap_not_active_at_final_health")
        dropped = integer(values, "micarray_diagnostic_tap_dropped")
        invalid = integer(values, "micarray_diagnostic_tap_invalid")
        require(dropped == 0,
                "validation_micarray_tap_drops_present")
        require(invalid == 0,
                "validation_micarray_tap_invalid_present")
        diagnostic_schema = (integer(values, "micarray_diagnostic_schema")
                             if "micarray_diagnostic_schema" in values else 1)
        require(diagnostic_schema in (1, 2),
                "validation_micarray_diagnostic_schema_invalid")
        outside_window = 0
        invalid_input_shape = 0
        invalid_output_length = 0
        invalid_output_pointer = 0
        unexpected_producer = 0
        queue_full = 0
        if diagnostic_schema == 2:
            outside_window = integer(values, "micarray_diagnostic_tap_outside_window")
            invalid_input_shape = integer(
                values, "micarray_diagnostic_tap_invalid_input_shape")
            invalid_output_length = integer(
                values, "micarray_diagnostic_tap_invalid_output_length")
            invalid_output_pointer = integer(
                values, "micarray_diagnostic_tap_invalid_output_pointer")
            unexpected_producer = integer(
                values, "micarray_diagnostic_tap_unexpected_producer")
            queue_full = integer(values, "micarray_diagnostic_tap_queue_full")
        require(outside_window >= 0,
                "validation_micarray_tap_outside_window_invalid")
        require(invalid_input_shape == 0,
                "validation_micarray_tap_invalid_input_shape_present")
        require(invalid_output_length == 0,
                "validation_micarray_tap_invalid_output_length_present")
        require(invalid_output_pointer == 0,
                "validation_micarray_tap_invalid_output_pointer_present")
        require(unexpected_producer == 0,
                "validation_micarray_tap_unexpected_producer_present")
        require(queue_full == 0,
                "validation_micarray_tap_queue_full_present")
        require(invalid == invalid_input_shape + invalid_output_length
                + invalid_output_pointer,
                "validation_micarray_tap_invalid_breakdown_mismatch")
        require(dropped == unexpected_producer + queue_full,
                "validation_micarray_tap_dropped_breakdown_mismatch")
        micarray_tap = {
            "calls": calls,
            "diagnostic_schema": diagnostic_schema,
            "first_sequence": first,
            "last_sequence": last,
            "sequence_gaps": 0,
            "dropped": 0,
            "invalid": 0,
            "outside_window": outside_window,
            "invalid_input_shape": 0,
            "invalid_output_length": 0,
            "invalid_output_pointer": 0,
            "unexpected_producer": 0,
            "queue_full": 0,
            "payloads": payloads,
            "sidecar_wavs": sidecars,
        }
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
    playback_reference_value = values.get("playback_reference_present", "false")
    require(playback_reference_value in {"true", "false"},
            "validation_playback_reference_presence_invalid")
    playback_reference_present = playback_reference_value == "true"
    playback_reference = None
    if not playback_reference_present:
        require(playback_reference_wav_path is None,
                "validation_unexpected_playback_reference_wav")
    else:
        require(playback_reference_wav_path is not None,
                "validation_playback_reference_wav_missing")
        reference_path = Path(playback_reference_wav_path)
        require(reference_path.is_file(), "validation_playback_reference_wav_missing")
        require(values.get("playback_reference_wav_name") == reference_path.name,
                "validation_playback_reference_wav_name_mismatch")
        reference_digest = sha256(reference_path)
        require(values.get("playback_reference_wav_sha256") == reference_digest,
                "validation_playback_reference_wav_hash_mismatch")
        with wave.open(str(reference_path), "rb") as recording:
            require(recording.getnchannels() == 1,
                    "validation_playback_reference_not_mono")
            require(recording.getsampwidth() == 2,
                    "validation_playback_reference_not_s16le")
            require(recording.getframerate() == 16000,
                    "validation_playback_reference_not_16khz")
            reference_pcm_bytes = recording.getnframes() * 2
        require(integer(values, "playback_reference_pcm_bytes") == reference_pcm_bytes,
                "validation_playback_reference_length_mismatch")
        target_duration_seconds = integer(values, "target_duration_seconds")
        require(reference_pcm_bytes <= (target_duration_seconds - 2) * 16000 * 2,
                "validation_playback_reference_too_long")
        reference_duration_ms = reference_pcm_bytes * 1000 // (16000 * 2)
        require(integer(values, "playback_reference_lead_in_ms") == 1000,
                "validation_playback_reference_lead_in_mismatch")
        capture_started = integer(values, "capture_started_monotonic_ns")
        playback_started = integer(values, "playback_started_monotonic_ns")
        playback_completed = integer(values, "playback_completed_monotonic_ns")
        playback_elapsed_ms = integer(values, "playback_elapsed_ms")
        require(playback_started >= capture_started + 900_000_000,
                "validation_playback_reference_started_too_early")
        require(playback_completed > playback_started,
                "validation_playback_reference_timing_invalid")
        require(playback_completed <= capture_started + integer(values, "elapsed_ms") * 1_000_000,
                "validation_playback_reference_outside_capture")
        observed_playback_ms = (playback_completed - playback_started) / 1_000_000
        require(playback_elapsed_consistent(playback_elapsed_ms, observed_playback_ms),
                "validation_playback_reference_elapsed_invalid")
        volume_index = integer(values, "music_volume_index")
        volume_max_index = integer(values, "music_volume_max_index")
        require(volume_max_index > 0 and 0 <= volume_index <= volume_max_index,
                "validation_playback_reference_volume_invalid")
        volume_percent = integer(values, "music_volume_percent")
        require(volume_percent == int(100.0 * volume_index / volume_max_index + 0.5),
                "validation_playback_reference_volume_percent_mismatch")
        playback_reference = {
            "wav_sha256": reference_digest,
            "pcm_bytes": reference_pcm_bytes,
            "duration_ms": reference_duration_ms,
            "lead_in_ms": 1000,
            "started_monotonic_ns": playback_started,
            "completed_monotonic_ns": playback_completed,
            "elapsed_ms": playback_elapsed_ms,
            "elapsed_clock_tolerance_ms": PLAYBACK_ELAPSED_CLOCK_TOLERANCE_MS,
            "music_volume_index": volume_index,
            "music_volume_max_index": volume_max_index,
            "music_volume_percent": volume_percent,
        }
    if micarray_tap is not None:
        claim_boundary = "micarray_symbol_binding_continuity_and_nonempty_payloads"
    elif diagnostic is not None and playback_reference is not None:
        claim_boundary = "transport_reported_doa_runtime_shape_and_controlled_playback_capture"
    elif diagnostic is not None:
        claim_boundary = "transport_reported_doa_and_runtime_output_shape"
    elif playback_reference is not None:
        claim_boundary = "transport_reported_doa_and_controlled_playback_capture"
    else:
        claim_boundary = "transport_and_reported_doa_only"
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
        "configured_aec_reference_channels": integer(
            values, "aec_reference_channels_configured"),
        "aec_configured": values.get("aec_configured") == "true",
        "vendor_debug_files_requested": vendor_debug_requested == "true",
        "vendor_debug_files_active": vendor_debug_active == "true",
        "micarray_diagnostic_tap_requested": micarray_tap_requested == "true",
        "micarray_diagnostic_tap_active": micarray_tap_active == "true",
        "micarray_diagnostic_tap": micarray_tap,
        "claim_boundary": claim_boundary,
        "diagnostic_output": diagnostic,
        "controlled_playback_reference": playback_reference,
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
    parser.add_argument("--playback-reference-wav")
    parser.add_argument("--micarray-raw-wav")
    parser.add_argument("--micarray-echo-wav")
    parser.add_argument("--micarray-asr-wav")
    parser.add_argument("--micarray-vad-wav")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        micarray_paths = {
            "raw": args.micarray_raw_wav,
            "echo": args.micarray_echo_wav,
            "asr": args.micarray_asr_wav,
            "vad": args.micarray_vad_wav,
        }
        if not any(micarray_paths.values()):
            micarray_paths = None
        else:
            require(all(micarray_paths.values()),
                    "micarray_sidecar_argument_set_incomplete")
        result = audit(args.wav, args.metadata, args.device, args.diagnostic_wav,
                       args.playback_reference_wav, micarray_paths)
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
