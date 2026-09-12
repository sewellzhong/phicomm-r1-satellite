#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD_DIR="$ROOT_DIR/local-deps/build/update-agent-host"
cmake --fresh -S "$ROOT_DIR/android/update-agent" -B "$BUILD_DIR" -DCMAKE_BUILD_TYPE=Release
cmake --build "$BUILD_DIR" --parallel 4
ctest --test-dir "$BUILD_DIR" --output-on-failure
