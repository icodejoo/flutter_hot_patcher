#!/bin/bash
# Phase B macOS セットアップ: depot_tools → fetch dart → checkout commit → apply patch → build iOS
# Run from any directory. Takes ~30-60 minutes for fetch dart.
set -e

DART_COMMIT="1aa7d7321fbfcf0cb07f4d1b62fafed76ca7e5fb"
PATCH_FILE="/Users/Cruz/Documents/flutter_hot_patcher/spikes/gate1_mixed_execution/vm_patch/gate1_vm_patch.diff"

# Step 1: depot_tools
if [ ! -d "$HOME/depot_tools" ]; then
  echo "=== Installing depot_tools ==="
  git clone https://chromium.googlesource.com/chromium/tools/depot_tools.git "$HOME/depot_tools"
fi
export PATH="$HOME/depot_tools:$PATH"

# Step 2: fetch dart
mkdir -p "$HOME/dart"
cd "$HOME/dart"
if [ ! -d sdk ]; then
  echo "=== Fetching Dart SDK (this takes 30-60 minutes) ==="
  fetch --no-history dart
  echo "=== fetch dart DONE ==="
fi

# Step 3: lock commit
cd "$HOME/dart/sdk"
echo "=== Checking out commit $DART_COMMIT ==="
git fetch origin
git checkout "$DART_COMMIT"
gclient sync --nohooks --no-history

# Step 4: apply patch
echo "=== Applying gate1_vm_patch.diff ==="
git apply "$PATCH_FILE"
echo "=== Patch applied ==="

# Step 5: build iOS arm64
echo "=== Building iOS arm64 Release (this takes 30-60 minutes) ==="
./tools/build.py --os ios --arch arm64 -m release --dart-dynamic-modules \
    runtime runtime_precompiled

echo ""
echo "=== BUILD COMPLETE ==="
echo "Products in: $HOME/dart/sdk/out/ReleaseIOS/"
ls "$HOME/dart/sdk/out/" 2>/dev/null || true
