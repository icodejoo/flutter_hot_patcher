#!/usr/bin/env bash
# Route-A regression: build the demo app + module and assert the module
# actually changes app behaviour.
set -euo pipefail
R="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="${1:-${TMPDIR:-/tmp}/route_a_test}"
rm -rf "$OUT"

"$R/tools/route_a/build.sh" \
  "$R/spikes/route_a_v2/app" bin/main.dart \
  "$R/spikes/route_a_v2/modules/patch_v1.dart" "$OUT" > "$OUT.build.log" 2>&1 \
  || { cat "$OUT.build.log"; exit 1; }

SDK_OUT="${FHP_DART_OUT:-$HOME/dart/sdk/xcodebuild/ReleaseARM64DM}"
actual="$("$SDK_OUT/dartaotruntime_product" "$OUT/app.snapshot" "$OUT/module.bytecode")"
expected=$'before: BASELINE\nafter: PATCHED_V1'

if [ "$actual" = "$expected" ]; then
  echo "PASS route_a_e2e"
else
  echo "FAIL route_a_e2e"
  echo "--- expected"; echo "$expected"
  echo "--- actual";   echo "$actual"
  exit 1
fi
