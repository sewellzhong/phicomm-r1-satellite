#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD_DIR="$ROOT_DIR/local-deps/build/system-control-host"
cmake --fresh -S "$ROOT_DIR/android/system-control-agent" -B "$BUILD_DIR" \
  -DCMAKE_BUILD_TYPE=Release
cmake --build "$BUILD_DIR" --parallel 4
ctest --test-dir "$BUILD_DIR" --output-on-failure
python3 -m unittest discover -s "$ROOT_DIR/tools/system_control/tests" -v
python3 "$ROOT_DIR/android/system-control-agent/tests/device_policy_test.py"
