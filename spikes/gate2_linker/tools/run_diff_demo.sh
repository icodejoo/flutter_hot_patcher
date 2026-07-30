#!/bin/bash
# Demonstrate the minimal diff-linker on the P2 patchleaf scenario:
#   base  = reloc_base.dart          (pureLeaf = x*3+1)
#   patch = reloc_patchleaf.dart     (pureLeaf = x*3+2, all else source-identical)
# Expected transitive closure ("must reinterpret"):
#   pureLeaf  (bytes changed, condition 1)
#   caller    (bytes identical, but directly calls pureLeaf -> condition 2)
#   main      (calls caller -> condition 2)
# Expected equivalent (baseline): callsLib (calls only unchanged library code).
#
# Usage: DART_SDK_SRC=/root/dart/sdk ./run_diff_demo.sh
set -e
: "${DART_SDK_SRC:?Set DART_SDK_SRC to the dart-lang/sdk source root}"

TOOLS="$(cd "$(dirname "$0")" && pwd)"
SRC="$TOOLS/../probe_reloc_equivalence"
SDK_OUT="$DART_SDK_SRC/out/ReleaseX64"
GEN_KERNEL="$SDK_OUT/gen/gen_kernel_aot.dart.snapshot"
GEN_SNAPSHOT="$SDK_OUT/gen_snapshot_product"
AOT_RUNTIME="$SDK_OUT/dartaotruntime_product"
VM_PLATFORM="$SDK_OUT/vm_platform.dill"
B=/root/gate2_diff_demo
mkdir -p "$B"

build() {
  local src="$1" out="$2"
  "$AOT_RUNTIME" "$GEN_KERNEL" --target vm -Ddart.vm.product=true \
    --aot --no-embed-sources --platform "$VM_PLATFORM" \
    --output "$B/${out}_aot.dill" "$SRC/${src}.dart" >/dev/null 2>&1
  "$GEN_SNAPSHOT" --snapshot-kind=app-aot-elf \
    --elf="$B/${out}.snapshot" "$B/${out}_aot.dill" >/dev/null 2>&1
}

build reloc_base base
build reloc_patchleaf patch
python3 "$TOOLS/diff_linker.py" "$B/base.snapshot" "$B/patch.snapshot" --list
