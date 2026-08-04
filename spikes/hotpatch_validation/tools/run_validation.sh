#!/usr/bin/env bash
# iOS Hotpatch Validation Suite Runner
# Requires bash 4+ (uses associative arrays) — on macOS use: brew install bash
# OR: env bash4 tools/run_validation.sh
set -euo pipefail

REPO=~/Documents/flutter_hot_patcher
VAL=$REPO/spikes/hotpatch_validation
HOST_OUT=$HOME/dart/sdk/xcodebuild/ReleaseARM64
LINKER=$REPO/spikes/gate2_linker/tools/kernel_linker
WORK=/tmp/hotpatch_val

mkdir -p $WORK
rm -f $WORK/kernel_results.jsonl

PACKAGES_FLAG=""
if [ -f "$VAL/.dart_tool/package_config.json" ]; then
  PACKAGES_FLAG="--packages $VAL/.dart_tool/package_config.json"
fi

SINGLE_SCENARIO="${SINGLE_SCENARIO:-}"
DRY_RUN="${DRY_RUN:-}"

get_scenarios() {
  local file_id="$1"
  case "$file_id" in
    t01_primitives)   echo "T01 T02 T03 T04 T05 T06 T07" ;;
    t02_collections)  echo "T08 T09 T10 T11 T12 T13 T14" ;;
    t03_nullsafety)   echo "T15 T16 T17 T18 T19" ;;
    t04_constants)    echo "T20 T21 T22 T23 T24 T25" ;;
    t05_functions)    echo "T26 T27 T28 T29 T30 T31 T32 T33 T34" ;;
    t06_classes)      echo "T35 T36 T37 T38 T39 T40 T41 T42" ;;
    t07_generics)     echo "T43 T44 T45 T46" ;;
    t08_operators)    echo "T47 T48 T49 T50 T51" ;;
    t09_async)        echo "T52 T53 T54 T55" ;;
    t10_errors)       echo "T56 T57 T58 T59" ;;
    t11_strings)      echo "T60 T61 T62 T63" ;;
    t12_thirdparty)   echo "T64 T65 T66 T67 T68" ;;
    t13_flutter_like) echo "T69 T70 T71 T72 T73" ;;
    t14_propagation)  echo "T74 T75 T76 T77 T78 T79 T80 T81" ;;
    t15_hierarchy)    echo "T82 T83 T84 T85 T86" ;;
    t16_edge)         echo "T87 T88 T89 T90 T91" ;;
    *)                echo "" ;;
  esac
}

FILE_ORDER="t01_primitives t02_collections t03_nullsafety t04_constants t05_functions
            t06_classes t07_generics t08_operators t09_async t10_errors
            t11_strings t12_thirdparty t13_flutter_like t14_propagation t15_hierarchy t16_edge"

for FILE_ID in $FILE_ORDER; do
  if [ -n "$SINGLE_SCENARIO" ] && [ "$FILE_ID" != "$SINGLE_SCENARIO" ]; then
    continue
  fi

  BASELINE_DILL=$WORK/${FILE_ID}_base.dill
  PATCH_DILL=$WORK/${FILE_ID}_patch.dill
  LINKER_OUT=$WORK/${FILE_ID}_linker
  LIB_FILE=$VAL/lib/${FILE_ID}.dart
  PATCH_FILE=$VAL/patches/${FILE_ID}.dart

  echo ""
  echo "=== Processing $FILE_ID ==="

  if [ -n "$DRY_RUN" ]; then
    echo "  [DRY-RUN] Would compile $LIB_FILE"
    continue
  fi

  # 1. Compile baseline dill
  echo "  [1/4] Compiling baseline..."
  if ! $HOST_OUT/dartaotruntime_product \
    $HOST_OUT/gen/gen_kernel_aot.dart.snapshot \
    --platform $HOST_OUT/vm_platform.dill --aot \
    $PACKAGES_FLAG \
    --output "$BASELINE_DILL" \
    "$LIB_FILE" 2>&1; then
    echo "  ERROR: baseline compile failed for $FILE_ID"
    continue
  fi

  # 2. COPY-COMPILE-RESTORE: compile patch from same path as baseline
  echo "  [2/4] Compiling patch (copy-compile-restore)..."
  cp "$LIB_FILE" "${LIB_FILE}.bak"
  cp "$PATCH_FILE" "$LIB_FILE"

  $HOST_OUT/dartaotruntime_product \
    $HOST_OUT/gen/gen_kernel_aot.dart.snapshot \
    --platform $HOST_OUT/vm_platform.dill --aot \
    $PACKAGES_FLAG \
    --output "$PATCH_DILL" \
    "$LIB_FILE" 2>&1
  COMPILE_EXIT=$?

  # Restore original regardless of compile result
  mv "${LIB_FILE}.bak" "$LIB_FILE"

  if [ $COMPILE_EXIT -ne 0 ]; then
    echo "  ERROR: patch compile failed for $FILE_ID"
    continue
  fi

  # 3. Run kernel_linker
  echo "  [3/4] Running kernel_linker diff..."
  mkdir -p "$LINKER_OUT"
  dart --packages=$LINKER/.dart_tool/package_config.json \
    $LINKER/bin/kernel_linker.dart \
    --base "$BASELINE_DILL" \
    --patch "$PATCH_DILL" \
    --dart-sdk-commit 1aa7d7321fb \
    --baseline-snapshot "$BASELINE_DILL" \
    --output-dir "$LINKER_OUT" \
    --allow-empty 2>&1 | tee "$WORK/${FILE_ID}_linker.log" || true

  # 4. Validate kernel_linker output vs expected.json
  echo "  [4/4] Validating manifest..."
  SCENARIOS=$(get_scenarios "$FILE_ID")
  python3 $VAL/tools/validate_manifest.py \
    "$LINKER_OUT/manifest.json" \
    "$VAL/tools/expected.json" \
    "$FILE_ID" \
    $SCENARIOS \
    >> $WORK/kernel_results.jsonl 2>&1 || true

  echo "  Done: $FILE_ID"
done

echo ""
echo "=== Merging results ==="
python3 - << 'PYEOF'
import json
results = []
try:
    for line in open('/tmp/hotpatch_val/kernel_results.jsonl'):
        line = line.strip()
        if line:
            try:
                results.extend(json.loads(line))
            except Exception as e:
                print(f"Parse error: {e}: {line[:80]}")
except FileNotFoundError:
    pass
json.dump(results, open('/tmp/hotpatch_val/kernel_only_results.json', 'w'), indent=2)
total = len(results)
passed = sum(1 for r in results if r.get('kernel_pass'))
fn = sum(len(r.get('false_negatives', [])) for r in results)
fp = sum(len(r.get('false_positives', [])) for r in results)
print(f"Kernel validation: {total} scenarios, {passed} passed, FalseNeg={fn}, FalsePos={fp}")
for r in results:
    if not r.get('kernel_pass'):
        kl = '[KNOWN]' if r.get('known_limitation') else ''
        print(f"  FAIL {r['id']} {kl}: FN={r.get('false_negatives',[])} FP={r.get('false_positives',[])} ISSUES={r.get('issues',[])}")
PYEOF

echo ""
echo "=== Done. Results: /tmp/hotpatch_val/kernel_results.jsonl ==="
