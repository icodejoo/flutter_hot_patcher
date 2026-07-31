#!/usr/bin/env bash
# One-time setup: fetch package:kernel source that matches the active dart SDK.
# Only needed when the custom dart SDK at ~/dart/sdk has no runnable Mac binary.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SDK_MIRROR="$SCRIPT_DIR/.dart_sdk_mirror"

DART_BIN="$(which dart 2>/dev/null || true)"
if [[ -z "$DART_BIN" ]]; then
  echo "ERROR: dart not found in PATH." >&2; exit 1
fi
DART_VER="$("$DART_BIN" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+'  | head -1)"
echo "[setup] dart version: $DART_VER"

KERNEL_DIR="$SDK_MIRROR/pkg/kernel"
FE_DIR="$SDK_MIRROR/pkg/_fe_analyzer_shared"

if [[ -d "$KERNEL_DIR/lib" && -d "$FE_DIR/lib" ]]; then
  echo "[setup] kernel source already at $SDK_MIRROR — skipping."
  echo "Re-run with --force to re-fetch."
  [[ "${1:-}" == "--force" ]] || { python3 "$SCRIPT_DIR/gen_package_config.py" --sdk "$SDK_MIRROR"; exit 0; }
fi

echo "[setup] Fetching dart-lang/sdk@$DART_VER pkg/kernel + pkg/_fe_analyzer_shared ..."
mkdir -p "$SDK_MIRROR"

# Sparse-checkout: only the two packages we need.
TMP_CLONE="$(mktemp -d)"
trap 'rm -rf "$TMP_CLONE"' EXIT

git clone \
  --depth=1 \
  --branch "$DART_VER" \
  --filter=blob:none \
  --sparse \
  https://github.com/dart-lang/sdk.git \
  "$TMP_CLONE"

(cd "$TMP_CLONE" && git sparse-checkout set pkg/kernel pkg/_fe_analyzer_shared)

mkdir -p "$SDK_MIRROR/pkg"
cp -r "$TMP_CLONE/pkg/kernel" "$SDK_MIRROR/pkg/"
cp -r "$TMP_CLONE/pkg/_fe_analyzer_shared" "$SDK_MIRROR/pkg/"

echo "[setup] Done. Generating package config..."
DART_SDK="$SDK_MIRROR" python3 "$SCRIPT_DIR/gen_package_config.py"
echo "[setup] Ready. Run: ./run.sh --base base.dill --patch patch.dill"
