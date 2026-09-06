#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"
: "${ANDROID_SDK_ROOT:?Set ANDROID_SDK_ROOT}"
command -v docker >/dev/null || { echo 'Docker is required for HA tests' >&2; exit 1; }
python3 tools/dev/audit-public.py
python3 tools/dev/scan-secrets.py
android/r1-probe/gradlew -p android/r1-probe --no-daemon -PhostCheck=true testDebugUnitTest lintDebug assembleDebug
python3 -m unittest discover -s tools/native/tests -v
HA_IMAGE='ghcr.io/home-assistant/home-assistant@sha256:56690a89c79a0de98035e1719f8324a92d5859c1192ff45adb0230ea81cb42a5'
docker run --rm --network none --entrypoint python -e PYTHONPATH=/work/integrations/home_assistant -v "$ROOT_DIR:/work:ro" "$HA_IMAGE" -m unittest discover -s /work/tools/ha/tests -p 'test_*.py' -v
docker run --rm --network none --entrypoint python -e PYTHONPATH=/work/integrations/home_assistant -v "$ROOT_DIR:/work:ro" "$HA_IMAGE" /work/tools/ha/tests/check_guard_setup.py
echo 'Host checks passed. Two private HA router tests live in tools/ha/local_tests; R1 verification remains pending.'
