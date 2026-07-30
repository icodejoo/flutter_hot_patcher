// P0 CanonicalName probe — library A. Same member names as libb.dart on
// purpose (foo, K.m) to force AOT symbol-name collisions the bare-name aligner
// can't resolve. Goal: check whether --save-debugging-info DWARF carries a
// LIBRARY-qualified name that disambiguates them.
library liba;

@pragma('vm:never-inline')
int foo() => 11;

class K {
  @pragma('vm:never-inline')
  int m() => 101;
}
