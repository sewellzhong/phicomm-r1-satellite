#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SDK_ROOT="${ANDROID_SDK_ROOT:?Set ANDROID_SDK_ROOT to your Android SDK}"
NDK_DIR="$SDK_ROOT/ndk/27.0.12077973"
SOURCE_DIR="$ROOT_DIR/local-deps/src/libfvad"
SOURCE_COMMIT="532ab666c20d3cfda38bca63abbb0f152706c369"
if [[ ! -d "$SOURCE_DIR/.git" ]]; then
  git clone https://github.com/dpirch/libfvad.git "$SOURCE_DIR"
  git -C "$SOURCE_DIR" checkout --detach "$SOURCE_COMMIT"
fi
[[ "$(git -C "$SOURCE_DIR" rev-parse HEAD)" == "$SOURCE_COMMIT" ]]
BUILD_DIR="$ROOT_DIR/local-deps/build/r1-vad"
OUTPUT_DIR="$ROOT_DIR/local-deps/r1-vad/jniLibs/armeabi-v7a"
cmake -S "$ROOT_DIR/android/native/vad-jni" -B "$BUILD_DIR" \
  -DCMAKE_TOOLCHAIN_FILE="$NDK_DIR/build/cmake/android.toolchain.cmake" \
  -DANDROID_ABI=armeabi-v7a -DANDROID_PLATFORM=android-21 \
  -DCMAKE_BUILD_TYPE=Release -DFVAD_DIR="$SOURCE_DIR"
cmake --build "$BUILD_DIR" --parallel 4
mkdir -p "$OUTPUT_DIR"
cp "$BUILD_DIR/libr1_vad.so" "$OUTPUT_DIR/"
sha256sum "$OUTPUT_DIR/libr1_vad.so"
"$NDK_DIR/toolchains/llvm/prebuilt/linux-x86_64/bin/llvm-readelf" -d "$OUTPUT_DIR/libr1_vad.so" | rg 'HASH|NEEDED'
