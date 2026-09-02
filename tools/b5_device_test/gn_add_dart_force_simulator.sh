#!/bin/bash
# gn_add_dart_force_simulator.sh
# Adds dart_force_simulator=true to the ios_release args.gn and re-runs gn.
# This makes ALL Dart code run through the Shorebird Simulator on device,
# which means BLR dispatch in simulator_arm64.cc gets exercised (required for B5).
#
# After this script succeeds, run:
#   ninja -C ~/shorebird_engine/engine/src/flutter/engine/src/out/ios_release flutter_framework
# (estimated 30-90 minutes to rebuild)

set -euo pipefail

FLUTTER_ENGINE_SRC="$HOME/shorebird_engine/engine/src/flutter/engine/src"
OUT_DIR="$FLUTTER_ENGINE_SRC/out/ios_release"
ARGS_GN="$OUT_DIR/args.gn"

if [ ! -f "$ARGS_GN" ]; then
  echo "ERROR: $ARGS_GN not found — B4 must be completed first"
  exit 1
fi

# Check if flag already present
if grep -q "dart_force_simulator" "$ARGS_GN"; then
  echo "dart_force_simulator already in args.gn:"
  grep "dart_force_simulator" "$ARGS_GN"
  echo ""
  echo "Skipping gn re-run (flag already set). If it's set to false, edit manually."
  exit 0
fi

echo "Adding dart_force_simulator = true to $ARGS_GN ..."
echo "" >> "$ARGS_GN"
echo "dart_force_simulator = true" >> "$ARGS_GN"
echo "Done."

echo ""
echo "Re-running gn ..."
cd "$FLUTTER_ENGINE_SRC"
export PATH="$HOME/depot_tools:$PATH"
python3 flutter/tools/gn \
  --no-goma \
  --ios \
  --runtime-mode=release \
  --target-dir=ios_release

echo ""
echo "gn completed. Now rebuild Flutter.framework with:"
echo "  ninja -C $OUT_DIR flutter_framework"
echo ""
echo "Estimated build time: 30-90 minutes."
