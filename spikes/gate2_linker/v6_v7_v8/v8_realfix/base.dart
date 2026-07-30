// V8 realistic fix scenario — BASE.
//
// A tiny pricing pipeline with branches. The patch makes TWO real policy edits
// (clampPct caps at 90 not 100; shipping base fee 5 -> 7). `discount`/`total`
// source is unchanged but each directly calls a changed function, so condition
// 2 must cascade them in. `taxFor` is untouched and must stay equivalent. The
// patched snapshot IS the full-recompile reference: running the closure
// interpreted (new source) + the rest as identical baseline machine code
// reproduces the patch snapshot's behavior exactly.
library;

import 'dart:io';

@pragma('vm:never-inline')
int clampPct(int p) => p < 0 ? 0 : (p > 100 ? 100 : p); // patch: cap 100 -> 90

@pragma('vm:never-inline')
int discount(int price, int pct) => price - price * clampPct(pct) ~/ 100;

@pragma('vm:never-inline')
int shipping(int weight) => weight <= 0 ? 0 : 5 + weight * 2; // patch: 5 -> 7

@pragma('vm:never-inline')
int taxFor(int amount) => amount * 13 ~/ 100; // untouched — expect equivalent

@pragma('vm:never-inline')
int total(int price, int pct, int weight) =>
    discount(price, pct) + shipping(weight) + taxFor(price);

void main(List<String> args) {
  final price = 100 + args.length;
  const pct = 95; // exceeds the patched 90 cap, so the fix is observable
  final weight = 3 + args.length;
  stdout.writeln(total(price, pct, weight));
}
