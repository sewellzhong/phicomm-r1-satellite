#!/usr/bin/env bash
set -euo pipefail

usage() {
    echo "Usage: $0 [offline-processing-ab-evidence-dir]" >&2
    exit 64
}

[[ $# -le 1 ]] || usage
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly REPO_ROOT
readonly SOURCE_DIR="${1:-$REPO_ROOT/test-results/2026-09-02T023918-r1-sample01/stage1/offline-processing-ab}"
readonly DEVICE_ID="${R1_DEVICE_ID:-r1-sample01}"
RUN_ID="$(date +%Y-%m-%dT%H%M%S)"
readonly RUN_ID
readonly EVIDENCE_DIR="$REPO_ROOT/test-results/${RUN_ID}-${DEVICE_ID}/stage1/offline-adaptive-gain"
readonly AUDIO_DIR="$EVIDENCE_DIR/audio"

[[ -f "$SOURCE_DIR/audio/silence-balanced.wav" \
    && -f "$SOURCE_DIR/audio/speech-balanced.wav" \
    && -f "$SOURCE_DIR/SHA256SUMS" ]] || {
    echo "Required balanced processing evidence is missing" >&2
    exit 66
}
(cd "$SOURCE_DIR" && sha256sum -c SHA256SUMS >/dev/null)
mkdir -p "$AUDIO_DIR"
exec > >(tee "$EVIDENCE_DIR/run.log") 2>&1

for kind in silence speech; do
    "$REPO_ROOT/tools/adaptive-gain-wav.py" \
        "$SOURCE_DIR/audio/silence-balanced.wav" \
        "$SOURCE_DIR/audio/${kind}-balanced.wav" \
        "$AUDIO_DIR/${kind}-balanced-agc.wav" \
        --target-rms-dbfs -28 --max-gain-db 18 --activity-ratio 1.5 --peak-limit-dbfs -1 \
        >"$AUDIO_DIR/${kind}-balanced-agc.processing.json"
    "$REPO_ROOT/tools/analyze-wav.py" "$AUDIO_DIR/${kind}-balanced-agc.wav" \
        >"$AUDIO_DIR/${kind}-balanced-agc.analysis.json"
done

"$REPO_ROOT/tools/compare-wav-levels.py" \
    "$AUDIO_DIR/silence-balanced-agc.wav" "$AUDIO_DIR/speech-balanced-agc.wav" \
    >"$AUDIO_DIR/balanced-agc.comparison.json"

python3 - "$AUDIO_DIR" >"$EVIDENCE_DIR/summary.json" <<'PY'
import json
import pathlib
import struct
import sys
import wave
import math

audio = pathlib.Path(sys.argv[1])
comparison = json.loads((audio / "balanced-agc.comparison.json").read_text())
analysis = json.loads((audio / "speech-balanced-agc.analysis.json").read_text())
processing = json.loads((audio / "speech-balanced-agc.processing.json").read_text())
with wave.open(str(audio / "speech-balanced-agc.wav"), "rb") as wav:
    values = [sample[0] for sample in struct.iter_unpack("<h", wav.readframes(wav.getnframes()))]
per_second = []
for second in range(len(values) // 16000):
    window = values[second * 16000:(second + 1) * 16000]
    rms = math.sqrt(sum(sample * sample for sample in window) / len(window))
    per_second.append({
        "second": second,
        "rms_dbfs": 20.0 * math.log10(rms / 32768.0) if rms else None,
        "peak_dbfs": 20.0 * math.log10(max(map(abs, window)) / 32768.0) if window else None,
    })
print(json.dumps({
    "production_integration_status": "not_integrated_pending_listening",
    "speech_to_silence_db": comparison["speech_to_silence_db"],
    "active_window_p95_delta_db": comparison["active_window_p95_delta_db"],
    "speech_rms_dbfs": analysis["rms_dbfs"],
    "speech_peak_dbfs": analysis["peak_dbfs"],
    "clipped_samples": analysis["clipped_samples"],
    "maximum_applied_gain_db": processing["maximum_applied_gain_db"],
    "mean_applied_gain_db": processing["mean_applied_gain_db"],
    "per_second": per_second,
}, ensure_ascii=False, indent=2, sort_keys=True))
PY

{
    printf 'status=complete\n'
    printf 'production_integration=false\n'
    printf 'subjective_intelligibility=pending_user_review\n'
    printf 'signal_separation_claim_from_agc=false\n'
} >"$EVIDENCE_DIR/RESULT.txt"

manifest_tmp="$(mktemp)"
(cd "$EVIDENCE_DIR" && find . -type f ! -name run.log ! -name SHA256SUMS -print0 \
    | sort -z | xargs -0 sha256sum >"$manifest_tmp")
mv "$manifest_tmp" "$EVIDENCE_DIR/SHA256SUMS"
(cd "$EVIDENCE_DIR" && sha256sum -c SHA256SUMS)
echo "Evidence: $EVIDENCE_DIR"
