#!/usr/bin/env bash
# Re-emit each variant's patch ELF with --strip (as tools/build_app_patch.sh now
# does in split mode), link against the split-mode base, diff, report sizes.
#   strip_rebuild.sh <app> <variant>...
set -euo pipefail
APP=$1; shift
HERE="$(cd "$(dirname "$0")" && pwd)"
D="$HERE/${APP}_split"
OUT=/Users/Cruz/shorebird_engine/engine/src/flutter/engine/src/out/ios_release_ref
GEN=$OUT/clang_arm64/gen_snapshot_arm64
AN=$OUT/artifacts_arm64/analyze_snapshot_arm64
PATCH=$HOME/.shorebird/bin/cache/artifacts/patch/patch
LINKER="$HERE/../../tools/linker.py"
for v in "$@"; do
  s="$D/strip_test/$v"; mkdir -p "$s"
  [ -f "$D/$v/ours/patch.dill" ] || { echo "$v: no patch.dill"; continue; }
  "$GEN" --deterministic --snapshot_kind=app-aot-elf --dwarf-stack-traces --resolve-dwarf-paths --strip \
      "--save-debugging-info=$s/patch.symbols" "--elf=$s/patch.aot" "$D/$v/ours/patch.dill" > "$s/gen.log" 2>&1
  "$AN" --shorebird "--out=$s/patch.json" "$s/patch.aot" > "$s/an.log" 2>&1
  python3 "$LINKER" "--base=$D/ours_release/base.aot" "--patch=$s/patch.aot" \
      "--base-json=$D/ours_release/base.json" "--patch-json=$s/patch.json" "--output=$s/out.vmcode" > "$s/link.log" 2>&1
  "$PATCH" "$D/ours_release/diff_base" "$s/out.vmcode" "$s/delta.patch" > "$s/diff.log" 2>&1
  echo "$v delta $(wc -c < "$s/delta.patch" | tr -d ' ') aot_sha $(shasum -a 256 "$s/patch.aot" | cut -c1-16) link $(tail -1 "$s/link.log")"
done
