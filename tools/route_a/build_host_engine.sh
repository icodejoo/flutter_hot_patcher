#!/usr/bin/env bash
# Builds an arm64 host toolchain for the X1 engine.
#
# out/host_release is target_cpu="x64" (its dartaotruntime and gen_snapshot are
# x86_64 running under Rosetta) and has no dart-sdk/ tree, so flutter_tools
# falls back to engine_src/flutter/prebuilts/macos-arm64/dart-sdk -- a prebuilt
# Dart whose kernel binary format is 122, while ~/dart/sdk is 121. The split is
# invisible until dart2bytecode tries to --import-dill an app kernel:
#   Unexpected Kernel Format Version 122 (expected 121)
# This out dir fixes both halves: target_cpu=arm64 and full_dart_sdk=true.
set -euo pipefail

ENGINE_SRC="${FHP_ENGINE_SRC:-$HOME/engine_ios/src}"
NAME="${FHP_ENGINE_HOST_NAME:-host_release_arm64}"
OUT="out/$NAME"

cd "$ENGINE_SRC"
export PATH="$HOME/depot_tools:$PATH"

mkdir -p "$OUT"
if [ ! -e "$OUT/args.gn" ]; then
  python3 - "$OUT/args.gn" <<'PY'
import sys, os
src = os.path.join(os.path.dirname(os.path.dirname(sys.argv[1])), 'host_release', 'args.gn')
s = open(src).read()
s = s.replace('target_cpu = "x64"', 'target_cpu = "arm64"')
s = s.replace('dart_target_arch = "x64"', 'dart_target_arch = "arm64"')
s = s.replace('full_dart_sdk = false', 'full_dart_sdk = true')
open(sys.argv[1], 'w').write(s)
PY
fi

flutter/third_party/gn/gn gen "$OUT"
flutter/third_party/ninja/ninja -C "$OUT" \
  dart-sdk/bin/dart \
  dart-sdk/bin/dartaotruntime \
  dart-sdk/bin/snapshots/frontend_server_aot.dart.snapshot \
  gen/dart2bytecode.dart.snapshot \
  flutter_patched_sdk

echo "[route_a] host toolchain ready: $ENGINE_SRC/$OUT"
