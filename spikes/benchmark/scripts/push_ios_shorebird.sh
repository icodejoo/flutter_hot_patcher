#!/usr/bin/env bash
# Shorebird iOS benchmark: publish patch → device downloads (needs WiFi) → two-launch cycle → pull result
# Usage: ./push_ios_shorebird.sh [UDID] [none|normal|cpu]
set -euo pipefail

UDID="${1:-040F89ED-E7CC-54B0-A7BB-908EE82C0224}"
PATCH_TYPE="${2:-normal}"
REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
BENCH_DIR="$REPO_ROOT/spikes/benchmark/shorebird_demo"
RESULTS="$REPO_ROOT/spikes/benchmark/results"
BUNDLE_ID="com.hotpatch.bench.shorebirdDemo"
SHOREBIRD="$HOME/.shorebird/bin/shorebird"

echo "=== Shorebird iOS Patch: $PATCH_TYPE ==="
echo "  UDID: $UDID"
echo "  NOTE: Device must have WiFi internet access for patch download."

_push_meta() {
  local SIZE="$1" TYPE="$2"
  printf "$SIZE" > /tmp/bench_patch_size.txt
  printf "$TYPE" > /tmp/bench_patch_type.txt
  for f in bench_patch_size.txt bench_patch_type.txt; do
    local DEST="Documents/${f/bench_patch_/patch_}"
    xcrun devicectl device copy to --device "$UDID" \
      --domain-type appDataContainer --domain-identifier "$BUNDLE_ID" \
      --source "/tmp/$f" --destination "$DEST" 2>/dev/null || true
  done
}

_launch_wait() {
  local SECS="$1"
  xcrun devicectl device process launch --device "$UDID" "$BUNDLE_ID" 2>/dev/null
  echo "  Waiting ${SECS}s..."
  sleep "$SECS"
}

_pull_result() {
  local OUT="$RESULTS/shorebird_ios_${PATCH_TYPE}.json"
  xcrun devicectl device copy from --device "$UDID" \
    --domain-type appDataContainer --domain-identifier "$BUNDLE_ID" \
    --source "Documents/benchmark.json" \
    --destination "$OUT" 2>/dev/null && \
    echo "  Result: $(python3 -c "import json; d=json.load(open('$OUT')); print(json.dumps(d))" 2>/dev/null)" || \
    echo "  [WARN] Could not pull benchmark.json"
}

if [ "$PATCH_TYPE" = "none" ]; then
  # Baseline: no patch
  _push_meta "0" "none"
  printf '' > /tmp/empty.txt
  xcrun devicectl device copy to --device "$UDID" \
    --domain-type appDataContainer --domain-identifier "$BUNDLE_ID" \
    --source /tmp/empty.txt --destination "Documents/benchmark.json" 2>/dev/null || true
  _launch_wait 15
  _pull_result
  exit 0
fi

# 1. Publish patch
ORIG="$BENCH_DIR/lib/greet.dart"
cp "$ORIG" "${ORIG}.bak"
[[ "$PATCH_TYPE" == "normal" ]] && cp "$BENCH_DIR/patches/greet_v1.dart" "$ORIG"
[[ "$PATCH_TYPE" == "cpu"    ]] && cp "$BENCH_DIR/patches/greet_cpu.dart" "$ORIG"

cd "$BENCH_DIR"
echo "  Publishing Shorebird patch..."
PATCH_LOG=$( "$SHOREBIRD" patch ios --release-version 1.0.0+3 2>&1 )
echo "$PATCH_LOG" | grep -E "✅|Error|Patch" | head -3
cp "${ORIG}.bak" "$ORIG" && rm -f "${ORIG}.bak"

PATCH_SIZE=$(echo "$PATCH_LOG" | grep -oE '[0-9]+ bytes' | grep -oE '[0-9]+' | tail -1 || echo "0")

# 2. Clear old benchmark.json + set metadata
printf '' > /tmp/empty.txt
xcrun devicectl device copy to --device "$UDID" \
  --domain-type appDataContainer --domain-identifier "$BUNDLE_ID" \
  --source /tmp/empty.txt --destination "Documents/benchmark.json" 2>/dev/null || true
_push_meta "$PATCH_SIZE" "$PATCH_TYPE"

# 3. Launch 1: Shorebird downloads patch (needs WiFi)
echo "  Launch 1: downloading patch from Shorebird CDN..."
_launch_wait 25

# 4. Launch 2: patch applied, run benchmark
echo "  Launch 2: patch active, running benchmark..."
printf '' > /tmp/empty.txt
xcrun devicectl device copy to --device "$UDID" \
  --domain-type appDataContainer --domain-identifier "$BUNDLE_ID" \
  --source /tmp/empty.txt --destination "Documents/benchmark.json" 2>/dev/null || true
_launch_wait 15

# 5. Pull result
_pull_result
echo "=== Done ==="
