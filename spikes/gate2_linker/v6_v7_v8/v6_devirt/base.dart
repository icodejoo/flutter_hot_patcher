// V6 devirtualization routing — BASE.
//
// `Shape` has a single implementor `Sq` and only `Sq` is ever instantiated, so
// AOT's CHA devirtualizes the interface call `sh.area()` in `useShape` into a
// DIRECT call to `Sq.area`. `Sq.area` is vm:never-inline so it stays a direct
// call (not inlined), giving the exact V6 form: a devirtualized static direct
// call. When the patch changes `Sq.area`'s body, condition 2 must propagate
// through that direct call and pull `useShape` into the closure. `unrelated`
// never touches Shape and must stay equivalent.
library;

import 'dart:io';

abstract class Shape {
  int area();
}

class Sq implements Shape {
  final int s;
  Sq(this.s);
  @pragma('vm:never-inline')
  int area() => s * s + 1; // patch changes +1 -> +2
}

@pragma('vm:never-inline')
int useShape(Shape sh) => sh.area() + 5; // devirtualized direct call to Sq.area

@pragma('vm:never-inline')
int unrelated(int x) => x * 7 + 99; // no Shape — expect equivalent

void main(List<String> args) {
  final Shape sh = Sq(args.length + 3);
  stdout.writeln(useShape(sh) + unrelated(args.length));
}
