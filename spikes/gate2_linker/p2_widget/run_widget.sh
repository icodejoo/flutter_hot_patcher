#!/bin/bash
# P2 Flutter widget diff: compile base/ and patch/ main.dart to host-x64 AOT
# ELF (libapp.so) via the Flutter frontend_server + engine gen_snapshot (no
# desktop shell / GTK needed — we only objdump the ELF, never run it), then run
# the CanonicalName diff-linker. Shows a widget change is detected and confined
# to a tiny closure while the whole Flutter framework stays equivalent.
#
# Usage: ./run_widget.sh   (paths are the WSL Flutter engine build)
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
TOOLS="$HERE/../tools"

# Stock Flutter cache toolchain (a matched set). P2 only needs the AOT ELF to
# objdump, so we do NOT need the custom Gate-1 engine here — using mismatched
# runtime/snapshot versions fails with "Wrong full snapshot version".
FLUTTER=/root/flutter
DARTAOT="$FLUTTER/bin/cache/dart-sdk/bin/dartaotruntime"
FES="$FLUTTER/bin/cache/dart-sdk/bin/snapshots/frontend_server_aot.dart.snapshot"
SDKROOT="$FLUTTER/bin/cache/artifacts/engine/common/flutter_patched_sdk"
GENSNAP="$FLUTTER/bin/cache/artifacts/engine/linux-x64/gen_snapshot"
PKG=/root/hotpatch_demo_app/.dart_tool/package_config.json
B="$(mktemp -d -t p2_widget_XXXXXX)"
trap 'rm -rf "$B"' EXIT

build() {
  local tree="$1"
  "$DARTAOT" "$FES" \
    --sdk-root "$SDKROOT/" --target=flutter --aot --tfa \
    -Ddart.vm.product=true --packages "$PKG" \
    --output-dill "$B/${tree}.dill" \
    "$HERE/${tree}/main.dart" >"$B/${tree}.fes.log" 2>&1
  "$GENSNAP" --snapshot-kind=app-aot-elf \
    --elf="$B/${tree}.so" --save-debugging-info="$B/${tree}.debug" \
    "$B/${tree}.dill" >/dev/null 2>&1
}
echo "== compiling base widget app -> AOT ELF =="; build base
echo "== compiling patch widget app -> AOT ELF =="; build patch
echo "== ELF sizes / total functions =="
ls -la "$B/base.so" "$B/patch.so" | awk '{print $5, $NF}'

echo "== diff-linker (CanonicalName, conservative) =="
python3 "$TOOLS/diff_linker.py" "$B/base.so" "$B/patch.so" \
  --base-debug "$B/base.debug" --patch-debug "$B/patch.debug" \
  --base-src-root "$HERE/base" --patch-src-root "$HERE/patch" --list \
  | grep -vE '^CLOSURE'
