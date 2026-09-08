#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD_DIR="$ROOT_DIR/local-deps/build/factory-audio-agent-host"
cmake --fresh -S "$ROOT_DIR/android/factory-audio-agent" -B "$BUILD_DIR" -DCMAKE_BUILD_TYPE=Release
cmake --build "$BUILD_DIR" --parallel 4
if [[ -n "${ANDROID_SDK_ROOT:-}" && -d "$ANDROID_SDK_ROOT/ndk/27.0.12077973" ]]; then
  ANDROID_BUILD_DIR="$ROOT_DIR/local-deps/build/factory-audio-agent-android"
  cmake --fresh -S "$ROOT_DIR/android/factory-audio-agent" -B "$ANDROID_BUILD_DIR" \
    -DCMAKE_TOOLCHAIN_FILE="$ANDROID_SDK_ROOT/ndk/27.0.12077973/build/cmake/android.toolchain.cmake" \
    -DANDROID_ABI=armeabi-v7a -DANDROID_PLATFORM=android-22 -DCMAKE_BUILD_TYPE=Release
  cmake --build "$ANDROID_BUILD_DIR" --parallel 4
fi
python3 -m unittest discover -s "$ROOT_DIR/tools/factory_audio/tests" -v
