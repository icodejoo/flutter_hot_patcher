// Completeness case: code-generated serialization (json_serializable-style).
// Hand-written to mirror what json_serializable/freezed emit (fromJson/toJson
// boilerplate over a model), WITHOUT pulling a third-party dep. Scenario: a dev
// adds a field to the model and regenerates the boilerplate — the diff must
// catch the regenerated fromJson/toJson + the constructor, and leave unrelated
// code (summarize) equivalent. (Real generated code lives in a `part` file;
// inlined here to avoid the separate part-file question — see COVERAGE_GAPS.)
library;

import 'dart:io';

class User {
  final String name;
  final int age;
  User(this.name, this.age);
}

@pragma('vm:never-inline')
User userFromJson(Map<String, dynamic> j) => User(j['name'] as String, j['age'] as int);

@pragma('vm:never-inline')
Map<String, dynamic> userToJson(User u) => {'name': u.name, 'age': u.age};

@pragma('vm:never-inline')
int summarize(User u) => u.name.length + u.age; // reads name/age only — should stay equivalent

void main(List<String> args) {
  final u = userFromJson({'name': 'ab', 'age': args.length});
  stdout.writeln(userToJson(u).length + summarize(u));
}
