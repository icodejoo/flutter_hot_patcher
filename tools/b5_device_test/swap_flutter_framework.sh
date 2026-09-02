#!/bin/bash
# swap_flutter_framework.sh
# Replaces the Flutter.framework in the Xcode project's Pod cache with our
# custom-built one (from B4-3, with our dart-sdk including Shorebird changes).
#
# ⚠️  MUST run AFTER rebuilding Flutter.framework with dart_force_simulator=true
#     (gn_add_dart_force_simulator.sh + ninja) — otherwise C6 won't be exercised.
#
# Run this BEFORE opening the Xcode project, or after `flutter pub get`.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$SCRIPT_DIR/b5_test_app"
OUR_FRAMEWORK="$HOME/shorebird_engine/engine/src/flutter/engine/src/out/ios_release/Flutter.framework"

if [ ! -f "$OUR_FRAMEWORK/Flutter" ]; then
  echo "ERROR: $OUR_FRAMEWORK/Flutter not found."
  echo "Run B4-3 (ninja flutter_framework) first."
  exit 1
fi

echo "Our Flutter.framework binary:"
ls -lh "$OUR_FRAMEWORK/Flutter"
lipo -info "$OUR_FRAMEWORK/Flutter"

echo ""
echo "Checking dart_force_simulator flag..."
ARGS_GN="$HOME/shorebird_engine/engine/src/flutter/engine/src/out/ios_release/args.gn"
if grep -q "dart_force_simulator = true" "$ARGS_GN" 2>/dev/null; then
  echo "✅ dart_force_simulator = true is set in args.gn"
else
  echo "⚠️  WARNING: dart_force_simulator NOT set in args.gn"
  echo "   C6 will NOT be exercised without this flag!"
  echo "   Run: tools/b5_device_test/gn_add_dart_force_simulator.sh"
  echo "   Then rebuild: ninja -C <out_dir> flutter_framework"
  echo "   Then re-run this script."
  echo ""
  read -r -p "Continue anyway? (y/N) " answer
  if [[ "$answer" != "y" && "$answer" != "Y" ]]; then
    exit 1
  fi
fi

# Run flutter pub get to populate Pods
echo ""
echo "Running flutter pub get ..."
cd "$APP_DIR"
/Users/Cruz/fvm/default/bin/flutter pub get --no-example 2>/dev/null || true

# Find where Flutter.framework lives in the build cache
# Flutter caches it in ~/.pub-cache or in the Pods directory after pod install
echo ""
echo "Running pod install to set up Xcode integration..."
cd "$APP_DIR/ios"
if command -v pod &>/dev/null; then
  pod install --repo-update 2>&1 | tail -5 || echo "pod install failed (may need 'gem install cocoapods')"
else
  echo "WARNING: pod command not found. Install via: sudo gem install cocoapods"
fi

# Replace Framework in Pods if present
PODS_FLUTTER="$APP_DIR/ios/Pods/Flutter/Flutter.framework"
if [ -d "$PODS_FLUTTER" ]; then
  echo ""
  echo "Replacing $PODS_FLUTTER ..."
  rm -rf "$PODS_FLUTTER"
  cp -R "$OUR_FRAMEWORK" "$PODS_FLUTTER"
  echo "✅ Pods Flutter.framework replaced with our custom build"
else
  echo "Pods Flutter.framework not found at $PODS_FLUTTER"
  echo "Open Xcode, run Product → Clean Build Folder, then re-run this script."
fi

# Also check .symlinks
SYMLINK_FLUTTER="$APP_DIR/ios/.symlinks/flutter/ios-release/Flutter.framework"
if [ -L "$(dirname "$SYMLINK_FLUTTER")" ] || [ -d "$(dirname "$SYMLINK_FLUTTER")" ]; then
  echo ""
  echo "Also replacing .symlinks Flutter.framework..."
  rm -rf "$SYMLINK_FLUTTER"
  cp -R "$OUR_FRAMEWORK" "$SYMLINK_FLUTTER"
  echo "✅ .symlinks Flutter.framework replaced"
fi

echo ""
echo "=== Done ==="
echo "Now open b5_test_app/ios/Runner.xcworkspace in Xcode,"
echo "select your device, and press Run (▶)."
echo ""
echo "Expected result: app shows 'PASS ✅' after running B5 test."
echo "If dart_force_simulator was NOT set: test will 'pass' trivially (no BLR in sim)."
