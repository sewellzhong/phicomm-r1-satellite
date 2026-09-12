#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SDK_ROOT="${ANDROID_SDK_ROOT:?Set ANDROID_SDK_ROOT to your Android SDK}"
NDK_DIR="$SDK_ROOT/ndk/27.0.12077973"
BUILD_DIR="$ROOT_DIR/local-deps/build/r1-update-client"
OUTPUT_DIR="$ROOT_DIR/local-deps/r1-update-client/jniLibs/armeabi-v7a"
cmake --fresh -S "$ROOT_DIR/android/update-agent" -B "$BUILD_DIR" \
  -DCMAKE_TOOLCHAIN_FILE="$NDK_DIR/build/cmake/android.toolchain.cmake" \
  -DANDROID_ABI=armeabi-v7a -DANDROID_PLATFORM=android-22 \
  -DCMAKE_BUILD_TYPE=Release
cmake --build "$BUILD_DIR" --parallel 4 --target r1_update_client
mkdir -p "$OUTPUT_DIR"
cp "$BUILD_DIR/libr1_update_client.so" "$OUTPUT_DIR/"
READELF="$NDK_DIR/toolchains/llvm/prebuilt/linux-x86_64/bin/llvm-readelf"
"$READELF" -d "$OUTPUT_DIR/libr1_update_client.so" | rg -q '\(HASH\)'
sha256sum "$OUTPUT_DIR/libr1_update_client.so"
"$READELF" -d "$OUTPUT_DIR/libr1_update_client.so" | rg '\((HASH|GNU_HASH|NEEDED)\)'
