#!/usr/bin/env bash
# Build and run V2-closure hotpatch demo on iOS Simulator (arm64)
# Prerequisites:
#   - DART_SDK_SRC: dart-lang/sdk source root (must have ReleaseIosSimARM64 built
#     with dart_dynamic_modules=true and the Gate1 VM patch applied)
#   - iOS Simulator running (default UDID below)
# Usage: DART_SDK_SRC=~/dart/sdk ./build_sim.sh [simulator-udid]
set -euo pipefail

: "${DART_SDK_SRC:?Set DART_SDK_SRC to dart-lang/sdk source root}"
SIM_UDID="${1:-33F3D819-6B24-4276-88FD-9BAE91D83CAD}"

HOST_OUT="$DART_SDK_SRC/xcodebuild/ReleaseARM64"
SIM_OUT="$DART_SDK_SRC/xcodebuild/ReleaseIosSimARM64"
HERE="$(cd "$(dirname "$0")" && pwd)"
B="$(mktemp -d -t e2e_v2_XXXXXX)"
trap 'rm -rf "$B"' EXIT

echo "=== 1. kernel ===" && \
"$HOST_OUT/dartaotruntime_product" \
  "$HOST_OUT/gen/gen_kernel_aot.dart.snapshot" \
  --platform "$HOST_OUT/vm_platform.dill" --aot \
  --output "$B/app.dill" "$HERE/main.dart"

echo "=== 2. snapshot (via simctl spawn) ===" && \
xcrun simctl spawn "$SIM_UDID" \
  "$SIM_OUT/gen_snapshot_product" \
  --snapshot-kind=app-aot-assembly \
  --assembly="$B/snap.S" "$B/app.dill"

echo "=== 3. assemble ===" && \
xcrun --sdk iphonesimulator as -arch arm64 "$B/snap.S" -o "$B/snap.o"

echo "=== 4. compile C++ shim ===" && \
xcrun --sdk iphonesimulator clang++ -arch arm64 \
  -target arm64-apple-ios14.0-simulator -std=c++17 \
  -I"$DART_SDK_SRC/runtime/include" \
  -c "$HERE/builtin_shim.cpp" -o "$B/shim.o"

echo "=== 5. compile C embedding ===" && \
xcrun --sdk iphonesimulator clang -arch arm64 \
  -target arm64-apple-ios14.0-simulator \
  -I"$DART_SDK_SRC/runtime/include" \
  -c "$HERE/dart_cli_demo.c" -o "$B/main.o"

echo "=== 6. build static lib from Dart runtime objects ===" && \
OBJ_DIR="$SIM_OUT/obj/gen/dartaotruntime_product_set"
ar rcs "$B/libdart_sim.a" "$OBJ_DIR"/*.o
ar d "$B/libdart_sim.a" dartaotruntime_product_set.main_impl.o 2>/dev/null || true
ar d "$B/libdart_sim.a" dartaotruntime_product_set.main.o 2>/dev/null || true
ar d "$B/libdart_sim.a" dartaotruntime_product_set.snapshot_empty.o 2>/dev/null || true

echo "=== 7. link ===" && \
xcrun --sdk iphonesimulator clang++ -arch arm64 \
  -target arm64-apple-ios14.0-simulator \
  "$B/main.o" "$B/shim.o" "$B/snap.o" \
  -Wl,-all_load "$B/libdart_sim.a" \
  "$SIM_OUT/obj/runtime/libdart_aotruntime_product.a" \
  -lpthread -ldl -lm -lc++ \
  -framework Foundation -framework Security \
  -o "$B/demo"

echo "=== 8. run ===" && \
xcrun simctl spawn "$SIM_UDID" "$B/demo"
