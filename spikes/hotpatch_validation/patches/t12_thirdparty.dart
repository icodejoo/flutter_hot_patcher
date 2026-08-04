library hotpatch_validation.t12;

import 'package:intl/intl.dart';
import 'package:collection/collection.dart';
import 'package:crypto/crypto.dart';
import 'dart:convert';
import 'package:path/path.dart' as p;

@pragma('vm:entry-point') @pragma('vm:never-inline')
String third_intl_format() => NumberFormat('###,###.00').format(1234567);  // T64: with decimals

@pragma('vm:entry-point') @pragma('vm:never-inline')
String third_intl_date() {
  final dt = DateTime(2026, 8, 4);
  return DateFormat('MM/dd/yyyy').format(dt);  // T65: '08/04/2026'
}

@pragma('vm:entry-point') @pragma('vm:never-inline')
String third_collection() {
  final list = [1, 3, 5, 2, 4];
  return list.sorted((a, b) => b.compareTo(a)).toString();  // T66: descending
}

@pragma('vm:entry-point') @pragma('vm:never-inline')
String third_crypto() {
  final bytes = utf8.encode('world');  // T67: changed input 'hello'→'world'
  return sha256.convert(bytes).toString().substring(0, 8);
}

@pragma('vm:entry-point') @pragma('vm:never-inline')
String third_path() => p.join('home', 'user', 'documents');  // T68

void main() {}
