part of 'app.dart';

@pragma('vm:never-inline')
int helperA(int x) => x + 1; // patch: MOVED into app.dart, body unchanged

@pragma('vm:never-inline')
int helperB(int x) => x * 2 + 5; // patch: body changes (2 -> 3), stays in this part file
