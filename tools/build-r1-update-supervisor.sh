#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SDK_ROOT="${ANDROID_SDK_ROOT:?Set ANDROID_SDK_ROOT to your Android SDK}"
NDK_DIR="$SDK_ROOT/ndk/27.0.12077973"
BUILD_TOOLS="$SDK_ROOT/build-tools/34.0.0"
ANDROID_JAR="$SDK_ROOT/platforms/android-35/android.jar"
BUILD_DIR="$ROOT_DIR/local-deps/build/r1-update-supervisor"
OUTPUT_DIR="$ROOT_DIR/local-deps/r1-update-supervisor"
JAVA_CLASSES="$BUILD_DIR/java-classes"
DEX_DIR="$BUILD_DIR/dex"

cmake --fresh -S "$ROOT_DIR/android/update-agent" -B "$BUILD_DIR/native" \
  -DCMAKE_TOOLCHAIN_FILE="$NDK_DIR/build/cmake/android.toolchain.cmake" \
  -DANDROID_ABI=armeabi-v7a -DANDROID_PLATFORM=android-22 \
  -DCMAKE_BUILD_TYPE=Release
cmake --build "$BUILD_DIR/native" --parallel 4 --target \
  r1-update-supervisor r1-update-backend-probe r1-update-fault-helper

rm -rf "$JAVA_CLASSES" "$DEX_DIR"
mkdir -p "$JAVA_CLASSES" "$DEX_DIR" "$OUTPUT_DIR"
javac -source 8 -target 8 -bootclasspath "$ANDROID_JAR" -d "$JAVA_CLASSES" \
  "$ROOT_DIR/android/update-agent/java/dev/sewellzhong/r1update/PackageIdentityHelper.java"
"$BUILD_TOOLS/d8" --min-api 22 --output "$DEX_DIR" \
  "$JAVA_CLASSES/dev/sewellzhong/r1update/PackageIdentityHelper.class"
TZ=UTC touch -t 200001010000.00 "$DEX_DIR/classes.dex"
cp "$BUILD_DIR/native/r1-update-supervisor" "$OUTPUT_DIR/"
cp "$BUILD_DIR/native/r1-update-backend-probe" "$OUTPUT_DIR/"
cp "$BUILD_DIR/native/r1-update-fault-helper" "$OUTPUT_DIR/"
(cd "$DEX_DIR" && zip -q -X "$OUTPUT_DIR/r1-update-helper.jar" classes.dex)

READELF="$NDK_DIR/toolchains/llvm/prebuilt/linux-x86_64/bin/llvm-readelf"
for binary in r1-update-supervisor r1-update-backend-probe r1-update-fault-helper; do
  "$READELF" -h "$OUTPUT_DIR/$binary" | rg -q 'Machine:.*ARM'
  "$READELF" -d "$OUTPUT_DIR/$binary" | rg -q '\(HASH\)'
done
sha256sum "$OUTPUT_DIR/r1-update-supervisor" \
  "$OUTPUT_DIR/r1-update-backend-probe" "$OUTPUT_DIR/r1-update-fault-helper" \
  "$OUTPUT_DIR/r1-update-helper.jar"
