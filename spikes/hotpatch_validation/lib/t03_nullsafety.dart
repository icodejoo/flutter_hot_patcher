library hotpatch_validation.t03;

@pragma('vm:entry-point') @pragma('vm:never-inline')
String null_nullable() { String? s; return s ?? 'null'; }

@pragma('vm:entry-point') @pragma('vm:never-inline')
int null_bang() { String? s = 'hello'; return s!.length; }

@pragma('vm:entry-point') @pragma('vm:never-inline')
String null_conditional() { String? s = 'Hello'; return s?.toUpperCase() ?? 'none'; }

@pragma('vm:entry-point') @pragma('vm:never-inline')
String null_coalesce() { String? a; String? b; return a ?? b ?? 'default'; }

@pragma('vm:entry-point') @pragma('vm:never-inline')
String null_late() { late String x; x = 'init'; return x; }
