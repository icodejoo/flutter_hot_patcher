#!/usr/bin/env bash
# Builds the host Dart SDK pieces Route-A needs, into a dedicated output
# directory so the Route-B toolchain in xcodebuild/ReleaseARM64 is untouched.
set -euo pipefail

SDK_ROOT="${FHP_DART_SDK:-$HOME/dart/sdk}"
OUT_NAME="${FHP_DART_OUT_NAME:-ReleaseARM64DM}"
OUT="xcodebuild/$OUT_NAME"

cd "$SDK_ROOT"
export PATH="$HOME/depot_tools:$PATH"

mkdir -p "$OUT"
if [ ! -e "$OUT/args.gn" ]; then
  sed 's/^dart_dynamic_modules = false$/dart_dynamic_modules = true/' \
    xcodebuild/ReleaseARM64/args.gn > "$OUT/args.gn"
  grep -q '^dart_dynamic_modules = true$' "$OUT/args.gn" \
    || echo 'dart_dynamic_modules = true' >> "$OUT/args.gn"
fi

./buildtools/gn gen "$OUT"
buildtools/ninja/ninja -C "$OUT" \
  dartaotruntime_product \
  gen_snapshot_product \
  gen/dart2bytecode.dart.snapshot \
  gen/gen_kernel_aot.dart.snapshot \
  vm_platform_strong.dill

echo "[route_a] SDK ready: $SDK_ROOT/$OUT"
