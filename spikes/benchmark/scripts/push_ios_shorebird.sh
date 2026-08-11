#!/usr/bin/env bash
# Publish Shorebird patch for iOS, launch app (Shorebird pulls via CDN), collect result
# Usage: ./push_ios_shorebird.sh [UDID] [normal|cpu]
# Note: Shorebird delivers patches via its CDN — requires device internet access.
#       This script handles the publish + device launch + result collection flow.
# Requires: shorebird CLI (~/.shorebird/bin/shorebird), devicectl (Xcode 15+)
set -euo pipefail

UDID="${1:-040F89ED-E7CC-54B0-A7BB-908EE82C0224}"
PATCH_TYPE="${2:-normal}"
REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
BENCH_DIR="$REPO_ROOT/spikes/benchmark/shorebird_demo"
RESULTS="$REPO_ROOT/spikes/benchmark/results"
BUNDLE_ID="com.hotpatch.bench.shorebird_demo"
SHOREBIRD="$HOME/.shorebird/bin/shorebird"

echo "=== Shorebird iOS Patch ==="
echo "  UDID:        $UDID"
echo "  patch_type:  $PATCH_TYPE"

# 1. Select patch source file
ORIG_GREET="$BENCH_DIR/lib/greet.dart"
case "$PATCH_TYPE" in
  normal) PATCH_SRC="$BENCH_DIR/patches/greet_v1.dart" ;;
  cpu)    PATCH_SRC="$BENCH_DIR/patches/greet_cpu.dart" ;;
  *) echo "Usage: $0 [UDID] normal|cpu"; exit 1 ;;
esac

# 2. Swap greet.dart → patch variant, publish, restore
cp "$ORIG_GREET" "${ORIG_GREET}.bak"
cp "$PATCH_SRC" "$ORIG_GREET"
echo "  Swapped greet.dart → $PATCH_TYPE variant"

PATCH_OUTPUT_LOG=$(mktemp)
cd "$BENCH_DIR"
"$SHOREBIRD" patch ios --staging 2>&1 | tee "$PATCH_OUTPUT_LOG" || {
    cp "${ORIG_GREET}.bak" "$ORIG_GREET"
    rm -f "${ORIG_GREET}.bak" "$PATCH_OUTPUT_LOG"
    echo "  [ERROR] shorebird patch failed — check shorebird login"
    exit 1
}

# Extract patch size from shorebird output (best-effort)
PATCH_SIZE=$(grep -oE '[0-9]+ bytes' "$PATCH_OUTPUT_LOG" | grep -oE '[0-9]+' | tail -1 || echo "0")
echo "  Shorebird patch published, size: ${PATCH_SIZE}B"

cp "${ORIG_GREET}.bak" "$ORIG_GREET"
rm -f "${ORIG_GREET}.bak" "$PATCH_OUTPUT_LOG"

# 3. Push metadata to device (patch_size.txt, patch_type.txt)
printf '%s' "$PATCH_SIZE" > /tmp/bench_patch_size.txt
printf '%s' "$PATCH_TYPE" > /tmp/bench_patch_type.txt

CONTAINER=$(xcrun devicectl device info containers \
  --device "$UDID" --bundle-id "$BUNDLE_ID" 2>/dev/null \
  | grep -m1 'dataContainer' | awk '{print $NF}' || echo "")

for META in bench_patch_size.txt bench_patch_type.txt; do
    DEST_NAME="${META/bench_patch_/patch_}"
    xcrun devicectl device copy to --device "$UDID" \
      --source "/tmp/$META" \
      --destination "${CONTAINER}/Documents/${DEST_NAME}" 2>/dev/null || true
done

# 4. Launch app (Shorebird updater will pull patch on startup)
echo "  Launching $BUNDLE_ID (Shorebird will pull patch from CDN)..."
xcrun devicectl device process launch \
  --device "$UDID" \
  --bundle-id "$BUNDLE_ID" 2>/dev/null || \
  echo "  [WARN] Launch failed — app may not be installed"

echo "  Waiting 20s for patch download + benchmark..."
sleep 20

# 5. Pull result
echo "  Pulling benchmark.json..."
xcrun devicectl device copy from \
  --device "$UDID" \
  --source "${CONTAINER}/Documents/benchmark.json" \
  --destination "$RESULTS/shorebird_ios_${PATCH_TYPE}.json" 2>/dev/null || {
    echo "  [WARN] Pull failed"
  }

if [ -f "$RESULTS/shorebird_ios_${PATCH_TYPE}.json" ]; then
    echo "  Result:"
    cat "$RESULTS/shorebird_ios_${PATCH_TYPE}.json"
    echo ""
fi

echo "=== Done ==="
