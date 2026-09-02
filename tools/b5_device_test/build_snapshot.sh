#!/bin/bash
# build_snapshot.sh
# Compiles test.dart → iOS arm64 AOT snapshot (assembly → object file)
# This does NOT embed into a Flutter app — it just verifies the compile pipeline.
#
# Prerequisites:
#   - ~/dart-3122/sdk/xcodebuild/ProductARM64/gen_snapshot (built in B4)
#   - /Users/Cruz/fvm/default/bin/cache/dart-sdk/bin/dart (system Dart)
#   - Xcode command line tools (xcrun clang)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# Must use matching Dart SDK for AOT kernel compilation (format must match gen_snapshot's expectation)
DART_SDK_ROOT="$HOME/dart-3122/sdk"
DART_BIN="$DART_SDK_ROOT/tools/sdks/dart-sdk/bin/dart"
GEN_KERNEL_DART="$DART_SDK_ROOT/pkg/vm/bin/gen_kernel.dart"
VM_PLATFORM="$DART_SDK_ROOT/xcodebuild/ProductARM64/vm_platform.dill"
GEN_SNAPSHOT="$DART_SDK_ROOT/xcodebuild/ProductARM64/gen_snapshot"
TEST_DART="$SCRIPT_DIR/test.dart"
OUTDIR="$SCRIPT_DIR/build"

mkdir -p "$OUTDIR"

echo "=== Step 1: Dart source → kernel.dill (AOT mode via gen_kernel) ==="
# NOTE: Must use gen_kernel.dart (not 'dart compile kernel') — the kernel format version
# must match what gen_snapshot expects (format 130 for Dart 3.12.2).
"$DART_BIN" "$GEN_KERNEL_DART" --aot --platform "$VM_PLATFORM" \
  --output "$OUTDIR/kernel.dill" "$TEST_DART"
echo "kernel.dill: $(du -h "$OUTDIR/kernel.dill" | cut -f1)"

echo ""
echo "=== Step 2: kernel.dill → snapshot.S (AOT assembly for arm64) ==="
"$GEN_SNAPSHOT" \
  --deterministic \
  --snapshot_kind=app-aot-assembly \
  --assembly="$OUTDIR/snapshot.S" \
  "$OUTDIR/kernel.dill"
echo "snapshot.S: $(wc -l < "$OUTDIR/snapshot.S") lines"

echo ""
echo "=== Step 3: snapshot.S → snapshot.o (assemble for arm64-apple-ios15.0) ==="
xcrun clang \
  -arch arm64 \
  -miphoneos-version-min=15.0 \
  -isysroot "$(xcrun --sdk iphoneos --show-sdk-path)" \
  -c "$OUTDIR/snapshot.S" \
  -o "$OUTDIR/snapshot.o"
echo "snapshot.o: $(du -h "$OUTDIR/snapshot.o" | cut -f1)"

echo ""
echo "=== Build pipeline OK ==="
echo "Outputs in $OUTDIR/:"
ls -lh "$OUTDIR/"
echo ""
echo "Note: This snapshot targets iOS arm64 and cannot run on macOS."
echo "To embed in the Flutter app, the Xcode project links snapshot.o + Flutter.framework."
