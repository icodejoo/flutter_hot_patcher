#!/bin/bash
# Gate 2 probe P2: is byte-level function equivalence a valid basis for the
# linker? Three experiments:
#   A. position-independence: does perturbing snapshot layout change bytes?
#   B. determinism: does the same source compile to the same function bytes?
#   C. byte-equality-unsound trap: a caller whose bytes are identical but whose
#      called function changed — must still be reinterpreted.
#
# Usage: DART_SDK_SRC=/root/dart/sdk ./run_all.sh
set -e
: "${DART_SDK_SRC:?Set DART_SDK_SRC to the dart-lang/sdk source root}"

CASE_DIR="$(cd "$(dirname "$0")" && pwd)"
SDK_OUT="$DART_SDK_SRC/out/ReleaseX64"
GEN_KERNEL="$SDK_OUT/gen/gen_kernel_aot.dart.snapshot"
GEN_SNAPSHOT="$SDK_OUT/gen_snapshot_product"
AOT_RUNTIME="$SDK_OUT/dartaotruntime_product"
VM_PLATFORM="$SDK_OUT/vm_platform.dill"
B=/root/gate2_probe_p2
mkdir -p "$B"

build() { # src_basename -> $B/out_basename.snapshot
  local src="$1" out="$2"
  "$AOT_RUNTIME" "$GEN_KERNEL" --target vm -Ddart.vm.product=true \
    --aot --no-embed-sources --platform "$VM_PLATFORM" \
    --output "$B/${out}_aot.dill" "$CASE_DIR/${src}.dart" >/dev/null 2>&1
  "$GEN_SNAPSHOT" --snapshot-kind=app-aot-elf \
    --elf="$B/${out}.snapshot" "$B/${out}_aot.dill" >/dev/null 2>&1
}

CMP="python3 $CASE_DIR/compare_fn.py"

build reloc_base base
build reloc_shifted shifted
build reloc_base det_b       # same source, 2nd build
build reloc_patchleaf patch

echo "###### A. position-independence (base vs shifted layout) ######"
$CMP "$B/base.snapshot" "$B/shifted.snapshot" pureLeaf caller callsLib
echo "  -> all True: function bytes are position-independent (pc-relative +"
echo "     r14/r15 pool addressing); layout shift alone does NOT change bytes."

echo ""
echo "###### B. determinism (same source, two builds) ######"
$CMP "$B/base.snapshot" "$B/det_b.snapshot" pureLeaf caller callsLib
echo "  -> all True: function machine code is deterministic run-to-run."
echo "     (whole-file md5 differs due to build-id metadata; diff per-function.)"

echo ""
echo "###### C. byte-equality-unsound trap (pureLeaf body changed 1 const) ######"
$CMP "$B/base.snapshot" "$B/patch.snapshot" pureLeaf caller callsLib
echo "  -> pureLeaf False (correct), but caller True: caller bytes identical"
echo "     yet it directly calls the replaced pureLeaf. Byte-equality alone is"
echo "     UNSOUND; equivalence must also require call targets to be equivalent."
