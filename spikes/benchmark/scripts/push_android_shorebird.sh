#!/usr/bin/env bash
# Publish Shorebird patch for Android, launch app, collect benchmark.json
# Usage: ./push_android_shorebird.sh [DEVICE_SERIAL] [normal|cpu]
# DEVICE_SERIAL: leave empty to use first connected adb device
# Requires: adb (android-platform-tools), shorebird CLI
set -euo pipefail

DEVICE="${1:-}"
PATCH_TYPE="${2:-normal}"
REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
BENCH_DIR="$REPO_ROOT/spikes/benchmark/shorebird_demo"
RESULTS="$REPO_ROOT/spikes/benchmark/results"
PKG="com.hotpatch.bench.shorebird_demo"
SHOREBIRD="$HOME/.shorebird/bin/shorebird"
ADB="adb${DEVICE:+ -s $DEVICE}"

echo "=== Shorebird Android Patch ==="
echo "  device:      ${DEVICE:-default}"
echo "  patch_type:  $PATCH_TYPE"

# 1. Select patch source, publish
ORIG_GREET="$BENCH_DIR/lib/greet.dart"
case "$PATCH_TYPE" in
  normal) PATCH_SRC="$BENCH_DIR/patches/greet_v1.dart" ;;
  cpu)    PATCH_SRC="$BENCH_DIR/patches/greet_cpu.dart" ;;
  *) echo "Usage: $0 [DEVICE_SERIAL] normal|cpu"; exit 1 ;;
esac

cp "$ORIG_GREET" "${ORIG_GREET}.bak"
cp "$PATCH_SRC" "$ORIG_GREET"

PATCH_LOG=$(mktemp)
cd "$BENCH_DIR"
"$SHOREBIRD" patch android --staging 2>&1 | tee "$PATCH_LOG" || {
    cp "${ORIG_GREET}.bak" "$ORIG_GREET"
    rm -f "${ORIG_GREET}.bak" "$PATCH_LOG"
    echo "  [ERROR] shorebird patch android failed"
    exit 1
}

PATCH_SIZE=$(grep -oE '[0-9]+ bytes' "$PATCH_LOG" | grep -oE '[0-9]+' | tail -1 || echo "0")
echo "  Shorebird patch published, size: ${PATCH_SIZE}B"
cp "${ORIG_GREET}.bak" "$ORIG_GREET"
rm -f "${ORIG_GREET}.bak" "$PATCH_LOG"

# 2. Push metadata via adb
FILES_DIR="/sdcard/Android/data/$PKG/files"
$ADB shell mkdir -p "$FILES_DIR"
echo -n "$PATCH_SIZE" | $ADB shell "cat > $FILES_DIR/patch_size.txt"
echo -n "$PATCH_TYPE" | $ADB shell "cat > $FILES_DIR/patch_type.txt"

# 3. Launch app
echo "  Launching $PKG..."
$ADB shell am start -n "$PKG/$PKG.MainActivity" 2>/dev/null || \
$ADB shell am start -n "$PKG/com.hotpatch.bench.shorebird_demo.MainActivity"

echo "  Waiting 20s for patch download + benchmark..."
sleep 20

# 4. Pull result
mkdir -p "$RESULTS"
$ADB pull "$FILES_DIR/benchmark.json" "$RESULTS/shorebird_android_${PATCH_TYPE}.json" 2>/dev/null || {
    echo "  [WARN] Pull failed — check: adb logcat | grep BENCH"
}

if [ -f "$RESULTS/shorebird_android_${PATCH_TYPE}.json" ]; then
    echo "  Result:"
    cat "$RESULTS/shorebird_android_${PATCH_TYPE}.json"
    echo ""
fi

echo "=== Done ==="
