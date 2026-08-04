library hotpatch_validation.t04;

@pragma('vm:entry-point') @pragma('vm:never-inline')
double const_toplevel() { const pi = 3.14; return pi; }

@pragma('vm:entry-point') @pragma('vm:never-inline')
int const_local() { const int max = 200; return max; }

@pragma('vm:entry-point') @pragma('vm:never-inline')
String const_final() { final name = 'Bob'; return name; }

const String _tag = 'v2';
@pragma('vm:entry-point') @pragma('vm:never-inline')
String const_static() => _tag;

@pragma('vm:entry-point') @pragma('vm:never-inline')
int const_list() { const list = [1, 2, 3, 4]; return list.length; }

@pragma('vm:entry-point') @pragma('vm:never-inline')
int const_expr() { const x = 2 * 4; return x; }
