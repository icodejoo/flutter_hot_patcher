library hotpatch_validation.t01;

@pragma('vm:entry-point') @pragma('vm:never-inline')
int prim_int() => 42;

@pragma('vm:entry-point') @pragma('vm:never-inline')
double prim_double() => 3.14;

@pragma('vm:entry-point') @pragma('vm:never-inline')
String prim_string() => 'hello';

@pragma('vm:entry-point') @pragma('vm:never-inline')
bool prim_bool() => true;

@pragma('vm:entry-point') @pragma('vm:never-inline')
dynamic prim_dynamic() { dynamic x = 1; return x; }

@pragma('vm:entry-point') @pragma('vm:never-inline')
int prim_var() { var x = 10; return x * 2; }

@pragma('vm:entry-point') @pragma('vm:never-inline')
Object prim_object() { Object o = 42; return o; }
