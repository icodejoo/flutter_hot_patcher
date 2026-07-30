// V7 inline cascade — PATCH. Identical to base EXCEPT leaf's body:
// x*3+1 -> x*3+2. callerA/callerB/untouched source is byte-for-byte unchanged;
// the point is that callerA/callerB machine code STILL changes because leaf was
// inlined into them, so the linker must flag them via condition 1.
library;

import 'dart:io';

int leaf(int x) => x * 3 + 2; // <-- was +1

@pragma('vm:never-inline')
int callerA(int x) => leaf(x) + 10;

@pragma('vm:never-inline')
int callerB(int x) => leaf(x) * 2 + leaf(x + 1);

@pragma('vm:never-inline')
int untouched(int x) => x * 7 + 99;

void main(List<String> args) {
  final n = args.length;
  stdout.writeln(callerA(n) + callerB(n) + untouched(n));
}
