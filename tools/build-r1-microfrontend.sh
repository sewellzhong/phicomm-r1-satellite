#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SDK_ROOT="${ANDROID_SDK_ROOT:?Set ANDROID_SDK_ROOT to your Android SDK}"
NDK_VERSION="27.0.12077973"
NDK_DIR="${SDK_ROOT}/ndk/${NDK_VERSION}"
SOURCE_COMMIT="96bd69cfad79aa67697e176570d3dd87052c3def"
SOURCE_DIR="${ROOT_DIR}/local-deps/src/pymicro-features-2.0.2"
BUILD_DIR="${ROOT_DIR}/local-deps/build/r1-microfrontend"
OUTPUT_DIR="${ROOT_DIR}/local-deps/r1-microfrontend/jniLibs/armeabi-v7a"

[[ -d "$NDK_DIR" ]] || { echo "Missing NDK: $NDK_DIR" >&2; exit 1; }
mkdir -p "$(dirname "$SOURCE_DIR")"
if [[ ! -d "$SOURCE_DIR/.git" ]]; then
  git init "$SOURCE_DIR"
  git -C "$SOURCE_DIR" remote add origin https://github.com/rhasspy/pymicro-features.git
  git -C "$SOURCE_DIR" fetch --depth 1 origin "$SOURCE_COMMIT"
  git -C "$SOURCE_DIR" checkout --detach FETCH_HEAD
fi
actual_commit="$(git -C "$SOURCE_DIR" rev-parse HEAD)"
[[ "$actual_commit" == "$SOURCE_COMMIT" ]] || {
  echo "Unexpected pymicro-features commit: $actual_commit" >&2
  exit 1
}

cmake --fresh -S "${ROOT_DIR}/android/native/microfrontend-jni" -B "$BUILD_DIR" \
  -DCMAKE_TOOLCHAIN_FILE="$NDK_DIR/build/cmake/android.toolchain.cmake" \
  -DANDROID_ABI=armeabi-v7a -DANDROID_PLATFORM=android-21 \
  -DCMAKE_BUILD_TYPE=Release -DPYMICRO_FEATURES_DIR="$SOURCE_DIR"
cmake --build "$BUILD_DIR" --parallel 4
mkdir -p "$OUTPUT_DIR"
cp "$BUILD_DIR/libr1_microfrontend.so" "$OUTPUT_DIR/"
READELF="$NDK_DIR/toolchains/llvm/prebuilt/linux-x86_64/bin/llvm-readelf"
"$READELF" -d "$OUTPUT_DIR/libr1_microfrontend.so" | grep -q '(HASH)'
sha256sum "$OUTPUT_DIR/libr1_microfrontend.so"
"$READELF" -d "$OUTPUT_DIR/libr1_microfrontend.so" | grep -E '\((HASH|GNU_HASH|NEEDED)\)'
