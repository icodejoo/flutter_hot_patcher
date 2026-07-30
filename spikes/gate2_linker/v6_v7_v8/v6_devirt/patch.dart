// V6 devirtualization routing — PATCH. Identical to base EXCEPT Sq.area:
// s*s+1 -> s*s+2. useShape/unrelated source unchanged. Sq.area changes (cond 1);
// useShape, which was devirtualized to a direct call to Sq.area, must be pulled
// in via cond 2.
library;

import 'dart:io';

abstract class Shape {
  int area();
}

class Sq implements Shape {
  final int s;
  Sq(this.s);
  @pragma('vm:never-inline')
  int area() => s * s + 2; // <-- was +1
}

@pragma('vm:never-inline')
int useShape(Shape sh) => sh.area() + 5;

@pragma('vm:never-inline')
int unrelated(int x) => x * 7 + 99;

void main(List<String> args) {
  final Shape sh = Sq(args.length + 3);
  stdout.writeln(useShape(sh) + unrelated(args.length));
}
