#!/usr/bin/env bash
# Route-A (KBC dynamic modules) build driver.
#
# Implements the pipeline that the Dart SDK itself uses for AOT dynamic modules
# (pkg/dynamic_modules/test/runner/aot.dart). The old tools/build_ios_patch.sh
# compiled modules standalone, which silently produced modules that could not
# reference any app code.
#
# Usage: tools/route_a/build.sh <app_dir> <entry.dart> <module.dart> <out_dir>
set -euo pipefail

APP_DIR="${1:?usage: build.sh <app_dir> <entry.dart> <module.dart> <out_dir>}"
ENTRY="${2:?}"
MODULE="${3:?}"
OUT="${4:?}"

# Dart SDK built with dart_dynamic_modules=true. Override with FHP_DART_OUT.
SDK_ROOT="${FHP_DART_SDK:-$HOME/dart/sdk}"
SDK_OUT="${FHP_DART_OUT:-$SDK_ROOT/xcodebuild/ReleaseARM64DM}"
# A stock Dart CLI, only used for `pub get` (the SDK build has no `dart`).
PUB_DART="${FHP_PUB_DART:-$HOME/fvm/versions/3.29.0/bin/cache/dart-sdk/bin/dart}"

AOTRUNTIME="$SDK_OUT/dartaotruntime_product"
GEN_SNAPSHOT="$SDK_OUT/gen_snapshot_product"
GEN_KERNEL="$SDK_OUT/gen/gen_kernel_aot.dart.snapshot"
DART2BYTECODE="$SDK_OUT/gen/dart2bytecode.dart.snapshot"
PLATFORM="$SDK_OUT/vm_platform_strong.dill"

for f in "$AOTRUNTIME" "$GEN_SNAPSHOT" "$GEN_KERNEL" "$DART2BYTECODE" "$PLATFORM"; do
  [ -e "$f" ] || { echo "missing: $f"; echo "build it with tools/route_a/build_sdk.sh"; exit 1; }
done

APP_DIR="$(cd "$APP_DIR" && pwd)"
IFACE="$APP_DIR/dynamic_interface.yaml"
[ -e "$IFACE" ] || { echo "missing dynamic interface: $IFACE"; exit 1; }
mkdir -p "$OUT"; OUT="$(cd "$OUT" && pwd)"

PKGCFG="$APP_DIR/.dart_tool/package_config.json"
[ -e "$PKGCFG" ] || (cd "$APP_DIR" && "$PUB_DART" pub get >/dev/null)

common=(--target vm --packages "$PKGCFG"
        -Ddart.vm.profile=false -Ddart.vm.product=true
        --platform "$PLATFORM" --dynamic-interface "$IFACE")

# 1. App kernel, AOT flavour — what gen_snapshot consumes.
echo "[route_a] app kernel (aot)"
"$AOTRUNTIME" "$GEN_KERNEL" "${common[@]}" --aot \
  --output "$OUT/app_aot.dill" "$APP_DIR/$ENTRY" > "$OUT/kernel_aot.log"

# 2. App kernel, non-AOT flavour — what the module is compiled *against*.
#    Without this the module cannot see a single app declaration.
echo "[route_a] app kernel (no_aot)"
"$AOTRUNTIME" "$GEN_KERNEL" "${common[@]}" --no-aot \
  --output "$OUT/app_no_aot.dill" "$APP_DIR/$ENTRY" > "$OUT/kernel_no_aot.log"

# 3. App AOT snapshot.
echo "[route_a] app snapshot"
"$GEN_SNAPSHOT" --snapshot-kind=app-aot-elf \
  --elf="$OUT/app.snapshot" "$OUT/app_aot.dill"

# 4. Module bytecode, linked against the app kernel and checked against the
#    dynamic interface.
echo "[route_a] module bytecode"
"$AOTRUNTIME" "$DART2BYTECODE" \
  --platform "$PLATFORM" --target vm --packages "$PKGCFG" \
  -Ddart.vm.profile=false -Ddart.vm.product=true \
  --import-dill "$OUT/app_no_aot.dill" \
  --validate "$IFACE" \
  --output "$OUT/module.bytecode" "$MODULE"

ver=$(python3 -c "
import struct,sys
d=open('$OUT/module.bytecode','rb').read()
print(struct.unpack('<I', d[4:8])[0])")
echo "[route_a] done — app.snapshot + module.bytecode (KBC v$ver, $(wc -c < "$OUT/module.bytecode" | tr -d ' ')B)"
echo "[route_a] run: $AOTRUNTIME $OUT/app.snapshot $OUT/module.bytecode"
