#!/usr/bin/env python3
"""Audit four labelled R1 DOA captures without contacting a device."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys


EXPECTED_LABELS = {"front", "right", "back", "left"}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def circular_difference(actual, expected):
    return (actual - expected + 180.0) % 360.0 - 180.0


def circular_offset(differences):
    x = sum(math.cos(math.radians(value)) for value in differences)
    y = sum(math.sin(math.radians(value)) for value in differences)
    require(x != 0.0 or y != 0.0, "direction_offset_undefined")
    return math.degrees(math.atan2(y, x)) % 360.0


def histogram_stats(histogram):
    total = sum(histogram)
    require(total > 0, "capture_histogram_empty")
    x = 0.0
    y = 0.0
    for index, count in enumerate(histogram):
        angle = math.radians(index * 10 + 5)
        x += count * math.cos(angle)
        y += count * math.sin(angle)
    return math.degrees(math.atan2(y, x)) % 360.0, math.hypot(x, y) / total


def audit(manifest_path, min_valid_fraction=0.8, min_resultant_length=0.5,
          max_residual_degrees=45.0):
    manifest_path = Path(manifest_path).resolve()
    manifest = load_json(manifest_path)
    require(manifest.get("device") == "r1-sample01", "device_not_r1_sample01")
    captures = manifest.get("captures")
    require(isinstance(captures, list) and len(captures) == 4,
            "exactly_four_direction_captures_required")
    labels = [item.get("label") for item in captures]
    require(set(labels) == EXPECTED_LABELS and len(labels) == len(set(labels)),
            "direction_labels_must_be_front_right_back_left")

    rows = []
    differences = []
    for item in captures:
        expected = item.get("expected_degrees")
        require(isinstance(expected, (int, float)) and 0 <= expected < 360,
                f"expected_degrees_invalid_{item.get('label')}")
        report_path = Path(item.get("audit_report", ""))
        if not report_path.is_absolute():
            report_path = manifest_path.parent / report_path
        require(report_path.is_file(), f"audit_report_missing_{item.get('label')}")
        report = load_json(report_path)
        require(report.get("status") == "pass", f"capture_not_audited_{item.get('label')}")
        require(report.get("device") == manifest["device"],
                f"capture_device_mismatch_{item.get('label')}")
        require(report.get("claim_boundary") in {
            "transport_and_reported_doa_only",
            "transport_reported_doa_and_runtime_output_shape",
            "transport_reported_doa_and_controlled_playback_capture",
            "transport_reported_doa_runtime_shape_and_controlled_playback_capture",
            "micarray_symbol_binding_continuity_and_nonempty_payloads",
        }, f"capture_claim_boundary_invalid_{item.get('label')}")
        histogram = report.get("doa_histogram_10_degrees")
        require(isinstance(histogram, list) and len(histogram) == 36
                and all(isinstance(value, int) and value >= 0 for value in histogram),
                f"capture_histogram_invalid_{item.get('label')}")
        require(sum(histogram) == report.get("doa_valid_frames"),
                f"capture_histogram_count_mismatch_{item.get('label')}")
        stats = report.get("doa_circular_stats")
        require(isinstance(stats, dict) and stats.get("mean_degrees") is not None,
                f"capture_doa_mean_missing_{item.get('label')}")
        valid_fraction = report.get("doa_valid_fraction")
        concentration = stats.get("resultant_length")
        require(isinstance(valid_fraction, (int, float)),
                f"capture_valid_fraction_missing_{item.get('label')}")
        require(isinstance(concentration, (int, float)),
                f"capture_concentration_missing_{item.get('label')}")
        observed, calculated_concentration = histogram_stats(histogram)
        require(abs(circular_difference(stats["mean_degrees"], observed)) < 1e-6,
                f"capture_doa_mean_mismatch_{item.get('label')}")
        require(abs(concentration - calculated_concentration) < 1e-6,
                f"capture_concentration_mismatch_{item.get('label')}")
        require(abs(valid_fraction - report["doa_valid_frames"] / report["frames"]) < 1e-9,
                f"capture_valid_fraction_mismatch_{item.get('label')}")
        differences.append(circular_difference(observed, expected))
        rows.append({
            "label": item["label"],
            "expected_degrees": expected,
            "observed_mean_degrees": observed,
            "doa_valid_fraction": valid_fraction,
            "resultant_length": concentration,
            "audit_report_sha256": sha256(report_path),
        })

    offset = circular_offset(differences)
    for row in rows:
        aligned_expected = (row["expected_degrees"] + offset) % 360.0
        row["aligned_expected_degrees"] = aligned_expected
        row["residual_degrees"] = circular_difference(
            row["observed_mean_degrees"], aligned_expected)
        row["valid_fraction_ok"] = row["doa_valid_fraction"] >= min_valid_fraction
        row["concentration_ok"] = row["resultant_length"] >= min_resultant_length
        row["residual_ok"] = abs(row["residual_degrees"]) <= max_residual_degrees

    directional_pass = all(row["valid_fraction_ok"] and row["concentration_ok"]
                           and row["residual_ok"] for row in rows)
    return {
        "status": "pass" if directional_pass else "fail",
        "device": manifest["device"],
        "claim_boundary": "four_direction_reported_doa_relative_response_only",
        "manifest_sha256": sha256(manifest_path),
        "fitted_device_zero_offset_degrees": offset,
        "thresholds": {
            "min_valid_fraction": min_valid_fraction,
            "min_resultant_length": min_resultant_length,
            "max_residual_degrees": max_residual_degrees,
        },
        "captures": rows,
        "unverified": [
            "independent_four_microphone_response",
            "aec_cancellation_effect",
            "dsp_output_quality",
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--min-valid-fraction", type=float, default=0.8)
    parser.add_argument("--min-resultant-length", type=float, default=0.5)
    parser.add_argument("--max-residual-degrees", type=float, default=45.0)
    args = parser.parse_args(argv)
    try:
        require(0 <= args.min_valid_fraction <= 1, "min_valid_fraction_invalid")
        require(0 <= args.min_resultant_length <= 1, "min_resultant_length_invalid")
        require(0 <= args.max_residual_degrees <= 180, "max_residual_degrees_invalid")
        output = Path(args.output)
        require(not output.exists(), "output_already_exists")
        result = audit(args.manifest, args.min_valid_fraction,
                       args.min_resultant_length, args.max_residual_degrees)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                          encoding="utf-8")
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] == "pass" else 2
    except (OSError, RuntimeError, TypeError, ValueError, json.JSONDecodeError) as error:
        print("DOA direction matrix audit refused: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
