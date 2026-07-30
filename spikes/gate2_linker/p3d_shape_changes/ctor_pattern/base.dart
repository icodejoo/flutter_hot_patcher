// Completeness case: constructors (factory / const / named / initializer list
// / super chain) and Dart 3 pattern matching (switch expression, destructuring,
// if-case). Both untested change shapes per COVERAGE_GAPS.
library;

import 'dart:io';

class Base {
  final int tag;
  Base(this.tag);
  Base.named(int t) : tag = t * 10; // named ctor + initializer list
}

class Derived extends Base {
  final int extra;
  Derived(int tag, this.extra) : super(tag); // super chain

  factory Derived.make(int x) {
    if (x < 0) return Derived(0, 0);
    return Derived(x, x * 2 + 1); // patch: x*2+1 -> x*2+2
  }
}

@pragma('vm:never-inline')
int describe(int code) {
  // Dart 3 switch expression + pattern matching over a record.
  final (int a, int b) = (code, code + 1);
  return switch (code) {
    0 => a + b,
    1 => a - b,
    _ when code > 1 => a * b, // patch: a*b -> a*b+1
    _ => 0,
  };
}

@pragma('vm:never-inline')
int unrelatedCtor(int n) => n * 6 + 2; // expect equivalent

void main(List<String> args) {
  final n = args.length;
  final d = Derived.make(n);
  final b = Base.named(n);
  stdout.writeln(d.extra + b.tag + describe(n) + unrelatedCtor(n));
}
