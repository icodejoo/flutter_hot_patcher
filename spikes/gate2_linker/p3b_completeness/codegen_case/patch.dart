// PATCH: added field `email` to User and regenerated the boilerplate (as a
// codegen run would). Expected byte-changed: userFromJson + userToJson
// (regenerated to handle email) + User ctor (new field) + main (map updated).
// summarize reads only name/age (whose offsets are stable when email is appended)
// -> must stay equivalent (precision).
library;

import 'dart:io';

class User {
  final String name;
  final int age;
  final String email;
  User(this.name, this.age, this.email);
}

@pragma('vm:never-inline')
User userFromJson(Map<String, dynamic> j) =>
    User(j['name'] as String, j['age'] as int, j['email'] as String);

@pragma('vm:never-inline')
Map<String, dynamic> userToJson(User u) => {'name': u.name, 'age': u.age, 'email': u.email};

@pragma('vm:never-inline')
int summarize(User u) => u.name.length + u.age; // UNCHANGED source

void main(List<String> args) {
  final u = userFromJson({'name': 'ab', 'age': args.length, 'email': 'x@y'});
  stdout.writeln(userToJson(u).length + summarize(u));
}
