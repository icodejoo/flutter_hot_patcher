// P0 CanonicalName probe — entry. Uses both libraries' colliding foo()/K.m()
// so all four survive AOT tree-shaking and appear (colliding) in the snapshot.
library;

import 'dart:io';
import 'liba.dart' as a;
import 'libb.dart' as b;

void main(List<String> args) {
  final r = a.foo() + b.foo() + a.K().m() + b.K().m();
  stdout.writeln(r);
}
