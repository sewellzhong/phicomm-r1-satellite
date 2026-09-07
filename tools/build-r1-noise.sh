#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_DIR="$ROOT_DIR/local-deps/src/noise-c"
[[ "$(git -C "$SOURCE_DIR" rev-parse HEAD)" == b3da54dc1020150237054004c5fdbffc63a23538 ]]
NDK_DIR="${ANDROID_SDK_ROOT:?Set ANDROID_SDK_ROOT to your Android SDK}/ndk/27.0.12077973"
BUILD_DIR="$ROOT_DIR/local-deps/build/r1-noise"
cmake --fresh -S "$ROOT_DIR/android/native/noise-jni" -B "$BUILD_DIR" \
 -DCMAKE_TOOLCHAIN_FILE="$NDK_DIR/build/cmake/android.toolchain.cmake" \
 -DANDROID_ABI=armeabi-v7a -DANDROID_PLATFORM=android-21 -DCMAKE_BUILD_TYPE=Release -DNOISE_DIR="$SOURCE_DIR"
cmake --build "$BUILD_DIR" --parallel 4
OUT="$ROOT_DIR/local-deps/r1-noise/jniLibs/armeabi-v7a"
mkdir -p "$OUT"
cp "$BUILD_DIR/libr1_noise.so" "$OUT/"
sha256sum "$OUT/libr1_noise.so"
