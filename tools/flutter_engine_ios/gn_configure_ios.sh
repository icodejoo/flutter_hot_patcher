#!/bin/bash
set -e

# Fix depot_tools PATH first
export PATH="$HOME/depot_tools:$PATH"
export DEPOT_TOOLS_UPDATE=0
export GCLIENT_SUPPRESS_GIT_VERSION_WARNING=1

echo "=== Check vpython3 ==="
which vpython3 2>/dev/null || echo "vpython3 not in PATH"
ls "$HOME/depot_tools/vpython3" 2>/dev/null || echo "vpython3 not in depot_tools"

# vpython3 is in depot_tools as a wrapper — trigger its setup
"$HOME/depot_tools/vpython3" --version 2>&1 | head -2 || true

echo "=== Check Python3 ==="
which python3 && python3 --version

echo "=== Test tools/gn ==="
cd ~/engine_ios/src/flutter

# Try with vpython3 directly
"$HOME/depot_tools/vpython3" tools/gn --help 2>&1 | grep -E "ios|dynamic|gn-args" | head -10

echo ""
echo "=== Build iOS with dart_dynamic_modules via --gn-args ==="
# --gn-args allows passing arbitrary GN arguments
# dart_dynamic_modules=true is the GN variable that enables dynamic modules
"$HOME/depot_tools/vpython3" tools/gn \
  --ios \
  --runtime-mode release \
  --no-prebuilt-dart-sdk \
  "--gn-args=dart_dynamic_modules=true" \
  2>&1 | tee /tmp/gn_ios_final.log

BUILD_DIR=$(ls ~/engine_ios/src/out/ 2>/dev/null | grep "ios_release" | head -1)
echo "Build dir: out/$BUILD_DIR"

if [ -z "$BUILD_DIR" ]; then
  echo "ERROR: No build directory created by GN"
  echo "--- GN log ---"
  cat /tmp/gn_ios_final.log
  exit 1
fi

echo "=== Verify dart_dynamic_modules in args.gn ==="
grep "dart_dynamic_modules" ~/engine_ios/src/out/$BUILD_DIR/args.gn 2>/dev/null || \
  echo "WARNING: dart_dynamic_modules not in args.gn"

echo "=== Start ninja build (background) ==="
echo "Ninja command: ninja -C ~/engine_ios/src/out/$BUILD_DIR flutter"
ninja -C "$HOME/engine_ios/src/out/$BUILD_DIR" flutter 2>&1 | tee /tmp/ninja_ios_final.log
echo "Ninja build complete"

echo "=== Artifacts ==="
ls "$HOME/engine_ios/src/out/$BUILD_DIR/" | head -15
echo "BUILD_COMPLETE"
