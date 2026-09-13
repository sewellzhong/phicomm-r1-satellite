#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SDK_ROOT="${ANDROID_SDK_ROOT:?Set ANDROID_SDK_ROOT to your Android SDK}"
NDK_DIR="$SDK_ROOT/ndk/27.0.12077973"
BUILD_DIR="$ROOT_DIR/local-deps/build/r1-system-control"
CLIENT_DIR="$ROOT_DIR/local-deps/r1-system-control-client/jniLibs/armeabi-v7a"
AGENT_DIR="$ROOT_DIR/local-deps/r1-system-control-agent"

cmake --fresh -S "$ROOT_DIR/android/system-control-agent" -B "$BUILD_DIR" \
  -DCMAKE_TOOLCHAIN_FILE="$NDK_DIR/build/cmake/android.toolchain.cmake" \
  -DANDROID_ABI=armeabi-v7a -DANDROID_PLATFORM=android-22 \
  -DCMAKE_BUILD_TYPE=Release
cmake --build "$BUILD_DIR" --parallel 4 --target \
  r1-system-control-agent r1_system_control_client
mkdir -p "$CLIENT_DIR" "$AGENT_DIR"
cp "$BUILD_DIR/libr1_system_control_client.so" "$CLIENT_DIR/"
cp "$BUILD_DIR/r1-system-control-agent" "$AGENT_DIR/"
READELF="$NDK_DIR/toolchains/llvm/prebuilt/linux-x86_64/bin/llvm-readelf"
for item in "$CLIENT_DIR/libr1_system_control_client.so" \
            "$AGENT_DIR/r1-system-control-agent"; do
  "$READELF" -h "$item" | rg -q 'Machine:.*ARM'
  "$READELF" -d "$item" | rg -q '\(HASH\)'
done
sha256sum "$CLIENT_DIR/libr1_system_control_client.so" \
  "$AGENT_DIR/r1-system-control-agent"
