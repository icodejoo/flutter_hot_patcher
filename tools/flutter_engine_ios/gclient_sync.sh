#!/bin/bash
set -e
export PATH="$HOME/depot_tools:$PATH"
export DEPOT_TOOLS_UPDATE=0
export GCLIENT_SUPPRESS_GIT_VERSION_WARNING=1

ENGINE_DIR="$HOME/engine_ios"
DART_SDK="$HOME/dart/sdk"

echo "=== Check third_party status ==="
ls "$ENGINE_DIR/src/third_party/" 2>/dev/null | head -20
echo ""
echo "Skia present: $(ls $ENGINE_DIR/src/third_party/skia/ 2>/dev/null | wc -l) files"

echo "=== Full gclient sync (will take 30-90 min) ==="
cd "$ENGINE_DIR"

# Run gclient sync - this will fetch all missing dependencies
gclient sync --no-history -j8 2>&1 | tee /tmp/gclient_full_sync.log

echo "=== Re-symlink Dart SDK after sync ==="
# gclient sync might have overwritten the symlink
rm -rf "$ENGINE_DIR/src/third_party/dart" 2>/dev/null || true
mkdir -p "$ENGINE_DIR/src/third_party"
ln -sf "$DART_SDK" "$ENGINE_DIR/src/third_party/dart"
echo "Dart SDK relinked: $(readlink $ENGINE_DIR/src/third_party/dart)"

echo "=== Check Skia after sync ==="
ls "$ENGINE_DIR/src/third_party/skia/" 2>/dev/null | head -5 || echo "Skia still missing"

echo "=== Try GN configure again ==="
cd "$ENGINE_DIR/src/flutter"
"$HOME/depot_tools/vpython3" tools/gn \
  --ios \
  --runtime-mode release \
  --no-prebuilt-dart-sdk \
  "--gn-args=dart_dynamic_modules=true" \
  2>&1 | tee /tmp/gn_after_sync.log

echo "GN done. Build dirs:"
ls "$ENGINE_DIR/src/out/" 2>/dev/null

echo "GCLIENT_FULL_DONE"
