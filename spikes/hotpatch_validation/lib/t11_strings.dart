library hotpatch_validation.t11;

@pragma('vm:entry-point') @pragma('vm:never-inline')
String str_interpolation() => 'Hello, World!';  // T60

@pragma('vm:entry-point') @pragma('vm:never-inline')
String str_multiline() => 'line1\nline2';  // T61

@pragma('vm:entry-point') @pragma('vm:never-inline')
String str_raw() => r'raw\nstring';  // T62

@pragma('vm:entry-point') @pragma('vm:never-inline')
bool str_regexp() => RegExp(r'^\d+$').hasMatch('123');  // T63: true

void main() {}
