#!/usr/bin/env python3
import argparse
import json
import re
import statistics
from pathlib import Path


def read_metadata(path):
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("metrics", type=Path)
    parser.add_argument("metadata", type=Path)
    parser.add_argument("logcat", type=Path)
    parser.add_argument("--require-duration", type=int, default=1800)
    parser.add_argument("--minimum-pss-samples", type=int, default=25)
    args = parser.parse_args()

    rows = []
    for line in args.metrics.read_text(encoding="utf-8").splitlines()[1:]:
        fields = line.split("\t")
        if len(fields) != 4 or not fields[2] or not fields[3]:
            continue
        rows.append({"elapsed_seconds": int(fields[0]), "pid": int(fields[2]),
                     "pss_kb": int(fields[3])})
    metadata = read_metadata(args.metadata)
    pids = sorted({row["pid"] for row in rows})
    pss = [row["pss_kb"] for row in rows]
    first_median = statistics.median(pss[:5]) if pss else None
    last_median = statistics.median(pss[-5:]) if pss else None
    growth = None if first_median is None else last_median - first_median

    log_lines = args.logcat.read_text(encoding="utf-8", errors="replace").splitlines()
    brief_pid_pattern = re.compile(r"\(\s*(\d+)\)")
    threadtime_pid_pattern = re.compile(
        r"^\S+\s+\S+\s+(\d+)\s+\d+\s+[VDIWEF]\s+")
    completion_index = next((index for index, line in enumerate(log_lines)
                             if "R1_PROCESSED_SOAK_COMPLETE" in line), len(log_lines))
    gc_lines = []
    allocation_failures = []
    for index, line in enumerate(log_lines):
        match = brief_pid_pattern.search(line) or threadtime_pid_pattern.search(line)
        if not match or int(match.group(1)) not in pids:
            continue
        lower = line.lower()
        if " gc" in lower or "gc_" in lower:
            gc_lines.append((index, line))
        if "outofmemory" in lower or "allocation failed" in lower:
            allocation_failures.append(line)

    duration = int(metadata.get("target_duration_seconds", "-1"))
    expected_samples = duration * 16000
    checks = {
        "duration_at_least_required": duration >= args.require_duration,
        "audio_not_retained": metadata.get("audio_retained") == "false",
        "input_samples_complete": int(metadata.get("input_samples", "-1")) == expected_samples,
        "output_samples_complete": int(metadata.get("output_samples", "-1")) == expected_samples,
        "partial_reads_zero": int(metadata.get("partial_reads", "-1")) == 0,
        "processing_overruns_zero": int(metadata.get("processing_overruns", "-1")) == 0,
        "clipped_samples_zero": int(metadata.get("clipped_samples", "-1")) == 0,
        "pss_samples_at_least_required": len(pss) >= args.minimum_pss_samples,
        "single_process_pid": len(pids) == 1,
        "maximum_pss_at_most_120_mb": bool(pss) and max(pss) <= 120 * 1024,
        "median_pss_growth_at_most_10_mb": growth is not None and growth <= 10 * 1024,
        "no_allocation_failure": not allocation_failures,
    }
    result = {
        "status": "pass" if all(checks.values()) else "fail",
        "checks": checks,
        "metrics_samples": len(rows),
        "pids": pids,
        "maximum_pss_kb": max(pss) if pss else None,
        "first_five_median_pss_kb": first_median,
        "last_five_median_pss_kb": last_median,
        "median_pss_growth_kb": growth,
        "application_gc_line_count": len(gc_lines),
        "processing_gc_line_count": sum(index < completion_index for index, _ in gc_lines),
        "post_processing_explicit_gc_line_count": sum(
            index > completion_index and "explicit" in line.lower() for index, line in gc_lines),
        "allocation_failure_count": len(allocation_failures),
        "metadata": metadata,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    raise SystemExit(0 if result["status"] == "pass" else 1)


if __name__ == "__main__":
    main()
