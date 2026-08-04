library hotpatch_validation.harness.main;

import 'dart:convert';
import 'registry.dart';

// Imports populated as categories are added — start empty
// All category imports will be added in subsequent tasks

@pragma('vm:entry-point')
String runCase(List args) {
  final id = args.isNotEmpty ? args[0].toString() : '';
  final tc = testRegistry.where((t) => t.id == id).firstOrNull;
  if (tc == null) return jsonEncode({'id': id, 'error': 'not_found'});
  try {
    final result = tc.baselineFn();
    return jsonEncode({'id': id, 'result': result, 'error': null});
  } catch (e, st) {
    return jsonEncode({'id': id, 'result': null, 'error': e.toString()});
  }
}

@pragma('vm:entry-point')
String listCases() {
  return jsonEncode(testRegistry.map((t) => {
    'id': t.id,
    'description': t.description,
    'category': t.category,
  }).toList());
}

void main() {}
