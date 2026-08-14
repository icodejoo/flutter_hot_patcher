import 'dart:io';

import 'package:dart_internal/dart_internal.dart' as loader;
import 'package:route_a_demo/greeting.dart' as greeting;

Future<void> main(List<String> args) async {
  print('before: ${greeting.greet()}');
  if (args.isEmpty) {
    print('usage: main <module.bytecode>');
    exit(2);
  }
  final bytes = File(args[0]).readAsBytesSync();
  await loader.loadModuleFromBytes(bytes);
  print('after: ${greeting.greet()}');
}
