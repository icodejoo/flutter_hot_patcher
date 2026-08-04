library hotpatch_validation.harness.main;

import 'dart:convert';
import 'registry.dart';
import '../lib/t01_primitives.dart' as t01;
import '../lib/t02_collections.dart' as t02;
import '../lib/t03_nullsafety.dart' as t03;
import '../lib/t04_constants.dart' as t04;

void _registerTests() {
  // T01-T07: Primitives
  registerTest('T01', 'Primitive int', 'primitives', () => t01.prim_int().toString());
  registerTest('T02', 'Primitive double', 'primitives', () => t01.prim_double().toString());
  registerTest('T03', 'Primitive string', 'primitives', () => t01.prim_string());
  registerTest('T04', 'Primitive bool', 'primitives', () => t01.prim_bool().toString());
  registerTest('T05', 'Primitive dynamic', 'primitives', () => t01.prim_dynamic().toString());
  registerTest('T06', 'Primitive var', 'primitives', () => t01.prim_var().toString());
  registerTest('T07', 'Primitive object', 'primitives', () => t01.prim_object().toString());

  // T08-T14: Collections
  registerTest('T08', 'Collection list literal', 'collections', () => t02.coll_list_literal());
  registerTest('T09', 'Collection list map', 'collections', () => t02.coll_list_map());
  registerTest('T10', 'Collection list where', 'collections', () => t02.coll_list_where());
  registerTest('T11', 'Collection map literal', 'collections', () => t02.coll_map_literal());
  registerTest('T12', 'Collection map access', 'collections', () => t02.coll_map_access().toString());
  registerTest('T13', 'Collection set', 'collections', () => t02.coll_set().toString());
  registerTest('T14', 'Collection fold', 'collections', () => t02.coll_fold().toString());

  // T15-T19: Null safety
  registerTest('T15', 'Null nullable', 'nullsafety', () => t03.null_nullable());
  registerTest('T16', 'Null bang', 'nullsafety', () => t03.null_bang().toString());
  registerTest('T17', 'Null conditional', 'nullsafety', () => t03.null_conditional());
  registerTest('T18', 'Null coalesce', 'nullsafety', () => t03.null_coalesce());
  registerTest('T19', 'Null late', 'nullsafety', () => t03.null_late());

  // T20-T25: Constants
  registerTest('T20', 'Constant toplevel', 'constants', () => t04.const_toplevel().toString());
  registerTest('T21', 'Constant local', 'constants', () => t04.const_local().toString());
  registerTest('T22', 'Constant final', 'constants', () => t04.const_final());
  registerTest('T23', 'Constant static', 'constants', () => t04.const_static());
  registerTest('T24', 'Constant list', 'constants', () => t04.const_list().toString());
  registerTest('T25', 'Constant expr', 'constants', () => t04.const_expr().toString());
}

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

void main() {
  _registerTests();
}
