#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
: "${ANDROID_SDK_ROOT:?Set ANDROID_SDK_ROOT}"
readonly SOURCE="$ROOT_DIR/local-deps/src/setools-android"
readonly COMMIT=e38bff264913e5bc2c8f18f67ec9f1017ace3982
readonly BASE_PATCH="$ROOT_DIR/tools/factory_audio/patches/setools-android-e38-policy-v26-new-domain.patch"
readonly REINDEX_PATCH="$ROOT_DIR/tools/update/patches/setools-android-reindex-new-types.patch"
readonly OUTPUT="$SOURCE/libs/armeabi-v7a/sepolicy-inject"
readonly EXPECTED=c289bcf5f0011bdbfaa520d813b0103f1d878285f6750e1972a6089321ade055

if [[ ! -d "$SOURCE/.git" ]]; then
  git clone https://github.com/xmikos/setools-android.git "$SOURCE"
fi
test "$(git -C "$SOURCE" rev-parse HEAD)" = "$COMMIT"
if git -C "$SOURCE" apply --reverse --check "$REINDEX_PATCH"; then
  : # The complete ordered stack is already present.
else
  if git -C "$SOURCE" apply --reverse --check "$BASE_PATCH"; then
    : # Only the base compatibility patch is present.
  elif git -C "$SOURCE" apply --check "$BASE_PATCH"; then
    git -C "$SOURCE" apply "$BASE_PATCH"
  else
    echo "setools-android source does not match reviewed base patch" >&2
    exit 2
  fi
  if git -C "$SOURCE" apply --check "$REINDEX_PATCH"; then
    git -C "$SOURCE" apply "$REINDEX_PATCH"
  else
    echo "setools-android source does not match reviewed reindex patch" >&2
    exit 2
  fi
fi
"$ANDROID_SDK_ROOT/ndk/27.0.12077973/ndk-build" -C "$SOURCE" -j2 \
  APP_ABI=armeabi-v7a APP_PLATFORM=android-22 APP_MODULES=sepolicy-inject
test "$(sha256sum "$OUTPUT" | cut -d' ' -f1)" = "$EXPECTED"
echo "$OUTPUT"
