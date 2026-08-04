library hotpatch_validation.t12;

import 'package:intl/intl.dart';
import 'package:collection/collection.dart';
import 'package:crypto/crypto.dart';
import 'dart:convert';
import 'package:path/path.dart' as p;

@pragma('vm:entry-point') @pragma('vm:never-inline')
String third_intl_format() => NumberFormat('#,###').format(1234567);  // T64: '1,234,567'

@pragma('vm:entry-point') @pragma('vm:never-inline')
String third_intl_date() {
  final dt = DateTime(2026, 8, 4);
  return DateFormat('yyyy-MM-dd').format(dt);  // T65: '2026-08-04'
}

@pragma('vm:entry-point') @pragma('vm:never-inline')
String third_collection() {
  final list = [1, 3, 5, 2, 4];
  return list.sorted((a, b) => a.compareTo(b)).toString();  // T66: [1, 2, 3, 4, 5]
}

@pragma('vm:entry-point') @pragma('vm:never-inline')
String third_crypto() {
  final bytes = utf8.encode('hello');
  return sha256.convert(bytes).toString().substring(0, 8);  // T67: first 8 chars of SHA256
}

@pragma('vm:entry-point') @pragma('vm:never-inline')
String third_path() => p.join('usr', 'local', 'bin');  // T68: 'usr/local/bin'

void main() {}
