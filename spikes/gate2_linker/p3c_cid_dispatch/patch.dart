// PATCH: adds a new Shape implementor `Extra`, declared BEFORE Sq/Tri/Circ
// (testing whether declaration position affects cid/dispatch assignment for
// EXISTING classes in a full recompile). Extra is retained (referenced, not
// tree-shaken) but never reached on the executed path (guarded by a flag we
// never pass) -- it changes the interface's implementor SET without changing
// any existing class's source. Sq/Tri/Circ/useShapes source is IDENTICAL to
// base.dart.
library;

import 'dart:io';

abstract class Shape {
  int area();
}

// NEW implementor, inserted BEFORE the pre-existing classes.
class Extra implements Shape {
  final int w;
  Extra(this.w);
  @pragma('vm:never-inline')
  int area() => w * 9;
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
  // Retain Extra (keep it in the snapshot / dispatch table) without executing
  // it on the normal path.
  if (args.contains('--extra')) {
    shapes.add(Extra(n));
  }
  stdout.writeln(useShapes(shapes));
}
