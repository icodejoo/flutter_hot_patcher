// V9 layer-2 host: loads the patch (which defines a class with NEW fields),
// gets its instance through the Shape virtual interface, and calls area().
// If the interpreter allocated Box with the right layout and reads its fields
// (w,h) at the right offsets, area() == w*h == 12.
library;

import 'dart:io';
import 'package:dynamic_modules/dynamic_modules.dart';

import 'shared/shared.dart';

Future<void> main(List<String> args) async {
  final moduleFile = args.isNotEmpty ? args[0] : 'modules/entry1.dart.bytecode';
  final bytes = File(moduleFile).readAsBytesSync();
  final result = await loadModuleFromBytes(bytes);
  final shape = result as Shape;
  final a = shape.area();
  print('area=$a expected=12');
  print(a == 12 ? 'V9-RUNTIME-PASS' : 'V9-RUNTIME-FAIL');
}
