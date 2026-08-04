library hotpatch_validation.t11;

@pragma('vm:entry-point') @pragma('vm:never-inline')
String str_interpolation() => 'Hi, World!';  // T60

@pragma('vm:entry-point') @pragma('vm:never-inline')
String str_multiline() => 'line1\nline2\nline3';  // T61: added line3

@pragma('vm:entry-point') @pragma('vm:never-inline')
String str_raw() => r'raw\tstring';  // T62: \t

@pragma('vm:entry-point') @pragma('vm:never-inline')
bool str_regexp() => RegExp(r'^[a-z]+$').hasMatch('abc');  // T63: letters pattern, true

void main() {}
