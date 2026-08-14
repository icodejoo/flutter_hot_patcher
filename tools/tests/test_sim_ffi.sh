#!/usr/bin/env bash
# dart:ffi must work while Dart code runs on the ARM64 Simulator.
#
# Upstream disables dart:ffi whenever USING_SIMULATOR is set, because upstream
# only ever sets it when host arch != target arch. Our A1 patch sets it with
# host == target, where the ABI barrier does not exist. See
# engine/patches/dartsdk_simulator_ffi.diff and docs/ROUTE_A_RESEARCH.md.
#
# Requires the dynamic-modules SDK build: tools/route_a/build_sdk.sh
set -uo pipefail
SDK_OUT="${FHP_DART_OUT:-$HOME/dart/sdk/xcodebuild/ReleaseARM64DM}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
FAILS=0
fail() { echo "FAIL: $1"; FAILS=$((FAILS+1)); }
pass() { echo "PASS: $1"; }

for f in dartaotruntime_product gen_snapshot_product \
         gen/gen_kernel_aot.dart.snapshot vm_platform_strong.dill; do
  [ -e "$SDK_OUT/$f" ] || { echo "FATAL: missing $SDK_OUT/$f (run tools/route_a/build_sdk.sh)"; exit 1; }
done

cat > "$TMP/lib.c" <<'EOF'
#include <stdint.h>
int64_t sum8(int64_t a,int64_t b,int64_t c,int64_t d,
             int64_t e,int64_t f,int64_t g,int64_t h) { return a+b+c+d+e+f+g+h; }
int64_t sum10(int64_t a,int64_t b,int64_t c,int64_t d,int64_t e,
              int64_t f,int64_t g,int64_t h,int64_t i,int64_t j) {
  return a+b+c+d+e+f+g+h+i+j;
}
double dsum10(double a,double b,double c,double d,double e,
              double f,double g,double h,double i,double j) {
  return a+b+c+d+e+f+g+h+i+j;
}
EOF
clang -shared -O2 -o "$TMP/libprobe.dylib" "$TMP/lib.c" || { echo "FATAL: clang failed"; exit 1; }

cat > "$TMP/probe.dart" <<EOF
import 'dart:ffi';

@Native<Int32 Function(Int32)>(symbol: 'abs', isLeaf: true)
external int nativeAbs(int x);

void main() {
  print('resolver: \${nativeAbs(-9)}');
  final p = DynamicLibrary.process();
  print('process: \${p.lookupFunction<Int32 Function(Int32), int Function(int)>('abs')(-7)}');
  final lib = DynamicLibrary.open('$TMP/libprobe.dylib');
  print('reg_int: \${lib.lookupFunction<
      Int64 Function(Int64,Int64,Int64,Int64,Int64,Int64,Int64,Int64),
      int Function(int,int,int,int,int,int,int,int)>('sum8')(1,2,3,4,5,6,7,8)}');
  print('stack_int: \${lib.lookupFunction<
      Int64 Function(Int64,Int64,Int64,Int64,Int64,Int64,Int64,Int64,Int64,Int64),
      int Function(int,int,int,int,int,int,int,int,int,int)>('sum10')(1,2,3,4,5,6,7,8,9,10)}');
  print('stack_dbl: \${lib.lookupFunction<
      Double Function(Double,Double,Double,Double,Double,Double,Double,Double,Double,Double),
      double Function(double,double,double,double,double,double,double,double,double,double)>('dsum10')(1,2,3,4,5,6,7,8,9,10)}');
}
EOF

"$SDK_OUT/dartaotruntime_product" "$SDK_OUT/gen/gen_kernel_aot.dart.snapshot" \
  --target vm --aot -Ddart.vm.product=true \
  --platform "$SDK_OUT/vm_platform_strong.dill" \
  --output "$TMP/p.dill" "$TMP/probe.dart" > "$TMP/kernel.log" 2>&1 \
  || { echo "FATAL: kernel build failed"; cat "$TMP/kernel.log"; exit 1; }
"$SDK_OUT/gen_snapshot_product" --snapshot-kind=app-aot-elf \
  --elf="$TMP/p.snapshot" "$TMP/p.dill" > /dev/null 2>&1 \
  || { echo "FATAL: gen_snapshot failed"; exit 1; }

# stdin closed: an unimplemented instruction drops into the sim debugger, which
# would otherwise block forever waiting for input.
"$SDK_OUT/dartaotruntime_product" "$TMP/p.snapshot" < /dev/null > "$TMP/out" 2>&1

check() {
  grep -qx "$2" "$TMP/out" && pass "$1" || { fail "$1"; }
}
check "@Native resolver reaches host code"  "resolver: 9"
check "DynamicLibrary.process() call"       "process: 7"
check "register arguments"                  "reg_int: 36"
check "stack integer arguments"             "stack_int: 55"
check "stack double arguments"              "stack_dbl: 55.0"
[ "$FAILS" -ne 0 ] && { echo "--- output ---"; cat "$TMP/out"; }

echo "---"
[ "$FAILS" -eq 0 ] && { echo "ALL PASS"; exit 0; } || { echo "$FAILS FAILURE(S)"; exit 1; }
