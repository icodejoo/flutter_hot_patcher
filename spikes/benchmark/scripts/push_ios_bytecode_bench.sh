#!/bin/bash
# Push working v02 dill (OTA_NEW) for bytecode interpreter benchmark
set -euo pipefail

UDID="${1:-040F89ED-E7CC-54B0-A7BB-908EE82C0224}"
BUNDLE_ID="com.hotpatch.bench.hotpatch"
REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
RESULTS="$REPO_ROOT/spikes/benchmark/results"
mkdir -p "$RESULTS"

# Use the verified v02 dill (PATCHED/OTA_NEW, 439B)
DILL="$REPO_ROOT/tools/patch_server/patches/1.0+1/bytecode-v6/bytecode/patch.dill"
DILL_SIZE=$(stat -f%z "$DILL")
echo "=== HotPatch DILL Bytecode Bench (v02, ${DILL_SIZE}B) ==="

printf "$DILL_SIZE" > /tmp/hp_patch_size.txt
printf 'ota_new'    > /tmp/hp_patch_type.txt
printf 'bytecode'   > /tmp/hp_patch_mode.txt

xcrun devicectl device install --device "$UDID" \
  /Users/Cruz/Library/Developer/Xcode/DerivedData/HotPatchBench-*/Build/Products/Release-iphoneos/HotPatchBench.app 2>/dev/null | tail -1 || true

for f in patch_size patch_type patch_mode; do
  xcrun devicectl device copy to --device "$UDID" \
    --domain-type appDataContainer --domain-identifier "$BUNDLE_ID" \
    --source /tmp/hp_${f}.txt --destination "Documents/${f}.txt" 2>/dev/null | grep "File on" || true
done

# Create bytecode dir and copy dill
xcrun devicectl device copy to --device "$UDID" \
  --domain-type appDataContainer --domain-identifier "$BUNDLE_ID" \
  --source "$DILL" --destination "Documents/bytecode/patch.dill" 2>/dev/null | grep "File on" || true

printf '' > /tmp/hp_empty.txt
xcrun devicectl device copy to --device "$UDID" \
  --domain-type appDataContainer --domain-identifier "$BUNDLE_ID" \
  --source /tmp/hp_empty.txt --destination "Documents/benchmark.json" 2>/dev/null || true

echo "  Launching..."
xcrun devicectl device process launch \
  --device "$UDID" --terminate-existing "$BUNDLE_ID" 2>/dev/null
echo "  Waiting 15s..."
sleep 15

OUT="$RESULTS/hotpatch_bytecode_ios_ota_new.json"
xcrun devicectl device copy from --device "$UDID" \
  --domain-type appDataContainer --domain-identifier "$BUNDLE_ID" \
  --source "Documents/benchmark.json" \
  --destination "$OUT" 2>/dev/null

python3 -c "
import json, os
p = '$OUT'
if os.path.exists(p) and os.path.getsize(p) > 0:
    d = json.load(open(p))
    print('  Result:', json.dumps(d, indent=2))
    ns = d.get('greet_call_ns', 0)
    us = ns / 1000.0
    print(f'  greet() mean: {ns} ns = {us:.1f} μs')
else:
    print('  EMPTY - check device logs')
"
echo "=== Done ==="
