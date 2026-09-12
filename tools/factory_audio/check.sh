#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD_DIR="$ROOT_DIR/local-deps/build/factory-audio-agent-host"
PYTHON_BIN="$ROOT_DIR/local-deps/esphome-interop-venv/bin/python"
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo 'Prepared host Python environment is missing; run python3 tools/dev/prepare.py' >&2
  exit 1
fi
if ! "$PYTHON_BIN" -c 'import aioesphomeapi, google.protobuf, noise.connection' >/dev/null 2>&1; then
  echo 'Prepared host Python environment is invalid; rerun python3 tools/dev/prepare.py' >&2
  exit 1
fi
cmake --fresh -S "$ROOT_DIR/android/factory-audio-agent" -B "$BUILD_DIR" -DCMAKE_BUILD_TYPE=Release
cmake --build "$BUILD_DIR" --parallel 4
if [[ -n "${ANDROID_SDK_ROOT:-}" && -d "$ANDROID_SDK_ROOT/ndk/27.0.12077973" ]]; then
  ANDROID_BUILD_DIR="$ROOT_DIR/local-deps/build/factory-audio-agent-android"
  cmake --fresh -S "$ROOT_DIR/android/factory-audio-agent" -B "$ANDROID_BUILD_DIR" \
    -DCMAKE_TOOLCHAIN_FILE="$ANDROID_SDK_ROOT/ndk/27.0.12077973/build/cmake/android.toolchain.cmake" \
    -DANDROID_ABI=armeabi-v7a -DANDROID_PLATFORM=android-22 -DCMAKE_BUILD_TYPE=Release
  cmake --build "$ANDROID_BUILD_DIR" --parallel 4
fi
"$PYTHON_BIN" -m unittest discover -s "$ROOT_DIR/tools/factory_audio/tests" -v
