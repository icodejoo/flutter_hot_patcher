// V9 static-completeness baseline. Class Point{x,y}; several functions access
// Point's fields in different ways, plus one function that never touches Point.
// The patch (v9_patch.dart) inserts a field z into Point. sumXY/bumpY/unrelated
// source is IDENTICAL across base/patch; only the layout changes. The diff
// linker must flag every Point accessor (their field offsets shift) as
// must-reinterpret, and leave `unrelated` equivalent.
library;

import 'dart:io';

class Point {
  int x;
  int y;
  Point(this.x, this.y);
}

@pragma('vm:never-inline')
int sumXY(Point p) => p.x + p.y; // reads x (offset unchanged) + y (offset shifts)

@pragma('vm:never-inline')
void bumpY(Point p, int d) {
  p.y += d; // writes y — offset shifts
}

@pragma('vm:never-inline')
Point makePoint(int a, int b) => Point(a, b); // allocates Point — layout changes

@pragma('vm:never-inline')
int unrelated(int n) => n * 2 + 1; // touches no Point — must stay equivalent

void main(List<String> args) {
  final n = args.length;
  final p = makePoint(n, n + 5); // object shared ACROSS functions (key for V9 L2)
  bumpY(p, 3);
  stdout.writeln('${sumXY(p)} ${unrelated(n)}');
}
