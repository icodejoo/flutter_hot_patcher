#!/usr/bin/env bash
# Push AOT patch mode benchmark to iOS device
# Usage: ./push_ios_hotpatch_aot.sh [UDID] [none|normal|cpu]
set -euo pipefail

UDID="${1:-040F89ED-E7CC-54B0-A7BB-908EE82C0224}"
PATCH_TYPE="${2:-none}"
BUNDLE_ID="com.hotpatch.bench.hotpatch"
RESULTS="/Users/Cruz/Documents/flutter_hot_patcher/spikes/benchmark/results"
mkdir -p "$RESULTS"

echo "=== HotPatch iOS AOT Mode: $PATCH_TYPE ==="

printf '0'         > /tmp/aot_patch_size.txt
printf "$PATCH_TYPE" > /tmp/aot_patch_type.txt
printf 'aot'       > /tmp/aot_patch_mode.txt
printf ''          > /tmp/aot_empty.txt

xcrun devicectl device copy to --device "$UDID" \
  --domain-type appDataContainer --domain-identifier "$BUNDLE_ID" \
  --source /tmp/aot_patch_size.txt --destination "Documents/patch_size.txt" 2>/dev/null | grep "File on" || true
xcrun devicectl device copy to --device "$UDID" \
  --domain-type appDataContainer --domain-identifier "$BUNDLE_ID" \
  --source /tmp/aot_patch_type.txt --destination "Documents/patch_type.txt" 2>/dev/null | grep "File on" || true
xcrun devicectl device copy to --device "$UDID" \
  --domain-type appDataContainer --domain-identifier "$BUNDLE_ID" \
  --source /tmp/aot_patch_mode.txt --destination "Documents/patch_mode.txt" 2>/dev/null | grep "File on" || true
xcrun devicectl device copy to --device "$UDID" \
  --domain-type appDataContainer --domain-identifier "$BUNDLE_ID" \
  --source /tmp/aot_empty.txt --destination "Documents/benchmark.json" 2>/dev/null || true

echo "  Launching..."
xcrun devicectl device process launch \
  --device "$UDID" --terminate-existing "$BUNDLE_ID" 2>/dev/null
echo "  Waiting 20s..."
sleep 20

OUT="$RESULTS/hotpatch_aot_ios_${PATCH_TYPE}.json"
xcrun devicectl device copy from --device "$UDID" \
  --domain-type appDataContainer --domain-identifier "$BUNDLE_ID" \
  --source "Documents/benchmark.json" \
  --destination "$OUT" 2>/dev/null

python3 -c "
import json, os
p = '$OUT'
if os.path.getsize(p) > 0:
    print('  Result:', json.dumps(json.load(open(p)), indent=2))
else:
    print('  EMPTY - check device logs')
" 2>/dev/null
echo "=== Done ==="
