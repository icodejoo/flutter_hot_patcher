// Completeness case: FFI Struct field-layout change (FFI analogue of Gate1 V9,
// which covered plain Dart class field layout). Point3D{x,y}; patch inserts a
// new field `z` BETWEEN x and y, shifting y's byte offset — with the accessor
// SOURCE unchanged (still reads x+y). All access codegen (offset immediates)
// must be caught even though nothing in the .dart source of the accessor
// changed. `unrelatedFfi` never touches the struct and must stay equivalent.
library;

import 'dart:ffi';
import 'dart:io';

final class Point3D extends Struct {
  @Int32()
  external int x;
  @Int32()
  external int y; // patch: a new field z is inserted BEFORE this, shifting y's offset
}

@pragma('vm:never-inline')
int sumXY(Pointer<Point3D> p) => p.ref.x + p.ref.y;

@pragma('vm:never-inline')
void bumpY(Pointer<Point3D> p, int d) {
  p.ref.y = p.ref.y + d;
}

@pragma('vm:never-inline')
int unrelatedFfi(int n) => n * 5 + 3; // no struct access — expect equivalent

void main(List<String> args) {
  final n = args.length;
  var acc = unrelatedFfi(n);
  if (args.contains('--deref')) {
    final p = Pointer<Point3D>.fromAddress(4096 + n);
    acc += sumXY(p);
    bumpY(p, 1);
  }
  stdout.writeln(acc);
}
