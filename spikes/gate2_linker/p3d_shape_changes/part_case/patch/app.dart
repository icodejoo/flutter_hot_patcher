// PATCH: helperA MOVED here from helpers.dart, body UNCHANGED (`x + 1`).
// helperB stays in helpers.dart with a changed body. unrelatedPart unchanged.
library;

import 'dart:io';

part 'helpers.dart';

@pragma('vm:never-inline')
int helperA(int x) => x + 1; // moved from helpers.dart, same logic

@pragma('vm:never-inline')
int unrelatedPart(int n) => n * 4 + 3;

void main(List<String> args) {
  final n = args.length;
  stdout.writeln(helperA(n) + helperB(n) + unrelatedPart(n));
}
