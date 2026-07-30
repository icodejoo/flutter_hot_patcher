// PATCH: Point3D gains a new field `z` inserted BETWEEN x and y (x stays at
// offset 0; y's offset shifts from 4 to 8). sumXY/bumpY SOURCE is unchanged
// (still `p.ref.x + p.ref.y` / `p.ref.y = p.ref.y + d`) but the access CODEGEN
// for y must change (different immediate offset). unrelatedFfi source unchanged.
library;

import 'dart:ffi';
import 'dart:io';

final class Point3D extends Struct {
  @Int32()
  external int x;
  @Int32()
  external int z; // <-- NEW field inserted here, shifts y below
  @Int32()
  external int y;
}

@pragma('vm:never-inline')
int sumXY(Pointer<Point3D> p) => p.ref.x + p.ref.y;

@pragma('vm:never-inline')
void bumpY(Pointer<Point3D> p, int d) {
  p.ref.y = p.ref.y + d;
}

@pragma('vm:never-inline')
int unrelatedFfi(int n) => n * 5 + 3;

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
