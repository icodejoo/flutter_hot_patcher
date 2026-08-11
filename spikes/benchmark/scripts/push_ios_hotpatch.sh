#!/usr/bin/env bash
# Push hotpatch .dill to iOS device via USB, launch app, pull benchmark.json
# Usage: ./push_ios_hotpatch.sh [UDID] [normal|cpu]
# Requires: ideviceinstaller (brew install ideviceinstaller), devicectl (Xcode 15+)
set -euo pipefail

UDID="${1:-040F89ED-E7CC-54B0-A7BB-908EE82C0224}"
PATCH_TYPE="${2:-normal}"
REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
RESULTS="$REPO_ROOT/spikes/benchmark/results"
BENCH_DIR="$REPO_ROOT/spikes/benchmark/hotpatch_demo"
BUNDLE_ID="com.hotpatch.bench.hotpatch"

echo "=== HotPatch iOS USB Push ==="
echo "  UDID:        $UDID"
echo "  patch_type:  $PATCH_TYPE"

# 1. Build patch .dill
cd "$BENCH_DIR"
./build_patch.sh "$PATCH_TYPE"
PATCH_FILE="$RESULTS/hotpatch_patch.dill"
PATCH_SIZE=$(cat "$RESULTS/hotpatch_patch_size.txt")
echo "  patch_size:  ${PATCH_SIZE}B"

# 2. Write metadata files
printf '%s' "$PATCH_SIZE" > /tmp/bench_patch_size.txt
printf '%s' "$PATCH_TYPE" > /tmp/bench_patch_type.txt

# 3. Push patch.dill + metadata to device Documents via devicectl
echo "  Pushing files to device..."
xcrun devicectl device copy to \
  --device "$UDID" \
  --source "$PATCH_FILE" \
  --destination "$(xcrun devicectl device info containers \
      --device "$UDID" --bundle-id "$BUNDLE_ID" 2>/dev/null \
      | grep -m1 'dataContainer' | awk '{print $NF}')/Documents/patch.dill" \
  2>/dev/null || {
    echo "  [INFO] devicectl copy with container path failed, trying direct path..."
    # Fallback: use idevicefs if available
    if command -v ifuse &>/dev/null; then
        MOUNT_PT=$(mktemp -d)
        ifuse --udid "$UDID" --appid "$BUNDLE_ID" "$MOUNT_PT" && \
          cp "$PATCH_FILE" "$MOUNT_PT/Documents/patch.dill" && \
          cp /tmp/bench_patch_size.txt "$MOUNT_PT/Documents/patch_size.txt" && \
          cp /tmp/bench_patch_type.txt "$MOUNT_PT/Documents/patch_type.txt" && \
          umount "$MOUNT_PT"
        rmdir "$MOUNT_PT"
    else
        echo "  [WARN] Cannot push files — install ifuse or use Xcode to deploy"
        echo "  Manual step: copy patch.dill, patch_size.txt, patch_type.txt to app Documents"
    fi
}

# Push metadata separately (devicectl per-file)
xcrun devicectl device copy to --device "$UDID" \
  --source /tmp/bench_patch_size.txt \
  --destination "$(xcrun devicectl device info containers \
      --device "$UDID" --bundle-id "$BUNDLE_ID" 2>/dev/null \
      | grep -m1 'dataContainer' | awk '{print $NF}')/Documents/patch_size.txt" \
  2>/dev/null || true
xcrun devicectl device copy to --device "$UDID" \
  --source /tmp/bench_patch_type.txt \
  --destination "$(xcrun devicectl device info containers \
      --device "$UDID" --bundle-id "$BUNDLE_ID" 2>/dev/null \
      | grep -m1 'dataContainer' | awk '{print $NF}')/Documents/patch_type.txt" \
  2>/dev/null || true

# 4. Launch app
echo "  Launching $BUNDLE_ID..."
xcrun devicectl device process launch \
  --device "$UDID" \
  --bundle-id "$BUNDLE_ID" 2>/dev/null || \
  echo "  [WARN] Launch failed — app may not be installed"

echo "  Waiting 8s for benchmark to complete..."
sleep 8

# 5. Pull benchmark.json
echo "  Pulling benchmark.json..."
CONTAINER=$(xcrun devicectl device info containers \
  --device "$UDID" --bundle-id "$BUNDLE_ID" 2>/dev/null \
  | grep -m1 'dataContainer' | awk '{print $NF}')
xcrun devicectl device copy from \
  --device "$UDID" \
  --source "${CONTAINER}/Documents/benchmark.json" \
  --destination "$RESULTS/hotpatch_ios_${PATCH_TYPE}.json" 2>/dev/null || {
    echo "  [WARN] Pull failed — check device console logs with:"
    echo "  xcrun devicectl device console --device $UDID"
    exit 1
  }

if [ -f "$RESULTS/hotpatch_ios_${PATCH_TYPE}.json" ]; then
    echo "  Result:"
    cat "$RESULTS/hotpatch_ios_${PATCH_TYPE}.json"
    echo ""
fi

echo "=== Done ==="
