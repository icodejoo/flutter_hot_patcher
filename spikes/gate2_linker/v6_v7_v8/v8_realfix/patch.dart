// V8 realistic fix scenario — PATCH. Two real policy edits vs base:
//   clampPct: cap 100 -> 90    (line body changed)
//   shipping: base fee 5 -> 7  (line body changed)
// discount/total/taxFor/main source unchanged. Expected closure: clampPct +
// shipping (cond 1); discount (calls clampPct) + total (calls both) + main
// (cond 2). taxFor and everything else equivalent.
library;

import 'dart:io';

@pragma('vm:never-inline')
int clampPct(int p) => p < 0 ? 0 : (p > 90 ? 90 : p); // <-- cap 100 -> 90

@pragma('vm:never-inline')
int discount(int price, int pct) => price - price * clampPct(pct) ~/ 100;

@pragma('vm:never-inline')
int shipping(int weight) => weight <= 0 ? 0 : 7 + weight * 2; // <-- 5 -> 7

@pragma('vm:never-inline')
int taxFor(int amount) => amount * 13 ~/ 100;

@pragma('vm:never-inline')
int total(int price, int pct, int weight) =>
    discount(price, pct) + shipping(weight) + taxFor(price);

void main(List<String> args) {
  final price = 100 + args.length;
  const pct = 95;
  final weight = 3 + args.length;
  stdout.writeln(total(price, pct, weight));
}
