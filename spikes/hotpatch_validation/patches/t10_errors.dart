library hotpatch_validation.t10;

@pragma('vm:entry-point') @pragma('vm:never-inline')
String err_try_catch() {
  try { throw FormatException('bad'); }
  catch (e) { return 'caught: ParseError'; }  // T56
}

@pragma('vm:entry-point') @pragma('vm:never-inline')
String err_throw() {
  try { throw ArgumentError('newValue'); }
  catch (e) { return 'ArgumentError: newValue'; }  // T57
}

@pragma('vm:entry-point') @pragma('vm:never-inline')
String err_on_type() {
  try { int.parse('abc'); }
  on FormatException { return 'ParseException'; }  // T58: different name
  catch (e) { return 'other'; }
  return 'none';
}

@pragma('vm:entry-point') @pragma('vm:never-inline')
String err_finally() {
  final buf = StringBuffer();
  try { buf.write('try'); }
  finally { buf.write('+finally+extra'); }  // T59
  return buf.toString();
}

void main() {}
