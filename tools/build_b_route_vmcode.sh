#!/usr/bin/env bash
# Build B-route vmcode patch: base.dart + patch.dart → vmcode (Shorebird-compatible)
# and report bipatch diff size.
#
# Usage: build_b_route_vmcode.sh <base.dart> <patch.dart> <out_dir>
#
# Requires:
#   Shorebird flutter rev c15ef637... cached in ~/.shorebird
#   linker.py in the same tools directory

set -euo pipefail

BASE_DART="${1:?Usage: $0 <base.dart> <patch.dart> <out_dir>}"
PATCH_DART="${2:?Usage: $0 <base.dart> <patch.dart> <out_dir>}"
OUT_DIR="${3:?Usage: $0 <base.dart> <patch.dart> <out_dir>}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

SB_REV=c15ef6379403a0a55531a058bdb2c8e55bc05c98
SB_ENGINE=~/.shorebird/bin/cache/flutter/$SB_REV/bin/cache/artifacts/engine
DARTAOTRUNTIME=~/.shorebird/bin/cache/flutter/$SB_REV/bin/cache/dart-sdk/bin/dartaotruntime
GEN_KERNEL=~/.shorebird/bin/cache/flutter/$SB_REV/bin/cache/dart-sdk/bin/snapshots/gen_kernel_aot.dart.snapshot
PLATFORM=$SB_ENGINE/common/flutter_patched_sdk_product/platform_strong.dill
GEN_SNAPSHOT=$SB_ENGINE/ios-release/gen_snapshot_arm64
ANALYZE_SNAPSHOT=$SB_ENGINE/ios-release/analyze_snapshot_arm64
SB_PATCH=~/.shorebird/bin/cache/artifacts/patch/patch
LINKER_PY="$REPO_ROOT/tools/linker.py"

for bin in "$DARTAOTRUNTIME" "$GEN_KERNEL" "$PLATFORM" "$GEN_SNAPSHOT" "$ANALYZE_SNAPSHOT" "$SB_PATCH" "$LINKER_PY"; do
    [ -e "$bin" ] || { echo "MISSING: $bin" >&2; exit 1; }
done

mkdir -p "$OUT_DIR"

aot() {
    local src="$1" out_base="$2"
    echo "[aot] $src → $out_base.aot"
    "$DARTAOTRUNTIME" "$GEN_KERNEL" \
        --platform "$PLATFORM" \
        --target=flutter --aot --tfa \
        -Ddart.vm.product=true \
        -o "$out_base.dill" "$src"
    "$GEN_SNAPSHOT" --deterministic \
        --snapshot_kind=app-aot-elf \
        --elf="$out_base.aot" \
        --print_class_table_link_info_to="$out_base.ct.link" \
        --print_field_table_link_info_to="$out_base.ft.link" \
        --print_dispatch_table_link_info_to="$out_base.dt.link" \
        "$out_base.dill"
}

echo "=== Build base ==="
aot "$BASE_DART" "$OUT_DIR/base"

echo "=== Build patch ==="
aot "$PATCH_DART" "$OUT_DIR/patch"

echo "=== analyze_snapshot ==="
"$ANALYZE_SNAPSHOT" --shorebird --out="$OUT_DIR/base.json" "$OUT_DIR/base.aot"
"$ANALYZE_SNAPSHOT" --shorebird --out="$OUT_DIR/patch.json" "$OUT_DIR/patch.aot"

echo "=== link ==="
LINK_PCT=$(python3 "$LINKER_PY" \
    --base="$OUT_DIR/base.aot" \
    --patch="$OUT_DIR/patch.aot" \
    --output="$OUT_DIR/out.vmcode" \
    --base-json="$OUT_DIR/base.json" \
    --patch-json="$OUT_DIR/patch.json" \
    --verbose)

echo "=== diff ==="
"$SB_PATCH" "$OUT_DIR/base.aot" "$OUT_DIR/out.vmcode" "$OUT_DIR/out.patch"
DIFF_BYTES=$(wc -c < "$OUT_DIR/out.patch" | tr -d ' ')

BASE_SIZE=$(wc -c < "$OUT_DIR/base.aot" | tr -d ' ')
PATCH_SIZE=$(wc -c < "$OUT_DIR/out.vmcode" | tr -d ' ')

echo ""
echo "=== RESULTS ==="
echo "base.aot:    ${BASE_SIZE} bytes"
echo "out.vmcode:  ${PATCH_SIZE} bytes"
echo "bipatch diff: ${DIFF_BYTES} bytes"
echo "link%:       ${LINK_PCT}%"
