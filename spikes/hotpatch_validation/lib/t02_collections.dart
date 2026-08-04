library hotpatch_validation.t02;

@pragma('vm:entry-point') @pragma('vm:never-inline')
String coll_list_literal() => [1, 2, 3].toString();

@pragma('vm:entry-point') @pragma('vm:never-inline')
String coll_list_map() => [1, 2, 3].map((x) => x * 2).toList().toString();

@pragma('vm:entry-point') @pragma('vm:never-inline')
String coll_list_where() => [1, -2, 3, -4].where((x) => x > 0).toList().toString();

@pragma('vm:entry-point') @pragma('vm:never-inline')
String coll_map_literal() => {'a': 1, 'b': 2}.toString();

@pragma('vm:entry-point') @pragma('vm:never-inline')
int coll_map_access() { final m = {'key': 42}; return m['key'] ?? 0; }

@pragma('vm:entry-point') @pragma('vm:never-inline')
int coll_set() => {1, 2, 3}.length;

@pragma('vm:entry-point') @pragma('vm:never-inline')
int coll_fold() => [1, 2, 3, 4].fold(0, (a, b) => a + b);
