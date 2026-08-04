library hotpatch_validation.harness.main;

import 'dart:convert';
import 'registry.dart';
import '../lib/t01_primitives.dart' as t01;
import '../lib/t02_collections.dart' as t02;
import '../lib/t03_nullsafety.dart' as t03;
import '../lib/t04_constants.dart' as t04;
import '../lib/t05_functions.dart' as t05;
import '../lib/t06_classes.dart' as t06;
import '../lib/t07_generics.dart' as t07;
import '../lib/t08_operators.dart' as t08;

void _registerTests() {
  registerTest('T01', 'Primitive int', 'primitives', () => t01.prim_int().toString());
  registerTest('T02', 'Primitive double', 'primitives', () => t01.prim_double().toString());
  registerTest('T03', 'Primitive string', 'primitives', () => t01.prim_string());
  registerTest('T04', 'Primitive bool', 'primitives', () => t01.prim_bool().toString());
  registerTest('T05', 'Primitive dynamic', 'primitives', () => t01.prim_dynamic().toString());
  registerTest('T06', 'Primitive var', 'primitives', () => t01.prim_var().toString());
  registerTest('T07', 'Primitive object', 'primitives', () => t01.prim_object().toString());

  registerTest('T08', 'Collection list literal', 'collections', () => t02.coll_list_literal());
  registerTest('T09', 'Collection list map', 'collections', () => t02.coll_list_map());
  registerTest('T10', 'Collection list where', 'collections', () => t02.coll_list_where());
  registerTest('T11', 'Collection map literal', 'collections', () => t02.coll_map_literal());
  registerTest('T12', 'Collection map access', 'collections', () => t02.coll_map_access().toString());
  registerTest('T13', 'Collection set', 'collections', () => t02.coll_set().toString());
  registerTest('T14', 'Collection fold', 'collections', () => t02.coll_fold().toString());

  registerTest('T15', 'Null nullable', 'nullsafety', () => t03.null_nullable());
  registerTest('T16', 'Null bang', 'nullsafety', () => t03.null_bang().toString());
  registerTest('T17', 'Null conditional', 'nullsafety', () => t03.null_conditional());
  registerTest('T18', 'Null coalesce', 'nullsafety', () => t03.null_coalesce());
  registerTest('T19', 'Null late', 'nullsafety', () => t03.null_late());

  registerTest('T20', 'Constant toplevel', 'constants', () => t04.const_toplevel().toString());
  registerTest('T21', 'Constant local', 'constants', () => t04.const_local().toString());
  registerTest('T22', 'Constant final', 'constants', () => t04.const_final());
  registerTest('T23', 'Constant static', 'constants', () => t04.const_static());
  registerTest('T24', 'Constant list', 'constants', () => t04.const_list().toString());
  registerTest('T25', 'Constant expr', 'constants', () => t04.const_expr().toString());

  registerTest('T26', 'Function toplevel', 'functions', () => t05.fn_toplevel());
  registerTest('T27', 'Function anonymous', 'functions', () => t05.fn_anonymous().toString());
  registerTest('T28', 'Function closure capture', 'functions', () => t05.fn_closure_capture().toString());
  registerTest('T29', 'Function named param', 'functions', () => t05.fn_named_param());
  registerTest('T30', 'Function optional param', 'functions', () => t05.fn_optional_param().toString());
  registerTest('T31', 'Function higher order', 'functions', () => t05.fn_higher_order().toString());
  registerTest('T32', 'Function transform', 'functions', () => t05.fn_transform());
  registerTest('T33', 'Function async label', 'functions', () => t05.fn_async_label());
  registerTest('T34', 'Function generator', 'functions', () => t05.fn_generator());

  registerTest('T35', 'Class basic method', 'classes', () => t06.cls_basic_method().toString());
  registerTest('T36', 'Class static method', 'classes', () => t06.cls_static_method());
  registerTest('T37', 'Class getter', 'classes', () => t06.cls_getter().toString());
  registerTest('T38', 'Class setter', 'classes', () => t06.cls_setter());
  registerTest('T39', 'Class inheritance', 'classes', () => t06.cls_inheritance());
  registerTest('T40', 'Class abstract', 'classes', () => t06.cls_abstract().toString());
  registerTest('T41', 'Class mixin', 'classes', () => t06.cls_mixin());
  registerTest('T42', 'Class enum', 'classes', () => t06.cls_enum());

  registerTest('T43', 'Generic function', 'generics', () => t07.generic_fn());
  registerTest('T44', 'Generic class', 'generics', () => t07.generic_class().toString());
  registerTest('T45', 'Generic constraint', 'generics', () => t07.generic_constraint().toString());
  registerTest('T46', 'Generic list', 'generics', () => t07.generic_list());

  registerTest('T47', 'Operator arithmetic', 'operators', () => t08.op_arithmetic().toString());
  registerTest('T48', 'Operator comparison', 'operators', () => t08.op_comparison().toString());
  registerTest('T49', 'Operator logical', 'operators', () => t08.op_logical().toString());
  registerTest('T50', 'Operator bitwise', 'operators', () => t08.op_bitwise().toString());
  registerTest('T51', 'Operator custom', 'operators', () => t08.op_custom());
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
