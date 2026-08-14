#!/usr/bin/env bash
# Compiles a KBC dynamic module for a Flutter app running on the X1 engine.
#
#   build_flutter_module.sh <app_dir> <module.dart> <out_dir>
#
# The app must already have been built with the SAME toolchain, i.e.
#
#   flutter build ios --release --no-codesign --no-tree-shake-icons \
#     --local-engine-src-path ~/engine_ios/src \
#     --local-engine ios_release --local-engine-host host_release_arm64 \
#     --extra-front-end-options=--dynamic-interface=<app_dir>/dynamic_interface.yaml
#
# --local-engine-host host_release_arm64 is not optional. Without it
# flutter_tools cannot find <host_out>/dart-sdk/bin and falls back to
# engine_src/flutter/prebuilts/macos-arm64/dart-sdk (artifacts.dart:1466),
# a prebuilt Dart whose kernel format is 122 while ~/dart/sdk is 121 -- and
# dart2bytecode then refuses the app kernel. Build that out dir with
# tools/route_a/build_host_engine.sh.
set -euo pipefail

APP_DIR="${1:?usage: $0 <app_dir> <module.dart> <out_dir>}"
MODULE="${2:?}"
OUT="${3:?}"

ENGINE_SRC="${FHP_ENGINE_SRC:-$HOME/engine_ios/src}"
HOST="${FHP_ENGINE_HOST:-$ENGINE_SRC/out/host_release_arm64}"
AOTRUNTIME="$HOST/dart-sdk/bin/dartaotruntime"
FRONTEND="$HOST/dart-sdk/bin/snapshots/frontend_server_aot.dart.snapshot"
DART2BYTECODE="$HOST/gen/dart2bytecode.dart.snapshot"
PLATFORM="$HOST/flutter_patched_sdk/platform_strong.dill"

for f in "$AOTRUNTIME" "$FRONTEND" "$DART2BYTECODE" "$PLATFORM"; do
  [ -e "$f" ] || { echo "missing: $f"; echo "build it with tools/route_a/build_host_engine.sh"; exit 1; }
done

APP_DIR="$(cd "$APP_DIR" && pwd)"
IFACE="$APP_DIR/dynamic_interface.yaml"
[ -e "$IFACE" ] || { echo "missing dynamic interface: $IFACE"; exit 1; }
PKGCFG="$APP_DIR/.dart_tool/package_config.json"
[ -e "$PKGCFG" ] || { echo "missing $PKGCFG (run flutter pub get)"; exit 1; }
PKGNAME="$(python3 -c "
import sys,re
for line in open('$APP_DIR/pubspec.yaml'):
    m = re.match(r'name:\s*(\S+)', line)
    if m: print(m.group(1)); break")"
mkdir -p "$OUT"; OUT="$(cd "$OUT" && pwd)"

cd "$APP_DIR"

# The module is compiled against the app's NON-AOT kernel. The app.dill left by
# `flutter build` is the TFA'd AOT one and cannot serve as --import-dill.
echo "[route_a] app kernel (no_aot)"
"$AOTRUNTIME" "$FRONTEND" \
  --sdk-root "$HOST/flutter_patched_sdk/" --target=flutter \
  -Ddart.vm.product=true --packages "$PKGCFG" \
  --dynamic-interface="$IFACE" \
  --output-dill "$OUT/app_no_aot.dill" "package:$PKGNAME/main.dart" \
  > "$OUT/kernel_no_aot.log" 2>&1

echo "[route_a] module bytecode"
"$AOTRUNTIME" "$DART2BYTECODE" \
  --platform "$PLATFORM" --target flutter --packages "$PKGCFG" \
  -Ddart.vm.product=true \
  --import-dill "$OUT/app_no_aot.dill" \
  --validate "$IFACE" \
  --output "$OUT/module.bytecode" "$MODULE"

python3 - "$OUT/module.bytecode" <<'PY'
import struct, sys
d = open(sys.argv[1], 'rb').read()
assert d[:4] == b'3CBD', d[:4]
print(f"[route_a] {sys.argv[1]}: KBC v{struct.unpack('<I', d[4:8])[0]}, {len(d)} bytes")
PY
