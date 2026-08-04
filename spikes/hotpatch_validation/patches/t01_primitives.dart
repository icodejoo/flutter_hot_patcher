library hotpatch_validation.t01;

@pragma('vm:entry-point') @pragma('vm:never-inline')
int prim_int() => 100;

@pragma('vm:entry-point') @pragma('vm:never-inline')
double prim_double() => 2.72;

@pragma('vm:entry-point') @pragma('vm:never-inline')
String prim_string() => 'world';

@pragma('vm:entry-point') @pragma('vm:never-inline')
bool prim_bool() => false;

@pragma('vm:entry-point') @pragma('vm:never-inline')
dynamic prim_dynamic() { dynamic x = 'one'; return x; }

@pragma('vm:entry-point') @pragma('vm:never-inline')
int prim_var() { var x = 10; return x * 3; }

@pragma('vm:entry-point') @pragma('vm:never-inline')
Object prim_object() { Object o = 'forty-two'; return o; }
