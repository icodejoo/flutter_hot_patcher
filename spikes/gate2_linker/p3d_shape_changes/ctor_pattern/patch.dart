// PATCH: Derived.make's factory body constant changed (x*2+1 -> x*2+2);
// describe's pattern-match branch changed (a*b -> a*b+1). Base/Derived
// constructors, unrelatedCtor unchanged.
library;

import 'dart:io';

class Base {
  final int tag;
  Base(this.tag);
  Base.named(int t) : tag = t * 10;
}

class Derived extends Base {
  final int extra;
  Derived(int tag, this.extra) : super(tag);

  factory Derived.make(int x) {
    if (x < 0) return Derived(0, 0);
    return Derived(x, x * 2 + 2); // <-- was +1
  }
}

@pragma('vm:never-inline')
int describe(int code) {
  final (int a, int b) = (code, code + 1);
  return switch (code) {
    0 => a + b,
    1 => a - b,
    _ when code > 1 => a * b + 1, // <-- was a*b
    _ => 0,
  };
}

@pragma('vm:never-inline')
int unrelatedCtor(int n) => n * 6 + 2;

void main(List<String> args) {
  final n = args.length;
  final d = Derived.make(n);
  final b = Base.named(n);
  stdout.writeln(d.extra + b.tag + describe(n) + unrelatedCtor(n));
}
