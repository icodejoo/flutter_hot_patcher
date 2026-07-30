// Completeness case: dart:ffi (低层). Covers a Struct subclass (field-offset
// access codegen), arithmetic on FFI-loaded values, and a Pointer.fromFunction
// callback (a native entry-point root). We only AOT-compile + objdump the ELF —
// never run — so no native lib / allocation is needed (fromAddress suffices for
// retention). Probes whether FFI-shaped code diffs like ordinary code.
library;

import 'dart:ffi';
import 'dart:io';

final class Point extends Struct {
  @Int32()
  external int x;
  @Int32()
  external int y;
}

// Reads struct fields (FFI offset-access codegen) + arithmetic.
@pragma('vm:never-inline')
int usePoint(Pointer<Point> p) => p.ref.x + p.ref.y * 3;

// A native callback entry-point root (passed to Pointer.fromFunction).
@pragma('vm:never-inline')
int cb(int a) => a + 2;

@pragma('vm:never-inline')
int makeCb() {
  final ptr = Pointer.fromFunction<Int32 Function(Int32)>(cb, 0);
  return ptr.address & 0xff;
}

void main(List<String> args) {
  final n = args.length;
  // Guard the dereferencing call behind a runtime flag so the program is safe
  // to run (we never pass --deref); usePoint stays retained/compiled for the
  // diff. args.contains is opaque to the AOT compiler, so no tree-shaking.
  var acc = makeCb();
  if (args.contains('--deref')) {
    final p = Pointer<Point>.fromAddress(4096 + n);
    acc += usePoint(p);
  }
  stdout.writeln(acc);
}
