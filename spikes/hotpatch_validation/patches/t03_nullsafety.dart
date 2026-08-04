library hotpatch_validation.t03;

@pragma('vm:entry-point') @pragma('vm:never-inline')
String null_nullable() { String? s; return s ?? 'empty'; }

@pragma('vm:entry-point') @pragma('vm:never-inline')
int null_bang() { String? s = 'hello'; return s!.length + 1; }

@pragma('vm:entry-point') @pragma('vm:never-inline')
String null_conditional() { String? s = 'Hello'; return s?.toLowerCase() ?? 'none'; }

@pragma('vm:entry-point') @pragma('vm:never-inline')
String null_coalesce() { String? a; String? b; return a ?? b ?? 'fallback'; }

@pragma('vm:entry-point') @pragma('vm:never-inline')
String null_late() { late String x; x = 'patched'; return x; }
