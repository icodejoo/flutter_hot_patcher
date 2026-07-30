// Completeness case: const inlining spread. A `const` used in several functions
// as `x + K` etc. Changing K must be caught in EVERY user (const folds into each
// user's code). Risk: if AOT loads the const from the object pool rather than as
// an inline immediate, the diff-linker's normalize() wildcards the pool slot and
// the change becomes invisible -> MISS (unsound). This case probes exactly that.
library;

import 'dart:io';

const K = 20;

@pragma('vm:never-inline')
int userA(int x) => x + K;
@pragma('vm:never-inline')
int userB(int x) => x * K + 1;
@pragma('vm:never-inline')
int userC(int x) => (x ^ K) + 3;
@pragma('vm:never-inline')
int unrelated(int x) => x * 7 + 3; // no K — must stay equivalent

void main(List<String> args) {
  final n = args.length;
  stdout.writeln(userA(n) + userB(n) + userC(n) + unrelated(n));
}
