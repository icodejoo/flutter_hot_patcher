// P0 CanonicalName probe — library B. Deliberately same member names as
// liba.dart (foo, K.m) but different bodies.
library libb;

@pragma('vm:never-inline')
int foo() => 22;

class K {
  @pragma('vm:never-inline')
  int m() => 202;
}
