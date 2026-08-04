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
import '../lib/t09_async.dart' as t09;
import '../lib/t10_errors.dart' as t10;
import '../lib/t11_strings.dart' as t11;
import '../lib/t12_thirdparty.dart' as t12;
import '../lib/t13_flutter_like.dart' as t13;
import '../lib/t14_propagation.dart' as t14;
import '../lib/t15_hierarchy.dart' as t15;
import '../lib/t16_edge.dart' as t16;

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

  registerTest('T52', 'Async future value', 'async', () => t09.async_future_value());
  registerTest('T53', 'Async await chain', 'async', () => t09.async_await_chain());
  registerTest('T54', 'Async future error', 'async', () => t09.async_future_error());
  registerTest('T55', 'Async stream', 'async', () => t09.async_stream());

  registerTest('T56', 'Error try catch', 'errors', () => t10.err_try_catch());
  registerTest('T57', 'Error throw', 'errors', () => t10.err_throw());
  registerTest('T58', 'Error on type', 'errors', () => t10.err_on_type());
  registerTest('T59', 'Error finally', 'errors', () => t10.err_finally());

  registerTest('T60', 'String interpolation', 'strings', () => t11.str_interpolation());
  registerTest('T61', 'String multiline', 'strings', () => t11.str_multiline());
  registerTest('T62', 'String raw', 'strings', () => t11.str_raw());
  registerTest('T63', 'String regexp', 'strings', () => t11.str_regexp().toString());

  registerTest('T64', 'Thirdparty intl format', 'thirdparty', () => t12.third_intl_format());
  registerTest('T65', 'Thirdparty intl date', 'thirdparty', () => t12.third_intl_date());
  registerTest('T66', 'Thirdparty collection', 'thirdparty', () => t12.third_collection());
  registerTest('T67', 'Thirdparty crypto', 'thirdparty', () => t12.third_crypto());
  registerTest('T68', 'Thirdparty path', 'thirdparty', () => t12.third_path());

  registerTest('T69', 'Flutter counter logic', 'flutter_like', () => t13.flutter_counter_logic().toString());
  registerTest('T70', 'Flutter state compute', 'flutter_like', () => t13.flutter_state_compute());
  registerTest('T71', 'Flutter builder fn', 'flutter_like', () => t13.flutter_builder_fn());
  registerTest('T72', 'Flutter callback', 'flutter_like', () => t13.flutter_callback());
  registerTest('T73', 'Flutter form validate', 'flutter_like', () => t13.flutter_form_validate());

  registerTest('T74', 'Propagation 2-level chain', 'propagation', () => t14.prop_a_2level());
  registerTest('T75', 'Propagation 3-level chain', 'propagation', () => t14.prop_a_3level());
  registerTest('T76', 'Propagation 4-level chain', 'propagation', () => t14.prop_a_4level());
  registerTest('T77', 'Propagation diamond', 'propagation', () => t14.prop_a_diamond());
  registerTest('T78', 'Propagation multi-point', 'propagation', () => t14.prop_a_multi());
  registerTest('T79', 'Propagation sibling', 'propagation', () => t14.prop_b_sibling());
  registerTest('T80', 'Propagation cross-class', 'propagation', () => t14.prop_cross_class());
  registerTest('T81', 'Propagation static chain', 'propagation', () => t14.prop_static_a());

  registerTest('T82', 'Hierarchy add field', 'hierarchy', () => t15.hierarchy_add_field());
  registerTest('T83', 'Hierarchy remove field', 'hierarchy', () => t15.hierarchy_remove_field());
  registerTest('T84', 'Hierarchy add class', 'hierarchy', () => t15.hierarchy_add_class());
  registerTest('T85', 'Hierarchy remove class', 'hierarchy', () => t15.hierarchy_remove_class());
  registerTest('T86', 'Hierarchy change inheritance', 'hierarchy', () => t15.hierarchy_change_inheritance());

  registerTest('T87', 'Edge empty function', 'edge', () => t16.edge_empty_fn());
  registerTest('T88', 'Edge recursive', 'edge', () => t16.edge_recursive_call().toString());
  registerTest('T89', 'Edge mutual recursive', 'edge', () => t16.edge_mutual_recursive());
  registerTest('T90', 'Edge large string', 'edge', () => t16.edge_large_string().toString());
  registerTest('T91', 'Edge identity', 'edge', () => t16.edge_identity_same());
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
