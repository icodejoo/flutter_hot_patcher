#!/bin/bash
# R7 spike probe: does --obfuscate produce cross-build renaming drift that
# fools diff_linker, given the SAME unchanged source compiled TWICE
# independently (simulating "base build" vs "patch build, but nothing
# actually changed" -- the strictest possible no-op test)?
#
# Reuses p1_sample/base/app.dart (already ~3000 functions, good sample size)
# as the shared, UNCHANGED source for all 4 builds below. Ground truth for
# every comparison in this probe is "0 real changes" by construction.
#
#   noobf1 vs noobf2  -- baseline cross-build determinism (no obfuscation)
#   obf1   vs obf2    -- same question WITH --obfuscate
#
# If obf1-vs-obf2 shows MORE byte-changed noise than noobf1-vs-noobf2, that
# noise is attributable to obfuscation-name drift, not generic build
# nondeterminism. Confirms/refutes REVIEW #14's flagged-but-untested risk.
set -e
export DART_SDK_SRC=/root/dart/sdk
SDK_OUT="$DART_SDK_SRC/out/ReleaseX64"
GEN_KERNEL="$SDK_OUT/gen/gen_kernel_aot.dart.snapshot"
GEN_SNAPSHOT="$SDK_OUT/gen_snapshot_product"
AOT_RUNTIME="$SDK_OUT/dartaotruntime_product"
VM_PLATFORM="$SDK_OUT/vm_platform.dill"
HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/../p1_sample/base/app.dart"
TOOLS="$HERE/../tools"
B="$HERE/_build"
rm -rf "$B"
mkdir -p "$B"

build() {
  local tree="$1"; shift
  "$AOT_RUNTIME" "$GEN_KERNEL" --target vm -Ddart.vm.product=true \
    --aot --no-embed-sources --platform "$VM_PLATFORM" \
    --output "$B/${tree}_aot.dill" "$SRC" >/dev/null 2>&1
  "$GEN_SNAPSHOT" --snapshot-kind=app-aot-elf \
    --elf="$B/${tree}.snapshot" --save-debugging-info="$B/${tree}.debug" \
    "$@" "$B/${tree}_aot.dill" >/dev/null 2>&1
}

echo "== building 2x unobfuscated (baseline determinism) =="
build noobf1
build noobf2
echo "== building 2x obfuscated (independent --obfuscate runs) =="
build obf1 --obfuscate --save-obfuscation-map="$B/obf1_map.json"
build obf2 --obfuscate --save-obfuscation-map="$B/obf2_map.json"

diff_pair() {
  local a="$1" b="$2"
  echo "---- $a vs $b ----"
  python3 "$TOOLS/diff_linker.py" "$B/$a.snapshot" "$B/$b.snapshot" \
    --base-debug "$B/$a.debug" --patch-debug "$B/$b.debug" \
    --base-src-root "$HERE/../p1_sample/base" --patch-src-root "$HERE/../p1_sample/base" \
    --emit-closure 2>&1 | grep -v '^CLOSURE'
}

echo "== noobf1 vs noobf2 (both unobfuscated, identical source) =="
diff_pair noobf1 noobf2

echo "== obf1 vs obf2 (both obfuscated independently, identical source) =="
diff_pair obf1 obf2

echo "== sanity: do the two obfuscation maps actually differ? (first 5 lines) =="
diff <(head -c 400 "$B/obf1_map.json") <(head -c 400 "$B/obf2_map.json") && echo "IDENTICAL (no drift at all)" || echo "DIFFERENT (obfuscation renaming did drift across independent builds)"
