library hotpatch_validation.t10;

@pragma('vm:entry-point') @pragma('vm:never-inline')
String err_try_catch() {
  try { throw FormatException('bad'); }
  catch (e) { return 'caught: FormatException'; }
}

@pragma('vm:entry-point') @pragma('vm:never-inline')
String err_throw() {
  try { throw ArgumentError('value'); }
  catch (e) { return 'ArgumentError: value'; }
}

@pragma('vm:entry-point') @pragma('vm:never-inline')
String err_on_type() {
  try { int.parse('abc'); }
  on FormatException { return 'FormatException'; }
  catch (e) { return 'other'; }
  return 'none';
}

@pragma('vm:entry-point') @pragma('vm:never-inline')
String err_finally() {
  final buf = StringBuffer();
  try { buf.write('try'); }
  finally { buf.write('+finally'); }
  return buf.toString();
}

void main() {}
