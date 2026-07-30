// V9 patched layout: field z inserted between x and y (and read, so TFA keeps
// it). sumXY / bumpY / unrelated source is UNCHANGED vs v9_base.dart. makePoint
// and main adapt to the new constructor / read z. Expectation from the diff
// linker (optimistic mode, ignoring runtime name collisions):
//   must-reinterpret: sumXY, bumpY, makePoint, Point ctor, main (Point layout /
//                     accessors changed, or call something that did)
//   equivalent:       unrelated (never touches Point)
library;

import 'dart:io';

class Point {
  int x;
  int z; // <-- inserted, and read below so it stays in the layout
  int y;
  Point(this.x, this.z, this.y);
}

@pragma('vm:never-inline')
int sumXY(Point p) => p.x + p.y; // UNCHANGED source; y offset now differs

@pragma('vm:never-inline')
void bumpY(Point p, int d) {
  p.y += d; // UNCHANGED source; y offset now differs
}

@pragma('vm:never-inline')
Point makePoint(int a, int b) => Point(a, 0, b); // ctor adapts to new layout

@pragma('vm:never-inline')
int unrelated(int n) => n * 2 + 1; // UNCHANGED — must stay equivalent

void main(List<String> args) {
  final n = args.length;
  final p = makePoint(n, n + 5);
  bumpY(p, 3);
  stdout.writeln('${sumXY(p)} ${unrelated(n)} z=${p.z}');
}
