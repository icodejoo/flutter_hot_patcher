// Probe for REVIEW critic finding #3: cid/dispatch-table layout drift is
// outside the diff-linker's model (it only compares function bytes + direct
// call edges). Scenario: Shape has 3+ implementors so `s.area()` in useShapes
// is megamorphic (CHA can't devirtualize to a single target) -> a real
// dispatch-table call. The patch adds a NEW implementor class BEFORE the
// existing ones in declaration order (a plausible trigger for cid/dispatch
// layout renumbering in a full recompile), while Sq/Tri/Circ source is
// byte-for-byte unchanged. Question: does this change area()'s machine code
// or useShapes' machine code at all (diff_linker's only observables)?
library;

import 'dart:io';

abstract class Shape {
  int area();
}

class Sq implements Shape {
  final int s;
  Sq(this.s);
  @pragma('vm:never-inline')
  int area() => s * s;
}

class Tri implements Shape {
  final int b, h;
  Tri(this.b, this.h);
  @pragma('vm:never-inline')
  int area() => b * h ~/ 2;
}

class Circ implements Shape {
  final int r;
  Circ(this.r);
  @pragma('vm:never-inline')
  int area() => r * r * 3;
}

// Megamorphic call site: 3 distinct implementors reached through a List<Shape>
// built from a runtime-opaque selection, defeating CHA devirtualization.
@pragma('vm:never-inline')
int useShapes(List<Shape> shapes) {
  var total = 0;
  for (final s in shapes) {
    total += s.area();
  }
  return total;
}

void main(List<String> args) {
  final n = args.length;
  final shapes = <Shape>[Sq(n + 2), Tri(n + 3, n + 4), Circ(n + 1)];
  stdout.writeln(useShapes(shapes));
}
