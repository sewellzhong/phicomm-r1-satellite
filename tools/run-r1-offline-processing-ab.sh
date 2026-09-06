#!/usr/bin/env bash
set -euo pipefail

usage() {
    echo "Usage: $0 [stereo-channel-controlled-evidence-dir]" >&2
    exit 64
}

[[ $# -le 1 ]] || usage
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly REPO_ROOT
readonly SOURCE_DIR="${1:-$REPO_ROOT/test-results/2026-09-02T023041-r1-sample01/stage1/stereo-channel-controlled}"
readonly DEVICE_ID="${R1_DEVICE_ID:-r1-sample01}"
RUN_ID="$(date +%Y-%m-%dT%H%M%S)"
readonly RUN_ID
readonly EVIDENCE_DIR="$REPO_ROOT/test-results/${RUN_ID}-${DEVICE_ID}/stage1/offline-processing-ab"
readonly AUDIO_DIR="$EVIDENCE_DIR/audio"

[[ -f "$SOURCE_DIR/audio/silence-average.wav" \
    && -f "$SOURCE_DIR/audio/speech-average.wav" \
    && -f "$SOURCE_DIR/SHA256SUMS" ]] || {
    echo "Required aligned average-channel evidence is missing" >&2
    exit 66
}
(cd "$SOURCE_DIR" && sha256sum -c SHA256SUMS >/dev/null)
mkdir -p "$AUDIO_DIR"
exec > >(tee "$EVIDENCE_DIR/run.log") 2>&1

process_profile() {
    local name="$1"
    local alpha="$2"
    local floor_gain="$3"
    for kind in silence speech; do
        "$REPO_ROOT/tools/spectral-denoise-wav.py" \
            "$SOURCE_DIR/audio/silence-average.wav" \
            "$SOURCE_DIR/audio/${kind}-average.wav" \
            "$AUDIO_DIR/${kind}-${name}.wav" \
            --alpha "$alpha" --floor-gain "$floor_gain" --output-gain-db 18 \
            >"$AUDIO_DIR/${kind}-${name}.processing.json"
        "$REPO_ROOT/tools/analyze-wav.py" "$AUDIO_DIR/${kind}-${name}.wav" \
            >"$AUDIO_DIR/${kind}-${name}.analysis.json"
    done
    "$REPO_ROOT/tools/compare-wav-levels.py" \
        "$AUDIO_DIR/silence-${name}.wav" "$AUDIO_DIR/speech-${name}.wav" \
        >"$AUDIO_DIR/${name}.comparison.json"
}

process_profile gentle 0.8 0.45
process_profile balanced 1.2 0.25
process_profile strong 1.8 0.12

python3 - "$AUDIO_DIR" >"$EVIDENCE_DIR/summary.json" <<'PY'
import json
import pathlib
import sys

audio = pathlib.Path(sys.argv[1])
profiles = []
for name in ("gentle", "balanced", "strong"):
    comparison = json.loads((audio / f"{name}.comparison.json").read_text())
    speech_analysis = json.loads((audio / f"speech-{name}.analysis.json").read_text())
    processing = json.loads((audio / f"speech-{name}.processing.json").read_text())
    profiles.append({
        "name": name,
        "speech_to_silence_db": comparison["speech_to_silence_db"],
        "active_window_p95_delta_db": comparison["active_window_p95_delta_db"],
        "speech_rms_dbfs": speech_analysis["rms_dbfs"],
        "speech_peak_dbfs": speech_analysis["peak_dbfs"],
        "clipped_samples": speech_analysis["clipped_samples"],
        "waveform_correlation_pre_gain": processing["waveform_correlation_pre_gain"],
        "alpha": processing["alpha"],
        "floor_gain": processing["floor_gain"],
        "output_gain_db": processing["output_gain_db"],
    })
print(json.dumps({
    "source": "aligned average channel from stereo diagnostic",
    "production_integration_status": "not_integrated_pending_metrics_and_listening",
    "profiles": profiles,
}, ensure_ascii=False, indent=2, sort_keys=True))
PY

{
    printf 'status=complete\n'
    printf 'source_evidence=%s\n' "$SOURCE_DIR"
    printf 'production_integration=false\n'
    printf 'subjective_intelligibility=pending_user_review\n'
    printf 'raw_source_modified=false\n'
} >"$EVIDENCE_DIR/RESULT.txt"

manifest_tmp="$(mktemp)"
(cd "$EVIDENCE_DIR" && find . -type f ! -name run.log ! -name SHA256SUMS -print0 \
    | sort -z | xargs -0 sha256sum >"$manifest_tmp")
mv "$manifest_tmp" "$EVIDENCE_DIR/SHA256SUMS"
(cd "$EVIDENCE_DIR" && sha256sum -c SHA256SUMS)
echo "Evidence: $EVIDENCE_DIR"
