#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
: "${ANDROID_SDK_ROOT:?Set ANDROID_SDK_ROOT}"
readonly SOURCE="$ROOT_DIR/local-deps/src/setools-android"
readonly COMMIT=e38bff264913e5bc2c8f18f67ec9f1017ace3982
readonly PATCH="$ROOT_DIR/tools/factory_audio/patches/setools-android-e38-policy-v26-new-domain.patch"
readonly OUTPUT="$SOURCE/libs/armeabi-v7a/sepolicy-inject"
readonly EXPECTED=9e301f027fb30244ef143d367d49d266c944e90345099a60e3414e7ad09d5c11

if [[ ! -d "$SOURCE/.git" ]]; then
  git clone https://github.com/xmikos/setools-android.git "$SOURCE"
fi
test "$(git -C "$SOURCE" rev-parse HEAD)" = "$COMMIT"
if git -C "$SOURCE" diff --quiet; then
  git -C "$SOURCE" apply "$PATCH"
elif git -C "$SOURCE" apply --reverse --check "$PATCH"; then
  : # The exact reviewed patch is already present.
else
  echo 'setools-android source has unexpected local changes' >&2
  exit 2
fi
"$ANDROID_SDK_ROOT/ndk/27.0.12077973/ndk-build" -C "$SOURCE" -j2 \
  APP_ABI=armeabi-v7a APP_PLATFORM=android-22 APP_MODULES=sepolicy-inject
test "$(sha256sum "$OUTPUT" | cut -d' ' -f1)" = "$EXPECTED"
echo "$OUTPUT"
