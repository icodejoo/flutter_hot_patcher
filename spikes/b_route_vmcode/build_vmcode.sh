#!/usr/bin/env bash
# build_vmcode.sh — build a base + patch AOT snapshot pair and dump their blobs.
#
# B-route (vmcode) spike scaffolding. Produces, in $OUT_DIR:
#   base.aot / patch.aot     raw gen_snapshot AOT output (Mach-O dylib)
#   base.blob / patch.blob   the concatenated 4-region "diff base" blobs
#
# NOTE: this deliberately does NOT run Shorebird's `aot_tools link`, because the
# linker lives in Shorebird's closed Dart VM fork. Without it the two snapshots
# are *unaligned*, so the resulting delta is an upper bound (worst case).
# Measuring that upper bound on a real app is exactly the point of this script.
#
# Usage:
#   ./build_vmcode.sh <base.dill> <patch.dill> [out_dir]
#
# Env overrides:
#   GEN_SNAPSHOT   path to gen_snapshot for the target arch
#   ANALYZE_SNAPSHOT  optional; if set, also dump blobs with Shorebird's
#                     analyze_snapshot --dump_blobs for cross-checking

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

BASE_DILL="${1:?usage: build_vmcode.sh <base.dill> <patch.dill> [out_dir]}"
PATCH_DILL="${2:?usage: build_vmcode.sh <base.dill> <patch.dill> [out_dir]}"
OUT_DIR="${3:-$SCRIPT_DIR/out}"

GEN_SNAPSHOT="${GEN_SNAPSHOT:-$HOME/engine_ios/src/out/ios_release/gen_snapshot_arm64}"

if [[ ! -x "$GEN_SNAPSHOT" ]]; then
  echo "error: gen_snapshot not found at $GEN_SNAPSHOT" >&2
  echo "       set GEN_SNAPSHOT=... (e.g. the Shorebird cached one:" >&2
  echo "       ~/.shorebird/bin/cache/flutter/<rev>/bin/cache/artifacts/engine/ios-release/gen_snapshot_arm64)" >&2
  exit 1
fi

mkdir -p "$OUT_DIR"

aot() {
  local dill="$1" out="$2"
  echo "==> gen_snapshot $(basename "$dill") -> $(basename "$out")"
  "$GEN_SNAPSHOT" \
    --deterministic \
    --snapshot_kind=app-aot-assembly \
    --assembly="$out.S" \
    "$dill"
  # assemble + link into the same shape Flutter produces for App.framework/App
  xcrun --sdk iphoneos clang -arch arm64 -miphoneos-version-min=12.0 \
    -c "$out.S" -o "$out.o"
  xcrun --sdk iphoneos clang -arch arm64 -miphoneos-version-min=12.0 \
    -dynamiclib -Xlinker -rpath -Xlinker '@executable_path/Frameworks' \
    -Xlinker -rpath -Xlinker '@loader_path/Frameworks' \
    -install_name '@rpath/App.framework/App' \
    -o "$out" "$out.o"
}

aot "$BASE_DILL"  "$OUT_DIR/base.aot"
aot "$PATCH_DILL" "$OUT_DIR/patch.aot"

echo "==> extracting snapshot blobs (our own Mach-O extractor)"
python3 "$SCRIPT_DIR/extract_blobs.py" "$OUT_DIR/base.aot"  "$OUT_DIR/base.blob"
python3 "$SCRIPT_DIR/extract_blobs.py" "$OUT_DIR/patch.aot" "$OUT_DIR/patch.blob"

if [[ -n "${ANALYZE_SNAPSHOT:-}" && -x "${ANALYZE_SNAPSHOT}" ]]; then
  echo "==> cross-checking with Shorebird analyze_snapshot --dump_blobs"
  "$ANALYZE_SNAPSHOT" --dump_blobs --out="$OUT_DIR/base.sb.blob"  "$OUT_DIR/base.aot"
  "$ANALYZE_SNAPSHOT" --dump_blobs --out="$OUT_DIR/patch.sb.blob" "$OUT_DIR/patch.aot"
  ls -l "$OUT_DIR"/*.blob
fi

echo
echo "done. next: ./gen_vmcode_diff.sh $OUT_DIR/base.blob $OUT_DIR/patch.blob"
